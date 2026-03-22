"""Workflow execution runtime."""

from __future__ import annotations

import time
from typing import Any

from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError, QueryExecutionError
from cruxible_core.group.types import CandidateSignal
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.provider.registry import resolve_provider
from cruxible_core.provider.types import ExecutionTrace, ProviderContext, ResolvedArtifact
from cruxible_core.query.engine import execute_query
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.workflow.compiler import compile_workflow, get_lock_path, load_lock
from cruxible_core.workflow.contracts import query_execution_error, validate_contract_payload
from cruxible_core.workflow.refs import resolve_value
from cruxible_core.workflow.types import (
    CandidateSet,
    CandidateSetMember,
    RelationshipGroupProposalArtifact,
    RelationshipGroupProposalMember,
    SignalBatch,
    SignalBatchSignal,
    WorkflowExecutionResult,
)


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
    alias_step_ids: dict[str, str] = {}
    step_trace_ids: dict[str, list[str]] = {}
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
            if compiled_step.as_name is not None:
                alias_step_ids[compiled_step.as_name] = compiled_step.step_id
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
                step_trace_ids.setdefault(compiled_step.step_id, []).append(trace.trace_id)
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
            step_trace_ids.setdefault(compiled_step.step_id, []).append(trace.trace_id)
            if compiled_step.as_name is not None:
                alias_step_ids[compiled_step.as_name] = compiled_step.step_id
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

        if compiled_step.kind == "make_candidates":
            candidate_set = _make_candidate_set(
                config,
                compiled_step.step_id,
                compiled_step.step_config,
                plan.input_payload,
                step_outputs,
            )
            step_outputs[compiled_step.as_name or compiled_step.step_id] = candidate_set.model_dump(
                mode="python"
            )
            if compiled_step.as_name is not None:
                alias_step_ids[compiled_step.as_name] = compiled_step.step_id
            receipt_builder.record_plan_step(
                compiled_step.step_id,
                "make_candidates",
                detail={
                    "relationship_type": candidate_set.relationship_type,
                    "candidate_count": len(candidate_set.candidates),
                    "item_count": len(
                        _resolve_step_items(
                            compiled_step.step_config,
                            plan.input_payload,
                            step_outputs,
                        )
                    ),
                },
            )
            continue

        if compiled_step.kind == "map_signals":
            signal_batch = _map_signal_batch(
                compiled_step.step_id,
                compiled_step.step_config,
                plan.input_payload,
                step_outputs,
            )
            step_outputs[compiled_step.as_name or compiled_step.step_id] = signal_batch.model_dump(
                mode="python"
            )
            if compiled_step.as_name is not None:
                alias_step_ids[compiled_step.as_name] = compiled_step.step_id
            receipt_builder.record_plan_step(
                compiled_step.step_id,
                "map_signals",
                detail={
                    "integration": signal_batch.integration,
                    "signal_count": len(signal_batch.signals),
                    "item_count": len(
                        _resolve_step_items(
                            compiled_step.step_config,
                            plan.input_payload,
                            step_outputs,
                        )
                    ),
                },
            )
            continue

        if compiled_step.kind == "propose_relationship_group":
            proposal = _build_relationship_group_proposal(
                compiled_step.step_id,
                compiled_step.step_config,
                plan.input_payload,
                step_outputs,
            )
            step_outputs[compiled_step.as_name or compiled_step.step_id] = proposal.model_dump(
                mode="python"
            )
            if compiled_step.as_name is not None:
                alias_step_ids[compiled_step.as_name] = compiled_step.step_id
            receipt_builder.record_plan_step(
                compiled_step.step_id,
                "propose_relationship_group",
                detail={
                    "relationship_type": proposal.relationship_type,
                    "candidates_from": compiled_step.step_config["candidates_from"],
                    "signals_from": compiled_step.step_config["signals_from"],
                    "member_count": len(proposal.members),
                    "integrations_used": proposal.integrations_used,
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
        step_outputs=step_outputs,
        alias_step_ids=alias_step_ids,
        step_trace_ids=step_trace_ids,
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


def _resolve_step_items(
    step_config: dict[str, Any],
    input_payload: dict[str, Any],
    step_outputs: dict[str, Any],
) -> list[Any]:
    items = resolve_value(step_config["items"], input_payload, step_outputs)
    if not isinstance(items, list):
        raise QueryExecutionError("Built-in workflow step 'items' must resolve to a list")
    return items


def _make_candidate_set(
    config: CoreConfig,
    step_id: str,
    step_config: dict[str, Any],
    input_payload: dict[str, Any],
    step_outputs: dict[str, Any],
) -> CandidateSet:
    relationship_type = step_config["relationship_type"]
    rel_schema = config.get_relationship(relationship_type)
    if rel_schema is None:
        raise QueryExecutionError(
            f"Workflow step '{step_id}' references unknown relationship '{relationship_type}'"
        )

    items = _resolve_step_items(step_config, input_payload, step_outputs)
    seen: set[tuple[str, str, str, str]] = set()
    candidates: list[CandidateSetMember] = []

    for item in items:
        member = CandidateSetMember.model_validate(
            {
                "from_type": resolve_value(
                    step_config["from_type"],
                    input_payload,
                    step_outputs,
                    item_payload=item,
                    allow_item=True,
                ),
                "from_id": resolve_value(
                    step_config["from_id"],
                    input_payload,
                    step_outputs,
                    item_payload=item,
                    allow_item=True,
                ),
                "to_type": resolve_value(
                    step_config["to_type"],
                    input_payload,
                    step_outputs,
                    item_payload=item,
                    allow_item=True,
                ),
                "to_id": resolve_value(
                    step_config["to_id"],
                    input_payload,
                    step_outputs,
                    item_payload=item,
                    allow_item=True,
                ),
                "properties": resolve_value(
                    step_config.get("properties", {}),
                    input_payload,
                    step_outputs,
                    item_payload=item,
                    allow_item=True,
                ),
            }
        )
        if member.from_type != rel_schema.from_entity or member.to_type != rel_schema.to_entity:
            raise QueryExecutionError(
                f"Workflow step '{step_id}' produced candidate types "
                f"{member.from_type}->{member.to_type} which do not match "
                "relationship "
                f"'{relationship_type}' "
                f"({rel_schema.from_entity}->{rel_schema.to_entity})"
            )
        key = (member.from_type, member.from_id, member.to_type, member.to_id)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(member)

    return CandidateSet(relationship_type=relationship_type, candidates=candidates)


def _map_signal_batch(
    step_id: str,
    step_config: dict[str, Any],
    input_payload: dict[str, Any],
    step_outputs: dict[str, Any],
) -> SignalBatch:
    items = _resolve_step_items(step_config, input_payload, step_outputs)
    seen_pairs: set[tuple[str, str]] = set()
    signals: list[SignalBatchSignal] = []

    for item in items:
        from_id = str(
            resolve_value(
                step_config["from_id"],
                input_payload,
                step_outputs,
                item_payload=item,
                allow_item=True,
            )
        )
        to_id = str(
            resolve_value(
                step_config["to_id"],
                input_payload,
                step_outputs,
                item_payload=item,
                allow_item=True,
            )
        )
        key = (from_id, to_id)
        if key in seen_pairs:
            raise QueryExecutionError(
                f"Workflow step '{step_id}' produced duplicate signal for pair {from_id}->{to_id}"
            )

        evidence = ""
        if "evidence" in step_config:
            resolved_evidence = resolve_value(
                step_config["evidence"],
                input_payload,
                step_outputs,
                item_payload=item,
                allow_item=True,
            )
            if resolved_evidence is not None:
                evidence = str(resolved_evidence)

        if "score" in step_config:
            score_spec = step_config["score"]
            score_value = resolve_value(
                f"$item.{score_spec['path']}",
                input_payload,
                step_outputs,
                item_payload=item,
                allow_item=True,
            )
            if isinstance(score_value, bool) or not isinstance(score_value, (int, float)):
                raise QueryExecutionError(
                    f"Workflow step '{step_id}' score path '{score_spec['path']}' "
                    "must resolve to a number"
                )
            numeric_score = float(score_value)
            if numeric_score >= float(score_spec["support_gte"]):
                signal = "support"
            elif numeric_score >= float(score_spec["unsure_gte"]):
                signal = "unsure"
            else:
                signal = "contradict"
        else:
            enum_spec = step_config["enum"]
            enum_value = resolve_value(
                f"$item.{enum_spec['path']}",
                input_payload,
                step_outputs,
                item_payload=item,
                allow_item=True,
            )
            if not isinstance(enum_value, str):
                raise QueryExecutionError(
                    f"Workflow step '{step_id}' enum path '{enum_spec['path']}' "
                    "must resolve to a string"
                )
            if enum_value not in enum_spec["map"]:
                raise QueryExecutionError(
                    f"Workflow step '{step_id}' enum path '{enum_spec['path']}' returned "
                    f"unknown value '{enum_value}'"
                )
            signal = enum_spec["map"][enum_value]

        signals.append(
            SignalBatchSignal(
                from_id=from_id,
                to_id=to_id,
                signal=signal,
                evidence=evidence,
            )
        )
        seen_pairs.add(key)

    return SignalBatch(integration=step_config["integration"], signals=signals)


def _build_relationship_group_proposal(
    step_id: str,
    step_config: dict[str, Any],
    input_payload: dict[str, Any],
    step_outputs: dict[str, Any],
) -> RelationshipGroupProposalArtifact:
    candidate_set = CandidateSet.model_validate(step_outputs[step_config["candidates_from"]])
    relationship_type = step_config["relationship_type"]
    if candidate_set.relationship_type != relationship_type:
        raise QueryExecutionError(
            f"Workflow step '{step_id}' expected candidate relationship '{relationship_type}' "
            f"but received '{candidate_set.relationship_type}'"
        )

    members_by_pair: dict[tuple[str, str], RelationshipGroupProposalMember] = {
        (candidate.from_id, candidate.to_id): RelationshipGroupProposalMember(
            from_type=candidate.from_type,
            from_id=candidate.from_id,
            to_type=candidate.to_type,
            to_id=candidate.to_id,
            properties=candidate.properties,
        )
        for candidate in candidate_set.candidates
    }

    integrations_used: list[str] = []
    for alias in step_config["signals_from"]:
        signal_batch = SignalBatch.model_validate(step_outputs[alias])
        integrations_used.append(signal_batch.integration)
        for signal in signal_batch.signals:
            key = (signal.from_id, signal.to_id)
            if key not in members_by_pair:
                raise QueryExecutionError(
                    f"Workflow step '{step_id}' received signal for unknown candidate pair "
                    f"{signal.from_id}->{signal.to_id}"
                )
            member = members_by_pair[key]
            if any(existing.integration == signal_batch.integration for existing in member.signals):
                raise QueryExecutionError(
                    f"Workflow step '{step_id}' produced duplicate integration "
                    f"'{signal_batch.integration}' for pair {signal.from_id}->{signal.to_id}"
                )
            member.signals.append(
                CandidateSignal(
                    integration=signal_batch.integration,
                    signal=signal.signal,
                    evidence=signal.evidence,
                )
            )

    return RelationshipGroupProposalArtifact.model_validate(
        {
            "relationship_type": relationship_type,
            "members": [member.model_dump(mode="python") for member in members_by_pair.values()],
            "thesis_text": resolve_value(
                step_config.get("thesis_text", ""),
                input_payload,
                step_outputs,
            ),
            "thesis_facts": resolve_value(
                step_config.get("thesis_facts", {}),
                input_payload,
                step_outputs,
            ),
            "analysis_state": resolve_value(
                step_config.get("analysis_state", {}),
                input_payload,
                step_outputs,
            ),
            "integrations_used": integrations_used,
            "suggested_priority": resolve_value(
                step_config.get("suggested_priority"),
                input_payload,
                step_outputs,
            ),
            "proposed_by": step_config.get("proposed_by", "ai_review"),
        }
    )
