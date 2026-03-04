"""Query engine: execute named queries from config against an EntityGraph.

Traversal model:
- Start at an entry entity (resolved from params via primary key)
- Each TraversalStep follows one or more relationships (fan-out),
  applying edge filters and target entity constraints
- Steps chain: output entities of step N become input for step N+1
- max_depth controls how many hops a single step traverses (BFS)
- Final step output is the query result
"""

from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from cruxible_core.errors import (
    EntityNotFoundError,
    QueryExecutionError,
    QueryNotFoundError,
    RelationshipNotFoundError,
)
from cruxible_core.graph.types import EntityInstance
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.receipt.types import Receipt

if TYPE_CHECKING:
    from cruxible_core.config.schema import CoreConfig, TraversalStep
    from cruxible_core.graph.entity_graph import EntityGraph


class QueryResult(BaseModel):
    """Result of executing a named query."""

    query_name: str
    parameters: dict[str, Any]
    results: list[EntityInstance]
    steps_executed: int
    total_results: int | None = None
    receipt: Receipt | None = None

    def model_post_init(self, _context: Any) -> None:
        if self.total_results is None:
            self.total_results = len(self.results)


def execute_query(
    config: CoreConfig,
    graph: EntityGraph,
    query_name: str,
    params: dict[str, Any],
) -> QueryResult:
    """Execute a named query from the config against the graph.

    Resolves the entry entity from params using the entry_point type's
    primary key, then chains traversal steps. Builds a receipt DAG
    recording every lookup, traversal, filter, and constraint.

    Args:
        config: Config with named query definitions
        graph: Populated graph to query
        query_name: Name of the query in config.named_queries
        params: Query parameters (must include entry entity ID)

    Returns:
        QueryResult with matching entities and a Receipt
    """
    query_schema = config.named_queries.get(query_name)
    if query_schema is None:
        raise QueryNotFoundError(query_name)

    builder = ReceiptBuilder(query_name=query_name, parameters=params)

    entry_entity = _resolve_entry_entity(
        config,
        graph,
        query_schema.entry_point,
        params,
        builder=builder,
    )

    current_entities = [entry_entity]
    current_parent_ids: list[str] | None = None
    steps_executed = 0

    for step in query_schema.traversal:
        current_entities, current_parent_ids = _execute_step(
            config,
            graph,
            step,
            current_entities,
            params,
            builder=builder,
        )
        steps_executed += 1

    result_dicts = [e.model_dump() for e in current_entities]
    builder.record_results(result_dicts, parent_ids=current_parent_ids)
    receipt = builder.build(result_dicts)

    return QueryResult(
        query_name=query_name,
        parameters=params,
        results=current_entities,
        steps_executed=steps_executed,
        receipt=receipt,
    )


def _resolve_entry_entity(
    config: CoreConfig,
    graph: EntityGraph,
    entry_point: str,
    params: dict[str, Any],
    *,
    builder: ReceiptBuilder | None = None,
) -> EntityInstance:
    """Find the entry entity using the primary key from params."""
    entity_schema = config.get_entity_type(entry_point)
    if entity_schema is None:
        raise QueryExecutionError(f"Entry point entity type '{entry_point}' not in config")

    pk = entity_schema.get_primary_key()
    if pk is None:
        raise QueryExecutionError(f"Entity type '{entry_point}' has no primary key")

    entity_id = params.get(pk)
    if entity_id is None:
        raise QueryExecutionError(
            f"Parameter '{pk}' required for entry point '{entry_point}'. "
            f"Got params: {sorted(params.keys())}"
        )

    entity = graph.get_entity(entry_point, str(entity_id))
    if entity is None:
        raise EntityNotFoundError(entry_point, str(entity_id))

    if builder is not None:
        builder.record_entity_lookup(
            entity_type=entity.entity_type,
            entity_id=entity.entity_id,
        )

    return entity


def _execute_step(
    config: CoreConfig,
    graph: EntityGraph,
    step: TraversalStep,
    current_entities: list[EntityInstance],
    params: dict[str, Any],
    *,
    builder: ReceiptBuilder | None = None,
) -> tuple[list[EntityInstance], list[str] | None]:
    """Execute one traversal step via BFS with multi-relationship fan-out.

    Supports multiple relationship types per step and multi-hop traversal
    via max_depth. Three dedup layers:
      1. Expansion dedup: never expand the same node twice
      2. Result dedup: each entity appears once in output (first path owns lineage)
      3. Evidence: all traversal edges recorded in receipt regardless of dedup
    """
    # Validate all relationship types up front
    rel_types = step.relationship_types
    for rel_name in rel_types:
        if config.get_relationship(rel_name) is None:
            raise RelationshipNotFoundError(rel_name)

    direction = step.direction
    next_entities: list[EntityInstance] = []
    next_parent_ids: list[str] = []

    # BFS state
    # Queue entries: (entity, current_depth, parent_traversal_id)
    queue: deque[tuple[EntityInstance, int, str | None]] = deque()
    seen_expanded: set[str] = set()  # nodes already expanded (neighbors queried)
    seen_results: set[str] = set()  # nodes already in result list

    # Seed queue with input entities (they are inputs, not results)
    for entity in current_entities:
        nid = entity.node_id()
        seen_expanded.add(nid)
        seen_results.add(nid)
        queue.append((entity, 0, None))

    while queue:
        entity, depth, parent_tid = queue.popleft()

        if depth >= step.max_depth:
            continue

        for rel_type in rel_types:
            neighbors = graph.get_neighbors_with_edge_refs(
                entity.entity_type,
                entity.entity_id,
                relationship_type=rel_type,
                direction=direction,
            )

            for neighbor, edge_props, edge_key in neighbors:
                if edge_props.get("review_status") in _REJECTED_STATUSES:
                    continue

                nid = neighbor.node_id()

                # Record evidence regardless of dedup
                traversal_id = None
                if builder is not None:
                    traversal_id = builder.record_traversal(
                        from_entity_type=entity.entity_type,
                        from_entity_id=entity.entity_id,
                        to_entity_type=neighbor.entity_type,
                        to_entity_id=neighbor.entity_id,
                        relationship=rel_type,
                        edge_props=edge_props,
                        edge_key=edge_key,
                        parent_id=parent_tid,
                    )

                # Apply filter (blocks subtree on failure)
                if step.filter:
                    passed = _matches_filter(edge_props, step.filter)
                    if builder is not None and traversal_id is not None:
                        builder.record_filter(
                            filter_spec=step.filter,
                            passed=passed,
                            parent_id=traversal_id,
                        )
                    if not passed:
                        continue

                # Apply constraint (blocks subtree on failure)
                if step.constraint:
                    passed = _evaluate_constraint(
                        step.constraint,
                        neighbor,
                        params,
                    )
                    if builder is not None and traversal_id is not None:
                        builder.record_constraint(
                            constraint=step.constraint,
                            passed=passed,
                            entity_type=neighbor.entity_type,
                            entity_id=neighbor.entity_id,
                            parent_id=traversal_id,
                        )
                    if not passed:
                        continue

                # Result dedup: first path owns the lineage
                if nid not in seen_results:
                    seen_results.add(nid)
                    next_entities.append(neighbor)
                    if traversal_id is not None:
                        next_parent_ids.append(traversal_id)

                # Expansion dedup: enqueue for deeper hops if not yet expanded
                if nid not in seen_expanded:
                    seen_expanded.add(nid)
                    queue.append((neighbor, depth + 1, traversal_id))

    return next_entities, next_parent_ids or None


def _matches_filter(
    edge_props: dict[str, Any],
    filter_spec: dict[str, Any],
) -> bool:
    """Check if edge properties match a filter specification.

    Filter values can be:
    - A scalar: edge property must equal it
    - A list: edge property must be in the list
    """
    for key, expected in filter_spec.items():
        actual = edge_props.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


_REJECTED_STATUSES = {"human_rejected", "ai_rejected"}

_CONSTRAINT_RE = re.compile(r"^(target|source)\.(\w+)\s*(==|!=)\s*(.+)$")


def _evaluate_constraint(
    constraint: str,
    target_entity: EntityInstance,
    params: dict[str, Any],
) -> bool:
    """Evaluate a simple constraint expression.

    Supported format: "target.<property> == $<param>" or literal.

    Examples:
        "target.vehicle_id == $vehicle_id"
        "target.category != brakes"
    """
    match = _CONSTRAINT_RE.match(constraint.strip())
    if match is None:
        return True  # Unknown constraint format — don't filter

    side, prop, operator, rhs = match.groups()
    rhs = rhs.strip()

    if side == "target":
        lhs_value = target_entity.properties.get(prop)
    else:
        return True  # 'source' not supported in collection mode

    if rhs.startswith("$"):
        rhs_value = params.get(rhs[1:])
    else:
        rhs_value = _parse_literal(rhs)

    if operator == "==":
        return lhs_value == rhs_value
    if operator == "!=":
        return lhs_value != rhs_value
    return True


def _parse_literal(value: str) -> Any:
    """Parse a literal value from a constraint string."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    # Strip quotes if present
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value
