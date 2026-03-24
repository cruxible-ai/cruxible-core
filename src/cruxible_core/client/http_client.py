"""HTTP client for Cruxible server mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from cruxible_core.errors import ConfigError, CoreError
from cruxible_core.mcp import contracts
from cruxible_core.server.errors import ErrorResponse, response_to_error

ModelT = TypeVar("ModelT", bound=BaseModel)


class CruxibleClient:
    """Thin sync client for local UDS or remote HTTP transports."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        socket_path: str | None = None,
        token: str | None = None,
    ) -> None:
        if bool(base_url) == bool(socket_path):
            raise ConfigError("Configure exactly one of base_url or socket_path for CruxibleClient")

        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if socket_path is not None:
            self._client = httpx.Client(
                base_url="http://cruxible",
                headers=headers,
                transport=httpx.HTTPTransport(uds=socket_path),
            )
        else:
            assert base_url is not None
            self._client = httpx.Client(base_url=base_url, headers=headers)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CruxibleClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _check_error(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            body = ErrorResponse.model_validate(response.json())
        except Exception as exc:
            raise CoreError(
                f"Server request failed with status {response.status_code}: {response.text}"
            ) from exc
        raise response_to_error(response.status_code, body)

    def _parse_model(self, response: httpx.Response, model_cls: type[ModelT]) -> ModelT:
        self._check_error(response)
        return model_cls.model_validate(response.json())

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
        self._check_error(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise CoreError("Expected JSON object response from Cruxible server")
        return payload

    def init(
        self,
        root_dir: str,
        config_path: str | None = None,
        config_yaml: str | None = None,
        data_dir: str | None = None,
    ) -> contracts.InitResult:
        response = self._client.post(
            "/api/v1/instances",
            json={
                "root_dir": root_dir,
                "config_path": config_path,
                "config_yaml": config_yaml,
                "data_dir": data_dir,
            },
        )
        return self._parse_model(response, contracts.InitResult)

    def validate(
        self,
        config_path: str | None = None,
        config_yaml: str | None = None,
    ) -> contracts.ValidateResult:
        response = self._client.post(
            "/api/v1/validate",
            json={"config_path": config_path, "config_yaml": config_yaml},
        )
        return self._parse_model(response, contracts.ValidateResult)

    def ingest(
        self,
        instance_id: str,
        mapping_name: str,
        *,
        file_path: str | None = None,
        data_csv: str | None = None,
        data_json: str | list[dict[str, Any]] | None = None,
        data_ndjson: str | None = None,
        upload_id: str | None = None,
    ) -> contracts.IngestResult:
        if file_path is not None:
            path = Path(file_path)
            with path.open("rb") as handle:
                response = self._client.post(
                    f"/api/v1/{instance_id}/ingest",
                    data={
                        "mapping_name": mapping_name,
                        "upload_id": upload_id or "",
                    },
                    files={"file": (path.name, handle)},
                )
            return self._parse_model(response, contracts.IngestResult)

        response = self._client.post(
            f"/api/v1/{instance_id}/ingest",
            json={
                "mapping_name": mapping_name,
                "data_csv": data_csv,
                "data_json": data_json,
                "data_ndjson": data_ndjson,
                "upload_id": upload_id,
            },
        )
        return self._parse_model(response, contracts.IngestResult)

    def query(
        self,
        instance_id: str,
        query_name: str,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> contracts.QueryToolResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/query",
            json={"query_name": query_name, "params": params, "limit": limit},
        )
        return self._parse_model(response, contracts.QueryToolResult)

    def receipt(self, instance_id: str, receipt_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/v1/{instance_id}/receipts/{receipt_id}")
        return self._parse_json(response)

    def feedback(
        self,
        instance_id: str,
        *,
        receipt_id: str,
        action: contracts.FeedbackAction,
        source: contracts.FeedbackSource,
        from_type: str,
        from_id: str,
        relationship: str,
        to_type: str,
        to_id: str,
        edge_key: int | None = None,
        reason: str = "",
        corrections: dict[str, Any] | None = None,
        group_override: bool = False,
    ) -> contracts.FeedbackResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/feedback",
            json={
                "receipt_id": receipt_id,
                "action": action,
                "source": source,
                "from_type": from_type,
                "from_id": from_id,
                "relationship": relationship,
                "to_type": to_type,
                "to_id": to_id,
                "edge_key": edge_key,
                "reason": reason,
                "corrections": corrections,
                "group_override": group_override,
            },
        )
        return self._parse_model(response, contracts.FeedbackResult)

    def feedback_batch(
        self,
        instance_id: str,
        *,
        items: list[contracts.FeedbackBatchItemInput],
        source: contracts.FeedbackSource,
    ) -> contracts.FeedbackBatchResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/feedback/batch",
            json={
                "source": source,
                "items": [item.model_dump(mode="json") for item in items],
            },
        )
        return self._parse_model(response, contracts.FeedbackBatchResult)

    def outcome(
        self,
        instance_id: str,
        *,
        receipt_id: str,
        outcome: contracts.OutcomeValue,
        detail: dict[str, Any] | None = None,
    ) -> contracts.OutcomeResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/outcome",
            json={"receipt_id": receipt_id, "outcome": outcome, "detail": detail},
        )
        return self._parse_model(response, contracts.OutcomeResult)

    def list(
        self,
        instance_id: str,
        *,
        resource_type: contracts.ResourceType,
        entity_type: str | None = None,
        relationship_type: str | None = None,
        query_name: str | None = None,
        receipt_id: str | None = None,
        limit: int = 50,
        property_filter: dict[str, Any] | None = None,
        operation_type: str | None = None,
    ) -> contracts.ListResult:
        params: dict[str, Any] = {
            "entity_type": entity_type,
            "relationship_type": relationship_type,
            "query_name": query_name,
            "receipt_id": receipt_id,
            "limit": limit,
            "operation_type": operation_type,
        }
        if property_filter is not None:
            params["property_filter"] = json.dumps(property_filter)
        response = self._client.get(f"/api/v1/{instance_id}/list/{resource_type}", params=params)
        return self._parse_model(response, contracts.ListResult)

    def find_candidates(
        self,
        instance_id: str,
        *,
        relationship_type: str,
        strategy: contracts.CandidateStrategy,
        match_rules: list[dict[str, str]] | None = None,
        via_relationship: str | None = None,
        min_overlap: float = 0.5,
        min_confidence: float = 0.5,
        limit: int = 20,
        min_distinct_neighbors: int = 2,
    ) -> contracts.CandidatesResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/candidates",
            json={
                "relationship_type": relationship_type,
                "strategy": strategy,
                "match_rules": match_rules,
                "via_relationship": via_relationship,
                "min_overlap": min_overlap,
                "min_confidence": min_confidence,
                "limit": limit,
                "min_distinct_neighbors": min_distinct_neighbors,
            },
        )
        return self._parse_model(response, contracts.CandidatesResult)

    def evaluate(
        self,
        instance_id: str,
        *,
        confidence_threshold: float = 0.5,
        max_findings: int = 100,
        exclude_orphan_types: list[str] | None = None,
    ) -> contracts.EvaluateResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/evaluate",
            json={
                "confidence_threshold": confidence_threshold,
                "max_findings": max_findings,
                "exclude_orphan_types": exclude_orphan_types,
            },
        )
        return self._parse_model(response, contracts.EvaluateResult)

    def schema(self, instance_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/v1/{instance_id}/schema")
        return self._parse_json(response)

    def sample(self, instance_id: str, entity_type: str, limit: int = 5) -> contracts.SampleResult:
        response = self._client.get(
            f"/api/v1/{instance_id}/sample/{entity_type}",
            params={"limit": limit},
        )
        return self._parse_model(response, contracts.SampleResult)

    def add_relationships(
        self,
        instance_id: str,
        relationships: list[contracts.RelationshipInput],
    ) -> contracts.AddRelationshipResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/relationships",
            json={"relationships": [item.model_dump(mode="json") for item in relationships]},
        )
        return self._parse_model(response, contracts.AddRelationshipResult)

    def add_entities(
        self,
        instance_id: str,
        entities: list[contracts.EntityInput],
    ) -> contracts.AddEntityResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/entities",
            json={"entities": [item.model_dump(mode="json") for item in entities]},
        )
        return self._parse_model(response, contracts.AddEntityResult)

    def workflow_lock(self, instance_id: str) -> contracts.WorkflowLockResult:
        response = self._client.post(f"/api/v1/{instance_id}/workflows/lock")
        return self._parse_model(response, contracts.WorkflowLockResult)

    def workflow_plan(
        self,
        instance_id: str,
        *,
        workflow_name: str,
        input_payload: dict[str, Any] | None = None,
    ) -> contracts.WorkflowPlanResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/workflows/plan",
            json={"workflow_name": workflow_name, "input": input_payload or {}},
        )
        return self._parse_model(response, contracts.WorkflowPlanResult)

    def workflow_run(
        self,
        instance_id: str,
        *,
        workflow_name: str,
        input_payload: dict[str, Any] | None = None,
    ) -> contracts.WorkflowRunResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/workflows/run",
            json={"workflow_name": workflow_name, "input": input_payload or {}},
        )
        return self._parse_model(response, contracts.WorkflowRunResult)

    def workflow_apply(
        self,
        instance_id: str,
        *,
        workflow_name: str,
        expected_apply_digest: str,
        expected_head_snapshot_id: str | None = None,
        input_payload: dict[str, Any] | None = None,
    ) -> contracts.WorkflowApplyResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/workflows/apply",
            json={
                "workflow_name": workflow_name,
                "input": input_payload or {},
                "expected_apply_digest": expected_apply_digest,
                "expected_head_snapshot_id": expected_head_snapshot_id,
            },
        )
        return self._parse_model(response, contracts.WorkflowApplyResult)

    def workflow_test(
        self,
        instance_id: str,
        *,
        name: str | None = None,
    ) -> contracts.WorkflowTestResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/workflows/test",
            json={"name": name},
        )
        return self._parse_model(response, contracts.WorkflowTestResult)

    def propose_workflow(
        self,
        instance_id: str,
        *,
        workflow_name: str,
        input_payload: dict[str, Any] | None = None,
    ) -> contracts.WorkflowProposeResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/workflows/propose",
            json={"workflow_name": workflow_name, "input": input_payload or {}},
        )
        return self._parse_model(response, contracts.WorkflowProposeResult)

    def create_snapshot(
        self,
        instance_id: str,
        *,
        label: str | None = None,
    ) -> contracts.SnapshotCreateResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/snapshots",
            json={"label": label},
        )
        return self._parse_model(response, contracts.SnapshotCreateResult)

    def list_snapshots(self, instance_id: str) -> contracts.SnapshotListResult:
        response = self._client.get(f"/api/v1/{instance_id}/snapshots")
        return self._parse_model(response, contracts.SnapshotListResult)

    def fork_snapshot(
        self,
        instance_id: str,
        *,
        snapshot_id: str,
        root_dir: str,
    ) -> contracts.ForkSnapshotResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/fork",
            json={"snapshot_id": snapshot_id, "root_dir": root_dir},
        )
        return self._parse_model(response, contracts.ForkSnapshotResult)

    def add_constraint(
        self,
        instance_id: str,
        *,
        name: str,
        rule: str,
        severity: contracts.ConstraintSeverity = "warning",
        description: str | None = None,
    ) -> contracts.AddConstraintResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/constraints",
            json={
                "name": name,
                "rule": rule,
                "severity": severity,
                "description": description,
            },
        )
        return self._parse_model(response, contracts.AddConstraintResult)

    def get_entity(
        self,
        instance_id: str,
        entity_type: str,
        entity_id: str,
    ) -> contracts.GetEntityResult:
        response = self._client.get(f"/api/v1/{instance_id}/entities/{entity_type}/{entity_id}")
        return self._parse_model(response, contracts.GetEntityResult)

    def get_relationship(
        self,
        instance_id: str,
        *,
        from_type: str,
        from_id: str,
        relationship_type: str,
        to_type: str,
        to_id: str,
        edge_key: int | None = None,
    ) -> contracts.GetRelationshipResult:
        response = self._client.get(
            f"/api/v1/{instance_id}/relationships/lookup",
            params={
                "from_type": from_type,
                "from_id": from_id,
                "relationship_type": relationship_type,
                "to_type": to_type,
                "to_id": to_id,
                "edge_key": edge_key,
            },
        )
        return self._parse_model(response, contracts.GetRelationshipResult)

    def propose_group(
        self,
        instance_id: str,
        *,
        relationship_type: str,
        members: list[contracts.MemberInput],
        thesis_text: str = "",
        thesis_facts: dict[str, Any] | None = None,
        analysis_state: dict[str, Any] | None = None,
        integrations_used: list[str] | None = None,
        proposed_by: contracts.GroupProposedBy = "ai_review",
        suggested_priority: str | None = None,
    ) -> contracts.ProposeGroupToolResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/groups/propose",
            json={
                "relationship_type": relationship_type,
                "members": [item.model_dump(mode="json") for item in members],
                "thesis_text": thesis_text,
                "thesis_facts": thesis_facts,
                "analysis_state": analysis_state,
                "integrations_used": integrations_used,
                "proposed_by": proposed_by,
                "suggested_priority": suggested_priority,
            },
        )
        return self._parse_model(response, contracts.ProposeGroupToolResult)

    def resolve_group(
        self,
        instance_id: str,
        group_id: str,
        *,
        action: contracts.GroupAction,
        rationale: str = "",
        resolved_by: contracts.GroupResolvedBy = "human",
    ) -> contracts.ResolveGroupToolResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/groups/{group_id}/resolve",
            json={"action": action, "rationale": rationale, "resolved_by": resolved_by},
        )
        return self._parse_model(response, contracts.ResolveGroupToolResult)

    def update_trust_status(
        self,
        instance_id: str,
        resolution_id: str,
        *,
        trust_status: contracts.GroupTrustStatus,
        reason: str = "",
    ) -> contracts.UpdateTrustStatusToolResult:
        response = self._client.patch(
            f"/api/v1/{instance_id}/resolutions/{resolution_id}/trust",
            json={"trust_status": trust_status, "reason": reason},
        )
        return self._parse_model(response, contracts.UpdateTrustStatusToolResult)

    def get_group(self, instance_id: str, group_id: str) -> contracts.GetGroupToolResult:
        response = self._client.get(f"/api/v1/{instance_id}/groups/{group_id}")
        return self._parse_model(response, contracts.GetGroupToolResult)

    def list_groups(
        self,
        instance_id: str,
        *,
        relationship_type: str | None = None,
        status: contracts.GroupStatus | None = None,
        limit: int = 50,
    ) -> contracts.ListGroupsToolResult:
        response = self._client.get(
            f"/api/v1/{instance_id}/groups",
            params={
                "relationship_type": relationship_type,
                "status": status,
                "limit": limit,
            },
        )
        return self._parse_model(response, contracts.ListGroupsToolResult)

    def list_resolutions(
        self,
        instance_id: str,
        *,
        relationship_type: str | None = None,
        action: contracts.GroupAction | None = None,
        limit: int = 50,
    ) -> contracts.ListResolutionsToolResult:
        response = self._client.get(
            f"/api/v1/{instance_id}/resolutions",
            params={
                "relationship_type": relationship_type,
                "action": action,
                "limit": limit,
            },
        )
        return self._parse_model(response, contracts.ListResolutionsToolResult)

    def propose_entity_changes(
        self,
        instance_id: str,
        *,
        members: list[contracts.EntityChangeInput],
        thesis_text: str = "",
        thesis_facts: dict[str, Any] | None = None,
        analysis_state: dict[str, Any] | None = None,
        proposed_by: contracts.GroupProposedBy = "ai_review",
        suggested_priority: str | None = None,
        source_workflow_name: str | None = None,
        source_workflow_receipt_id: str | None = None,
        source_trace_ids: list[str] | None = None,
        source_step_ids: list[str] | None = None,
    ) -> contracts.ProposeEntityChangesToolResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/entity-proposals",
            json={
                "members": [item.model_dump(mode="json") for item in members],
                "thesis_text": thesis_text,
                "thesis_facts": thesis_facts,
                "analysis_state": analysis_state,
                "proposed_by": proposed_by,
                "suggested_priority": suggested_priority,
                "source_workflow_name": source_workflow_name,
                "source_workflow_receipt_id": source_workflow_receipt_id,
                "source_trace_ids": source_trace_ids,
                "source_step_ids": source_step_ids,
            },
        )
        return self._parse_model(response, contracts.ProposeEntityChangesToolResult)

    def get_entity_proposal(
        self,
        instance_id: str,
        proposal_id: str,
    ) -> contracts.GetEntityProposalToolResult:
        response = self._client.get(f"/api/v1/{instance_id}/entity-proposals/{proposal_id}")
        return self._parse_model(response, contracts.GetEntityProposalToolResult)

    def list_entity_proposals(
        self,
        instance_id: str,
        *,
        status: contracts.EntityProposalStatus | None = None,
        limit: int = 50,
    ) -> contracts.ListEntityProposalsToolResult:
        response = self._client.get(
            f"/api/v1/{instance_id}/entity-proposals",
            params={"status": status, "limit": limit},
        )
        return self._parse_model(response, contracts.ListEntityProposalsToolResult)

    def resolve_entity_proposal(
        self,
        instance_id: str,
        proposal_id: str,
        *,
        action: contracts.GroupAction,
        rationale: str = "",
        resolved_by: contracts.GroupResolvedBy = "human",
    ) -> contracts.ResolveEntityProposalToolResult:
        response = self._client.post(
            f"/api/v1/{instance_id}/entity-proposals/{proposal_id}/resolve",
            json={"action": action, "rationale": rationale, "resolved_by": resolved_by},
        )
        return self._parse_model(response, contracts.ResolveEntityProposalToolResult)
