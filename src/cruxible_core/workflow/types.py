"""Workflow lock, plan, and execution types."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from cruxible_core.config.schema import (
    ApplyEntitiesSpec,
    ApplyRelationshipsSpec,
    AssertSpec,
    ListEntitiesSpec,
    ListRelationshipsSpec,
    MakeCandidatesSpec,
    MakeEntitiesSpec,
    MakeRelationshipsSpec,
    MapSignalsSpec,
    ProposeRelationshipGroupSpec,
)
from cruxible_core.group.types import CandidateMember, SignalValue
from cruxible_core.provider.types import ExecutionTrace, ProviderRuntime
from cruxible_core.receipt.types import Receipt


class _DuplicateTrackedCollection(BaseModel):
    """Mixin for workflow artifacts that report input-duplicate diagnostics.

    Tracks how many inputs were deduped and how many were dropped due to
    conflicting duplicates, plus a bounded sample for debugging.
    """

    duplicate_input_count: int = 0
    conflicting_duplicate_count: int = 0
    duplicate_examples: list[dict[str, Any]] = Field(default_factory=list)


class LockedArtifact(BaseModel):
    """Artifact details captured in a generated lock file."""

    kind: str
    uri: str
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LockedProvider(BaseModel):
    """Resolved provider metadata captured in a generated lock file."""

    version: str
    ref: str
    provider_entrypoint_sha256: str | None = None
    runtime: ProviderRuntime
    deterministic: bool
    side_effects: bool
    artifact: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowLock(BaseModel):
    """Generated lock file for workflow execution."""

    version: str = "1"
    config_digest: str
    lock_digest: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    artifacts: dict[str, LockedArtifact] = Field(default_factory=dict)
    providers: dict[str, LockedProvider] = Field(default_factory=dict)


class CompiledPlanStep(BaseModel):
    """Single compiled workflow step."""

    step_id: str
    kind: Literal[
        "query",
        "provider",
        "assert",
        "list_entities",
        "list_relationships",
        "make_candidates",
        "map_signals",
        "propose_relationship_group",
        "make_entities",
        "make_relationships",
        "apply_entities",
        "apply_relationships",
    ]
    canonical: bool = False
    as_name: str | None = None
    query_name: str | None = None
    provider_name: str | None = None
    provider_ref: str | None = None
    provider_version: str | None = None
    provider_entrypoint_sha256: str | None = None
    artifact_name: str | None = None
    artifact_sha256: str | None = None
    params_template: dict[str, Any] = Field(default_factory=dict)
    params_preview: dict[str, Any] = Field(default_factory=dict)
    input_template: dict[str, Any] = Field(default_factory=dict)
    input_preview: dict[str, Any] = Field(default_factory=dict)
    assert_spec: AssertSpec | None = None
    list_entities_spec: ListEntitiesSpec | None = None
    list_relationships_spec: ListRelationshipsSpec | None = None
    make_candidates_spec: MakeCandidatesSpec | None = None
    map_signals_spec: MapSignalsSpec | None = None
    propose_relationship_group_spec: ProposeRelationshipGroupSpec | None = None
    make_entities_spec: MakeEntitiesSpec | None = None
    make_relationships_spec: MakeRelationshipsSpec | None = None
    apply_entities_spec: ApplyEntitiesSpec | None = None
    apply_relationships_spec: ApplyRelationshipsSpec | None = None


class CompiledPlan(BaseModel):
    """Compiled workflow plan artifact."""

    workflow: str
    contract_in: str
    config_digest: str
    lock_digest: str | None = None
    canonical: bool = False
    steps: list[CompiledPlanStep]
    returns: str
    input_payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionResult(BaseModel):
    """Runtime workflow execution result."""

    workflow: str
    output: Any
    receipt: Receipt
    mode: Literal["run", "preview", "apply"] = "run"
    canonical: bool = False
    apply_digest: str | None = None
    head_snapshot_id: str | None = None
    committed_snapshot_id: str | None = None
    apply_previews: dict[str, Any] = Field(default_factory=dict)
    query_receipt_ids: list[str] = Field(default_factory=list)
    traces: list[ExecutionTrace] = Field(default_factory=list)
    step_outputs: dict[str, Any] = Field(default_factory=dict)
    alias_step_ids: dict[str, str] = Field(default_factory=dict)
    step_trace_ids: dict[str, list[str]] = Field(default_factory=dict)


class WorkflowTestCaseResult(BaseModel):
    """Single workflow test case result."""

    name: str
    workflow: str
    passed: bool
    output: Any | None = None
    receipt_id: str | None = None
    error: str | None = None


class CandidateSetMember(BaseModel):
    """Candidate relationship endpoints produced inside a workflow."""

    from_type: str
    from_id: str
    to_type: str
    to_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class CandidateSet(BaseModel):
    """Internal workflow artifact containing candidate relationship pairs."""

    relationship_type: str
    candidates: list[CandidateSetMember] = Field(default_factory=list)


class SignalBatchSignal(BaseModel):
    """Governed signal produced for a specific candidate pair."""

    from_id: str
    to_id: str
    signal: SignalValue
    evidence: str = ""


class SignalBatch(BaseModel):
    """Internal workflow artifact containing one integration's signals."""

    integration: str
    signals: list[SignalBatchSignal] = Field(default_factory=list)


class RelationshipGroupProposalArtifact(BaseModel):
    """Internal workflow artifact bridged into a governed relationship proposal."""

    relationship_type: str
    members: list[CandidateMember]
    thesis_text: str = ""
    thesis_facts: dict[str, Any] = Field(default_factory=dict)
    analysis_state: dict[str, Any] = Field(default_factory=dict)
    integrations_used: list[str] = Field(default_factory=list)
    suggested_priority: str | None = None
    proposed_by: Literal["human", "agent"] = "agent"


class EntitySetMember(BaseModel):
    """Entity payload assembled inside a workflow."""

    entity_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class EntitySet(_DuplicateTrackedCollection):
    """Internal workflow artifact containing entity upserts."""

    entity_type: str
    entities: list[EntitySetMember] = Field(default_factory=list)


class RelationshipSet(_DuplicateTrackedCollection):
    """Internal workflow artifact containing relationship upserts."""

    relationship_type: str
    relationships: list[CandidateSetMember] = Field(default_factory=list)


class ApplyEntitiesPreview(_DuplicateTrackedCollection):
    """Preview summary for applying an entity set."""

    entity_type: str
    create_count: int = 0
    update_count: int = 0
    noop_count: int = 0


class ApplyRelationshipsPreview(_DuplicateTrackedCollection):
    """Preview summary for applying a relationship set."""

    relationship_type: str
    create_count: int = 0
    update_count: int = 0
    noop_count: int = 0
