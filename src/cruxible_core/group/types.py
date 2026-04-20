"""Runtime types for candidate group resolve."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from cruxible_core.graph.types import RelationshipInstance

SignalValue = Literal["support", "contradict", "unsure"]
"""Tri-state signal value produced by an integration about a candidate."""


class CandidateSignal(BaseModel):
    """Tri-state signal from an integration. Replaces vibed confidence scores."""

    integration: str
    signal: SignalValue
    evidence: str = ""


class CandidateMember(RelationshipInstance):
    """A candidate edge within a group proposal.

    Extends ``RelationshipInstance`` with integration signals. ``edge_key``
    is inherited but stays ``None`` for candidates since the edge does not
    yet exist in the graph.
    """

    signals: list[CandidateSignal] = Field(default_factory=list)


class GroupResolution(BaseModel):
    """Persisted resolution of a candidate group (approve or reject)."""

    resolution_id: str  # RES-{uuid[:12]}
    relationship_type: str
    group_signature: str
    action: Literal["approve", "reject"]
    rationale: str = ""
    thesis_text: str = ""
    thesis_facts: dict[str, Any] = Field(default_factory=dict)
    analysis_state: dict[str, Any] = Field(default_factory=dict)
    trust_status: Literal["trusted", "watch", "invalidated"] = "watch"
    trust_reason: str = ""
    confirmed: bool = False
    resolved_by: Literal["human", "agent"] = "human"
    resolved_at: datetime


class CandidateGroup(BaseModel):
    """A group of candidate edges proposed before they exist in the graph."""

    group_id: str  # GRP-{uuid[:12]}
    relationship_type: str
    signature: str
    status: Literal["pending_review", "auto_resolved", "applying", "resolved"] = "pending_review"
    thesis_text: str = ""
    thesis_facts: dict[str, Any] = Field(default_factory=dict)
    analysis_state: dict[str, Any] = Field(default_factory=dict)
    integrations_used: list[str] = Field(default_factory=list)
    proposed_by: Literal["human", "agent"] = "agent"
    member_count: int = 0
    review_priority: Literal["critical", "review", "normal"] = "normal"
    suggested_priority: str | None = None
    source_workflow_name: str | None = None
    source_workflow_receipt_id: str | None = None
    source_trace_ids: list[str] = Field(default_factory=list)
    source_step_ids: list[str] = Field(default_factory=list)
    resolution_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
