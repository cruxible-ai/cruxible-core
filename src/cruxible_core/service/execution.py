"""Workflow execution service functions."""

from __future__ import annotations

from typing import Any

from cruxible_core.errors import ConfigError, QueryExecutionError
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.service.types import (
    LockServiceResult,
    PlanServiceResult,
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
from cruxible_core.workflow.types import WorkflowTestCaseResult


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
