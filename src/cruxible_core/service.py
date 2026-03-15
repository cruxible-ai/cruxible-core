"""Shared service layer — the execution contract behind CLI, MCP, and REST/SDK.

Every product operation goes through this module. Callers (CLI commands, MCP
handlers, REST endpoints) are thin wrappers that handle I/O formatting,
permission checks, and protocol-specific concerns.
"""

from __future__ import annotations

import json as _json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.config.loader import load_config, load_config_from_string
from cruxible_core.config.schema import CoreConfig, MatchingConfig
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import (
    ConfigError,
    DataValidationError,
    EdgeAmbiguityError,
    ReceiptNotFoundError,
)
from cruxible_core.evaluate import EvaluationReport, evaluate_graph
from cruxible_core.feedback.applier import apply_feedback
from cruxible_core.feedback.types import EdgeTarget, FeedbackRecord, OutcomeRecord
from cruxible_core.graph.operations import (
    apply_entity,
    apply_relationship,
    validate_entity,
    validate_relationship,
)
from cruxible_core.graph.types import EntityInstance, RelationshipInstance
from cruxible_core.group.signature import compute_group_signature
from cruxible_core.group.types import CandidateGroup, CandidateMember
from cruxible_core.ingest import ingest_file, ingest_from_mapping, load_data_from_string
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.query.candidates import CandidateMatch, MatchRule, find_candidates
from cruxible_core.query.engine import execute_query
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


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def service_validate(
    config_path: str | None = None,
    config_yaml: str | None = None,
) -> ValidateServiceResult:
    """Validate a config file or inline YAML string.

    Runs both structural (Pydantic) and semantic (cross-reference) validation.
    Raises ConfigError on source violations or validation failures.
    """
    sources = sum(x is not None for x in (config_path, config_yaml))
    if sources == 0:
        raise ConfigError("Provide exactly one of config_path or config_yaml")
    if sources > 1:
        raise ConfigError("Provide exactly one of config_path or config_yaml")

    if config_yaml is not None:
        config = load_config_from_string(config_yaml)
    else:
        assert config_path is not None
        config = load_config(config_path)

    warnings = validate_config(config)
    return ValidateServiceResult(config=config, warnings=warnings)


# ---------------------------------------------------------------------------
# Query + Feedback
# ---------------------------------------------------------------------------


def service_query(
    instance: InstanceProtocol,
    query_name: str,
    params: dict[str, Any],
) -> QueryServiceResult:
    """Execute a named query and persist the receipt.

    Returns results, receipt, and execution metadata.
    """
    config = instance.load_config()
    graph = instance.load_graph()
    result = execute_query(config, graph, query_name, params)

    if result.receipt:
        store = instance.get_receipt_store()
        try:
            store.save_receipt(result.receipt)
        finally:
            store.close()

    total = result.total_results or len(result.results)
    return QueryServiceResult(
        results=result.results,
        receipt_id=result.receipt.receipt_id if result.receipt else None,
        receipt=result.receipt,
        total_results=total,
        steps_executed=result.steps_executed,
    )


def service_feedback(
    instance: InstanceProtocol,
    receipt_id: str,
    action: Literal["approve", "reject", "correct", "flag"],
    source: Literal["human", "ai_review", "system"],
    target: EdgeTarget,
    reason: str = "",
    corrections: dict[str, Any] | None = None,
) -> FeedbackServiceResult:
    """Record feedback on an edge.

    Validates corrections, checks receipt existence, persists feedback,
    and applies to the graph.
    """
    _VALID_ACTIONS = ("approve", "reject", "correct", "flag")
    if action not in _VALID_ACTIONS:
        raise ConfigError(f"Invalid action '{action}'. Use: {', '.join(_VALID_ACTIONS)}")

    _VALID_SOURCES = ("human", "ai_review", "system")
    if source not in _VALID_SOURCES:
        raise ConfigError(f"Invalid source '{source}'. Use: {', '.join(_VALID_SOURCES)}")

    if corrections is not None and not isinstance(corrections, dict):
        raise ConfigError("corrections must be an object")

    # Fail-fast: validate confidence in corrections BEFORE persisting
    if corrections is not None:
        confidence = corrections.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise DataValidationError(
                    f"corrections.confidence must be numeric (float). "
                    f"Got {confidence!r}. "
                    f"Suggested: low=0.3, medium=0.5, high=0.7, very_high=0.9"
                )
        # Strip _provenance from corrections (prevent spoofing in audit trail)
        corrections = {k: v for k, v in corrections.items() if k != "_provenance"}

    graph = instance.load_graph()
    receipt_store = instance.get_receipt_store()

    try:
        if receipt_store.get_receipt(receipt_id) is None:
            raise ReceiptNotFoundError(receipt_id)
    finally:
        receipt_store.close()

    record = FeedbackRecord(
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        corrections=corrections or {},
    )

    feedback_store = instance.get_feedback_store()
    try:
        feedback_store.save_feedback(record)
    finally:
        feedback_store.close()

    applied = apply_feedback(graph, record)
    instance.save_graph(graph)

    return FeedbackServiceResult(feedback_id=record.feedback_id, applied=applied)


def service_outcome(
    instance: InstanceProtocol,
    receipt_id: str,
    outcome: Literal["correct", "incorrect", "partial", "unknown"],
    detail: dict[str, Any] | None = None,
) -> OutcomeServiceResult:
    """Record an outcome for a query.

    Validates receipt existence, persists the outcome record.
    """
    _VALID_OUTCOMES = ("correct", "incorrect", "partial", "unknown")
    if outcome not in _VALID_OUTCOMES:
        raise ConfigError(f"Invalid outcome '{outcome}'. Use: {', '.join(_VALID_OUTCOMES)}")

    if detail is not None and not isinstance(detail, dict):
        raise ConfigError("detail must be an object")

    receipt_store = instance.get_receipt_store()
    try:
        if receipt_store.get_receipt(receipt_id) is None:
            raise ReceiptNotFoundError(receipt_id)
    finally:
        receipt_store.close()

    record = OutcomeRecord(
        receipt_id=receipt_id,
        outcome=outcome,
        detail=detail or {},
    )
    feedback_store = instance.get_feedback_store()
    try:
        feedback_store.save_outcome(record)
    finally:
        feedback_store.close()

    return OutcomeServiceResult(outcome_id=record.outcome_id)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def service_find_candidates(
    instance: InstanceProtocol,
    relationship_type: str,
    strategy: Literal["property_match", "shared_neighbors"],
    match_rules: list[MatchRule] | None = None,
    via_relationship: str | None = None,
    min_overlap: float = 0.5,
    min_confidence: float = 0.5,
    limit: int = 20,
    min_distinct_neighbors: int = 2,
) -> list[CandidateMatch]:
    """Find candidate relationships using a deterministic strategy."""
    _VALID_STRATEGIES = ("property_match", "shared_neighbors")
    if strategy not in _VALID_STRATEGIES:
        raise ConfigError(f"Invalid strategy '{strategy}'. Use: {', '.join(_VALID_STRATEGIES)}")

    if min_distinct_neighbors < 1:
        raise ConfigError("min_distinct_neighbors must be >= 1")

    config = instance.load_config()
    graph = instance.load_graph()

    return find_candidates(
        config,
        graph,
        relationship_type,
        strategy,
        match_rules=match_rules,
        via_relationship=via_relationship,
        min_overlap=min_overlap,
        min_confidence=min_confidence,
        limit=limit,
        min_distinct_neighbors=min_distinct_neighbors,
    )


def service_evaluate(
    instance: InstanceProtocol,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> EvaluationReport:
    """Evaluate graph quality with deterministic checks."""
    config = instance.load_config()
    graph = instance.load_graph()
    return evaluate_graph(
        config,
        graph,
        confidence_threshold=confidence_threshold,
        max_findings=max_findings,
        exclude_orphan_types=exclude_orphan_types,
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def service_init(
    root_dir: str | Path,
    config_path: str | None = None,
    config_yaml: str | None = None,
    data_dir: str | None = None,
) -> InitResult:
    """Initialize a new cruxible instance (create-only).

    Validates config exclusivity, writes inline YAML if needed (with overwrite
    guard + cleanup on failure), creates instance dir.

    Raises ConfigError on source violations.
    """
    if config_path is not None and config_yaml is not None:
        raise ConfigError("Provide exactly one of config_path or config_yaml, not both")
    if config_path is None and config_yaml is None:
        raise ConfigError("config_path or config_yaml is required when initializing a new instance")

    root = Path(root_dir)

    # If config_yaml provided, validate and write to disk
    if config_yaml is not None:
        load_config_from_string(config_yaml)  # validate first
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigError(f"Failed to create directory {root}: {e}") from e
        disk_config = root / "config.yaml"
        if disk_config.exists():
            raise ConfigError(
                f"config.yaml already exists at {root}. "
                "Use config_path to reference the existing file, or remove it first."
            )
        try:
            disk_config.write_text(config_yaml)
        except OSError as e:
            raise ConfigError(f"Failed to write config.yaml: {e}") from e
        config_path = "config.yaml"

    assert config_path is not None
    # Resolve relative config_path against root_dir
    resolved = Path(config_path)
    if not resolved.is_absolute():
        resolved = root / resolved

    try:
        instance = CruxibleInstance.init(root, config_path, data_dir)
    except Exception:
        # Clean up orphaned config.yaml if we wrote it from inline YAML
        if config_yaml is not None:
            try:
                disk_config = root / "config.yaml"
                disk_config.unlink(missing_ok=True)
            except Exception:
                pass
        raise

    # Run semantic validation for warnings
    config = instance.load_config()
    warnings = validate_config(config)

    return InitResult(instance=instance, warnings=warnings)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def service_schema(instance: InstanceProtocol) -> CoreConfig:
    """Get the config for an instance."""
    return instance.load_config()


def service_sample(
    instance: InstanceProtocol,
    entity_type: str,
    limit: int = 5,
) -> list[EntityInstance]:
    """Sample entities of a given type."""
    graph = instance.load_graph()
    entities = graph.list_entities(entity_type)
    return entities[:limit]


def service_get_entity(
    instance: InstanceProtocol,
    entity_type: str,
    entity_id: str,
) -> EntityInstance | None:
    """Look up a specific entity by type and ID."""
    graph = instance.load_graph()
    return graph.get_entity(entity_type, entity_id)


def service_get_relationship(
    instance: InstanceProtocol,
    from_type: str,
    from_id: str,
    relationship_type: str,
    to_type: str,
    to_id: str,
    edge_key: int | None = None,
) -> RelationshipInstance | None:
    """Look up a specific relationship by its endpoints and type.

    Raises EdgeAmbiguityError if multiple edges match and no edge_key given.
    """
    graph = instance.load_graph()

    if edge_key is None:
        count = graph.relationship_count_between(
            from_type, from_id, to_type, to_id, relationship_type
        )
        if count > 1:
            raise EdgeAmbiguityError(
                from_type=from_type,
                from_id=from_id,
                to_type=to_type,
                to_id=to_id,
                relationship=relationship_type,
            )

    return graph.get_relationship(
        from_type, from_id, to_type, to_id, relationship_type, edge_key=edge_key
    )


def service_get_receipt(
    instance: InstanceProtocol,
    receipt_id: str,
) -> Receipt:
    """Retrieve a stored receipt by ID.

    Raises ReceiptNotFoundError if not found.
    """
    store = instance.get_receipt_store()
    try:
        receipt = store.get_receipt(receipt_id)
    finally:
        store.close()
    if receipt is None:
        raise ReceiptNotFoundError(receipt_id)
    return receipt


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def service_list(
    instance: InstanceProtocol,
    resource: Literal["entities", "edges", "receipts", "feedback", "outcomes"],
    *,
    entity_type: str | None = None,
    relationship_type: str | None = None,
    query_name: str | None = None,
    receipt_id: str | None = None,
    property_filter: dict[str, Any] | None = None,
    limit: int = 50,
) -> ListResult:
    """List entities, edges, receipts, feedback, or outcomes."""
    _VALID_RESOURCES = ("entities", "edges", "receipts", "feedback", "outcomes")
    if resource not in _VALID_RESOURCES:
        raise ConfigError(f"Unknown resource '{resource}'. Use: {', '.join(_VALID_RESOURCES)}")

    if property_filter is not None and resource not in ("entities", "edges"):
        raise ConfigError("property_filter is only supported for entities and edges")

    if resource == "entities":
        if not entity_type:
            raise ConfigError("entity_type is required when listing entities")
        graph = instance.load_graph()
        entities = graph.list_entities(entity_type, property_filter=property_filter)
        return ListResult(items=entities[:limit], total=len(entities))

    if resource == "edges":
        graph = instance.load_graph()
        all_edges = graph.list_edges(relationship_type=relationship_type)
        if property_filter:
            all_edges = [
                e
                for e in all_edges
                if all(e["properties"].get(k) == v for k, v in property_filter.items())
            ]
        return ListResult(items=all_edges[:limit], total=len(all_edges))

    if resource == "receipts":
        store = instance.get_receipt_store()
        try:
            summaries = store.list_receipts(query_name=query_name, limit=limit)
            total = store.count_receipts(query_name=query_name)
        finally:
            store.close()
        return ListResult(items=summaries, total=total)

    if resource == "feedback":
        feedback_store = instance.get_feedback_store()
        try:
            feedback_records = feedback_store.list_feedback(receipt_id=receipt_id, limit=limit)
            total = feedback_store.count_feedback(receipt_id=receipt_id)
        finally:
            feedback_store.close()
        return ListResult(items=feedback_records, total=total)

    # outcomes
    feedback_store = instance.get_feedback_store()
    try:
        outcome_records = feedback_store.list_outcomes(receipt_id=receipt_id, limit=limit)
        total = feedback_store.count_outcomes(receipt_id=receipt_id)
    finally:
        feedback_store.close()
    return ListResult(items=outcome_records, total=total)


# ---------------------------------------------------------------------------
# Group Resolve
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


def derive_review_priority(
    members: list[CandidateMember],
    matching: MatchingConfig | None,
    prior_resolution: dict[str, Any] | None,
) -> str:
    """Derive review_priority mechanically from universal states.

    Returns: "critical", "review", or "normal".
    Highest-severity bucket wins.
    """
    if matching is None:
        # No matching config → default to review (first-time, no guardrails)
        return "review" if prior_resolution is None else "normal"

    has_critical = False
    has_review = False

    # Check prior resolution trust
    if prior_resolution is not None:
        if prior_resolution.get("trust_status") == "invalidated":
            has_critical = True
        elif prior_resolution.get("trust_status") == "watch":
            has_review = True

    # Check signals on members
    for m in members:
        for sig in m.signals:
            icfg = matching.integrations.get(sig.integration)
            if icfg is None:
                continue
            if icfg.role == "advisory":
                continue  # Advisory signals ignored for priority

            if sig.signal == "contradict" and icfg.role == "blocking":
                has_critical = True
            elif sig.signal == "unsure":
                if icfg.always_review_on_unsure:
                    has_review = True
                if icfg.role in ("blocking", "required"):
                    has_review = True

    # No prior approved resolution → review
    if prior_resolution is None:
        has_review = True

    if has_critical:
        return "critical"
    if has_review:
        return "review"
    return "normal"


def service_propose_group(
    instance: InstanceProtocol,
    relationship_type: str,
    members: list[CandidateMember],
    thesis_text: str = "",
    thesis_facts: dict[str, Any] | None = None,
    analysis_state: dict[str, Any] | None = None,
    integrations_used: list[str] | None = None,
    proposed_by: Literal["human", "ai_review"] = "ai_review",
    suggested_priority: str | None = None,
) -> ProposeGroupResult:
    """Propose a group of candidate edges for batch review/approval."""
    config = instance.load_config()
    thesis_facts = thesis_facts or {}
    analysis_state = analysis_state or {}
    integrations_used = integrations_used or []

    # 1. Validate relationship_type
    rel_schema = config.get_relationship(relationship_type)
    if rel_schema is None:
        raise ConfigError(f"Relationship type '{relationship_type}' not found in config")

    # 2. Validate members not empty
    if not members:
        raise ConfigError("Members list must not be empty")

    # 3. Validate each member
    for m in members:
        if m.relationship_type != relationship_type:
            raise ConfigError(
                f"Member {m.from_id}\u2192{m.to_id} has relationship_type "
                f"'{m.relationship_type}' but group is for '{relationship_type}'"
            )
        if m.from_type != rel_schema.from_entity:
            raise ConfigError(
                f"Member {m.from_id} from_type '{m.from_type}' does not match "
                f"relationship '{relationship_type}' which expects '{rel_schema.from_entity}'"
            )
        if m.to_type != rel_schema.to_entity:
            raise ConfigError(
                f"Member {m.to_id} to_type '{m.to_type}' does not match "
                f"relationship '{relationship_type}' which expects '{rel_schema.to_entity}'"
            )

    # 4. thesis_facts serialization check
    try:
        _json.dumps(thesis_facts, sort_keys=True)
    except TypeError as exc:
        raise ConfigError(f"thesis_facts must be JSON-serializable: {exc}") from exc

    # 5. Duplicate member check
    seen_members: set[tuple[str, str, str, str, str]] = set()
    for m in members:
        key = (m.from_type, m.from_id, m.to_type, m.to_id, m.relationship_type)
        if key in seen_members:
            raise ConfigError(
                f"Duplicate member: {m.from_type}:{m.from_id} \u2192 "
                f"{m.to_type}:{m.to_id} via {m.relationship_type}"
            )
        seen_members.add(key)

    matching = rel_schema.matching

    # 6. Signal validation (all members)
    for m in members:
        seen_integrations: set[str] = set()
        for sig in m.signals:
            if sig.integration in seen_integrations:
                raise ConfigError(
                    f"Member {m.from_id}\u2192{m.to_id} has duplicate signals "
                    f"from integration '{sig.integration}'"
                )
            seen_integrations.add(sig.integration)

            if matching is not None and matching.integrations:
                if sig.integration not in matching.integrations:
                    declared = ", ".join(sorted(matching.integrations.keys()))
                    raise ConfigError(
                        f"Signal from undeclared integration '{sig.integration}'; "
                        f"declared: {declared}"
                    )

    # 7. Config guardrails (if matching section exists)
    if matching is not None and matching.integrations:
        # Blocking + required integrations: every member must have a signal
        for iname, icfg in matching.integrations.items():
            if icfg.role in ("blocking", "required"):
                for m in members:
                    member_integrations = {s.integration for s in m.signals}
                    if iname not in member_integrations:
                        raise ConfigError(
                            f"Member {m.from_id}\u2192{m.to_id} missing signal "
                            f"from {icfg.role} integration '{iname}'"
                        )

        # integrations_used validation
        for iname in integrations_used:
            if iname not in matching.integrations:
                raise ConfigError(f"Integration '{iname}' not declared in matching.integrations")

        # max_group_size
        if len(members) > matching.max_group_size:
            raise ConfigError(
                f"Group size {len(members)} exceeds max_group_size {matching.max_group_size}"
            )

    # 8. Compute signature
    signature = compute_group_signature(relationship_type, thesis_facts)

    # 9. Check for prior confirmed approved resolution
    group_store = instance.get_group_store()
    try:
        prior = group_store.find_resolution(
            relationship_type, signature, action="approve", confirmed=True
        )

        status = "pending_review"
        if prior is not None:
            # Trust status gate
            if prior.get("trust_status") != "invalidated":
                # Prior trust gate
                trust_ok = False
                if matching is not None:
                    policy = matching.auto_resolve_requires_prior_trust
                    prior_trust = prior.get("trust_status", "watch")
                    if policy == "trusted_only" and prior_trust == "trusted":
                        trust_ok = True
                    elif policy == "trusted_or_watch" and prior_trust in (
                        "trusted",
                        "watch",
                    ):
                        trust_ok = True

                if trust_ok and matching is not None:
                    # Signal policy check
                    auto_resolve = _check_auto_resolve_signals(members, matching)
                    if auto_resolve:
                        status = "auto_resolved"

        # 10. Derive review_priority
        review_priority = derive_review_priority(members, matching, prior)

        # 11. Create and save group
        group_id = f"GRP-{uuid.uuid4().hex[:12]}"
        group = CandidateGroup(
            group_id=group_id,
            relationship_type=relationship_type,
            signature=signature,
            status=status,
            thesis_text=thesis_text,
            thesis_facts=thesis_facts,
            analysis_state=analysis_state,
            integrations_used=integrations_used,
            proposed_by=proposed_by,
            member_count=len(members),
            review_priority=review_priority,
            suggested_priority=suggested_priority,
            created_at=datetime.now(timezone.utc),
        )

        with group_store.transaction():
            group_store.save_group(group)
            group_store.save_members(group_id, members)

        return ProposeGroupResult(
            group_id=group_id,
            signature=signature,
            status=status,
            review_priority=review_priority,
            member_count=len(members),
            prior_resolution=prior,
        )
    finally:
        group_store.close()


def _check_auto_resolve_signals(
    members: list[CandidateMember],
    matching: MatchingConfig,
) -> bool:
    """Check if signals meet the auto_resolve_when policy.

    Returns True if auto-resolve is eligible based on signals alone.
    """
    policy = matching.auto_resolve_when

    for m in members:
        for sig in m.signals:
            icfg = matching.integrations.get(sig.integration)
            if icfg is None or icfg.role == "advisory":
                continue

            # always_review_on_unsure override
            if sig.signal == "unsure" and icfg.always_review_on_unsure:
                return False

            if policy == "all_support":
                if sig.signal != "support":
                    return False
            elif policy == "no_contradict":
                if sig.signal == "contradict" and icfg.role == "blocking":
                    return False

    return True
