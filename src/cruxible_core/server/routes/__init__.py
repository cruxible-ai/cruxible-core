"""FastAPI route modules for Cruxible server."""

from __future__ import annotations

from cruxible_core.errors import InstanceNotFoundError
from cruxible_core.server.registry import LOCAL_FILESYSTEM_BACKEND, get_registry


def resolve_server_instance_id(instance_id: str) -> str:
    """Resolve an opaque server instance ID to a local backend location."""
    record = get_registry().get(instance_id)
    if record is None or record.backend != LOCAL_FILESYSTEM_BACKEND:
        raise InstanceNotFoundError(instance_id)
    return record.location


__all__ = ["resolve_server_instance_id"]
