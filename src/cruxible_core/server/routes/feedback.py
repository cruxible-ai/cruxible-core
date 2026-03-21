"""Feedback and outcome routes."""

from __future__ import annotations

from fastapi import APIRouter

from cruxible_core.mcp import contracts
from cruxible_core.mcp.handlers import _handle_feedback_local, _handle_outcome_local
from cruxible_core.server.request_models import FeedbackRequest, OutcomeRequest
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["feedback"])


@router.post("/{instance_id}/feedback", response_model=contracts.FeedbackResult)
async def feedback(instance_id: str, req: FeedbackRequest) -> contracts.FeedbackResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_feedback_local(
        instance_id=resolved_instance_id,
        receipt_id=req.receipt_id,
        action=req.action,
        source=req.source,
        from_type=req.from_type,
        from_id=req.from_id,
        relationship=req.relationship,
        to_type=req.to_type,
        to_id=req.to_id,
        edge_key=req.edge_key,
        reason=req.reason,
        corrections=req.corrections,
        group_override=req.group_override,
    )


@router.post("/{instance_id}/outcome", response_model=contracts.OutcomeResult)
async def outcome(instance_id: str, req: OutcomeRequest) -> contracts.OutcomeResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_outcome_local(
        instance_id=resolved_instance_id,
        receipt_id=req.receipt_id,
        outcome=req.outcome,
        detail=req.detail,
    )
