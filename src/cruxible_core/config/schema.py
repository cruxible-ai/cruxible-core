"""Pydantic models for Cruxible Core config YAML validation.

The config defines a decision domain: entity types, relationships,
named queries, constraints, ingestion mappings, and optional execution
artifacts such as contracts, providers, workflows, and workflow tests.

Hierarchy:
    CoreConfig
    ├── entity_types: dict[str, EntityTypeSchema]
    │   └── properties: dict[str, PropertySchema]
    ├── relationships: list[RelationshipSchema]
    │   └── properties: dict[str, PropertySchema]
    ├── named_queries: dict[str, NamedQuerySchema]
    │   └── traversal: list[TraversalStep]
    ├── constraints: list[ConstraintSchema]
    ├── ingestion: dict[str, IngestionMapping]
    ├── contracts: dict[str, ContractSchema]
    ├── artifacts: dict[str, ProviderArtifactSchema]
    ├── providers: dict[str, ProviderSchema]
    ├── workflows: dict[str, WorkflowSchema]
    └── tests: list[WorkflowTestSchema]
"""

from __future__ import annotations

import json as _json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Property Schema (shared between entity types and relationships)
# ---------------------------------------------------------------------------


class PropertySchema(BaseModel):
    """Schema for entity/relationship property definitions."""

    type: str  # string, int, float, bool, date
    primary_key: bool = False
    indexed: bool = False
    optional: bool = False
    default: Any | None = None
    enum: list[str] | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Entity Type Schema
# ---------------------------------------------------------------------------


class EntityTypeSchema(BaseModel):
    """Schema for an entity type definition."""

    description: str | None = None
    properties: dict[str, PropertySchema]
    constraints: list[str] = Field(default_factory=list)

    def get_primary_key(self) -> str | None:
        """Return the primary key property name, if any."""
        for name, prop in self.properties.items():
            if prop.primary_key:
                return name
        return None


# ---------------------------------------------------------------------------
# Integration & Matching Config (for candidate group resolve)
# ---------------------------------------------------------------------------


class IntegrationSpec(BaseModel):
    """Global integration definition. Identity + stable contract.

    Integration specs are immutable by convention: any semantic change
    (different model, different fields, different metric) requires a new key
    (e.g. cosine_similarity_v2). Not enforced at runtime in v0.2.0.
    """

    kind: str
    contract: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""

    @field_validator("contract")
    @classmethod
    def validate_contract_serializable(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Ensure contract is JSON-serializable."""
        try:
            _json.dumps(v, sort_keys=True)
        except (TypeError, ValueError) as exc:
            msg = f"contract must be JSON-serializable: {exc}"
            raise ValueError(msg) from exc
        return v


class IntegrationConfig(BaseModel):
    """Per-integration guardrails for candidate group proposals."""

    role: Literal["blocking", "required", "advisory"] = "required"
    always_review_on_unsure: bool = False
    note: str = ""


class MatchingConfig(BaseModel):
    """Guardrails for candidate group proposals on a relationship type."""

    integrations: dict[str, IntegrationConfig] = Field(default_factory=dict)
    auto_resolve_when: Literal["all_support", "no_contradict"] = "all_support"
    auto_resolve_requires_prior_trust: Literal["trusted_only", "trusted_or_watch"] = "trusted_only"
    max_group_size: int = 1000


# ---------------------------------------------------------------------------
# Relationship Schema
# ---------------------------------------------------------------------------


class RelationshipSchema(BaseModel):
    """Schema for a relationship type definition."""

    name: str
    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    cardinality: str = "many_to_many"
    properties: dict[str, PropertySchema] = Field(default_factory=dict)
    description: str | None = None
    inverse: str | None = None
    is_hierarchy: bool = False
    matching: MatchingConfig | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Named Query Schema (declarative traversal)
# ---------------------------------------------------------------------------


class TraversalStep(BaseModel):
    """A single step in a named query's traversal path.

    Each step follows one or more relationships in a direction, optionally
    filtering on edge/target properties and applying constraints. When
    multiple relationships are listed, the engine traverses all of them
    from the current entities and merges results (fan-out).
    """

    relationship: str | list[str]
    direction: Literal["outgoing", "incoming", "both"] = "outgoing"
    filter: dict[str, Any] | None = None
    constraint: str | None = None
    max_depth: int = Field(default=1, ge=1)

    @field_validator("relationship")
    @classmethod
    def validate_relationship(cls, v: str | list[str]) -> str | list[str]:
        if isinstance(v, list):
            if len(v) == 0:
                msg = "relationship list must not be empty"
                raise ValueError(msg)
            for item in v:
                if not isinstance(item, str) or not item.strip():
                    msg = "relationship list items must be non-empty strings"
                    raise ValueError(msg)
        return v

    @property
    def relationship_types(self) -> list[str]:
        """Normalize relationship to a deduplicated list."""
        if isinstance(self.relationship, str):
            return [self.relationship]
        return list(dict.fromkeys(self.relationship))


class NamedQuerySchema(BaseModel):
    """Schema for a declarative named query.

    Queries are defined as an entry_point entity type plus a sequence
    of traversal steps. The query engine interprets these declaratively.
    """

    description: str | None = None
    entry_point: str
    traversal: list[TraversalStep]
    returns: str


# ---------------------------------------------------------------------------
# Constraint Schema
# ---------------------------------------------------------------------------


class ConstraintSchema(BaseModel):
    """Schema for a constraint rule.

    Constraints are evaluated during ingestion or query time.
    Severity determines whether violations are warnings or errors.
    """

    name: str
    rule: str
    severity: Literal["warning", "error"] = "warning"
    description: str | None = None


# ---------------------------------------------------------------------------
# Workflow / Provider Contracts
# ---------------------------------------------------------------------------


class ContractSchema(BaseModel):
    """Typed payload contract for provider or workflow inputs."""

    description: str | None = None
    fields: dict[str, PropertySchema]


class ProviderArtifactSchema(BaseModel):
    """Pinned external artifact referenced by a provider."""

    kind: str
    uri: str
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderSchema(BaseModel):
    """Versioned executable leaf used by workflow provider steps."""

    kind: Literal["function", "model", "tool"]
    description: str | None = None
    contract_in: str
    contract_out: str
    ref: str
    version: str
    deterministic: bool = True
    artifact: str | None = None
    runtime: str = "python"
    side_effects: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class AssertSpec(BaseModel):
    """Structured workflow guard condition."""

    left: Any
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    right: Any
    message: str


class MakeCandidatesSpec(BaseModel):
    """Build a relationship candidate set from list-shaped workflow data."""

    relationship_type: str
    items: Any
    from_type: Any
    from_id: Any
    to_type: Any
    to_id: Any
    properties: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ScoreSignalMappingSpec(BaseModel):
    """Map numeric scores to tri-state candidate signals."""

    path: str
    support_gte: float
    unsure_gte: float

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_thresholds(self) -> ScoreSignalMappingSpec:
        if self.support_gte < self.unsure_gte:
            msg = "score.support_gte must be greater than or equal to score.unsure_gte"
            raise ValueError(msg)
        return self


class EnumSignalMappingSpec(BaseModel):
    """Map enum-like values to tri-state candidate signals."""

    path: str
    map: dict[str, Literal["support", "unsure", "contradict"]]

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_non_empty_map(self) -> EnumSignalMappingSpec:
        if not self.map:
            msg = "enum.map must not be empty"
            raise ValueError(msg)
        return self


class MapSignalsSpec(BaseModel):
    """Convert raw provider output into a governed signal batch."""

    integration: str
    items: Any
    from_id: Any
    to_id: Any
    evidence: Any | None = None
    score: ScoreSignalMappingSpec | None = None
    enum: EnumSignalMappingSpec | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_mapping_mode(self) -> MapSignalsSpec:
        mapping_modes = sum(mode is not None for mode in (self.score, self.enum))
        if mapping_modes != 1:
            msg = "map_signals must define exactly one of 'score' or 'enum'"
            raise ValueError(msg)
        return self


class ProposeRelationshipGroupSpec(BaseModel):
    """Assemble a governed relationship-group proposal from built-in artifacts."""

    relationship_type: str
    candidates_from: str
    signals_from: list[str]
    thesis_text: Any = ""
    thesis_facts: dict[str, Any] = Field(default_factory=dict)
    analysis_state: dict[str, Any] = Field(default_factory=dict)
    suggested_priority: Any | None = None
    proposed_by: Literal["human", "ai_review"] = "ai_review"

    model_config = {"extra": "forbid"}


class MakeEntitiesSpec(BaseModel):
    """Build an entity set from list-shaped workflow data."""

    entity_type: str
    items: Any
    entity_id: Any
    properties: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class MakeRelationshipsSpec(BaseModel):
    """Build a relationship set from list-shaped workflow data."""

    relationship_type: str
    items: Any
    from_type: Any
    from_id: Any
    to_type: Any
    to_id: Any
    properties: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ApplyEntitiesSpec(BaseModel):
    """Apply an entity set to staged canonical state."""

    entities_from: str

    model_config = {"extra": "forbid"}


class ApplyRelationshipsSpec(BaseModel):
    """Apply a relationship set to staged canonical state."""

    relationships_from: str

    model_config = {"extra": "forbid"}


class WorkflowStepSchema(BaseModel):
    """Single step in a declarative workflow."""

    id: str
    query: str | None = None
    provider: str | None = None
    assert_spec: AssertSpec | None = Field(alias="assert", default=None)
    make_candidates: MakeCandidatesSpec | None = None
    map_signals: MapSignalsSpec | None = None
    propose_relationship_group: ProposeRelationshipGroupSpec | None = None
    make_entities: MakeEntitiesSpec | None = None
    make_relationships: MakeRelationshipsSpec | None = None
    apply_entities: ApplyEntitiesSpec | None = None
    apply_relationships: ApplyRelationshipsSpec | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)
    as_: str | None = Field(alias="as", default=None)

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @model_validator(mode="after")
    def validate_step_shape(self) -> WorkflowStepSchema:
        kinds = sum(
            candidate is not None
            for candidate in (
                self.query,
                self.provider,
                self.assert_spec,
                self.make_candidates,
                self.map_signals,
                self.propose_relationship_group,
                self.make_entities,
                self.make_relationships,
                self.apply_entities,
                self.apply_relationships,
            )
        )
        if kinds != 1:
            msg = (
                "Workflow step must define exactly one of 'query', 'provider', 'assert', "
                "'make_candidates', 'map_signals', 'propose_relationship_group', "
                "'make_entities', 'make_relationships', 'apply_entities', "
                "or 'apply_relationships'"
            )
            raise ValueError(msg)

        if self.query is not None:
            if self.as_ is None:
                msg = "Query workflow steps require 'as'"
                raise ValueError(msg)
            if self.input:
                msg = "Query workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.provider is not None:
            if self.as_ is None:
                msg = "Provider workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "Provider workflow steps may not define 'params'"
                raise ValueError(msg)
            return self

        if self.make_candidates is not None:
            if self.as_ is None:
                msg = "make_candidates workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "make_candidates workflow steps may not define 'params'"
                raise ValueError(msg)
            if self.input:
                msg = "make_candidates workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.map_signals is not None:
            if self.as_ is None:
                msg = "map_signals workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "map_signals workflow steps may not define 'params'"
                raise ValueError(msg)
            if self.input:
                msg = "map_signals workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.propose_relationship_group is not None:
            if self.as_ is None:
                msg = "propose_relationship_group workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "propose_relationship_group workflow steps may not define 'params'"
                raise ValueError(msg)
            if self.input:
                msg = "propose_relationship_group workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.make_entities is not None:
            if self.as_ is None:
                msg = "make_entities workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "make_entities workflow steps may not define 'params'"
                raise ValueError(msg)
            if self.input:
                msg = "make_entities workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.make_relationships is not None:
            if self.as_ is None:
                msg = "make_relationships workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "make_relationships workflow steps may not define 'params'"
                raise ValueError(msg)
            if self.input:
                msg = "make_relationships workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.apply_entities is not None:
            if self.as_ is None:
                msg = "apply_entities workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "apply_entities workflow steps may not define 'params'"
                raise ValueError(msg)
            if self.input:
                msg = "apply_entities workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.apply_relationships is not None:
            if self.as_ is None:
                msg = "apply_relationships workflow steps require 'as'"
                raise ValueError(msg)
            if self.params:
                msg = "apply_relationships workflow steps may not define 'params'"
                raise ValueError(msg)
            if self.input:
                msg = "apply_relationships workflow steps may not define 'input'"
                raise ValueError(msg)
            return self

        if self.as_ is not None:
            msg = "Assert workflow steps may not define 'as'"
            raise ValueError(msg)
        if self.params:
            msg = "Assert workflow steps may not define 'params'"
            raise ValueError(msg)
        if self.input:
            msg = "Assert workflow steps may not define 'input'"
            raise ValueError(msg)
        return self


class WorkflowSchema(BaseModel):
    """Declarative composition of query and provider steps."""

    description: str | None = None
    canonical: bool = False
    contract_in: str
    steps: list[WorkflowStepSchema]
    returns: str

    model_config = {"extra": "forbid"}


class WorkflowTestExpectSchema(BaseModel):
    """Minimal assertions for config-defined workflow tests."""

    output_equals: Any | None = None
    output_contains: dict[str, Any] | None = None
    receipt_contains_provider: str | list[str] | None = None
    error_contains: str | None = None

    @property
    def required_providers(self) -> list[str]:
        if self.receipt_contains_provider is None:
            return []
        if isinstance(self.receipt_contains_provider, str):
            return [self.receipt_contains_provider]
        return self.receipt_contains_provider


class WorkflowTestSchema(BaseModel):
    """Fixture for exercising a workflow with expected outputs/evidence."""

    name: str
    workflow: str
    input: dict[str, Any] = Field(default_factory=dict)
    expect: WorkflowTestExpectSchema = Field(default_factory=WorkflowTestExpectSchema)


# ---------------------------------------------------------------------------
# Ingestion Mapping
# ---------------------------------------------------------------------------


class IngestionMapping(BaseModel):
    """Mapping for ingesting entity or relationship data from CSV/JSON.

    For entities: set entity_type + id_column. Remaining CSV columns
    map to entity properties by name, or use column_map to rename.

    For relationships: set relationship_type + from_column + to_column.
    Extra columns become edge properties.
    """

    description: str | None = None
    entity_type: str | None = None
    relationship_type: str | None = None
    file_pattern: str | None = None
    id_column: str | None = None
    from_column: str | None = None
    to_column: str | None = None
    column_map: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mapping_type(self) -> IngestionMapping:
        has_entity = self.entity_type is not None
        has_relationship = self.relationship_type is not None

        if has_entity == has_relationship:
            msg = "Exactly one of 'entity_type' or 'relationship_type' must be set"
            raise ValueError(msg)

        if has_entity and not self.id_column:
            msg = "Entity ingestion requires 'id_column'"
            raise ValueError(msg)

        if has_relationship and (not self.from_column or not self.to_column):
            msg = "Relationship ingestion requires both 'from_column' and 'to_column'"
            raise ValueError(msg)

        return self

    @property
    def is_entity(self) -> bool:
        return self.entity_type is not None

    @property
    def is_relationship(self) -> bool:
        return self.relationship_type is not None


# ---------------------------------------------------------------------------
# Top-Level Config
# ---------------------------------------------------------------------------


class CoreConfig(BaseModel):
    """Top-level Cruxible Core configuration.

    Parsed from YAML. Defines the complete decision domain: entity types,
    relationships, queries, constraints, and ingestion mappings.
    """

    version: str = "1.0"
    name: str
    description: str | None = None
    cruxible_version: str | None = None
    kind: Literal["ontology", "world_model"] = "world_model"

    entity_types: dict[str, EntityTypeSchema]
    relationships: list[RelationshipSchema]
    named_queries: dict[str, NamedQuerySchema] = Field(default_factory=dict)
    constraints: list[ConstraintSchema] = Field(default_factory=list)
    ingestion: dict[str, IngestionMapping] = Field(default_factory=dict)
    integrations: dict[str, IntegrationSpec] = Field(default_factory=dict)
    contracts: dict[str, ContractSchema] = Field(default_factory=dict)
    artifacts: dict[str, ProviderArtifactSchema] = Field(default_factory=dict)
    providers: dict[str, ProviderSchema] = Field(default_factory=dict)
    workflows: dict[str, WorkflowSchema] = Field(default_factory=dict)
    tests: list[WorkflowTestSchema] = Field(default_factory=list)

    def get_relationship(self, name: str) -> RelationshipSchema | None:
        """Find a relationship schema by name."""
        for rel in self.relationships:
            if rel.name == name:
                return rel
        return None

    def get_entity_type(self, name: str) -> EntityTypeSchema | None:
        """Find an entity type schema by name."""
        return self.entity_types.get(name)

    def get_hierarchy_relationships(self) -> list[RelationshipSchema]:
        """Return relationship schemas marked as hierarchy."""
        return [r for r in self.relationships if r.is_hierarchy]
