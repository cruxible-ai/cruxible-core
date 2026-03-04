"""Two-phase shared helpers for entity and relationship validation/application.

Phase 1 (validate): Pure functions that check inputs against config/graph,
returning a validated result or raising DataValidationError. No graph mutation.

Phase 2 (apply): Functions that mutate the graph using a validated result.

MCP handlers use validate in batch loops (collect errors, then apply all if
no errors — preserving batch atomicity). CLI validates and applies one at a time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import DataValidationError
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance, RelationshipInstance, make_provenance


@dataclass
class ValidatedEntity:
    """Result of validate_entity — ready to apply."""

    entity: EntityInstance
    is_update: bool


@dataclass
class ValidatedRelationship:
    """Result of validate_relationship — ready to apply."""

    relationship: RelationshipInstance
    is_update: bool


def validate_entity(
    config: CoreConfig,
    graph: EntityGraph,
    entity_type: str,
    entity_id: str,
    properties: dict[str, Any] | None = None,
) -> ValidatedEntity:
    """Validate an entity against config and graph state.

    Raises DataValidationError on failure.
    """
    if entity_type not in config.entity_types:
        raise DataValidationError(f"type '{entity_type}' not found in config")
    if not entity_id.strip():
        raise DataValidationError("entity_id must not be empty")

    is_update = graph.has_entity(entity_type, entity_id)
    entity = EntityInstance(
        entity_type=entity_type,
        entity_id=entity_id,
        properties=properties or {},
    )
    return ValidatedEntity(entity=entity, is_update=is_update)


def validate_relationship(
    config: CoreConfig,
    graph: EntityGraph,
    from_type: str,
    from_id: str,
    relationship: str,
    to_type: str,
    to_id: str,
    properties: dict[str, Any] | None = None,
) -> ValidatedRelationship:
    """Validate a relationship against config and graph state.

    Handles confidence coercion, provenance stripping, direction checks,
    and endpoint existence checks.

    Raises DataValidationError on failure.
    """
    props = dict(properties) if properties else {}

    # Validate relationship type exists in config
    rel_schema = config.get_relationship(relationship)
    if rel_schema is None:
        raise DataValidationError(f"relationship '{relationship}' not found in config")

    # Validate endpoint types match config direction
    if from_type != rel_schema.from_entity:
        raise DataValidationError(
            f"from_type '{from_type}' does not match "
            f"relationship '{relationship}' "
            f"which expects '{rel_schema.from_entity}'"
        )
    if to_type != rel_schema.to_entity:
        raise DataValidationError(
            f"to_type '{to_type}' does not match "
            f"relationship '{relationship}' "
            f"which expects '{rel_schema.to_entity}'"
        )

    # Validate source entity exists
    if graph.get_entity(from_type, from_id) is None:
        raise DataValidationError(f"entity {from_type}:{from_id} not found")

    # Validate target entity exists
    if graph.get_entity(to_type, to_id) is None:
        raise DataValidationError(f"entity {to_type}:{to_id} not found")

    # Confidence: reject bools, coerce strings to float, reject non-finite
    confidence = props.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool):
            raise DataValidationError(
                f"confidence must be numeric (float). "
                f"Got {confidence!r}. "
                f"Suggested: low=0.3, medium=0.5, high=0.7, very_high=0.9"
            )
        if not isinstance(confidence, (int, float)):
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                raise DataValidationError(
                    f"confidence must be numeric (float). "
                    f"Got {confidence!r}. "
                    f"Suggested: low=0.3, medium=0.5, high=0.7, very_high=0.9"
                )
        if not math.isfinite(confidence):
            raise DataValidationError(
                f"confidence must be a finite number. Got {confidence!r}."
            )
        props["confidence"] = confidence

    # Strip system-owned _provenance from user input
    props = {k: v for k, v in props.items() if k != "_provenance"}

    is_update = graph.has_relationship(from_type, from_id, to_type, to_id, relationship)

    rel = RelationshipInstance(
        relationship_type=relationship,
        from_entity_type=from_type,
        from_entity_id=from_id,
        to_entity_type=to_type,
        to_entity_id=to_id,
        properties=props,
    )
    return ValidatedRelationship(relationship=rel, is_update=is_update)


def apply_entity(graph: EntityGraph, validated: ValidatedEntity) -> None:
    """Apply a validated entity to the graph (add or update)."""
    graph.add_entity(validated.entity)


def apply_relationship(
    graph: EntityGraph,
    validated: ValidatedRelationship,
    source: str,
    source_ref: str,
) -> None:
    """Apply a validated relationship to the graph (add or update).

    New edges get provenance stamped via make_provenance(source, source_ref).
    Updated edges preserve existing provenance with last_modified_at/last_modified_by.
    """
    rel = validated.relationship
    if validated.is_update:
        existing_rel = graph.get_relationship(
            rel.from_entity_type,
            rel.from_entity_id,
            rel.to_entity_type,
            rel.to_entity_id,
            rel.relationship_type,
        )
        replace_props = dict(rel.properties)
        if existing_rel:
            old_prov = existing_rel.properties.get("_provenance")
            if old_prov:
                prov = dict(old_prov)
                prov["last_modified_at"] = datetime.now(timezone.utc).isoformat()
                prov["last_modified_by"] = source
                replace_props["_provenance"] = prov
        graph.replace_edge_properties(
            rel.from_entity_type,
            rel.from_entity_id,
            rel.to_entity_type,
            rel.to_entity_id,
            rel.relationship_type,
            replace_props,
        )
    else:
        rel.properties["_provenance"] = make_provenance(source, source_ref)
        graph.add_relationship(rel)
