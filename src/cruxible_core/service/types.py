"""Input and result types for the service layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cruxible_core.config.schema import CoreConfig
from cruxible_core.graph.types import EntityInstance
from cruxible_core.group.types import CandidateGroup, CandidateMember
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.provider.types import ExecutionTrace
from cruxible_core.receipt.types import Receipt
from cruxible_core.snapshot.types import WorldSnapshot
from cruxible_core.workflow.types import CompiledPlan, WorkflowTestCaseResult

# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------


@dataclass
class EntityUpsertInput:
    """Service-layer input for entity upsert operations."""

    entity_type: str
    entity_id: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipUpsertInput:
    """Service-layer input for relationship upsert operations."""

    from_type: str
    from_id: str
    relationship: str
    to_type: str
    to_id: str
    properties: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AddEntityResult:
    added: int
    updated: int
    receipt_id: str | None = None


@dataclass
class AddRelationshipResult:
    added: int
    updated: int
    receipt_id: str | None = None


@dataclass
class IngestResult:
    records_ingested: int
    records_updated: int
    mapping: str
    entity_type: str | None
    relationship_type: str | None
    receipt_id: str | None = None


@dataclass
class ValidateServiceResult:
    config: CoreConfig
    warnings: list[str]


@dataclass
class QueryParamHints:
    entry_point: str
    required_params: list[str] = field(default_factory=list)
    primary_key: str | None = None
    example_ids: list[str] = field(default_factory=list)


@dataclass
class QueryServiceResult:
    results: list[EntityInstance]
    receipt_id: str | None
    receipt: Receipt | None
    total_results: int
    steps_executed: int
    param_hints: QueryParamHints | None = None


@dataclass
class StatsServiceResult:
    entity_count: int
    edge_count: int
    entity_counts: dict[str, int] = field(default_factory=dict)
    relationship_counts: dict[str, int] = field(default_factory=dict)
    head_snapshot_id: str | None = None


@dataclass
class InspectNeighborResult:
    direction: str
    relationship_type: str
    edge_key: int | None
    properties: dict[str, Any] = field(default_factory=dict)
    entity: EntityInstance | None = None


@dataclass
class InspectEntityResult:
    found: bool
    entity_type: str
    entity_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    neighbors: list[InspectNeighborResult] = field(default_factory=list)
    total_neighbors: int = 0


@dataclass
class ReloadConfigResult:
    config_path: str
    updated: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class FeedbackServiceResult:
    feedback_id: str
    applied: bool
    receipt_id: str | None = None


@dataclass
class FeedbackBatchServiceResult:
    feedback_ids: list[str] = field(default_factory=list)
    applied_count: int = 0
    total: int = 0
    receipt_id: str | None = None


@dataclass
class OutcomeServiceResult:
    outcome_id: str


@dataclass
class InitResult:
    instance: InstanceProtocol
    warnings: list[str]


@dataclass
class ListResult:
    items: list[Any]
    total: int


@dataclass
class LockServiceResult:
    lock_path: str
    config_digest: str
    providers_locked: int
    artifacts_locked: int


@dataclass
class PlanServiceResult:
    plan: CompiledPlan


@dataclass
class WorkflowExecutionServiceResult:
    workflow: str
    output: Any
    receipt_id: str
    mode: str
    canonical: bool
    apply_digest: str | None = None
    head_snapshot_id: str | None = None
    committed_snapshot_id: str | None = None
    apply_previews: dict[str, Any] = field(default_factory=dict)
    query_receipt_ids: list[str] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)
    receipt: Receipt | None = None
    traces: list[ExecutionTrace] = field(default_factory=list)


@dataclass
class RunServiceResult(WorkflowExecutionServiceResult):
    mode: str = "run"
    canonical: bool = False


@dataclass
class ApplyWorkflowResult(WorkflowExecutionServiceResult):
    mode: str = "apply"
    canonical: bool = True


@dataclass
class TestServiceResult:
    total: int
    passed: int
    failed: int
    cases: list[WorkflowTestCaseResult] = field(default_factory=list)


@dataclass
class ProposeWorkflowResult:
    workflow: str
    output: Any
    receipt_id: str
    group_id: str
    group_status: str
    review_priority: str
    query_receipt_ids: list[str] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)
    prior_resolution: dict[str, Any] | None = None
    receipt: Receipt | None = None
    traces: list[ExecutionTrace] = field(default_factory=list)


@dataclass
class SnapshotCreateResult:
    snapshot: WorldSnapshot


@dataclass
class SnapshotListResult:
    snapshots: list[WorldSnapshot] = field(default_factory=list)


@dataclass
class ForkSnapshotResult:
    instance: InstanceProtocol
    snapshot: WorldSnapshot


# ---------------------------------------------------------------------------
# Group result types
# ---------------------------------------------------------------------------


@dataclass
class ProposeGroupResult:
    group_id: str
    signature: str
    status: str
    review_priority: str
    member_count: int
    prior_resolution: dict[str, Any] | None


@dataclass
class ResolveGroupResult:
    group_id: str
    action: str
    edges_created: int
    edges_skipped: int
    resolution_id: str | None = None
    receipt_id: str | None = None


@dataclass
class GetGroupResult:
    group: CandidateGroup
    members: list[CandidateMember]


@dataclass
class ListGroupsResult:
    groups: list[CandidateGroup]
    total: int


@dataclass
class ListResolutionsResult:
    resolutions: list[dict[str, Any]]
    total: int
