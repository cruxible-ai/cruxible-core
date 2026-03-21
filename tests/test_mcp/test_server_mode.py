"""Server-mode MCP behavior tests."""

from __future__ import annotations

import pytest

from cruxible_core.errors import ConfigError
from cruxible_core.mcp import contracts, handlers
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
