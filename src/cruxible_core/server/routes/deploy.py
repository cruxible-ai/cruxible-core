"""Remote deploy/bootstrap and runtime-credential routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Query, Request, UploadFile

from cruxible_client import contracts
from cruxible_core.errors import ConfigError
from cruxible_core.server.auth import require_bootstrap_or_admin_auth
from cruxible_core.server.config import get_deploy_upload_max_bytes
from cruxible_core.server.deploy import (
    claim_deploy_admin_key,
    create_runtime_key,
    get_deploy_operation_status,
    get_deploy_status,
    list_runtime_keys,
    recover_deploy_admin_key,
    revoke_runtime_key,
    stage_deploy_upload,
    start_deploy_bootstrap,
)
from cruxible_core.server.request_models import (
    DeployBootstrapStartRequest,
    RuntimeCredentialCreateRequest,
)

router = APIRouter(prefix="/api/v1/deploy", tags=["deploy"])


@router.post("/uploads", response_model=contracts.DeployUploadResult)
async def upload_deploy_bundle(bundle: UploadFile = File(...)) -> contracts.DeployUploadResult:
    """Upload and stage a deploy bundle for bootstrap."""
    require_bootstrap_or_admin_auth()
    max_bytes = get_deploy_upload_max_bytes()
    suffix = Path(bundle.filename or "bundle.zip").suffix or ".zip"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            temp_path = Path(handle.name)
            total_bytes = 0
            while True:
                chunk = await bundle.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise ConfigError(
                        f"Deploy bundle exceeds the maximum upload size of {max_bytes} bytes"
                    )
                handle.write(chunk)
        assert temp_path is not None
        return stage_deploy_upload(temp_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.post("/bootstrap/start", response_model=contracts.DeployBootstrapStartResult)
async def bootstrap_start(
    req: DeployBootstrapStartRequest,
    request: Request,
) -> contracts.DeployBootstrapStartResult:
    """Start or resume bootstrap for the primary deployed governed instance."""
    return start_deploy_bootstrap(
        system_id=req.system_id,
        upload_id=req.upload_id,
        instance_slug=req.instance_slug,
        server_url=str(request.base_url).rstrip("/"),
    )


@router.get(
    "/operations/{operation_id}",
    response_model=contracts.DeployOperationStatus,
)
async def deploy_operation_status(
    operation_id: str,
    request: Request,
) -> contracts.DeployOperationStatus:
    """Read detailed status for an async deploy operation."""
    return get_deploy_operation_status(
        operation_id=operation_id,
        server_url=str(request.base_url).rstrip("/"),
    )


@router.post(
    "/operations/{operation_id}/claim-admin-key",
    response_model=contracts.ClaimAdminKeyResult,
)
async def claim_admin_key(
    operation_id: str,
    request: Request,
) -> contracts.ClaimAdminKeyResult:
    """Claim the one-time initial admin credential for a completed deploy."""
    return claim_deploy_admin_key(
        operation_id=operation_id,
        server_url=str(request.base_url).rstrip("/"),
    )


@router.post(
    "/operations/{operation_id}/recover-admin-key",
    response_model=contracts.ClaimAdminKeyResult,
)
async def recover_admin_key(
    operation_id: str,
    request: Request,
) -> contracts.ClaimAdminKeyResult:
    """Recover the initial admin credential after losing the in-memory claim token."""
    return recover_deploy_admin_key(
        operation_id=operation_id,
        server_url=str(request.base_url).rstrip("/"),
    )


@router.get("/status", response_model=contracts.DeployStatusResult)
async def deploy_status(
    request: Request,
    system_id: str = Query(...),
) -> contracts.DeployStatusResult:
    """Read deploy/bootstrap status for a system."""
    require_bootstrap_or_admin_auth(system_id=system_id)
    return get_deploy_status(system_id=system_id, server_url=str(request.base_url).rstrip("/"))


@router.post("/keys", response_model=contracts.RuntimeCredentialCreateResult)
async def create_key(
    req: RuntimeCredentialCreateRequest,
) -> contracts.RuntimeCredentialCreateResult:
    """Create an instance-scoped runtime bearer credential."""
    return create_runtime_key(role=req.role, subject_label=req.subject_label)


@router.get("/keys", response_model=contracts.RuntimeCredentialListResult)
async def list_keys() -> contracts.RuntimeCredentialListResult:
    """List runtime bearer credentials for the authenticated instance."""
    return list_runtime_keys()


@router.post("/keys/{key_id}/revoke", response_model=contracts.RuntimeCredentialRevokeResult)
async def revoke_key(key_id: str) -> contracts.RuntimeCredentialRevokeResult:
    """Revoke a runtime bearer credential."""
    return revoke_runtime_key(key_id)
