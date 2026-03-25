"""Tests for the HTTP client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from cruxible_core.client.http_client import CruxibleClient
from cruxible_core.errors import ConstraintViolationError, DataValidationError


def _build_client(handler):
    transport = httpx.MockTransport(handler)
    client = CruxibleClient(base_url="http://cruxible")
    client._client = httpx.Client(base_url="http://cruxible", transport=transport)  # type: ignore[attr-defined]
    return client


def test_successful_call_returns_contract_model():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "instance_id": "inst_123",
                "status": "initialized",
                "warnings": [],
            },
        )

    client = _build_client(handler)
    result = client.init("/srv/project", config_yaml="name: demo")
    assert result.instance_id == "inst_123"
    assert result.status == "initialized"


def test_error_response_rehydrates_correct_exception():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error_type": "ConstraintViolationError",
                "message": "constraint failed",
                "errors": [],
                "context": {"violations": ["mismatch"]},
                "mutation_receipt_id": "RCPT-1",
            },
        )

    client = _build_client(handler)
    with pytest.raises(ConstraintViolationError) as exc_info:
        client.query("inst_123", "parts_for_vehicle")

    assert exc_info.value.violations == ["mismatch"]
    assert exc_info.value.mutation_receipt_id == "RCPT-1"


def test_validation_error_preserves_errors_list():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error_type": "DataValidationError",
                "message": "bad data",
                "errors": ["wrong type"],
                "context": {},
                "mutation_receipt_id": None,
            },
        )

    client = _build_client(handler)
    with pytest.raises(DataValidationError) as exc_info:
        client.query("inst_123", "parts_for_vehicle")

    assert exc_info.value.errors == ["wrong type"]


def test_file_upload_uses_multipart(tmp_path: Path):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers["content-type"]
        captured["path"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "records_ingested": 1,
                "records_updated": 0,
                "mapping": "vehicles",
                "entity_type": "Vehicle",
                "relationship_type": None,
                "receipt_id": "RCPT-1",
            },
        )

    csv_path = tmp_path / "vehicles.csv"
    csv_path.write_text("vehicle_id,make\nV-1,Honda\n")

    client = _build_client(handler)
    result = client.ingest("inst_123", "vehicles", file_path=str(csv_path))

    assert result.records_ingested == 1
    assert "multipart/form-data" in captured["content_type"]
    assert captured["path"].endswith("/api/v1/inst_123/ingest")


def test_workflow_propose_uses_expected_route():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "workflow": "wf",
                "output": {"members": []},
                "receipt_id": "RCP-1",
                "group_id": "GRP-1",
                "group_status": "pending_review",
                "review_priority": "review",
                "query_receipt_ids": [],
                "trace_ids": ["TRC-1"],
                "prior_resolution": None,
                "receipt": None,
                "traces": [],
            },
        )

    client = _build_client(handler)
    result = client.propose_workflow("inst_123", workflow_name="wf", input_payload={"id": "1"})
    assert result.group_id == "GRP-1"
    assert captured["path"].endswith("/api/v1/inst_123/workflows/propose")
    assert captured["payload"]["workflow_name"] == "wf"


def test_workflow_apply_uses_expected_route():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "workflow": "wf",
                "output": {"total_results": 1},
                "receipt_id": "RCP-2",
                "mode": "apply",
                "canonical": True,
                "apply_digest": "sha256:abc",
                "head_snapshot_id": None,
                "committed_snapshot_id": "snap_2",
                "apply_previews": {},
                "query_receipt_ids": [],
                "trace_ids": ["TRC-2"],
                "receipt": None,
                "traces": [],
            },
        )

    client = _build_client(handler)
    result = client.workflow_apply(
        "inst_123",
        workflow_name="wf",
        expected_apply_digest="sha256:abc",
        expected_head_snapshot_id=None,
        input_payload={"id": "1"},
    )
    assert result.committed_snapshot_id == "snap_2"
    assert captured["path"].endswith("/api/v1/inst_123/workflows/apply")
    assert captured["payload"]["workflow_name"] == "wf"
    assert captured["payload"]["expected_apply_digest"] == "sha256:abc"


def test_evaluate_uses_expected_route():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "entity_count": 4,
                "edge_count": 3,
                "findings": [],
                "summary": {},
                "quality_summary": {"check_ok": 0},
            },
        )

    client = _build_client(handler)
    result = client.evaluate("inst_123", confidence_threshold=0.7, max_findings=5)
    assert result.quality_summary == {"check_ok": 0}
    assert captured["path"].endswith("/api/v1/inst_123/evaluate")
    assert captured["payload"]["confidence_threshold"] == 0.7
    assert captured["payload"]["max_findings"] == 5


def test_snapshot_create_uses_expected_route():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "snapshot": {
                    "snapshot_id": "snap_1",
                    "created_at": "2026-03-21T00:00:00Z",
                    "label": "baseline",
                    "config_digest": "sha256:abc",
                    "lock_digest": None,
                    "graph_sha256": "sha256:def",
                    "parent_snapshot_id": None,
                    "origin_snapshot_id": None,
                }
            },
        )

    client = _build_client(handler)
    result = client.create_snapshot("inst_123", label="baseline")
    assert result.snapshot.snapshot_id == "snap_1"
    assert captured["path"].endswith("/api/v1/inst_123/snapshots")
    assert captured["payload"]["label"] == "baseline"


def test_stats_inspect_and_reload_use_expected_routes():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = str(request.url)
        if request.url.path.endswith("/stats"):
            return httpx.Response(
                200,
                json={
                    "entity_count": 4,
                    "edge_count": 3,
                    "entity_counts": {"Vehicle": 2},
                    "relationship_counts": {"fits": 3},
                    "head_snapshot_id": "snap_1",
                },
            )
        if "/inspect/entity/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "found": True,
                    "entity_type": "Vehicle",
                    "entity_id": "V-1",
                    "properties": {"vehicle_id": "V-1"},
                    "neighbors": [],
                    "total_neighbors": 0,
                },
            )
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "config_path": "/srv/project/config.yaml",
                "updated": True,
                "warnings": [],
            },
        )

    client = _build_client(handler)

    stats_result = client.stats("inst_123")
    assert stats_result.entity_count == 4
    assert captured["path"].endswith("/api/v1/inst_123/stats")

    inspect_result = client.inspect_entity("inst_123", "Vehicle", "V-1", direction="both")
    assert inspect_result.found is True
    assert "/api/v1/inst_123/inspect/entity/Vehicle/V-1" in captured["path"]

    reload_result = client.reload_config("inst_123", config_path="/srv/project/config.yaml")
    assert reload_result.updated is True
    assert captured["path"].endswith("/api/v1/inst_123/config/reload")
    assert captured["payload"]["config_path"] == "/srv/project/config.yaml"
