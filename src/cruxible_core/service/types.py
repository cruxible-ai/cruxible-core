"""Input and result types for the service layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cruxible_core.config.schema import CoreConfig
from cruxible_core.graph.types import EntityInstance
from cruxible_core.group.types import CandidateGroup, CandidateMember
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.receipt.types import Receipt

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
class QueryServiceResult:
    results: list[EntityInstance]
    receipt_id: str | None
    receipt: Receipt | None
    total_results: int
    steps_executed: int


@dataclass
class FeedbackServiceResult:
    feedback_id: str
    applied: bool
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
