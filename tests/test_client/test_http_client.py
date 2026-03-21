"""Tests for the HTTP client."""

from __future__ import annotations

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
