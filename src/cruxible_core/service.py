"""Shared service layer — the execution contract behind CLI, MCP, and REST/SDK.

Every product operation goes through this module. Callers (CLI commands, MCP
handlers, REST endpoints) are thin wrappers that handle I/O formatting,
permission checks, and protocol-specific concerns.
"""

from __future__ import annotations

import json as _json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from cruxible_core.errors import ConfigError, DataValidationError
from cruxible_core.graph.operations import (
    apply_entity,
    apply_relationship,
    validate_entity,
    validate_relationship,
)
from cruxible_core.ingest import ingest_file, ingest_from_mapping, load_data_from_string
from cruxible_core.instance_protocol import InstanceProtocol

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


@dataclass
class AddRelationshipResult:
    added: int
    updated: int


@dataclass
class IngestResult:
    records_ingested: int
    records_updated: int
    mapping: str
    entity_type: str | None
    relationship_type: str | None


# ---------------------------------------------------------------------------
# Mutation functions
# ---------------------------------------------------------------------------


def service_add_entities(
    instance: InstanceProtocol,
    entities: Sequence[EntityUpsertInput],
) -> AddEntityResult:
    """Add or update entities in the graph (batch upsert).

    Validates all entities first, then applies atomically.
    Raises DataValidationError on duplicates within the batch or schema violations.
    """
    config = instance.load_config()
    graph = instance.load_graph()

    errors: list[str] = []
    batch_seen: set[tuple[str, str]] = set()
    pending = []

    for i, ent in enumerate(entities, start=1):
        key = (ent.entity_type, ent.entity_id)
        if key in batch_seen:
            errors.append(f"Entity {i}: duplicate in batch {ent.entity_type}:{ent.entity_id}")
            continue

        try:
            validated = validate_entity(
                config,
                graph,
                ent.entity_type,
                ent.entity_id,
                ent.properties,
            )
        except DataValidationError as exc:
            errors.append(f"Entity {i}: {exc}")
            continue

        batch_seen.add(key)
        pending.append(validated)

    if errors:
        raise DataValidationError(
            f"Entity validation failed with {len(errors)} error(s)",
            errors=errors,
        )

    added = 0
    updated = 0
    for validated in pending:
        apply_entity(graph, validated)
        if validated.is_update:
            updated += 1
        else:
            added += 1

    instance.save_graph(graph)
    return AddEntityResult(added=added, updated=updated)


def service_add_relationships(
    instance: InstanceProtocol,
    relationships: Sequence[RelationshipUpsertInput],
    source: str,
    source_ref: str,
) -> AddRelationshipResult:
    """Add or update relationships in the graph (batch upsert).

    Validates all relationships first, then applies atomically.
    New edges get provenance stamped. Updated edges preserve existing provenance.
    Raises DataValidationError on duplicates within the batch or schema violations.
    """
    config = instance.load_config()
    graph = instance.load_graph()

    errors: list[str] = []
    batch_seen: set[tuple[str, str, str, str, str]] = set()
    pending = []

    for i, edge in enumerate(relationships, start=1):
        key = (
            edge.from_type,
            edge.from_id,
            edge.to_type,
            edge.to_id,
            edge.relationship,
        )
        if key in batch_seen:
            errors.append(
                f"Edge {i}: duplicate in batch "
                f"{edge.from_type}:{edge.from_id} "
                f"-[{edge.relationship}]-> "
                f"{edge.to_type}:{edge.to_id}"
            )
            continue

        try:
            validated = validate_relationship(
                config,
                graph,
                edge.from_type,
                edge.from_id,
                edge.relationship,
                edge.to_type,
                edge.to_id,
                edge.properties,
            )
        except DataValidationError as exc:
            errors.append(f"Edge {i}: {exc}")
            continue

        batch_seen.add(key)
        pending.append(validated)

    if errors:
        raise DataValidationError(
            f"Relationship validation failed with {len(errors)} error(s)",
            errors=errors,
        )

    added = 0
    updated = 0
    for validated in pending:
        apply_relationship(graph, validated, source, source_ref)
        if validated.is_update:
            updated += 1
        else:
            added += 1

    instance.save_graph(graph)
    return AddRelationshipResult(added=added, updated=updated)


def service_ingest(
    instance: InstanceProtocol,
    mapping_name: str,
    file_path: str | None = None,
    data_csv: str | None = None,
    data_json: str | list[dict[str, Any]] | None = None,
    data_ndjson: str | None = None,
    upload_id: str | None = None,
) -> IngestResult:
    """Ingest data through an ingestion mapping.

    Accepts exactly one data source. Raises ConfigError on source violations.
    """
    sources = sum(x is not None for x in (file_path, data_csv, data_json, data_ndjson, upload_id))
    if sources == 0:
        raise ConfigError(
            "Provide exactly one of file_path, data_csv, data_json, data_ndjson, or upload_id"
        )
    if sources > 1:
        raise ConfigError(
            "Provide exactly one of file_path, data_csv, data_json, data_ndjson, or upload_id"
        )

    if upload_id is not None:
        raise ConfigError("upload_id is not supported in local mode")

    config = instance.load_config()
    graph = instance.load_graph()

    if file_path is not None:
        added, updated = ingest_file(config, graph, mapping_name, file_path)
    elif data_csv is not None:
        df = load_data_from_string(data_csv, "csv")
        added, updated = ingest_from_mapping(config, graph, mapping_name, df)
    elif data_ndjson is not None:
        df = load_data_from_string(data_ndjson, "ndjson")
        added, updated = ingest_from_mapping(config, graph, mapping_name, df)
    else:
        assert data_json is not None
        if not isinstance(data_json, str):
            data_json = _json.dumps(data_json)
        df = load_data_from_string(data_json, "json")
        added, updated = ingest_from_mapping(config, graph, mapping_name, df)

    instance.save_graph(graph)
    mapping = config.ingestion[mapping_name]
    return IngestResult(
        records_ingested=added,
        records_updated=updated,
        mapping=mapping_name,
        entity_type=mapping.entity_type,
        relationship_type=mapping.relationship_type,
    )
