"""Runtime types for governed entity change proposals."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EntityChangeMember(BaseModel):
    """A proposed create or patch operation for one entity."""

    entity_type: str
    entity_id: str
    operation: Literal["create", "patch"]
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityChangeProposal(BaseModel):
    """A batch proposal for governed entity changes."""

    proposal_id: str
    status: Literal["pending_review", "applying", "resolved"] = "pending_review"
    thesis_text: str = ""
    thesis_facts: dict[str, Any] = Field(default_factory=dict)
    analysis_state: dict[str, Any] = Field(default_factory=dict)
    proposed_by: Literal["human", "ai_review"] = "ai_review"
    suggested_priority: str | None = None
    source_workflow_name: str | None = None
    source_workflow_receipt_id: str | None = None
    source_trace_ids: list[str] = Field(default_factory=list)
    source_step_ids: list[str] = Field(default_factory=list)
    member_count: int = 0
    resolution_id: str | None = None
    resolution: dict[str, Any] | None = None
    created_at: datetime
