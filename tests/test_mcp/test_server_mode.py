"""Server-mode MCP behavior tests."""

from __future__ import annotations

import pytest

from cruxible_client import contracts
from cruxible_core.errors import ConfigError
from cruxible_core.mcp import handlers
from cruxible_core.mcp.server import create_server


def test_create_server_fails_when_server_required_without_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CRUXIBLE_REQUIRE_SERVER", "true")
    with pytest.raises(ConfigError):
        create_server()


def test_public_handler_delegates_to_client(monkeypatch: pytest.MonkeyPatch):
    class StubClient:
        def query(self, instance_id, query_name, params, limit=None):
            assert instance_id == "inst_123"
            assert query_name == "parts_for_vehicle"
            assert params == {"vehicle_id": "V-1"}
            assert limit == 5
            return contracts.QueryToolResult(
                results=[],
                receipt_id="RCPT-1",
                receipt=None,
                total_results=0,
                truncated=False,
                steps_executed=1,
            )

    monkeypatch.setattr(handlers, "_get_client", lambda: StubClient())
    result = handlers.handle_query(
        "inst_123",
        "parts_for_vehicle",
        {"vehicle_id": "V-1"},
        limit=5,
    )
    assert result.receipt_id == "RCPT-1"


def test_workflow_propose_handler_delegates_to_client(monkeypatch: pytest.MonkeyPatch):
    class StubClient:
        def propose_workflow(self, instance_id, *, workflow_name, input_payload=None):
            assert instance_id == "inst_123"
            assert workflow_name == "wf"
            assert input_payload == {"id": "1"}
            return contracts.WorkflowProposeResult(
                workflow="wf",
                output={"members": []},
                receipt_id="RCP-1",
                group_id="GRP-1",
                group_status="pending_review",
                review_priority="review",
                trace_ids=["TRC-1"],
            )

    monkeypatch.setattr(handlers, "_get_client", lambda: StubClient())
    result = handlers.handle_propose_workflow("inst_123", "wf", {"id": "1"})
    assert result.group_id == "GRP-1"
