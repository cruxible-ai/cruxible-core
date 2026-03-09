"""Runtime graph types for entity instances and relationship instances.

These are the runtime objects stored in the EntityGraph, distinct from
the schema types (PropertySchema, EntityTypeSchema, etc.) which define
the config structure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def make_node_id(entity_type: str, entity_id: str) -> str:
    """Build the canonical node ID for a (type, id) pair."""
    return f"{entity_type}:{entity_id}"


def split_node_id(node_id: str) -> tuple[str, str]:
    """Split a canonical node ID back into (entity_type, entity_id).

    Inverse of ``make_node_id``.  Handles entity IDs that contain colons.
    """
    entity_type, sep, entity_id = node_id.partition(":")
    if not sep:
        raise ValueError(f"Invalid node_id: {node_id!r}")
    return entity_type, entity_id


class EntityInstance(BaseModel):
    """A single entity instance in the graph."""

    entity_type: str
    entity_id: str
    properties: dict[str, Any] = Field(default_factory=dict)

    def node_id(self) -> str:
        """Return the unique node ID for this entity."""
        return make_node_id(self.entity_type, self.entity_id)


class RelationshipInstance(BaseModel):
    """A single relationship instance (edge) in the graph."""

    relationship_type: str
    from_entity_type: str
    from_entity_id: str
    to_entity_type: str
    to_entity_id: str
    edge_key: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    def from_node_id(self) -> str:
        """Return the source node ID."""
        return make_node_id(self.from_entity_type, self.from_entity_id)

    def to_node_id(self) -> str:
        """Return the target node ID."""
        return make_node_id(self.to_entity_type, self.to_entity_id)


REJECTED_STATUSES: frozenset[str] = frozenset({"human_rejected", "ai_rejected"})
"""Edge review_status values that indicate rejection."""


def make_provenance(source: str, source_ref: str) -> dict[str, str]:
    """Create a provenance metadata dict for edge creation."""
    return {
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_ref": source_ref,
    }
