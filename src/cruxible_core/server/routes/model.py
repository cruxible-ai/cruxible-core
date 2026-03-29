"""Published model release and pull routes."""

from __future__ import annotations

from fastapi import APIRouter

from cruxible_client import contracts
from cruxible_core.runtime import local_api
from cruxible_core.server.request_models import (
    ModelForkRequest,
    ModelPublishRequest,
    ModelPullApplyRequest,
)
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["model"])


@router.post("/models/fork", response_model=contracts.ModelForkResult)
async def model_fork(req: ModelForkRequest) -> contracts.ModelForkResult:
    """Create a new local fork from a published model release."""
    return local_api._handle_model_fork_local(
        transport_ref=req.transport_ref,
        root_dir=req.root_dir,
    )


@router.post("/{instance_id}/model/publish", response_model=contracts.ModelPublishResult)
async def model_publish(
    instance_id: str,
    req: ModelPublishRequest,
) -> contracts.ModelPublishResult:
    """Publish a root world-model instance to a release transport."""
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_model_publish_local(
        resolved_instance_id,
        transport_ref=req.transport_ref,
        model_id=req.model_id,
        release_id=req.release_id,
        compatibility=req.compatibility,
    )


@router.get("/{instance_id}/model/status", response_model=contracts.ModelStatusResult)
async def model_status(instance_id: str) -> contracts.ModelStatusResult:
    """Read upstream tracking metadata for a release-backed fork."""
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_model_status_local(resolved_instance_id)


@router.post(
    "/{instance_id}/model/pull/preview",
    response_model=contracts.ModelPullPreviewResult,
)
async def model_pull_preview(instance_id: str) -> contracts.ModelPullPreviewResult:
    """Preview pulling a new upstream release into a fork."""
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_model_pull_preview_local(resolved_instance_id)


@router.post(
    "/{instance_id}/model/pull/apply",
    response_model=contracts.ModelPullApplyResult,
)
async def model_pull_apply(
    instance_id: str,
    req: ModelPullApplyRequest,
) -> contracts.ModelPullApplyResult:
    """Apply a previewed upstream release into a fork."""
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_model_pull_apply_local(
        resolved_instance_id,
        expected_apply_digest=req.expected_apply_digest,
    )
