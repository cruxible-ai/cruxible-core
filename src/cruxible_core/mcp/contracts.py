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
EntityProposalStatus = Literal["pending_review", "applying", "resolved"]
EntityProposalAction = Literal["approve", "reject"]
EntityProposalResolvedBy = Literal["human", "ai_review"]
EntityChangeOperation = Literal["create", "patch"]


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


class EdgeTargetInput(BaseModel):
    from_type: str
    from_id: str
    relationship: str
    to_type: str
    to_id: str
    edge_key: int | None = None


class MemberInput(BaseModel):
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relationship_type: str
    signals: list[SignalInput] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class FeedbackBatchItemInput(BaseModel):
    receipt_id: str
    action: FeedbackAction
    target: EdgeTargetInput
    reason: str = ""
    corrections: dict[str, Any] | None = None
    group_override: bool = False


class EntityChangeInput(BaseModel):
    entity_type: str
    entity_id: str
    operation: EntityChangeOperation
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
    receipt_id: str | None = None


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
    receipt_id: str | None = None


class FeedbackBatchResult(BaseModel):
    feedback_ids: list[str] = Field(default_factory=list)
    applied_count: int
    total: int
    receipt_id: str | None = None


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
    receipt_id: str | None = None


class AddEntityResult(BaseModel):
    entities_added: int
    entities_updated: int
    receipt_id: str | None = None


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


class WorkflowLockResult(BaseModel):
    lock_path: str
    config_digest: str
    providers_locked: int
    artifacts_locked: int


class WorkflowPlanResult(BaseModel):
    plan: dict[str, Any]


class WorkflowRunResult(BaseModel):
    workflow: str
    output: Any
    receipt_id: str
    mode: str = "run"
    canonical: bool = False
    apply_digest: str | None = None
    head_snapshot_id: str | None = None
    committed_snapshot_id: str | None = None
    apply_previews: dict[str, Any] = Field(default_factory=dict)
    query_receipt_ids: list[str] = Field(default_factory=list)
    trace_ids: list[str] = Field(default_factory=list)
    receipt: dict[str, Any] | None = None
    traces: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowApplyResult(BaseModel):
    workflow: str
    output: Any
    receipt_id: str
    mode: str = "apply"
    canonical: bool = True
    apply_digest: str | None = None
    head_snapshot_id: str | None = None
    committed_snapshot_id: str | None = None
    apply_previews: dict[str, Any] = Field(default_factory=dict)
    query_receipt_ids: list[str] = Field(default_factory=list)
    trace_ids: list[str] = Field(default_factory=list)
    receipt: dict[str, Any] | None = None
    traces: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowTestCaseResult(BaseModel):
    name: str
    workflow: str
    passed: bool
    output: Any | None = None
    receipt_id: str | None = None
    error: str | None = None


class WorkflowTestResult(BaseModel):
    total: int
    passed: int
    failed: int
    cases: list[WorkflowTestCaseResult] = Field(default_factory=list)


class WorkflowProposeResult(BaseModel):
    workflow: str
    output: Any
    receipt_id: str
    group_id: str
    group_status: str
    review_priority: str
    query_receipt_ids: list[str] = Field(default_factory=list)
    trace_ids: list[str] = Field(default_factory=list)
    prior_resolution: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    traces: list[dict[str, Any]] = Field(default_factory=list)


class SnapshotMetadata(BaseModel):
    snapshot_id: str
    created_at: str
    label: str | None = None
    config_digest: str
    lock_digest: str | None = None
    graph_sha256: str
    parent_snapshot_id: str | None = None
    origin_snapshot_id: str | None = None


class SnapshotCreateResult(BaseModel):
    snapshot: SnapshotMetadata


class SnapshotListResult(BaseModel):
    snapshots: list[SnapshotMetadata] = Field(default_factory=list)


class ForkSnapshotResult(BaseModel):
    instance_id: str
    snapshot: SnapshotMetadata


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
    resolution_id: str | None = None
    receipt_id: str | None = None


class ProposeEntityChangesToolResult(BaseModel):
    proposal_id: str
    status: str
    member_count: int


class GetEntityProposalToolResult(BaseModel):
    proposal: dict[str, Any]
    members: list[dict[str, Any]] = Field(default_factory=list)


class ListEntityProposalsToolResult(BaseModel):
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    total: int


class ResolveEntityProposalToolResult(BaseModel):
    proposal_id: str
    action: str
    entities_created: int
    entities_patched: int
    resolution_id: str | None = None
    receipt_id: str | None = None


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
