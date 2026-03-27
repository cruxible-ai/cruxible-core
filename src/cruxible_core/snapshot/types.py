"""Snapshot and release metadata types for immutable world-model state."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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


class PublishedModelManifest(BaseModel):
    """Distribution metadata for a published model release bundle."""

    format_version: int = 1
    model_id: str
    release_id: str
    snapshot_id: str
    compatibility: str
    owned_entity_types: list[str] = Field(default_factory=list)
    owned_relationship_types: list[str] = Field(default_factory=list)
    parent_release_id: str | None = None

    @field_validator("release_id")
    @classmethod
    def validate_release_id(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[a-zA-Z0-9._-]+", value):
            raise ValueError("release_id must match [a-zA-Z0-9._-]+")
        return value


class UpstreamMetadata(BaseModel):
    """Per-instance upstream release tracking metadata for pullable forks."""

    transport_ref: str
    model_id: str
    release_id: str
    snapshot_id: str
    compatibility: str
    owned_entity_types: list[str] = Field(default_factory=list)
    owned_relationship_types: list[str] = Field(default_factory=list)
    overlay_config_path: str = "config.yaml"
    active_config_path: str = ".cruxible/composed/config.yaml"
    manifest_path: str = ".cruxible/upstream/current/manifest.json"
    graph_path: str = ".cruxible/upstream/current/graph.json"
    config_path: str = ".cruxible/upstream/current/config.yaml"
    lock_path: str = ".cruxible/upstream/current/cruxible.lock.yaml"
    manifest_digest: str | None = None
    graph_digest: str | None = None
