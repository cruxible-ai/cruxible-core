"""Snapshot metadata types for immutable world-model state."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WorldSnapshot(BaseModel):
    """Immutable local snapshot of graph state and build lineage."""

    snapshot_id: str
    created_at: datetime
    label: str | None = None
    config_digest: str
    lock_digest: str | None = None
    graph_sha256: str
    parent_snapshot_id: str | None = None
    origin_snapshot_id: str | None = None
