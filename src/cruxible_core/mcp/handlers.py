"""Handler implementations for MCP tools.

Each handler takes typed arguments and returns a contract model instance.
The InstanceManager holds live CruxibleInstance references.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.loader import load_config, load_config_from_string
from cruxible_core.config.schema import ConstraintSchema
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import (
    ConfigError,
    DataValidationError,
    EdgeAmbiguityError,
    InstanceNotFoundError,
    ReceiptNotFoundError,
)
from cruxible_core.evaluate import evaluate_graph
from cruxible_core.feedback.applier import apply_feedback
from cruxible_core.feedback.types import EdgeTarget, FeedbackRecord, OutcomeRecord
from cruxible_core.graph.operations import (
    apply_entity as _apply_entity,
)
from cruxible_core.graph.operations import (
    apply_relationship as _apply_relationship,
)
from cruxible_core.graph.operations import (
    validate_entity as _validate_entity,
)
from cruxible_core.graph.operations import (
    validate_relationship as _validate_relationship,
)
from cruxible_core.ingest import ingest_file, ingest_from_mapping, load_data_from_string
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.mcp import contracts
from cruxible_core.mcp.permissions import (
    PermissionMode,
    check_permission,
    validate_root_dir,
)
from cruxible_core.query.candidates import MatchRule, find_candidates
from cruxible_core.query.engine import execute_query


class InstanceManager:
    """Registry of live instance objects keyed by instance_id."""

    def __init__(self) -> None:
        self._instances: dict[str, InstanceProtocol] = {}

    def register(self, instance_id: str, instance: InstanceProtocol) -> None:
        self._instances[instance_id] = instance

    def get(self, instance_id: str) -> InstanceProtocol:
        if instance_id not in self._instances:
            raise InstanceNotFoundError(instance_id)
        return self._instances[instance_id]

    def list_ids(self) -> list[str]:
        return list(self._instances.keys())

    def clear(self) -> None:
        self._instances.clear()


_manager = InstanceManager()


def _check_config_compatibility(instance: InstanceProtocol) -> list[str]:
    """Check if graph contents are compatible with the current config.

    Warns when entity or relationship types exist in the graph but are
    missing from the config (e.g. after a config edit removed a type).
    """
    warnings: list[str] = []
    config = instance.load_config()
    graph = instance.load_graph()

    config_entity_types = set(config.entity_types.keys())
    for graph_type in graph.list_entity_types():
        if graph_type not in config_entity_types:
            count = graph.entity_count(graph_type)
            warnings.append(
                f"Entity type '{graph_type}' exists in graph ({count} entities) "
                "but is missing from config"
            )

    config_rel_types = {r.name for r in config.relationships}
    for graph_rel in graph.list_relationship_types():
        if graph_rel not in config_rel_types:
            count = graph.edge_count(graph_rel)
            warnings.append(
                f"Relationship type '{graph_rel}' exists in graph ({count} edges) "
                "but is missing from config"
            )

    return warnings


def handle_init(
    root_dir: str,
    config_path: str | None = None,
    config_yaml: str | None = None,
    data_dir: str | None = None,
) -> contracts.InitResult:
    """Initialize a new cruxible instance, or reload an existing one."""
    check_permission("cruxible_init")

    has_config = config_path is not None or config_yaml is not None

    # Permission gate first — any config input signals create intent
    if has_config:
        check_permission(
            "cruxible_init",
            instance_id=root_dir,
            required_mode=PermissionMode.ADMIN,
        )
        if config_path is not None and config_yaml is not None:
            raise ConfigError("Provide exactly one of config_path or config_yaml, not both")

    validate_root_dir(root_dir)
    root = Path(root_dir)
    instance_json = root / CruxibleInstance.INSTANCE_DIR / "instance.json"

    if instance_json.exists():
        if has_config:
            raise ConfigError(
                f"Instance already exists at {root}. "
                "To update the config, edit the YAML file on disk, then call "
                "cruxible_init(root_dir=...) without config_path/config_yaml to reload. "
                "The updated config takes effect immediately."
            )
        instance = CruxibleInstance.load(root)
        instance_id = str(root)
        _manager.register(instance_id, instance)
        warnings = _check_config_compatibility(instance)
        return contracts.InitResult(instance_id=instance_id, status="loaded", warnings=warnings)

    if not has_config:
        raise ConfigError("config_path or config_yaml is required when initializing a new instance")

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
    try:
        instance = CruxibleInstance.init(root, config_path, data_dir)
    except Exception:
        # Clean up orphaned config.yaml if we wrote it from inline YAML
        if config_yaml is not None:
            try:
                disk_config = root / "config.yaml"
                disk_config.unlink(missing_ok=True)
            except Exception:
                pass  # Suppress cleanup errors to preserve original exception
        raise
    instance_id = str(root)
    _manager.register(instance_id, instance)
    return contracts.InitResult(instance_id=instance_id, status="initialized")


def handle_validate(
    config_path: str | None = None,
    config_yaml: str | None = None,
) -> contracts.ValidateResult:
    """Validate a config file or inline YAML string."""
    check_permission("cruxible_validate")

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
    return contracts.ValidateResult(
        valid=True,
        name=config.name,
        entity_types=list(config.entity_types.keys()),
        relationships=[r.name for r in config.relationships],
        named_queries=list(config.named_queries.keys()),
        warnings=warnings,
    )


def handle_ingest(
    instance_id: str,
    mapping_name: str,
    file_path: str | None = None,
    data_csv: str | None = None,
    data_json: str | list[dict[str, Any]] | None = None,
    data_ndjson: str | None = None,
    upload_id: str | None = None,
) -> contracts.IngestResult:
    """Ingest a data file or inline data into the graph."""
    check_permission("cruxible_ingest", instance_id=instance_id)

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

    instance = _manager.get(instance_id)
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
        # FastMCP's pre_parse_json may have already deserialized the string
        # into a list/dict for `str | None` annotations. Re-serialize if needed.
        if not isinstance(data_json, str):
            data_json = _json.dumps(data_json)
        df = load_data_from_string(data_json, "json")
        added, updated = ingest_from_mapping(config, graph, mapping_name, df)

    instance.save_graph(graph)
    mapping = config.ingestion[mapping_name]
    return contracts.IngestResult(
        records_ingested=added,
        records_updated=updated,
        mapping=mapping_name,
        entity_type=mapping.entity_type,
        relationship_type=mapping.relationship_type,
    )


def handle_query(
    instance_id: str,
    query_name: str,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
) -> contracts.QueryToolResult:
    """Execute a named query."""
    check_permission("cruxible_query")
    if limit is not None and limit < 1:
        raise ConfigError("limit must be a positive integer")

    instance = _manager.get(instance_id)
    config = instance.load_config()
    graph = instance.load_graph()
    result = execute_query(config, graph, query_name, params or {})

    # Persist receipt for future lookup (always, regardless of limit)
    if result.receipt:
        store = instance.get_receipt_store()
        try:
            store.save_receipt(result.receipt)
        finally:
            store.close()

    total = result.total_results or len(result.results)
    truncated = limit is not None and total > limit
    visible = result.results[:limit] if truncated else result.results

    # Omit inline receipt whenever limit is set — agent opted into bounded output
    include_receipt = limit is None

    return contracts.QueryToolResult(
        results=[e.model_dump(mode="json") for e in visible],
        receipt_id=result.receipt.receipt_id if result.receipt else None,
        receipt=(
            result.receipt.model_dump(mode="json") if result.receipt and include_receipt else None
        ),
        total_results=total,
        truncated=truncated,
        steps_executed=result.steps_executed,
    )


def handle_receipt(
    instance_id: str,
    receipt_id: str,
) -> dict[str, Any]:
    """Retrieve a stored receipt by ID."""
    check_permission("cruxible_receipt")
    instance = _manager.get(instance_id)
    store = instance.get_receipt_store()
    try:
        receipt = store.get_receipt(receipt_id)
    finally:
        store.close()
    if receipt is None:
        raise ReceiptNotFoundError(receipt_id)

    return receipt.model_dump(mode="json")


def handle_feedback(
    instance_id: str,
    receipt_id: str,
    action: contracts.FeedbackAction,
    source: contracts.FeedbackSource,
    from_type: str,
    from_id: str,
    relationship: str,
    to_type: str,
    to_id: str,
    edge_key: int | None = None,
    reason: str = "",
    corrections: dict[str, Any] | None = None,
) -> contracts.FeedbackResult:
    """Record feedback on an edge."""
    check_permission("cruxible_feedback", instance_id=instance_id)
    if corrections is not None and not isinstance(corrections, dict):
        raise ConfigError("corrections must be an object")

    # Fail-fast: validate confidence in corrections BEFORE persisting to SQLite
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

    instance = _manager.get(instance_id)
    graph = instance.load_graph()
    receipt_store = instance.get_receipt_store()

    try:
        if receipt_store.get_receipt(receipt_id) is None:
            raise ReceiptNotFoundError(receipt_id)
    finally:
        receipt_store.close()

    target = EdgeTarget(
        from_type=from_type,
        from_id=from_id,
        relationship=relationship,
        to_type=to_type,
        to_id=to_id,
        edge_key=edge_key,
    )
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

    return contracts.FeedbackResult(feedback_id=record.feedback_id, applied=applied)


def handle_outcome(
    instance_id: str,
    receipt_id: str,
    outcome: contracts.OutcomeValue,
    detail: dict[str, Any] | None = None,
) -> contracts.OutcomeResult:
    """Record an outcome for a query."""
    check_permission("cruxible_outcome", instance_id=instance_id)
    instance = _manager.get(instance_id)
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

    return contracts.OutcomeResult(outcome_id=record.outcome_id)


def handle_list(
    instance_id: str,
    resource_type: contracts.ResourceType,
    entity_type: str | None = None,
    relationship_type: str | None = None,
    query_name: str | None = None,
    receipt_id: str | None = None,
    limit: int = 50,
    property_filter: dict[str, Any] | None = None,
) -> contracts.ListResult:
    """List entities, edges, receipts, feedback, or outcomes."""
    check_permission("cruxible_list")

    if property_filter is not None and resource_type not in ("entities", "edges"):
        raise ConfigError("property_filter is only supported for entities and edges")

    instance = _manager.get(instance_id)

    if resource_type == "entities":
        if not entity_type:
            raise ConfigError("entity_type is required when listing entities")
        graph = instance.load_graph()
        entities = graph.list_entities(entity_type, property_filter=property_filter)
        items = [e.model_dump(mode="json") for e in entities[:limit]]
        return contracts.ListResult(items=items, total=len(entities))

    elif resource_type == "edges":
        graph = instance.load_graph()
        all_edges = graph.list_edges(relationship_type=relationship_type)
        if property_filter:
            all_edges = [
                e
                for e in all_edges
                if all(e["properties"].get(k) == v for k, v in property_filter.items())
            ]
        total = len(all_edges)
        items = all_edges[:limit]
        return contracts.ListResult(items=items, total=total)

    elif resource_type == "receipts":
        store = instance.get_receipt_store()
        try:
            summaries = store.list_receipts(query_name=query_name, limit=limit)
            total = store.count_receipts(query_name=query_name)
        finally:
            store.close()
        return contracts.ListResult(items=summaries, total=total)

    elif resource_type == "feedback":
        feedback_store = instance.get_feedback_store()
        try:
            feedback_records = feedback_store.list_feedback(receipt_id=receipt_id, limit=limit)
            total = feedback_store.count_feedback(receipt_id=receipt_id)
        finally:
            feedback_store.close()
        items = [r.model_dump(mode="json") for r in feedback_records]
        return contracts.ListResult(items=items, total=total)

    elif resource_type == "outcomes":
        feedback_store = instance.get_feedback_store()
        try:
            outcome_records = feedback_store.list_outcomes(receipt_id=receipt_id, limit=limit)
            total = feedback_store.count_outcomes(receipt_id=receipt_id)
        finally:
            feedback_store.close()
        items = [r.model_dump(mode="json") for r in outcome_records]
        return contracts.ListResult(items=items, total=total)

    else:
        raise ConfigError(
            f"Unknown resource_type '{resource_type}'. "
            "Use: entities, edges, receipts, feedback, outcomes"
        )


def handle_find_candidates(
    instance_id: str,
    relationship_type: str,
    strategy: contracts.CandidateStrategy,
    match_rules: list[dict[str, str]] | None = None,
    via_relationship: str | None = None,
    min_overlap: float = 0.5,
    min_confidence: float = 0.5,
    limit: int = 20,
    min_distinct_neighbors: int = 2,
) -> contracts.CandidatesResult:
    """Find candidate relationships."""
    check_permission("cruxible_find_candidates")
    if min_distinct_neighbors < 1:
        raise ConfigError("min_distinct_neighbors must be >= 1")
    instance = _manager.get(instance_id)
    config = instance.load_config()
    graph = instance.load_graph()

    rules = None
    if match_rules:
        rules = [MatchRule.model_validate(r) for r in match_rules]

    candidates = find_candidates(
        config,
        graph,
        relationship_type,
        strategy,
        match_rules=rules,
        via_relationship=via_relationship,
        min_overlap=min_overlap,
        min_confidence=min_confidence,
        limit=limit,
        min_distinct_neighbors=min_distinct_neighbors,
    )

    return contracts.CandidatesResult(
        candidates=[c.model_dump(mode="json") for c in candidates],
        total=len(candidates),
    )


def handle_evaluate(
    instance_id: str,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> contracts.EvaluateResult:
    """Evaluate graph quality."""
    check_permission("cruxible_evaluate")
    instance = _manager.get(instance_id)
    config = instance.load_config()
    graph = instance.load_graph()
    report = evaluate_graph(
        config,
        graph,
        confidence_threshold=confidence_threshold,
        max_findings=max_findings,
        exclude_orphan_types=exclude_orphan_types,
    )
    return contracts.EvaluateResult(
        entity_count=report.entity_count,
        edge_count=report.edge_count,
        findings=[f.model_dump(mode="json") for f in report.findings],
        summary=report.summary,
    )


def handle_schema(instance_id: str) -> dict[str, Any]:
    """Get config schema details."""
    check_permission("cruxible_schema")
    instance = _manager.get(instance_id)
    config = instance.load_config()
    return config.model_dump(mode="json")


def handle_sample(
    instance_id: str,
    entity_type: str,
    limit: int = 5,
) -> contracts.SampleResult:
    """Sample entities of a given type."""
    check_permission("cruxible_sample")
    instance = _manager.get(instance_id)
    graph = instance.load_graph()
    entities = graph.list_entities(entity_type)
    sampled = entities[:limit]
    return contracts.SampleResult(
        entities=[e.model_dump(mode="json") for e in sampled],
        entity_type=entity_type,
        count=len(sampled),
    )


def handle_add_relationship(
    instance_id: str,
    relationships: list[contracts.RelationshipInput],
) -> contracts.AddRelationshipResult:
    """Add or update one or more relationships in the graph (upsert)."""
    check_permission("cruxible_add_relationship", instance_id=instance_id)
    instance = _manager.get(instance_id)
    config = instance.load_config()
    graph = instance.load_graph()

    errors: list[str] = []
    batch_seen: set[tuple[str, str, str, str, str]] = set()
    pending = []

    for i, edge in enumerate(relationships, start=1):
        # Duplicate in batch check (stays in handler for batch-level logic)
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
            validated = _validate_relationship(
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
        _apply_relationship(graph, validated, "mcp_add", "cruxible_add_relationship")
        if validated.is_update:
            updated += 1
        else:
            added += 1

    instance.save_graph(graph)
    return contracts.AddRelationshipResult(added=added, updated=updated)


def handle_add_entity(
    instance_id: str,
    entities: list[contracts.EntityInput],
) -> contracts.AddEntityResult:
    """Add or update one or more entities in the graph (upsert)."""
    check_permission("cruxible_add_entity", instance_id=instance_id)
    instance = _manager.get(instance_id)
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
            validated = _validate_entity(
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
        _apply_entity(graph, validated)
        if validated.is_update:
            updated += 1
        else:
            added += 1

    instance.save_graph(graph)
    return contracts.AddEntityResult(entities_added=added, entities_updated=updated)


def handle_add_constraint(
    instance_id: str,
    name: str,
    rule: str,
    severity: contracts.ConstraintSeverity = "warning",
    description: str | None = None,
) -> contracts.AddConstraintResult:
    """Add a constraint rule to the config and write back to YAML."""
    check_permission("cruxible_add_constraint", instance_id=instance_id)
    instance = _manager.get(instance_id)
    config = instance.load_config()

    # Check for duplicate constraint name
    for existing in config.constraints:
        if existing.name == name:
            raise ConfigError(f"Constraint '{name}' already exists in config")

    # Validate rule syntax
    parsed = parse_constraint_rule(rule)
    if parsed is None:
        raise ConfigError(
            f"Rule syntax not supported: {rule!r}. "
            "Expected: RELATIONSHIP.FROM.property == RELATIONSHIP.TO.property"
        )

    warnings: list[str] = []
    rel_name, from_prop, to_prop = parsed

    # Validate property names against schema
    rel_schema = config.get_relationship(rel_name)
    if rel_schema is None:
        warnings.append(f"Relationship '{rel_name}' not found in config schema")
    else:
        from_entity_schema = config.get_entity_type(rel_schema.from_entity)
        to_entity_schema = config.get_entity_type(rel_schema.to_entity)
        if from_entity_schema and from_prop not in from_entity_schema.properties:
            warnings.append(
                f"Property '{from_prop}' not found on entity type '{rel_schema.from_entity}'"
            )
        if to_entity_schema and to_prop not in to_entity_schema.properties:
            warnings.append(
                f"Property '{to_prop}' not found on entity type '{rel_schema.to_entity}'"
            )

    # Create and append constraint
    constraint = ConstraintSchema(
        name=name,
        rule=rule,
        severity=severity,
        description=description,
    )
    config.constraints.append(constraint)

    # Run cross-reference validation
    config_warnings = validate_config(config)
    warnings.extend(config_warnings)

    # Write back to YAML
    instance.save_config(config)

    return contracts.AddConstraintResult(
        name=name,
        added=True,
        config_updated=True,
        warnings=warnings,
    )


def handle_get_entity(
    instance_id: str,
    entity_type: str,
    entity_id: str,
) -> contracts.GetEntityResult:
    """Look up a specific entity by type and ID."""
    check_permission("cruxible_get_entity")
    instance = _manager.get(instance_id)
    graph = instance.load_graph()
    entity = graph.get_entity(entity_type, entity_id)
    if entity is None:
        return contracts.GetEntityResult(found=False, entity_type=entity_type, entity_id=entity_id)
    return contracts.GetEntityResult(
        found=True,
        entity_type=entity.entity_type,
        entity_id=entity.entity_id,
        properties=entity.properties,
    )


def handle_get_relationship(
    instance_id: str,
    from_type: str,
    from_id: str,
    relationship_type: str,
    to_type: str,
    to_id: str,
    edge_key: int | None = None,
) -> contracts.GetRelationshipResult:
    """Look up a specific relationship by its endpoints and type."""
    check_permission("cruxible_get_relationship")
    instance = _manager.get(instance_id)
    graph = instance.load_graph()

    not_found = contracts.GetRelationshipResult(
        found=False,
        from_type=from_type,
        from_id=from_id,
        relationship_type=relationship_type,
        to_type=to_type,
        to_id=to_id,
    )

    # When no edge_key, check for ambiguity
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

    rel = graph.get_relationship(
        from_type, from_id, to_type, to_id, relationship_type, edge_key=edge_key
    )
    if rel is None:
        return not_found

    return contracts.GetRelationshipResult(
        found=True,
        from_type=rel.from_entity_type,
        from_id=rel.from_entity_id,
        relationship_type=rel.relationship_type,
        to_type=rel.to_entity_type,
        to_id=rel.to_entity_id,
        edge_key=rel.edge_key,
        properties=rel.properties,
    )
