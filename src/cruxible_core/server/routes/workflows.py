"""Workflow execution and proposal routes."""

from __future__ import annotations

from fastapi import APIRouter

from cruxible_core.mcp import contracts
from cruxible_core.mcp.handlers import (
    _handle_propose_workflow_local,
    _handle_workflow_lock_local,
    _handle_workflow_plan_local,
    _handle_workflow_run_local,
    _handle_workflow_test_local,
)
from cruxible_core.server.request_models import WorkflowInputRequest, WorkflowTestRequest
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["workflows"])


@router.post("/{instance_id}/workflows/lock", response_model=contracts.WorkflowLockResult)
async def workflow_lock(instance_id: str) -> contracts.WorkflowLockResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_workflow_lock_local(resolved_instance_id)


@router.post("/{instance_id}/workflows/plan", response_model=contracts.WorkflowPlanResult)
async def workflow_plan(
    instance_id: str,
    req: WorkflowInputRequest,
) -> contracts.WorkflowPlanResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_workflow_plan_local(
        resolved_instance_id,
        req.workflow_name,
        req.input,
    )


@router.post("/{instance_id}/workflows/run", response_model=contracts.WorkflowRunResult)
async def workflow_run(
    instance_id: str,
    req: WorkflowInputRequest,
) -> contracts.WorkflowRunResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_workflow_run_local(
        resolved_instance_id,
        req.workflow_name,
        req.input,
    )


@router.post("/{instance_id}/workflows/test", response_model=contracts.WorkflowTestResult)
async def workflow_test(
    instance_id: str,
    req: WorkflowTestRequest,
) -> contracts.WorkflowTestResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_workflow_test_local(resolved_instance_id, req.name)


@router.post("/{instance_id}/workflows/propose", response_model=contracts.WorkflowProposeResult)
async def workflow_propose(
    instance_id: str,
    req: WorkflowInputRequest,
) -> contracts.WorkflowProposeResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_propose_workflow_local(
        resolved_instance_id,
        req.workflow_name,
        req.input,
    )
