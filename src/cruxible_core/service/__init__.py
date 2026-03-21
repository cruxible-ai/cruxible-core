"""Shared service layer — the execution contract behind CLI, MCP, and REST/SDK.

Every product operation goes through this package. Callers (CLI commands, MCP
handlers, REST endpoints) are thin wrappers that handle I/O formatting,
permission checks, and protocol-specific concerns.
"""

from cruxible_core.service.analysis import service_evaluate, service_find_candidates
from cruxible_core.service.execution import (
    service_lock,
    service_plan,
    service_propose_workflow,
    service_run,
    service_test,
)
from cruxible_core.service.feedback import service_feedback, service_outcome
from cruxible_core.service.groups import (
    derive_review_priority,
    service_get_group,
    service_list_groups,
    service_list_resolutions,
    service_propose_group,
    service_resolve_group,
    service_update_trust_status,
)
from cruxible_core.service.mutations import (
    service_add_entities,
    service_add_relationships,
    service_ingest,
)
from cruxible_core.service.queries import (
    service_get_entity,
    service_get_receipt,
    service_get_relationship,
    service_init,
    service_list,
    service_query,
    service_sample,
    service_schema,
    service_validate,
)
from cruxible_core.service.snapshots import (
    service_create_snapshot,
    service_fork_snapshot,
    service_list_snapshots,
)
from cruxible_core.service.types import (
    AddEntityResult,
    AddRelationshipResult,
    EntityUpsertInput,
    FeedbackServiceResult,
    ForkSnapshotResult,
    GetGroupResult,
    IngestResult,
    InitResult,
    ListGroupsResult,
    ListResolutionsResult,
    ListResult,
    LockServiceResult,
    OutcomeServiceResult,
    PlanServiceResult,
    ProposeGroupResult,
    ProposeWorkflowResult,
    QueryServiceResult,
    RelationshipUpsertInput,
    ResolveGroupResult,
    RunServiceResult,
    SnapshotCreateResult,
    SnapshotListResult,
    TestServiceResult,
    ValidateServiceResult,
)

__all__ = [
    # Types
    "AddEntityResult",
    "AddRelationshipResult",
    "EntityUpsertInput",
    "FeedbackServiceResult",
    "ForkSnapshotResult",
    "GetGroupResult",
    "IngestResult",
    "InitResult",
    "LockServiceResult",
    "ListGroupsResult",
    "ListResolutionsResult",
    "ListResult",
    "OutcomeServiceResult",
    "PlanServiceResult",
    "ProposeWorkflowResult",
    "ProposeGroupResult",
    "QueryServiceResult",
    "RelationshipUpsertInput",
    "ResolveGroupResult",
    "RunServiceResult",
    "SnapshotCreateResult",
    "SnapshotListResult",
    "TestServiceResult",
    "ValidateServiceResult",
    # Execution
    "service_lock",
    "service_plan",
    "service_propose_workflow",
    "service_run",
    "service_test",
    "service_create_snapshot",
    "service_fork_snapshot",
    "service_list_snapshots",
    # Analysis
    "service_evaluate",
    "service_find_candidates",
    # Feedback
    "service_feedback",
    "service_outcome",
    # Groups
    "derive_review_priority",
    "service_get_group",
    "service_list_groups",
    "service_list_resolutions",
    "service_propose_group",
    "service_resolve_group",
    "service_update_trust_status",
    # Mutations
    "service_add_entities",
    "service_add_relationships",
    "service_ingest",
    # Queries
    "service_get_entity",
    "service_get_receipt",
    "service_get_relationship",
    "service_init",
    "service_list",
    "service_query",
    "service_sample",
    "service_schema",
    "service_validate",
]
