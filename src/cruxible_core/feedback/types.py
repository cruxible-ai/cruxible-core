"""Feedback and outcome types for the learning loop."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    source: Literal["human", "ai_review", "system"] = "human"
    model_id: str | None = None
    corrections: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OutcomeRecord(BaseModel):
    """Record of what actually happened after a decision was made."""

    outcome_id: str = Field(default_factory=lambda: f"OUT-{uuid.uuid4().hex[:12]}")
    receipt_id: str
    outcome: Literal["correct", "incorrect", "partial", "unknown"]
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
