"""Lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter

from cruxible_client import contracts
from cruxible_core.runtime import local_api
from cruxible_core.server.request_models import InitRequest, ValidateRequest

router = APIRouter(prefix="/api/v1", tags=["instances"])


@router.post("/instances", response_model=contracts.InitResult)
async def init_instance(req: InitRequest) -> contracts.InitResult:
    """Create or reload an instance, returning an opaque server ID."""
    return local_api._handle_init_governed(
        root_dir=req.root_dir,
        config_path=req.config_path,
        config_yaml=req.config_yaml,
        data_dir=req.data_dir,
    )


@router.post("/validate", response_model=contracts.ValidateResult)
async def validate_instance(req: ValidateRequest) -> contracts.ValidateResult:
    """Validate a config file or inline YAML."""
    return local_api._handle_validate_local(
        config_path=req.config_path,
        config_yaml=req.config_yaml,
    )
