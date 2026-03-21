"""Workflow execution service functions."""

from __future__ import annotations

from typing import Any

from cruxible_core.errors import ConfigError, QueryExecutionError
from cruxible_core.group.types import CandidateMember
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.service.groups import service_propose_group
from cruxible_core.service.types import (
    LockServiceResult,
    PlanServiceResult,
    ProposeWorkflowResult,
    RunServiceResult,
    TestServiceResult,
)
from cruxible_core.workflow import (
    build_lock,
    compile_workflow,
    execute_workflow,
    get_lock_path,
    load_lock,
    write_lock,
)
from cruxible_core.workflow.types import RelationshipGroupProposalPayload, WorkflowTestCaseResult


def service_lock(instance: InstanceProtocol) -> LockServiceResult:
    """Generate and persist a workflow lock file for the instance config."""
    config = instance.load_config()
    lock = build_lock(config)
    lock_path = get_lock_path(instance)
    write_lock(lock, lock_path)
    return LockServiceResult(
        lock_path=str(lock_path),
        config_digest=lock.config_digest,
        providers_locked=len(lock.providers),
        artifacts_locked=len(lock.artifacts),
    )


def service_plan(
    instance: InstanceProtocol,
    workflow_name: str,
    input_payload: dict[str, Any],
) -> PlanServiceResult:
    """Compile a workflow plan using the current config and generated lock."""
    config = instance.load_config()
    lock = load_lock(get_lock_path(instance))
    plan = compile_workflow(config, lock, workflow_name, input_payload)
    return PlanServiceResult(plan=plan)


def service_run(
    instance: InstanceProtocol,
    workflow_name: str,
    input_payload: dict[str, Any],
) -> RunServiceResult:
    """Execute a workflow and return output plus receipt/trace identifiers."""
    config = instance.load_config()
    result = execute_workflow(instance, config, workflow_name, input_payload)
    return RunServiceResult(
        workflow=result.workflow,
        output=result.output,
        receipt_id=result.receipt.receipt_id,
        query_receipt_ids=result.query_receipt_ids,
        trace_ids=[trace.trace_id for trace in result.traces],
        receipt=result.receipt,
        traces=result.traces,
    )


def service_propose_workflow(
    instance: InstanceProtocol,
    workflow_name: str,
    input_payload: dict[str, Any],
) -> ProposeWorkflowResult:
    """Execute a workflow and bridge its declared output into a candidate group."""
    config = instance.load_config()
    workflow = config.workflows.get(workflow_name)
    if workflow is None:
        raise ConfigError(f"Workflow '{workflow_name}' not found in workflows")
    if workflow.proposal_output is None:
        raise ConfigError(
            f"Workflow '{workflow_name}' does not declare proposal_output and cannot propose state"
        )
    if workflow.proposal_output.kind != "relationship_group":
        raise ConfigError(
            "Workflow "
            f"'{workflow_name}' proposal_output kind '{workflow.proposal_output.kind}' "
            "is not supported"
        )

    result = execute_workflow(instance, config, workflow_name, input_payload)
    source_alias = workflow.proposal_output.source_alias or workflow.returns
    if source_alias not in result.step_outputs:
        raise QueryExecutionError(
            f"Workflow '{workflow_name}' proposal source alias '{source_alias}' was not produced"
        )

    proposal_payload = RelationshipGroupProposalPayload.model_validate(
        result.step_outputs[source_alias]
    )
    relationship_type = workflow.proposal_output.relationship_type
    members = [
        CandidateMember(
            from_type=member.from_type,
            from_id=member.from_id,
            to_type=member.to_type,
            to_id=member.to_id,
            relationship_type=relationship_type,
            signals=member.signals,
            properties=member.properties,
        )
        for member in proposal_payload.members
    ]

    source_step_id = result.alias_step_ids.get(source_alias)
    source_trace_ids = result.step_trace_ids.get(source_step_id, []) if source_step_id else []
    group_result = service_propose_group(
        instance,
        relationship_type,
        members,
        thesis_text=proposal_payload.thesis_text,
        thesis_facts=proposal_payload.thesis_facts,
        analysis_state=proposal_payload.analysis_state,
        integrations_used=proposal_payload.integrations_used,
        proposed_by=workflow.proposal_output.proposed_by,
        suggested_priority=proposal_payload.suggested_priority,
        source_workflow_name=workflow_name,
        source_workflow_receipt_id=result.receipt.receipt_id,
        source_trace_ids=source_trace_ids,
        source_step_ids=[source_step_id] if source_step_id is not None else [],
    )
    return ProposeWorkflowResult(
        workflow=result.workflow,
        output=result.output,
        receipt_id=result.receipt.receipt_id,
        group_id=group_result.group_id,
        group_status=group_result.status,
        review_priority=group_result.review_priority,
        query_receipt_ids=result.query_receipt_ids,
        trace_ids=[trace.trace_id for trace in result.traces],
        prior_resolution=group_result.prior_resolution,
        receipt=result.receipt,
        traces=result.traces,
    )


def service_test(instance: InstanceProtocol, test_name: str | None = None) -> TestServiceResult:
    """Execute config-defined workflow tests."""
    config = instance.load_config()
    tests = config.tests
    if test_name is not None:
        tests = [test for test in tests if test.name == test_name]
        if not tests:
            raise ConfigError(f"Test '{test_name}' not found in config")
    if not tests:
        raise ConfigError("No workflow tests are defined in config")

    cases: list[WorkflowTestCaseResult] = []
    passed = 0

    for test in tests:
        try:
            result = execute_workflow(instance, config, test.workflow, test.input)
            _validate_test_expectation(
                test.expect.output_equals,
                result.output,
                test.name,
                "output_equals",
            )
            if test.expect.output_contains is not None:
                if not _contains_subset(result.output, test.expect.output_contains):
                    raise QueryExecutionError(
                        f"Test '{test.name}' failed: output does not contain expected subset"
                    )
            if test.expect.required_providers:
                providers_used = {trace.provider_name for trace in result.traces}
                missing = [
                    name for name in test.expect.required_providers if name not in providers_used
                ]
                if missing:
                    missing_str = ", ".join(missing)
                    raise QueryExecutionError(
                        f"Test '{test.name}' failed: missing provider evidence for {missing_str}"
                    )
            if test.expect.error_contains is not None:
                raise QueryExecutionError(
                    "Test "
                    f"'{test.name}' expected error containing "
                    f"'{test.expect.error_contains}' but run succeeded"
                )
        except Exception as exc:
            error_text = str(exc)
            expected_error = test.expect.error_contains
            if expected_error is not None and expected_error in error_text:
                passed += 1
                cases.append(
                    WorkflowTestCaseResult(
                        name=test.name,
                        workflow=test.workflow,
                        passed=True,
                        error=error_text,
                    )
                )
                continue
            cases.append(
                WorkflowTestCaseResult(
                    name=test.name,
                    workflow=test.workflow,
                    passed=False,
                    error=error_text,
                )
            )
            continue

        passed += 1
        cases.append(
            WorkflowTestCaseResult(
                name=test.name,
                workflow=test.workflow,
                passed=True,
                output=result.output,
                receipt_id=result.receipt.receipt_id,
            )
        )

    total = len(cases)
    return TestServiceResult(total=total, passed=passed, failed=total - passed, cases=cases)


def _validate_test_expectation(expected: Any, actual: Any, test_name: str, field_name: str) -> None:
    if expected is not None and actual != expected:
        raise QueryExecutionError(
            f"Test '{test_name}' failed: {field_name} expected {expected!r}, got {actual!r}"
        )


def _contains_subset(actual: Any, expected_subset: Any) -> bool:
    if isinstance(expected_subset, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and _contains_subset(actual[key], expected_value)
            for key, expected_value in expected_subset.items()
        )

    if isinstance(expected_subset, list):
        if not isinstance(actual, list) or len(expected_subset) > len(actual):
            return False
        return all(
            _contains_subset(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected_subset, strict=False)
        )

    return actual == expected_subset
