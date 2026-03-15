"""Shared Pydantic contracts for MCP tools.

Single source of truth for tool return shapes and constrained input types.
Both handlers.py and tools.py import from here.
FastMCP auto-generates outputSchema from the BaseModel return annotations.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Constrained input types ───────────────────────────────────────────

ConstraintSeverity = Literal["warning", "error"]
FeedbackAction = Literal["approve", "reject", "correct", "flag"]
FeedbackSource = Literal["human", "ai_review", "system"]
OutcomeValue = Literal["correct", "incorrect", "partial", "unknown"]
ResourceType = Literal["entities", "edges", "receipts", "feedback", "outcomes"]
CandidateStrategy = Literal["property_match", "shared_neighbors"]
GroupAction = Literal["approve", "reject"]
GroupResolvedBy = Literal["human", "ai_review"]
GroupStatus = Literal["pending_review", "auto_resolved", "applying", "resolved"]
GroupProposedBy = Literal["human", "ai_review"]
GroupTrustStatus = Literal["trusted", "watch", "invalidated"]


# ── Structured input types ───────────────────────────────────────────


class RelationshipInput(BaseModel):
    from_type: str
    from_id: str
    relationship: str
    to_type: str
    to_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityInput(BaseModel):
    entity_type: str
    entity_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class SignalInput(BaseModel):
    integration: str
    signal: Literal["support", "contradict", "unsure"]
    evidence: str = ""


class MemberInput(BaseModel):
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relationship_type: str
    signals: list[SignalInput] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


# ── Tool return contracts ─────────────────────────────────────────────


class InitResult(BaseModel):
    instance_id: str
    status: str
    warnings: list[str] = Field(default_factory=list)


class ValidateResult(BaseModel):
    valid: bool
    name: str
    entity_types: list[str]
    relationships: list[str]
    named_queries: list[str]
    warnings: list[str]


class IngestResult(BaseModel):
    records_ingested: int
    records_updated: int = 0
    mapping: str
    entity_type: str | None
    relationship_type: str | None


class QueryToolResult(BaseModel):
    results: list[dict[str, Any]]
    receipt_id: str | None
    receipt: dict[str, Any] | None
    total_results: int
    truncated: bool = False
    steps_executed: int


class FeedbackResult(BaseModel):
    feedback_id: str
    applied: bool


class OutcomeResult(BaseModel):
    outcome_id: str


class ListResult(BaseModel):
    items: list[dict[str, Any]]
    total: int


class CandidatesResult(BaseModel):
    candidates: list[dict[str, Any]]
    total: int


class EvaluateResult(BaseModel):
    entity_count: int
    edge_count: int
    findings: list[dict[str, Any]]
    summary: dict[str, int]


class SampleResult(BaseModel):
    entities: list[dict[str, Any]]
    entity_type: str
    count: int


class AddRelationshipResult(BaseModel):
    added: int
    updated: int


class AddEntityResult(BaseModel):
    entities_added: int
    entities_updated: int


class AddConstraintResult(BaseModel):
    name: str
    added: bool
    config_updated: bool
    warnings: list[str] = Field(default_factory=list)


class GetEntityResult(BaseModel):
    found: bool
    entity_type: str
    entity_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GetRelationshipResult(BaseModel):
    found: bool
    from_type: str
    from_id: str
    relationship_type: str
    to_type: str
    to_id: str
    edge_key: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ProposeGroupToolResult(BaseModel):
    group_id: str
    signature: str
    status: str
    review_priority: str
    member_count: int
    prior_resolution: dict[str, Any] | None = None


class ResolveGroupToolResult(BaseModel):
    group_id: str
    action: str
    edges_created: int
    edges_skipped: int


class UpdateTrustStatusToolResult(BaseModel):
    resolution_id: str
    trust_status: str


class GetGroupToolResult(BaseModel):
    group: dict[str, Any]
    members: list[dict[str, Any]]


class ListGroupsToolResult(BaseModel):
    groups: list[dict[str, Any]]
    total: int


class ListResolutionsToolResult(BaseModel):
    resolutions: list[dict[str, Any]]
    total: int
