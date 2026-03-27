"""Mutation routes."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, Request

from cruxible_core.errors import ConfigError
from cruxible_core.mcp import contracts
from cruxible_core.runtime import local_api
from cruxible_core.server.request_models import (
    AddConstraintRequest,
    AddDecisionPolicyRequest,
    AddEntitiesRequest,
    AddRelationshipsRequest,
    IngestRequest,
    ReloadConfigRequest,
)
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["mutations"])


def _normalize_data_json(raw: str | None) -> str | list[dict[str, Any]] | None:
    if raw is None:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ConfigError("data_json must decode to a JSON array")
    return parsed


@router.post("/{instance_id}/ingest", response_model=contracts.IngestResult)
async def ingest(instance_id: str, request: Request) -> contracts.IngestResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        mapping_name = str(form.get("mapping_name") or "")
        if not mapping_name:
            raise ConfigError("mapping_name is required")

        upload_id_raw = form.get("upload_id")
        upload_id = str(upload_id_raw) if upload_id_raw else None
        data_csv = str(form.get("data_csv")) if form.get("data_csv") is not None else None
        data_ndjson = str(form.get("data_ndjson")) if form.get("data_ndjson") is not None else None
        data_json_value = (
            _normalize_data_json(str(form.get("data_json")))
            if form.get("data_json") is not None
            else None
        )
        file_item = form.get("file")
        upload = (
            file_item
            if file_item is not None
            and hasattr(file_item, "read")
            and hasattr(file_item, "filename")
            else None
        )

        temp_path: str | None = None
        if upload is not None:
            suffix = Path(upload.filename or "upload.dat").suffix
            with NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(await upload.read())
                temp_path = handle.name
        try:
            return local_api._handle_ingest_local(
                instance_id=resolved_instance_id,
                mapping_name=mapping_name,
                file_path=temp_path,
                data_csv=data_csv,
                data_json=data_json_value,
                data_ndjson=data_ndjson,
                upload_id=upload_id,
            )
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    payload = IngestRequest.model_validate(await request.json())
    return local_api._handle_ingest_local(
        instance_id=resolved_instance_id,
        mapping_name=payload.mapping_name,
        data_csv=payload.data_csv,
        data_json=payload.data_json,
        data_ndjson=payload.data_ndjson,
        upload_id=payload.upload_id,
    )


@router.post("/{instance_id}/entities", response_model=contracts.AddEntityResult)
async def add_entities(
    instance_id: str,
    req: AddEntitiesRequest,
) -> contracts.AddEntityResult:
    return local_api._handle_add_entity_local(
        instance_id=resolve_server_instance_id(instance_id),
        entities=req.entities,
    )


@router.post("/{instance_id}/relationships", response_model=contracts.AddRelationshipResult)
async def add_relationships(
    instance_id: str,
    req: AddRelationshipsRequest,
) -> contracts.AddRelationshipResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_add_relationship_impl(
        instance_id=resolved_instance_id,
        relationships=req.relationships,
        provenance_source="http_api",
        provenance_source_ref="cruxible_add_relationship",
    )


@router.post("/{instance_id}/constraints", response_model=contracts.AddConstraintResult)
async def add_constraint(
    instance_id: str,
    req: AddConstraintRequest,
) -> contracts.AddConstraintResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_add_constraint_local(
        instance_id=resolved_instance_id,
        name=req.name,
        rule=req.rule,
        severity=req.severity,
        description=req.description,
    )


@router.post(
    "/{instance_id}/decision-policies",
    response_model=contracts.AddDecisionPolicyResult,
)
async def add_decision_policy(
    instance_id: str,
    req: AddDecisionPolicyRequest,
) -> contracts.AddDecisionPolicyResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return local_api._handle_add_decision_policy_local(
        instance_id=resolved_instance_id,
        name=req.name,
        applies_to=req.applies_to,
        relationship_type=req.relationship_type,
        effect=req.effect,
        match=req.match,
        description=req.description,
        rationale=req.rationale,
        query_name=req.query_name,
        workflow_name=req.workflow_name,
        expires_at=req.expires_at,
    )


@router.post("/{instance_id}/config/reload", response_model=contracts.ReloadConfigResult)
async def reload_config(
    instance_id: str,
    req: ReloadConfigRequest,
) -> contracts.ReloadConfigResult:
    return local_api._handle_reload_config_local(
        instance_id=resolve_server_instance_id(instance_id),
        config_path=req.config_path,
    )
