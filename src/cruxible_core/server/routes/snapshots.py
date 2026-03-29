"""Snapshot and fork routes."""

from __future__ import annotations

from fastapi import APIRouter

from cruxible_client import contracts
from cruxible_core.runtime import local_api
from cruxible_core.server.request_models import ForkSnapshotRequest, SnapshotCreateRequest
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["snapshots"])


@router.post("/{instance_id}/snapshots", response_model=contracts.SnapshotCreateResult)
async def create_snapshot(
    instance_id: str,
    req: SnapshotCreateRequest,
) -> contracts.SnapshotCreateResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_create_snapshot_local(resolved_instance_id, req.label)


@router.get("/{instance_id}/snapshots", response_model=contracts.SnapshotListResult)
async def list_snapshots(instance_id: str) -> contracts.SnapshotListResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_list_snapshots_local(resolved_instance_id)


@router.post("/{instance_id}/fork", response_model=contracts.ForkSnapshotResult)
async def fork_snapshot(
    instance_id: str,
    req: ForkSnapshotRequest,
) -> contracts.ForkSnapshotResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_fork_snapshot_local(
        resolved_instance_id,
        req.snapshot_id,
        req.root_dir,
    )
