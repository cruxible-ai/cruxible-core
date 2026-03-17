"""Handler implementations for MCP tools.

Each handler takes typed arguments and returns a contract model instance.
The InstanceManager holds live CruxibleInstance references.

Most handlers are thin wrappers: permission check → instance get →
map inputs → service call → map result to contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.schema import ConstraintSchema
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import (
    ConfigError,
    InstanceNotFoundError,
)
from cruxible_core.feedback.types import EdgeTarget
from cruxible_core.group.types import CandidateMember, CandidateSignal
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.mcp import contracts
from cruxible_core.mcp.permissions import (
    PermissionMode,
    check_permission,
    validate_root_dir,
)
from cruxible_core.query.candidates import MatchRule
from cruxible_core.service import (
    EntityUpsertInput,
    RelationshipUpsertInput,
    service_add_entities,
    service_add_relationships,
    service_evaluate,
    service_feedback,
    service_find_candidates,
    service_get_entity,
    service_get_group,
    service_get_receipt,
    service_get_relationship,
    service_ingest,
    service_init,
    service_list,
    service_list_groups,
    service_list_resolutions,
    service_outcome,
    service_propose_group,
    service_query,
    service_resolve_group,
    service_sample,
    service_schema,
    service_update_trust_status,
    service_validate,
)


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

    # MCP-specific: validate_root_dir stays here (not in service layer)
    validate_root_dir(root_dir)
    root = Path(root_dir)
    instance_json = root / CruxibleInstance.INSTANCE_DIR / "instance.json"

    # Reload path — MCP-specific (InstanceManager lookup + compatibility check)
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

    # Create path — delegates to service layer
    result = service_init(
        root_dir, config_path=config_path, config_yaml=config_yaml, data_dir=data_dir
    )
    instance_id = str(root)
    _manager.register(instance_id, result.instance)
    return contracts.InitResult(instance_id=instance_id, status="initialized")


def handle_validate(
    config_path: str | None = None,
    config_yaml: str | None = None,
) -> contracts.ValidateResult:
    """Validate a config file or inline YAML string."""
    check_permission("cruxible_validate")

    result = service_validate(config_path=config_path, config_yaml=config_yaml)
    config = result.config
    return contracts.ValidateResult(
        valid=True,
        name=config.name,
        entity_types=list(config.entity_types.keys()),
        relationships=[r.name for r in config.relationships],
        named_queries=list(config.named_queries.keys()),
        warnings=result.warnings,
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
    instance = _manager.get(instance_id)

    result = service_ingest(
        instance,
        mapping_name,
        file_path=file_path,
        data_csv=data_csv,
        data_json=data_json,
        data_ndjson=data_ndjson,
        upload_id=upload_id,
    )
    return contracts.IngestResult(
        records_ingested=result.records_ingested,
        records_updated=result.records_updated,
        mapping=result.mapping,
        entity_type=result.entity_type,
        relationship_type=result.relationship_type,
        receipt_id=result.receipt_id,
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
    result = service_query(instance, query_name, params or {})

    # Limit/truncation is a caller concern — stays in handler
    total = result.total_results
    truncated = limit is not None and total > limit
    visible = result.results[:limit] if truncated else result.results

    # Omit inline receipt whenever limit is set — agent opted into bounded output
    include_receipt = limit is None

    return contracts.QueryToolResult(
        results=[e.model_dump(mode="json") for e in visible],
        receipt_id=result.receipt_id,
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
    receipt = service_get_receipt(instance, receipt_id)
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
    group_override: bool = False,
) -> contracts.FeedbackResult:
    """Record feedback on an edge."""
    check_permission("cruxible_feedback", instance_id=instance_id)
    instance = _manager.get(instance_id)

    target = EdgeTarget(
        from_type=from_type,
        from_id=from_id,
        relationship=relationship,
        to_type=to_type,
        to_id=to_id,
        edge_key=edge_key,
    )
    result = service_feedback(
        instance,
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        corrections=corrections,
        group_override=group_override,
    )
    return contracts.FeedbackResult(
        feedback_id=result.feedback_id, applied=result.applied, receipt_id=result.receipt_id
    )


def handle_outcome(
    instance_id: str,
    receipt_id: str,
    outcome: contracts.OutcomeValue,
    detail: dict[str, Any] | None = None,
) -> contracts.OutcomeResult:
    """Record an outcome for a query."""
    check_permission("cruxible_outcome", instance_id=instance_id)
    instance = _manager.get(instance_id)
    result = service_outcome(instance, receipt_id=receipt_id, outcome=outcome, detail=detail)
    return contracts.OutcomeResult(outcome_id=result.outcome_id)


def handle_list(
    instance_id: str,
    resource_type: contracts.ResourceType,
    entity_type: str | None = None,
    relationship_type: str | None = None,
    query_name: str | None = None,
    receipt_id: str | None = None,
    limit: int = 50,
    property_filter: dict[str, Any] | None = None,
    operation_type: str | None = None,
) -> contracts.ListResult:
    """List entities, edges, receipts, feedback, or outcomes."""
    check_permission("cruxible_list")
    instance = _manager.get(instance_id)

    result = service_list(
        instance,
        resource_type,
        entity_type=entity_type,
        relationship_type=relationship_type,
        query_name=query_name,
        receipt_id=receipt_id,
        property_filter=property_filter,
        operation_type=operation_type,
        limit=limit,
    )

    # Serialize typed items at the MCP edge
    if resource_type in ("entities", "feedback", "outcomes"):
        items = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in result.items
        ]
    else:
        # edges and receipts are already dicts
        items = result.items

    return contracts.ListResult(items=items, total=result.total)


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
    instance = _manager.get(instance_id)

    # Convert dicts to MatchRule at the MCP edge
    rules = None
    if match_rules:
        rules = [MatchRule.model_validate(r) for r in match_rules]

    candidates = service_find_candidates(
        instance,
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
    report = service_evaluate(
        instance,
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
    config = service_schema(instance)
    return config.model_dump(mode="json")


def handle_sample(
    instance_id: str,
    entity_type: str,
    limit: int = 5,
) -> contracts.SampleResult:
    """Sample entities of a given type."""
    check_permission("cruxible_sample")
    instance = _manager.get(instance_id)
    sampled = service_sample(instance, entity_type, limit=limit)
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

    inputs = [
        RelationshipUpsertInput(
            from_type=edge.from_type,
            from_id=edge.from_id,
            relationship=edge.relationship,
            to_type=edge.to_type,
            to_id=edge.to_id,
            properties=edge.properties,
        )
        for edge in relationships
    ]
    result = service_add_relationships(
        instance, inputs, source="mcp_add", source_ref="cruxible_add_relationship"
    )
    return contracts.AddRelationshipResult(
        added=result.added, updated=result.updated, receipt_id=result.receipt_id
    )


def handle_add_entity(
    instance_id: str,
    entities: list[contracts.EntityInput],
) -> contracts.AddEntityResult:
    """Add or update one or more entities in the graph (upsert)."""
    check_permission("cruxible_add_entity", instance_id=instance_id)
    instance = _manager.get(instance_id)

    inputs = [
        EntityUpsertInput(
            entity_type=ent.entity_type,
            entity_id=ent.entity_id,
            properties=ent.properties,
        )
        for ent in entities
    ]
    result = service_add_entities(instance, inputs)
    return contracts.AddEntityResult(
        entities_added=result.added, entities_updated=result.updated, receipt_id=result.receipt_id
    )


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
    entity = service_get_entity(instance, entity_type, entity_id)
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
    rel = service_get_relationship(
        instance, from_type, from_id, relationship_type, to_type, to_id, edge_key=edge_key
    )
    if rel is None:
        return contracts.GetRelationshipResult(
            found=False,
            from_type=from_type,
            from_id=from_id,
            relationship_type=relationship_type,
            to_type=to_type,
            to_id=to_id,
        )
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


def handle_propose_group(
    instance_id: str,
    relationship_type: str,
    members: list[contracts.MemberInput],
    thesis_text: str = "",
    thesis_facts: dict[str, Any] | None = None,
    analysis_state: dict[str, Any] | None = None,
    integrations_used: list[str] | None = None,
    proposed_by: contracts.GroupProposedBy = "ai_review",
    suggested_priority: str | None = None,
) -> contracts.ProposeGroupToolResult:
    """Propose a candidate group for batch edge review."""
    check_permission("cruxible_propose_group", instance_id=instance_id)
    instance = _manager.get(instance_id)

    domain_members = [
        CandidateMember(
            from_type=m.from_type,
            from_id=m.from_id,
            to_type=m.to_type,
            to_id=m.to_id,
            relationship_type=m.relationship_type,
            signals=[
                CandidateSignal(
                    integration=s.integration,
                    signal=s.signal,
                    evidence=s.evidence,
                )
                for s in m.signals
            ],
            properties=m.properties,
        )
        for m in members
    ]

    result = service_propose_group(
        instance,
        relationship_type,
        domain_members,
        thesis_text=thesis_text,
        thesis_facts=thesis_facts,
        analysis_state=analysis_state,
        integrations_used=integrations_used,
        proposed_by=proposed_by,
        suggested_priority=suggested_priority,
    )
    return contracts.ProposeGroupToolResult(
        group_id=result.group_id,
        signature=result.signature,
        status=result.status,
        review_priority=result.review_priority,
        member_count=result.member_count,
        prior_resolution=result.prior_resolution,
    )


def handle_resolve_group(
    instance_id: str,
    group_id: str,
    action: contracts.GroupAction,
    rationale: str = "",
    resolved_by: contracts.GroupResolvedBy = "human",
) -> contracts.ResolveGroupToolResult:
    """Resolve a candidate group (approve or reject)."""
    check_permission("cruxible_resolve_group", instance_id=instance_id)
    instance = _manager.get(instance_id)

    result = service_resolve_group(
        instance,
        group_id,
        action,
        rationale=rationale,
        resolved_by=resolved_by,
    )
    return contracts.ResolveGroupToolResult(
        group_id=result.group_id,
        action=result.action,
        edges_created=result.edges_created,
        edges_skipped=result.edges_skipped,
        resolution_id=result.resolution_id,
        receipt_id=result.receipt_id,
    )


def handle_update_trust_status(
    instance_id: str,
    resolution_id: str,
    trust_status: contracts.GroupTrustStatus,
    reason: str = "",
) -> contracts.UpdateTrustStatusToolResult:
    """Update trust status on a resolution."""
    check_permission("cruxible_update_trust_status", instance_id=instance_id)
    instance = _manager.get(instance_id)

    service_update_trust_status(instance, resolution_id, trust_status, reason=reason)
    return contracts.UpdateTrustStatusToolResult(
        resolution_id=resolution_id,
        trust_status=trust_status,
    )


def handle_get_group(
    instance_id: str,
    group_id: str,
) -> contracts.GetGroupToolResult:
    """Get a candidate group with its members."""
    check_permission("cruxible_get_group")
    instance = _manager.get(instance_id)

    result = service_get_group(instance, group_id)
    return contracts.GetGroupToolResult(
        group=result.group.model_dump(mode="json"),
        members=[m.model_dump(mode="json") for m in result.members],
    )


def handle_list_groups(
    instance_id: str,
    relationship_type: str | None = None,
    status: contracts.GroupStatus | None = None,
    limit: int = 50,
) -> contracts.ListGroupsToolResult:
    """List candidate groups with optional filters."""
    check_permission("cruxible_list_groups")
    instance = _manager.get(instance_id)

    result = service_list_groups(
        instance,
        relationship_type=relationship_type,
        status=status,
        limit=limit,
    )
    return contracts.ListGroupsToolResult(
        groups=[g.model_dump(mode="json") for g in result.groups],
        total=result.total,
    )


def handle_list_resolutions(
    instance_id: str,
    relationship_type: str | None = None,
    action: contracts.GroupAction | None = None,
    limit: int = 50,
) -> contracts.ListResolutionsToolResult:
    """List group resolutions with optional filters."""
    check_permission("cruxible_list_resolutions")
    instance = _manager.get(instance_id)

    result = service_list_resolutions(
        instance,
        relationship_type=relationship_type,
        action=action,
        limit=limit,
    )
    return contracts.ListResolutionsToolResult(
        resolutions=result.resolutions,
        total=result.total,
    )
