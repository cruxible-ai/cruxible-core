"""Lifecycle routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from cruxible_core.mcp import contracts
from cruxible_core.mcp.handlers import _handle_init_local, _handle_validate_local, get_manager
from cruxible_core.server.registry import get_registry
from cruxible_core.server.request_models import InitRequest, ValidateRequest

router = APIRouter(prefix="/api/v1", tags=["instances"])


@router.post("/instances", response_model=contracts.InitResult)
async def init_instance(req: InitRequest) -> contracts.InitResult:
    """Create or reload an instance, returning an opaque server ID."""
    result = _handle_init_local(
        root_dir=req.root_dir,
        config_path=req.config_path,
        config_yaml=req.config_yaml,
        data_dir=req.data_dir,
    )
    instance = get_manager().get(result.instance_id)
    registered = get_registry().get_or_create_local_instance(Path(req.root_dir))
    get_manager().register(registered.record.instance_id, instance)
    return contracts.InitResult(
        instance_id=registered.record.instance_id,
        status=result.status,
        warnings=result.warnings,
    )


@router.post("/validate", response_model=contracts.ValidateResult)
async def validate_instance(req: ValidateRequest) -> contracts.ValidateResult:
    """Validate a config file or inline YAML."""
    return _handle_validate_local(config_path=req.config_path, config_yaml=req.config_yaml)
