"""Canonical in-process instance manager singleton."""

from __future__ import annotations

from pathlib import Path

from cruxible_core.errors import InstanceNotFoundError
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.server.registry import LOCAL_FILESYSTEM_BACKEND, get_registry


class InstanceManager:
    """Registry of live instance objects keyed by instance_id."""

    def __init__(self) -> None:
        self._instances: dict[str, InstanceProtocol] = {}

    def register(self, instance_id: str, instance: InstanceProtocol) -> None:
        self._instances[instance_id] = instance

    def get(self, instance_id: str) -> InstanceProtocol:
        instance = self._instances.get(instance_id)
        if instance is not None:
            return instance

        record = get_registry().get(instance_id)
        if record is not None and record.backend == LOCAL_FILESYSTEM_BACKEND:
            loaded = CruxibleInstance.load(Path(record.location))
            self.register(instance_id, loaded)
            return loaded

        try:
            loaded = CruxibleInstance.load(Path(instance_id))
        except InstanceNotFoundError as exc:
            raise InstanceNotFoundError(instance_id) from exc
        self.register(instance_id, loaded)
        return loaded

    def list_ids(self) -> list[str]:
        return list(self._instances.keys())

    def clear(self) -> None:
        self._instances.clear()


_manager = InstanceManager()


def get_manager() -> InstanceManager:
    """Return the process-global instance manager."""
    return _manager
