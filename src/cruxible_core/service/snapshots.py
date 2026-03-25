"""Snapshot and fork service functions."""

from __future__ import annotations

from pathlib import Path

from cruxible_core.errors import ConfigError
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.service.types import ForkSnapshotResult, SnapshotCreateResult, SnapshotListResult


def service_create_snapshot(
    instance: InstanceProtocol,
    label: str | None = None,
) -> SnapshotCreateResult:
    """Create an immutable full snapshot for the current instance."""
    snapshot = instance.create_snapshot(label=label)
    return SnapshotCreateResult(snapshot=snapshot)


def service_list_snapshots(instance: InstanceProtocol) -> SnapshotListResult:
    """List snapshots for the current instance."""
    return SnapshotListResult(snapshots=instance.list_snapshots())


def service_fork_snapshot(
    instance: InstanceProtocol,
    snapshot_id: str,
    root_dir: str | Path,
) -> ForkSnapshotResult:
    """Create a new local instance from a selected snapshot."""
    if not isinstance(instance, CruxibleInstance):
        raise ConfigError("Snapshot fork currently supports only local filesystem instances")

    forked, snapshot = CruxibleInstance.fork_from_snapshot(instance, snapshot_id, root_dir)
    return ForkSnapshotResult(instance=forked, snapshot=snapshot)
