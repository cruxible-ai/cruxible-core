"""Governed entity proposal routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from cruxible_core.mcp import contracts
from cruxible_core.mcp.handlers import (
    _handle_get_entity_proposal_local,
    _handle_list_entity_proposals_local,
    _handle_propose_entity_changes_local,
    _handle_resolve_entity_proposal_local,
)
from cruxible_core.server.request_models import (
    ProposeEntityChangesRequest,
    ResolveEntityProposalRequest,
)
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["entity-proposals"])


@router.post(
    "/{instance_id}/entity-proposals",
    response_model=contracts.ProposeEntityChangesToolResult,
)
async def propose_entity_changes(
    instance_id: str,
    req: ProposeEntityChangesRequest,
) -> contracts.ProposeEntityChangesToolResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_propose_entity_changes_local(
        instance_id=resolved_instance_id,
        members=req.members,
        thesis_text=req.thesis_text,
        thesis_facts=req.thesis_facts,
        analysis_state=req.analysis_state,
        proposed_by=req.proposed_by,
        suggested_priority=req.suggested_priority,
        source_workflow_name=req.source_workflow_name,
        source_workflow_receipt_id=req.source_workflow_receipt_id,
        source_trace_ids=req.source_trace_ids,
        source_step_ids=req.source_step_ids,
    )


@router.get(
    "/{instance_id}/entity-proposals/{proposal_id}",
    response_model=contracts.GetEntityProposalToolResult,
)
async def get_entity_proposal(
    instance_id: str,
    proposal_id: str,
) -> contracts.GetEntityProposalToolResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_get_entity_proposal_local(
        instance_id=resolved_instance_id,
        proposal_id=proposal_id,
    )


@router.get(
    "/{instance_id}/entity-proposals",
    response_model=contracts.ListEntityProposalsToolResult,
)
async def list_entity_proposals(
    instance_id: str,
    status: contracts.EntityProposalStatus | None = Query(default=None),
    limit: int = Query(default=50),
) -> contracts.ListEntityProposalsToolResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_list_entity_proposals_local(
        instance_id=resolved_instance_id,
        status=status,
        limit=limit,
    )


@router.post(
    "/{instance_id}/entity-proposals/{proposal_id}/resolve",
    response_model=contracts.ResolveEntityProposalToolResult,
)
async def resolve_entity_proposal(
    instance_id: str,
    proposal_id: str,
    req: ResolveEntityProposalRequest,
) -> contracts.ResolveEntityProposalToolResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_resolve_entity_proposal_local(
        instance_id=resolved_instance_id,
        proposal_id=proposal_id,
        action=req.action,
        rationale=req.rationale,
        resolved_by=req.resolved_by,
    )
