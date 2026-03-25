"""Query and read service functions."""

from __future__ import annotations

from typing import Any, Literal

from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError, EdgeAmbiguityError, ReceiptNotFoundError
from cruxible_core.graph.types import EntityInstance, RelationshipInstance
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.query.engine import execute_query
from cruxible_core.receipt.types import Receipt
from cruxible_core.service.types import (
    InspectEntityResult,
    InspectNeighborResult,
    ListResult,
    QueryParamHints,
    QueryServiceResult,
    StatsServiceResult,
)

# ---------------------------------------------------------------------------
# Query
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
        param_hints=_query_param_hints(config, graph, query_name),
    )


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


def service_stats(instance: InstanceProtocol) -> StatsServiceResult:
    """Return graph counts grouped by entity and relationship type."""
    graph = instance.load_graph()
    entity_counts = {
        entity_type: graph.entity_count(entity_type)
        for entity_type in graph.list_entity_types()
    }
    relationship_counts = {
        relationship_type: graph.edge_count(relationship_type)
        for relationship_type in graph.list_relationship_types()
    }
    return StatsServiceResult(
        entity_count=graph.entity_count(),
        edge_count=graph.edge_count(),
        entity_counts=entity_counts,
        relationship_counts=relationship_counts,
        head_snapshot_id=instance.get_head_snapshot_id(),
    )


def service_get_entity(
    instance: InstanceProtocol,
    entity_type: str,
    entity_id: str,
) -> EntityInstance | None:
    """Look up a specific entity by type and ID."""
    graph = instance.load_graph()
    return graph.get_entity(entity_type, entity_id)


def service_inspect_entity(
    instance: InstanceProtocol,
    entity_type: str,
    entity_id: str,
    *,
    direction: Literal["incoming", "outgoing", "both"] = "both",
    relationship_type: str | None = None,
    limit: int | None = None,
) -> InspectEntityResult:
    """Look up an entity and its immediate neighbors."""
    graph = instance.load_graph()
    entity = graph.get_entity(entity_type, entity_id)
    if entity is None:
        return InspectEntityResult(found=False, entity_type=entity_type, entity_id=entity_id)

    neighbor_rows = graph.get_neighbor_relationships(
        entity_type,
        entity_id,
        relationship_type=relationship_type,
        direction=direction,
    )
    total_neighbors = len(neighbor_rows)
    if limit is not None:
        neighbor_rows = neighbor_rows[:limit]
    neighbors = [
        InspectNeighborResult(
            direction=row["direction"],
            relationship_type=str(row["relationship_type"]),
            edge_key=row.get("edge_key"),
            properties=dict(row.get("properties", {})),
            entity=row["entity"],
        )
        for row in neighbor_rows
    ]
    return InspectEntityResult(
        found=True,
        entity_type=entity.entity_type,
        entity_id=entity.entity_id,
        properties=dict(entity.properties),
        neighbors=neighbors,
        total_neighbors=total_neighbors,
    )


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


def _query_param_hints(
    config: CoreConfig,
    graph,
    query_name: str,
) -> QueryParamHints | None:
    query_schema = config.named_queries.get(query_name)
    if query_schema is None:
        return None
    entity_schema = config.get_entity_type(query_schema.entry_point)
    primary_key = entity_schema.get_primary_key() if entity_schema is not None else None
    required_params = [primary_key] if primary_key is not None else []
    example_ids: list[str] = []
    if primary_key is not None:
        example_ids = sorted(
            entity.entity_id for entity in graph.list_entities(query_schema.entry_point)
        )[:3]
    return QueryParamHints(
        entry_point=query_schema.entry_point,
        required_params=required_params,
        primary_key=primary_key,
        example_ids=example_ids,
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
    operation_type: str | None = None,
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
            summaries = store.list_receipts(
                query_name=query_name, operation_type=operation_type, limit=limit
            )
            total = store.count_receipts(query_name=query_name, operation_type=operation_type)
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
