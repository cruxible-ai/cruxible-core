"""Receipt types: a DAG of evidence showing how a query result was derived.

A receipt is a structured proof — not a log, not a trace. It records which
entities were consulted, which edges were traversed, which filters/constraints
passed or failed, and what produced the final result.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReceiptNode(BaseModel):
    """A single node in the receipt DAG."""

    node_id: str
    node_type: Literal[
        "query",
        "entity_lookup",
        "edge_traversal",
        "filter_applied",
        "constraint_check",
        "result",
        "mutation",
        "validation",
        "entity_write",
        "relationship_write",
        "feedback_applied",
        "ingest_batch",
    ]
    entity_type: str | None = None
    entity_id: str | None = None
    relationship: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceEdge(BaseModel):
    """A directed edge in the receipt DAG connecting two nodes."""

    from_node: str
    to_node: str
    edge_type: Literal[
        "consulted",
        "traversed",
        "filtered",
        "evaluated",
        "produced",
        "validated",
        "mutated",
        "applied",
    ]


class Receipt(BaseModel):
    """A complete receipt for a query execution."""

    receipt_id: str = Field(default_factory=lambda: f"RCP-{uuid.uuid4().hex[:12]}")
    query_name: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    nodes: list[ReceiptNode]
    edges: list[EvidenceEdge]
    results: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0
    operation_type: str = "query"
    committed: bool = True
