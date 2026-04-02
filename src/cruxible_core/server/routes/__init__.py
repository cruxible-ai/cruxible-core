"""FastAPI route modules for Cruxible server."""

from __future__ import annotations

from cruxible_core.errors import InstanceNotFoundError
from cruxible_core.server.registry import GOVERNED_DAEMON_BACKEND, get_registry


def resolve_server_instance_id(instance_id: str) -> str:
    """Validate and return an opaque governed instance ID."""
    record = get_registry().get(instance_id)
    if record is None or record.backend != GOVERNED_DAEMON_BACKEND:
        raise InstanceNotFoundError(instance_id)
    return instance_id


__all__ = ["resolve_server_instance_id"]
