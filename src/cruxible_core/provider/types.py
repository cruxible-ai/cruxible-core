"""Provider execution types."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class ResolvedArtifact(BaseModel):
    """Resolved artifact metadata passed to provider executions."""

    name: str
    kind: str
    uri: str
    local_path: str | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderContext(BaseModel):
    """Read-only execution metadata exposed to provider callables."""

    workflow_name: str
    step_id: str
    provider_name: str
    provider_version: str
    provider_config: dict[str, Any] = Field(default_factory=dict)
    deterministic: bool = True
    artifact: ResolvedArtifact | None = None


class ExecutionTrace(BaseModel):
    """Persisted trace proving that a provider execution ran."""

    trace_id: str = Field(default_factory=lambda: f"TRC-{uuid.uuid4().hex[:12]}")
    workflow_name: str
    step_id: str
    provider_name: str
    provider_version: str
    provider_ref: str
    provider_entrypoint_sha256: str | None = None
    runtime: str
    deterministic: bool
    side_effects: bool
    artifact_name: str | None = None
    artifact_sha256: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "error"] = "success"
    error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0


class ProviderCallable(Protocol):
    """Callable provider implementation resolved from a provider ref."""

    def __call__(self, input_payload: dict[str, Any], context: ProviderContext) -> dict[str, Any]:
        """Execute a provider call and return a JSON-serializable payload."""
