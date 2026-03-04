"""Receipt builder: records evidence during query execution.

The builder is created before a query runs, collects nodes and edges
as the engine traverses the graph, and produces a Receipt at the end.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from cruxible_core.receipt.types import EvidenceEdge, Receipt, ReceiptNode

_EdgeType = Literal["consulted", "traversed", "filtered", "evaluated", "produced"]


class ReceiptBuilder:
    """Collects evidence nodes and edges during query execution."""

    def __init__(self, query_name: str, parameters: dict[str, Any]) -> None:
        self._query_name = query_name
        self._parameters = parameters
        self._nodes: list[ReceiptNode] = []
        self._edges: list[EvidenceEdge] = []
        self._counter = 0
        self._start_ns = time.monotonic_ns()

        self._root_id = self._add_node(
            node_type="query",
            detail={"query_name": query_name, "parameters": parameters},
        )

    def _next_id(self) -> str:
        self._counter += 1
        return f"n{self._counter}"

    def _add_node(self, **kwargs: Any) -> str:
        node_id = self._next_id()
        self._nodes.append(ReceiptNode(node_id=node_id, **kwargs))
        return node_id

    def _add_edge(self, from_node: str, to_node: str, edge_type: _EdgeType) -> None:
        self._edges.append(EvidenceEdge(from_node=from_node, to_node=to_node, edge_type=edge_type))

    @property
    def root_id(self) -> str:
        return self._root_id

    def record_entity_lookup(
        self,
        entity_type: str,
        entity_id: str,
        parent_id: str | None = None,
    ) -> str:
        """Record that an entity was looked up from the graph."""
        node_id = self._add_node(
            node_type="entity_lookup",
            entity_type=entity_type,
            entity_id=entity_id,
        )
        self._add_edge(parent_id or self._root_id, node_id, "consulted")
        return node_id

    def record_traversal(
        self,
        from_entity_type: str,
        from_entity_id: str,
        to_entity_type: str,
        to_entity_id: str,
        relationship: str,
        edge_props: dict[str, Any],
        edge_key: int | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Record that an edge was traversed from one entity to another."""
        detail: dict[str, Any] = {
            "from_entity_type": from_entity_type,
            "from_entity_id": from_entity_id,
            "edge_properties": edge_props,
        }
        if edge_key is not None:
            detail["edge_key"] = edge_key

        node_id = self._add_node(
            node_type="edge_traversal",
            entity_type=to_entity_type,
            entity_id=to_entity_id,
            relationship=relationship,
            detail=detail,
        )
        self._add_edge(parent_id or self._root_id, node_id, "traversed")
        return node_id

    def record_filter(
        self,
        filter_spec: dict[str, Any],
        passed: bool,
        parent_id: str,
    ) -> str:
        """Record that a filter was applied to an edge."""
        node_id = self._add_node(
            node_type="filter_applied",
            detail={"filter": filter_spec, "passed": passed},
        )
        self._add_edge(parent_id, node_id, "filtered")
        return node_id

    def record_constraint(
        self,
        constraint: str,
        passed: bool,
        entity_type: str,
        entity_id: str,
        parent_id: str,
    ) -> str:
        """Record that a constraint was evaluated against an entity."""
        node_id = self._add_node(
            node_type="constraint_check",
            entity_type=entity_type,
            entity_id=entity_id,
            detail={"constraint": constraint, "passed": passed},
        )
        self._add_edge(parent_id, node_id, "evaluated")
        return node_id

    def record_results(
        self,
        results: list[dict[str, Any]],
        parent_ids: list[str] | None = None,
    ) -> str:
        """Record the final query results."""
        node_id = self._add_node(
            node_type="result",
            detail={"count": len(results)},
        )
        for pid in parent_ids or [self._root_id]:
            self._add_edge(pid, node_id, "produced")
        return node_id

    def build(self, results: list[dict[str, Any]]) -> Receipt:
        """Finalize and return the receipt."""
        elapsed_ms = (time.monotonic_ns() - self._start_ns) / 1_000_000
        return Receipt(
            query_name=self._query_name,
            parameters=self._parameters,
            nodes=list(self._nodes),
            edges=list(self._edges),
            results=results,
            duration_ms=round(elapsed_ms, 3),
        )
