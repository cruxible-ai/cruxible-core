"""Read/query routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from cruxible_core.errors import ConfigError
from cruxible_core.mcp import contracts
from cruxible_core.mcp.handlers import (
    _handle_evaluate_local,
    _handle_find_candidates_local,
    _handle_get_entity_local,
    _handle_get_group_local,
    _handle_get_relationship_local,
    _handle_inspect_entity_local,
    _handle_list_groups_local,
    _handle_list_local,
    _handle_list_resolutions_local,
    _handle_query_local,
    _handle_receipt_local,
    _handle_sample_local,
    _handle_schema_local,
    _handle_stats_local,
)
from cruxible_core.server.request_models import EvaluateRequest, FindCandidatesRequest, QueryRequest
from cruxible_core.server.routes import resolve_server_instance_id

router = APIRouter(prefix="/api/v1", tags=["queries"])


def _parse_property_filter(property_filter: str | None) -> dict[str, Any] | None:
    if property_filter is None:
        return None
    try:
        parsed = json.loads(property_filter)
    except json.JSONDecodeError as exc:
        raise ConfigError("property_filter must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ConfigError("property_filter must decode to a JSON object")
    return parsed


@router.post("/{instance_id}/query", response_model=contracts.QueryToolResult)
async def query(instance_id: str, req: QueryRequest) -> contracts.QueryToolResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_query_local(
        instance_id=resolved_instance_id,
        query_name=req.query_name,
        params=req.params,
        limit=req.limit,
    )


@router.get("/{instance_id}/receipts/{receipt_id}")
async def receipt(instance_id: str, receipt_id: str) -> dict[str, Any]:
    return _handle_receipt_local(
        instance_id=resolve_server_instance_id(instance_id),
        receipt_id=receipt_id,
    )


@router.get("/{instance_id}/list/{resource_type}", response_model=contracts.ListResult)
async def list_resources(
    instance_id: str,
    resource_type: contracts.ResourceType,
    entity_type: str | None = None,
    relationship_type: str | None = None,
    query_name: str | None = None,
    receipt_id: str | None = None,
    limit: int = 50,
    property_filter: str | None = None,
    operation_type: str | None = None,
) -> contracts.ListResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_list_local(
        instance_id=resolved_instance_id,
        resource_type=resource_type,
        entity_type=entity_type,
        relationship_type=relationship_type,
        query_name=query_name,
        receipt_id=receipt_id,
        limit=limit,
        property_filter=_parse_property_filter(property_filter),
        operation_type=operation_type,
    )


@router.get("/{instance_id}/schema")
async def schema(instance_id: str) -> dict[str, Any]:
    return _handle_schema_local(resolve_server_instance_id(instance_id))


@router.get("/{instance_id}/stats", response_model=contracts.StatsResult)
async def stats(instance_id: str) -> contracts.StatsResult:
    return _handle_stats_local(resolve_server_instance_id(instance_id))


@router.get("/{instance_id}/sample/{entity_type}", response_model=contracts.SampleResult)
async def sample(instance_id: str, entity_type: str, limit: int = 5) -> contracts.SampleResult:
    return _handle_sample_local(
        resolve_server_instance_id(instance_id),
        entity_type,
        limit=limit,
    )


@router.post("/{instance_id}/evaluate", response_model=contracts.EvaluateResult)
async def evaluate(instance_id: str, req: EvaluateRequest) -> contracts.EvaluateResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_evaluate_local(
        instance_id=resolved_instance_id,
        confidence_threshold=req.confidence_threshold,
        max_findings=req.max_findings,
        exclude_orphan_types=req.exclude_orphan_types,
    )


@router.post("/{instance_id}/candidates", response_model=contracts.CandidatesResult)
async def candidates(
    instance_id: str,
    req: FindCandidatesRequest,
) -> contracts.CandidatesResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_find_candidates_local(
        instance_id=resolved_instance_id,
        relationship_type=req.relationship_type,
        strategy=req.strategy,
        match_rules=req.match_rules,
        via_relationship=req.via_relationship,
        min_overlap=req.min_overlap,
        min_confidence=req.min_confidence,
        limit=req.limit,
        min_distinct_neighbors=req.min_distinct_neighbors,
    )


@router.get(
    "/{instance_id}/entities/{entity_type}/{entity_id}",
    response_model=contracts.GetEntityResult,
)
async def get_entity(
    instance_id: str,
    entity_type: str,
    entity_id: str,
) -> contracts.GetEntityResult:
    return _handle_get_entity_local(
        resolve_server_instance_id(instance_id),
        entity_type,
        entity_id,
    )


@router.get(
    "/{instance_id}/inspect/entity/{entity_type}/{entity_id}",
    response_model=contracts.InspectEntityResult,
)
async def inspect_entity(
    instance_id: str,
    entity_type: str,
    entity_id: str,
    direction: str = Query("both"),
    relationship_type: str | None = None,
    limit: int | None = None,
) -> contracts.InspectEntityResult:
    return _handle_inspect_entity_local(
        resolve_server_instance_id(instance_id),
        entity_type,
        entity_id,
        direction=direction,
        relationship_type=relationship_type,
        limit=limit,
    )


@router.get(
    "/{instance_id}/relationships/lookup",
    response_model=contracts.GetRelationshipResult,
)
async def get_relationship(
    instance_id: str,
    from_type: str = Query(...),
    from_id: str = Query(...),
    relationship_type: str = Query(...),
    to_type: str = Query(...),
    to_id: str = Query(...),
    edge_key: int | None = None,
) -> contracts.GetRelationshipResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_get_relationship_local(
        instance_id=resolved_instance_id,
        from_type=from_type,
        from_id=from_id,
        relationship_type=relationship_type,
        to_type=to_type,
        to_id=to_id,
        edge_key=edge_key,
    )


@router.get("/{instance_id}/groups/{group_id}", response_model=contracts.GetGroupToolResult)
async def get_group(instance_id: str, group_id: str) -> contracts.GetGroupToolResult:
    return _handle_get_group_local(resolve_server_instance_id(instance_id), group_id)


@router.get("/{instance_id}/groups", response_model=contracts.ListGroupsToolResult)
async def list_groups(
    instance_id: str,
    relationship_type: str | None = None,
    status: contracts.GroupStatus | None = None,
    limit: int = 50,
) -> contracts.ListGroupsToolResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_list_groups_local(
        resolved_instance_id,
        relationship_type=relationship_type,
        status=status,
        limit=limit,
    )


@router.get("/{instance_id}/resolutions", response_model=contracts.ListResolutionsToolResult)
async def list_resolutions(
    instance_id: str,
    relationship_type: str | None = None,
    action: contracts.GroupAction | None = None,
    limit: int = 50,
) -> contracts.ListResolutionsToolResult:
    resolved_instance_id = resolve_server_instance_id(instance_id)
    return _handle_list_resolutions_local(
        resolved_instance_id,
        relationship_type=relationship_type,
        action=action,
        limit=limit,
    )
