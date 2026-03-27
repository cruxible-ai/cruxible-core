"""Feedback and outcome types for the learning loop."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EdgeTarget(BaseModel):
    """Identifies a specific edge in the graph."""

    from_type: str
    from_id: str
    relationship: str
    to_type: str
    to_id: str
    edge_key: int | None = None


class FeedbackRecord(BaseModel):
    """Human or AI feedback on a query result or specific edge."""

    feedback_id: str = Field(default_factory=lambda: f"FB-{uuid.uuid4().hex[:12]}")
    receipt_id: str
    action: Literal["approve", "reject", "correct", "flag"]
    target: EdgeTarget
    reason: str = ""
    reason_code: str | None = None
    reason_remediation_hint: str | None = None
    scope_hints: dict[str, Any] = Field(default_factory=dict)
    feedback_profile_key: str | None = None
    feedback_profile_version: int | None = None
    decision_context: dict[str, Any] = Field(default_factory=dict)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    source: Literal["human", "ai_review", "system"] = "human"
    model_id: str | None = None
    corrections: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackBatchItem(BaseModel):
    """Input payload for one batch feedback item."""

    receipt_id: str
    action: Literal["approve", "reject", "correct", "flag"]
    target: EdgeTarget
    reason: str = ""
    reason_code: str | None = None
    scope_hints: dict[str, Any] = Field(default_factory=dict)
    corrections: dict[str, Any] = Field(default_factory=dict)
    group_override: bool = False


class OutcomeRecord(BaseModel):
    """Record of what actually happened after a decision was made."""

    outcome_id: str = Field(default_factory=lambda: f"OUT-{uuid.uuid4().hex[:12]}")
    receipt_id: str
    anchor_type: Literal["resolution", "receipt"] = "receipt"
    anchor_id: str | None = None
    outcome: Literal["correct", "incorrect", "partial", "unknown"]
    outcome_code: str | None = None
    outcome_remediation_hint: str | None = None
    scope_hints: dict[str, Any] = Field(default_factory=dict)
    outcome_profile_key: str | None = None
    outcome_profile_version: int | None = None
    decision_context: dict[str, Any] = Field(default_factory=dict)
    lineage_snapshot: dict[str, Any] = Field(default_factory=dict)
    relationship_type: str | None = None
    source: Literal["human", "ai_review", "system"] = "human"
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def default_anchor_id(self) -> OutcomeRecord:
        if self.anchor_type == "receipt" and self.anchor_id is None:
            self.anchor_id = self.receipt_id
        return self
