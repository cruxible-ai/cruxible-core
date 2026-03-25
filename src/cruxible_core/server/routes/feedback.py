"""Feedback and outcome routes."""

from __future__ import annotations

from fastapi import APIRouter

from cruxible_core.mcp import contracts
from cruxible_core.runtime import local_api
from cruxible_core.server.request_models import (
    AnalyzeFeedbackRequest,
    FeedbackBatchRequest,
    FeedbackRequest,
    OutcomeRequest,
)
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["feedback"])


@router.post("/{instance_id}/feedback", response_model=contracts.FeedbackResult)
async def feedback(instance_id: str, req: FeedbackRequest) -> contracts.FeedbackResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_feedback_local(
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
        reason_code=req.reason_code,
        scope_hints=req.scope_hints,
        corrections=req.corrections,
        group_override=req.group_override,
    )


@router.post("/{instance_id}/feedback/batch", response_model=contracts.FeedbackBatchResult)
async def feedback_batch(
    instance_id: str,
    req: FeedbackBatchRequest,
) -> contracts.FeedbackBatchResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_feedback_batch_local(
        instance_id=resolved_instance_id,
        items=req.items,
        source=req.source,
    )


@router.post(
    "/{instance_id}/feedback/analyze",
    response_model=contracts.AnalyzeFeedbackResult,
)
async def analyze_feedback(
    instance_id: str,
    req: AnalyzeFeedbackRequest,
) -> contracts.AnalyzeFeedbackResult:
    return local_api._handle_analyze_feedback_local(
        instance_id=resolve_server_instance_id(instance_id),
        relationship_type=req.relationship_type,
        limit=req.limit,
        min_support=req.min_support,
        decision_surface_type=req.decision_surface_type,
        decision_surface_name=req.decision_surface_name,
        property_pairs=req.property_pairs,
    )


@router.get(
    "/{instance_id}/feedback/profiles/{relationship_type}",
    response_model=contracts.FeedbackProfileResult,
)
async def get_feedback_profile(
    instance_id: str,
    relationship_type: str,
) -> contracts.FeedbackProfileResult:
    return local_api._handle_get_feedback_profile_local(
        instance_id=resolve_server_instance_id(instance_id),
        relationship_type=relationship_type,
    )


@router.post("/{instance_id}/outcome", response_model=contracts.OutcomeResult)
async def outcome(instance_id: str, req: OutcomeRequest) -> contracts.OutcomeResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_outcome_local(
        instance_id=resolved_instance_id,
        receipt_id=req.receipt_id,
        outcome=req.outcome,
        detail=req.detail,
    )
