"""Workflow execution runtime."""

from __future__ import annotations

import time
from typing import Any

from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError, QueryExecutionError
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.provider.registry import resolve_provider
from cruxible_core.provider.types import ExecutionTrace, ProviderContext, ResolvedArtifact
from cruxible_core.query.engine import execute_query
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.workflow.compiler import compile_workflow, get_lock_path, load_lock
from cruxible_core.workflow.contracts import query_execution_error, validate_contract_payload
from cruxible_core.workflow.refs import resolve_value
from cruxible_core.workflow.types import WorkflowExecutionResult


def execute_workflow(
    instance: InstanceProtocol,
    config: CoreConfig,
    workflow_name: str,
    input_payload: dict[str, Any],
) -> WorkflowExecutionResult:
    """Execute a workflow against the current instance and persist traces/receipts."""
    lock = load_lock(get_lock_path(instance))
    plan = compile_workflow(config, lock, workflow_name, input_payload)
    graph = instance.load_graph()
    workflow = config.workflows[workflow_name]
    receipt_builder = ReceiptBuilder(
        query_name=workflow_name,
        parameters=plan.input_payload,
        operation_type="workflow",
    )

    step_outputs: dict[str, Any] = {}
    query_receipt_ids: list[str] = []
    traces: list[ExecutionTrace] = []

    for compiled_step, workflow_step in zip(plan.steps, workflow.steps, strict=True):
        if compiled_step.kind == "query":
            assert compiled_step.query_name is not None
            step_params = resolve_value(
                compiled_step.params_template,
                plan.input_payload,
                step_outputs,
            )
            query_result = execute_query(config, graph, compiled_step.query_name, step_params)
            if query_result.receipt is None:
                raise QueryExecutionError(
                    f"Query step '{compiled_step.step_id}' did not produce a receipt"
                )
            store = instance.get_receipt_store()
            try:
                store.save_receipt(query_result.receipt)
            finally:
                store.close()
            query_receipt_ids.append(query_result.receipt.receipt_id)
            step_outputs[compiled_step.as_name or compiled_step.step_id] = {
                "results": [item.model_dump() for item in query_result.results],
                "receipt_id": query_result.receipt.receipt_id,
                "total_results": query_result.total_results,
                "steps_executed": query_result.steps_executed,
            }
            receipt_builder.record_plan_step(
                compiled_step.step_id,
                "query",
                detail={
                    "query_name": compiled_step.query_name,
                    "receipt_id": query_result.receipt.receipt_id,
                    "params": step_params,
                },
            )
            continue

        if compiled_step.kind == "provider":
            assert compiled_step.provider_name is not None
            provider_schema = config.providers[compiled_step.provider_name]
            locked_provider = lock.providers[compiled_step.provider_name]
            raw_input = resolve_value(
                compiled_step.input_template,
                plan.input_payload,
                step_outputs,
            )
            provider_input = validate_contract_payload(
                config,
                provider_schema.contract_in,
                raw_input,
                subject=f"Provider step '{compiled_step.step_id}' input",
                error_factory=query_execution_error,
            )
            artifact = None
            if locked_provider.artifact is not None:
                locked_artifact = lock.artifacts[locked_provider.artifact]
                artifact = ResolvedArtifact(
                    name=locked_provider.artifact,
                    kind=locked_artifact.kind,
                    uri=locked_artifact.uri,
                    sha256=locked_artifact.sha256,
                    metadata=locked_artifact.metadata,
                )

            context = ProviderContext(
                workflow_name=workflow_name,
                step_id=compiled_step.step_id,
                provider_name=compiled_step.provider_name,
                provider_version=locked_provider.version,
                provider_config=locked_provider.config,
                deterministic=locked_provider.deterministic,
                artifact=artifact,
            )
            provider_fn = resolve_provider(compiled_step.provider_name, provider_schema)
            started = time.monotonic_ns()
            status = "success"
            error_message: str | None = None
            try:
                raw_output = provider_fn(provider_input, context)
                if not isinstance(raw_output, dict):
                    raise QueryExecutionError(
                        f"Provider '{compiled_step.provider_name}' returned non-dict output"
                    )
                provider_output = validate_contract_payload(
                    config,
                    provider_schema.contract_out,
                    raw_output,
                    subject=f"Provider step '{compiled_step.step_id}' output",
                    error_factory=query_execution_error,
                )
            except Exception as exc:
                status = "error"
                error_message = str(exc)
                trace = _build_trace(
                    workflow_name=workflow_name,
                    step_id=compiled_step.step_id,
                    provider_name=compiled_step.provider_name,
                    provider_version=locked_provider.version,
                    provider_ref=locked_provider.ref,
                    runtime=locked_provider.runtime,
                    deterministic=locked_provider.deterministic,
                    side_effects=locked_provider.side_effects,
                    artifact_name=locked_provider.artifact,
                    artifact_sha256=artifact.sha256 if artifact is not None else None,
                    input_payload=provider_input,
                    output_payload={},
                    status=status,
                    error=error_message,
                    duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                )
                _persist_trace(instance, trace)
                traces.append(trace)
                receipt_builder.record_plan_step(
                    compiled_step.step_id,
                    "provider",
                    detail={
                        "provider_name": compiled_step.provider_name,
                        "trace_id": trace.trace_id,
                        "status": status,
                    },
                )
                raise QueryExecutionError(error_message or "Provider execution failed") from exc

            trace = _build_trace(
                workflow_name=workflow_name,
                step_id=compiled_step.step_id,
                provider_name=compiled_step.provider_name,
                provider_version=locked_provider.version,
                provider_ref=locked_provider.ref,
                runtime=locked_provider.runtime,
                deterministic=locked_provider.deterministic,
                side_effects=locked_provider.side_effects,
                artifact_name=locked_provider.artifact,
                artifact_sha256=artifact.sha256 if artifact is not None else None,
                input_payload=provider_input,
                output_payload=provider_output,
                status=status,
                error=error_message,
                duration_ms=(time.monotonic_ns() - started) / 1_000_000,
            )
            _persist_trace(instance, trace)
            traces.append(trace)
            step_outputs[compiled_step.as_name or compiled_step.step_id] = provider_output
            receipt_builder.record_plan_step(
                compiled_step.step_id,
                "provider",
                detail={
                    "provider_name": compiled_step.provider_name,
                    "provider_version": locked_provider.version,
                    "trace_id": trace.trace_id,
                },
            )
            continue

        left = resolve_value(workflow_step.assert_spec.left, plan.input_payload, step_outputs)
        right = resolve_value(workflow_step.assert_spec.right, plan.input_payload, step_outputs)
        passed = _evaluate_assert(left, workflow_step.assert_spec.op, right)
        step_node = receipt_builder.record_plan_step(
            compiled_step.step_id,
            "assert",
            detail={
                "op": workflow_step.assert_spec.op,
                "left": left,
                "right": right,
                "message": workflow_step.assert_spec.message,
            },
        )
        receipt_builder.record_validation(
            passed=passed,
            detail={"message": workflow_step.assert_spec.message},
            parent_id=step_node,
        )
        if not passed:
            receipt = receipt_builder.build(results=[{"output": None}])
            store = instance.get_receipt_store()
            try:
                store.save_receipt(receipt)
            finally:
                store.close()
            raise QueryExecutionError(workflow_step.assert_spec.message)

    output = step_outputs[plan.returns]
    receipt_builder.record_results([{"output": output}])
    receipt = receipt_builder.build(results=[{"output": output}])
    store = instance.get_receipt_store()
    try:
        store.save_receipt(receipt)
    finally:
        store.close()

    return WorkflowExecutionResult(
        workflow=workflow_name,
        output=output,
        receipt=receipt,
        query_receipt_ids=query_receipt_ids,
        traces=traces,
    )


def _persist_trace(instance: InstanceProtocol, trace: ExecutionTrace) -> None:
    store = instance.get_receipt_store()
    try:
        store.save_trace(trace)
    finally:
        store.close()


def _build_trace(
    *,
    workflow_name: str,
    step_id: str,
    provider_name: str,
    provider_version: str,
    provider_ref: str,
    runtime: str,
    deterministic: bool,
    side_effects: bool,
    artifact_name: str | None,
    artifact_sha256: str | None,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    status: str,
    error: str | None,
    duration_ms: float,
) -> ExecutionTrace:
    return ExecutionTrace(
        workflow_name=workflow_name,
        step_id=step_id,
        provider_name=provider_name,
        provider_version=provider_version,
        provider_ref=provider_ref,
        runtime=runtime,
        deterministic=deterministic,
        side_effects=side_effects,
        artifact_name=artifact_name,
        artifact_sha256=artifact_sha256,
        input_payload=input_payload,
        output_payload=output_payload,
        status=status,
        error=error,
        duration_ms=round(duration_ms, 3),
    )


def _evaluate_assert(left: Any, op: str, right: Any) -> bool:
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    raise ConfigError(f"Unsupported assert op '{op}'")
