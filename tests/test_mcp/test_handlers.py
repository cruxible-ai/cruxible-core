"""Tests for MCP tool handlers.

Uses server.call_tool() to exercise the full tool chain.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from cruxible_core.mcp.permissions import reset_permissions
from cruxible_core.mcp.server import create_server


def call_tool(server, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and parse the JSON result."""
    result = asyncio.run(server.call_tool(name, args))
    # FastMCP returns (content_blocks, structured_output) tuple for dict-returning tools
    if isinstance(result, tuple):
        # Structured output is the second element
        return result[1]
    # Fallback: parse text from content blocks
    text = result[0].text
    return json.loads(text)


def call_tool_expect_error(server, name: str, args: dict[str, Any]) -> str:
    """Call a tool expecting failure. Returns the error message."""
    with pytest.raises(ToolError) as exc_info:
        asyncio.run(server.call_tool(name, args))
    return str(exc_info.value)


@pytest.fixture
def server():
    """Create a fresh MCP server for each test."""
    return create_server()


# ── cruxible_init ──────────────────────────────────────────────────────


class TestInit:
    def test_init_creates_instance(self, server, tmp_project):
        result = call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        assert result["status"] == "initialized"
        assert result["instance_id"] == str(tmp_project)

    def test_init_with_data_dir(self, server, tmp_project):
        data_dir = tmp_project / "data"
        data_dir.mkdir()
        result = call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
                "data_dir": str(data_dir),
            },
        )
        assert result["status"] == "initialized"

    def test_init_bad_config(self, server, tmp_path):
        error_msg = call_tool_expect_error(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_path),
                "config_path": "nonexistent.yaml",
            },
        )
        assert "nonexistent.yaml" in error_msg

    def test_init_reload_existing_instance(self, server, tmp_project):
        """Init then reload without config_path → status='loaded'."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        result = call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        assert result["status"] == "loaded"
        assert result["instance_id"] == str(tmp_project)
        assert result["warnings"] == []

    def test_init_reload_preserves_graph(self, server, tmp_project, vehicles_csv):
        """Reload after ingest preserves ingested entities."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        # Reload
        result = call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        assert result["status"] == "loaded"
        # Verify entities survived
        sample = call_tool(
            server,
            "cruxible_sample",
            {"instance_id": str(tmp_project), "entity_type": "Vehicle"},
        )
        assert sample["count"] == 2

    def test_init_requires_config_path_for_new(self, server, tmp_path):
        """Fresh dir with no config_path → error."""
        error_msg = call_tool_expect_error(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_path)},
        )
        assert "config_path" in error_msg.lower()

    def test_init_reload_with_config_path_errors(self, server, tmp_project):
        """Init with config, then reload passing config → error with guidance."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        assert "already exists" in error_msg.lower()
        assert "edit the yaml file" in error_msg.lower()

    def test_init_reload_warns_on_removed_entity_type(self, server, tmp_project, vehicles_csv):
        """Reload warns when graph has entities whose type was removed from config."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        # Remove Vehicle entity type from config
        config_path = tmp_project / "config.yaml"
        text = config_path.read_text()
        # Remove Vehicle section — replace with a minimal config that lacks Vehicle
        import yaml

        config_data = yaml.safe_load(text)
        del config_data["entity_types"]["Vehicle"]
        # Remove relationships and named_queries that reference Vehicle
        config_data["relationships"] = [
            r
            for r in config_data.get("relationships", [])
            if r.get("from") != "Vehicle" and r.get("to") != "Vehicle"
        ]
        config_data["named_queries"] = {}
        config_data["ingestion"] = {
            k: v
            for k, v in config_data.get("ingestion", {}).items()
            if v.get("entity_type") != "Vehicle"
        }
        config_path.write_text(yaml.dump(config_data))
        # Reload
        result = call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        assert result["status"] == "loaded"
        assert any("Vehicle" in w and "missing from config" in w for w in result["warnings"])

    def test_init_reload_warns_on_removed_relationship_type(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """Reload warns when graph has edges whose type was removed from config."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        # Remove 'fits' relationship from config
        config_path = tmp_project / "config.yaml"
        import yaml

        config_data = yaml.safe_load(config_path.read_text())
        config_data["relationships"] = [
            r for r in config_data.get("relationships", []) if r.get("name") != "fits"
        ]
        config_data["named_queries"] = {}
        config_data["ingestion"] = {
            k: v
            for k, v in config_data.get("ingestion", {}).items()
            if v.get("relationship_type") != "fits"
        }
        config_path.write_text(yaml.dump(config_data))
        # Reload
        result = call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        assert result["status"] == "loaded"
        assert any("fits" in w and "missing from config" in w for w in result["warnings"])

    def test_init_reload_no_warnings_on_additive_change(self, server, tmp_project, vehicles_csv):
        """Reload has no warnings when config adds a new type (additive change)."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        # Add a new entity type to config (additive — should be safe)
        config_path = tmp_project / "config.yaml"
        import yaml

        config_data = yaml.safe_load(config_path.read_text())
        config_data["entity_types"]["Brand"] = {
            "properties": {"brand_id": {"type": "string", "primary_key": True}}
        }
        config_path.write_text(yaml.dump(config_data))
        # Reload
        result = call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        assert result["status"] == "loaded"
        assert result["warnings"] == []


# ── cruxible_validate ──────────────────────────────────────────────────


class TestValidate:
    def test_validate_valid_config(self, server, tmp_project):
        config_path = str(tmp_project / "config.yaml")
        result = call_tool(server, "cruxible_validate", {"config_path": config_path})
        assert result["valid"] is True
        assert result["name"] == "car_parts_compatibility"
        assert "Vehicle" in result["entity_types"]
        assert "Part" in result["entity_types"]
        assert "fits" in result["relationships"]

    def test_validate_bad_path(self, server):
        error_msg = call_tool_expect_error(
            server, "cruxible_validate", {"config_path": "/no/such/file.yaml"}
        )
        assert "file.yaml" in error_msg


# ── cruxible_ingest ────────────────────────────────────────────────────


class TestIngest:
    def test_ingest_entities(self, server, tmp_project, vehicles_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        result = call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        assert result["records_ingested"] == 2
        assert result["mapping"] == "vehicles"

    def test_ingest_unknown_instance(self, server):
        error_msg = call_tool_expect_error(
            server,
            "cruxible_ingest",
            {
                "instance_id": "/no/such/instance",
                "mapping_name": "vehicles",
                "file_path": "/some/file.csv",
            },
        )
        assert "/no/such/instance" in error_msg


# ── cruxible_query ─────────────────────────────────────────────────────


class TestQuery:
    def test_query_returns_results(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "parts",
                "file_path": str(parts_csv),
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "fitments",
                "file_path": str(fitments_csv),
            },
        )
        result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        assert result["total_results"] == 2
        assert result["receipt_id"] is not None
        assert len(result["results"]) == 2

    def test_query_bad_name(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "nonexistent_query",
                "params": {},
            },
        )
        assert "nonexistent_query" in error_msg

    def test_query_with_limit(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
                "limit": 1,
            },
        )
        assert len(result["results"]) == 1
        assert result["total_results"] == 2
        assert result["truncated"] is True
        assert result["receipt"] is None  # Omitted when limit is set
        assert result["receipt_id"] is not None  # Still available for later lookup

    def test_query_without_limit(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        assert result["truncated"] is False
        assert result["receipt"] is not None

    def test_query_limit_larger_than_results(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
                "limit": 1000,
            },
        )
        assert len(result["results"]) == 2  # All results fit
        assert result["truncated"] is False
        assert result["receipt"] is None  # Still omitted — limit was set


class TestQueryLimitValidation:
    """Test limit validation via handle_query directly."""

    def test_query_limit_zero_raises(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        from cruxible_core.errors import ConfigError
        from cruxible_core.mcp.handlers import handle_query

        with pytest.raises(ConfigError, match="limit must be a positive integer"):
            handle_query(str(tmp_project), "parts_for_vehicle", {"vehicle_id": "V-1"}, limit=0)

    def test_query_limit_negative_raises(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        from cruxible_core.errors import ConfigError
        from cruxible_core.mcp.handlers import handle_query

        with pytest.raises(ConfigError, match="limit must be a positive integer"):
            handle_query(str(tmp_project), "parts_for_vehicle", {"vehicle_id": "V-1"}, limit=-1)


# ── cruxible_receipt ──────────────────────────────────────────────────


class TestReceipt:
    def test_query_includes_inline_receipt(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        # Set up and query
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        assert query_result["receipt"] is not None
        assert query_result["receipt"]["receipt_id"] == query_result["receipt_id"]
        assert query_result["receipt"]["query_name"] == "parts_for_vehicle"
        assert len(query_result["receipt"]["nodes"]) > 0

    def test_receipt_lookup(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        # Set up, query, then look up the receipt by ID
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        receipt_id = query_result["receipt_id"]

        result = call_tool(
            server,
            "cruxible_receipt",
            {
                "instance_id": str(tmp_project),
                "receipt_id": receipt_id,
            },
        )
        assert result["receipt_id"] == receipt_id
        assert result["query_name"] == "parts_for_vehicle"
        assert len(result["nodes"]) > 0

    def test_receipt_bad_id(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_receipt",
            {
                "instance_id": str(tmp_project),
                "receipt_id": "RCP-nonexistent",
            },
        )
        assert "RCP-nonexistent" in error_msg


# ── cruxible_feedback ──────────────────────────────────────────────────


class TestFeedback:
    def test_feedback_approve(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )

        result = call_tool(
            server,
            "cruxible_feedback",
            {
                "instance_id": str(tmp_project),
                "receipt_id": query_result["receipt_id"],
                "action": "approve",
                "source": "human",
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
                "reason": "Verified correct",
            },
        )
        assert result["feedback_id"].startswith("FB-")
        assert result["applied"] is True

    def test_feedback_ai_review_source(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """AI review feedback produces ai_approved review_status."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        result = call_tool(
            server,
            "cruxible_feedback",
            {
                "instance_id": str(tmp_project),
                "receipt_id": query_result["receipt_id"],
                "action": "approve",
                "source": "ai_review",
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
            },
        )
        assert result["applied"] is True

        # Verify the edge has ai_approved status
        rel = call_tool(
            server,
            "cruxible_get_relationship",
            {
                "instance_id": str(tmp_project),
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship_type": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
            },
        )
        assert rel["properties"]["review_status"] == "ai_approved"

    def test_feedback_rejects_unknown_receipt(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_feedback",
            {
                "instance_id": str(tmp_project),
                "receipt_id": "RCP-missing",
                "action": "approve",
                "source": "human",
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
            },
        )
        assert "RCP-missing" in error_msg

    def test_feedback_correct_string_confidence_rejected(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """Feedback corrections with string confidence are rejected before persistence."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_feedback",
            {
                "instance_id": str(tmp_project),
                "receipt_id": query_result["receipt_id"],
                "action": "correct",
                "source": "human",
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
                "corrections": {"confidence": "high"},
            },
        )
        assert "confidence must be numeric" in error_msg

    def test_feedback_invalid_confidence_not_persisted(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """Invalid feedback corrections are not persisted to the feedback store."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        # This should fail
        call_tool_expect_error(
            server,
            "cruxible_feedback",
            {
                "instance_id": str(tmp_project),
                "receipt_id": query_result["receipt_id"],
                "action": "correct",
                "source": "human",
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
                "corrections": {"confidence": "high"},
            },
        )
        # Verify nothing was persisted to feedback store
        list_result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "feedback",
            },
        )
        assert list_result["total"] == 0


# ── cruxible_outcome ───────────────────────────────────────────────────


class TestOutcome:
    def test_outcome_correct(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )

        result = call_tool(
            server,
            "cruxible_outcome",
            {
                "instance_id": str(tmp_project),
                "receipt_id": query_result["receipt_id"],
                "outcome": "correct",
                "detail": {"notes": "All parts confirmed"},
            },
        )
        assert result["outcome_id"].startswith("OUT-")

    def test_outcome_rejects_unknown_receipt(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_outcome",
            {
                "instance_id": str(tmp_project),
                "receipt_id": "RCP-missing",
                "outcome": "correct",
            },
        )
        assert "RCP-missing" in error_msg


# ── cruxible_list ──────────────────────────────────────────────────────


class TestList:
    def test_list_entities(self, server, tmp_project, vehicles_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "entities",
                "entity_type": "Vehicle",
            },
        )
        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_list_receipts(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "receipts",
            },
        )
        assert result["total"] >= 1

    def test_list_feedback(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        call_tool(
            server,
            "cruxible_feedback",
            {
                "instance_id": str(tmp_project),
                "receipt_id": query_result["receipt_id"],
                "action": "approve",
                "source": "human",
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
            },
        )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "feedback",
            },
        )
        assert result["total"] >= 1

    def test_list_outcomes(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        call_tool(
            server,
            "cruxible_outcome",
            {
                "instance_id": str(tmp_project),
                "receipt_id": query_result["receipt_id"],
                "outcome": "correct",
            },
        )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "outcomes",
            },
        )
        assert result["total"] >= 1

    def test_list_entities_requires_type(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "entities",
            },
        )
        assert "entity_type" in error_msg

    def test_list_bad_resource_type(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "unknown",
            },
        )
        assert "unknown" in error_msg.lower()

    def test_list_entities_with_property_filter(self, server, tmp_project, vehicles_csv):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "entities",
                "entity_type": "Vehicle",
                "property_filter": {"make": "Honda"},
            },
        )
        assert result["total"] == 2

    def test_property_filter_non_entity_raises(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "receipts",
                "property_filter": {"make": "Honda"},
            },
        )
        assert "property_filter" in error_msg

    def test_list_edges_all(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for name, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": name,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_list",
            {"instance_id": str(tmp_project), "resource_type": "edges"},
        )
        assert result["total"] > 0
        edge = result["items"][0]
        assert "from_type" in edge
        assert "to_type" in edge
        assert "edge_key" in edge
        assert isinstance(edge["edge_key"], int)
        assert "properties" in edge
        assert "relationship_type" in edge

    def test_list_edges_by_relationship_type(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for name, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": name,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "edges",
                "relationship_type": "fits",
            },
        )
        assert result["total"] >= 3  # 3 fitments in fixture
        for edge in result["items"]:
            assert edge["relationship_type"] == "fits"

    def test_list_edges_with_property_filter(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for name, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": name,
                    "file_path": str(path),
                },
            )
        # Add an edge with a known source property
        call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1002",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-ACCORD-SPORT",
                        "properties": {"source": "ai_inferred", "confidence": 0.6},
                    }
                ],
            },
        )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "edges",
                "property_filter": {"source": "ai_inferred"},
            },
        )
        assert result["total"] >= 1
        for edge in result["items"]:
            assert edge["properties"]["source"] == "ai_inferred"

    def test_list_edges_with_limit(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for name, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": name,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_list",
            {
                "instance_id": str(tmp_project),
                "resource_type": "edges",
                "limit": 2,
            },
        )
        assert len(result["items"]) <= 2


# ── cruxible_find_candidates ───────────────────────────────────────────


class TestFindCandidates:
    def test_find_shared_neighbors(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_find_candidates",
            {
                "instance_id": str(tmp_project),
                "relationship_type": "replaces",
                "strategy": "shared_neighbors",
                "via_relationship": "fits",
                "min_overlap": 0.1,
            },
        )
        assert "candidates" in result
        assert isinstance(result["total"], int)

    def test_min_distinct_neighbors_zero_rejected_handler(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """handle_find_candidates raises ConfigError for min_distinct_neighbors < 1."""
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_find_candidates",
            {
                "instance_id": str(tmp_project),
                "relationship_type": "replaces",
                "strategy": "shared_neighbors",
                "via_relationship": "fits",
                "min_distinct_neighbors": 0,
            },
        )
        assert "min_distinct_neighbors" in error_msg

    def test_find_property_match(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_find_candidates",
            {
                "instance_id": str(tmp_project),
                "relationship_type": "replaces",
                "strategy": "property_match",
                "match_rules": [{"from_property": "category", "to_property": "category"}],
            },
        )
        assert "candidates" in result


# ── cruxible_evaluate ──────────────────────────────────────────────────


class TestEvaluate:
    def test_evaluate_graph(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        result = call_tool(
            server,
            "cruxible_evaluate",
            {
                "instance_id": str(tmp_project),
            },
        )
        assert result["entity_count"] > 0
        assert result["edge_count"] > 0
        assert isinstance(result["findings"], list)
        assert isinstance(result["summary"], dict)

    def test_evaluate_empty_graph(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        result = call_tool(
            server,
            "cruxible_evaluate",
            {
                "instance_id": str(tmp_project),
            },
        )
        assert result["entity_count"] == 0
        # Should have coverage gaps at minimum
        assert len(result["findings"]) > 0


# ── cruxible_schema ────────────────────────────────────────────────────


class TestSchema:
    def test_schema(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        result = call_tool(
            server,
            "cruxible_schema",
            {
                "instance_id": str(tmp_project),
            },
        )
        assert result["name"] == "car_parts_compatibility"
        assert "Vehicle" in result["entity_types"]
        assert "Part" in result["entity_types"]
        assert len(result["relationships"]) == 2
        assert "parts_for_vehicle" in result["named_queries"]


# ── cruxible_sample ────────────────────────────────────────────────────


class TestSample:
    def test_sample_entities(self, server, tmp_project, vehicles_csv):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        result = call_tool(
            server,
            "cruxible_sample",
            {
                "instance_id": str(tmp_project),
                "entity_type": "Vehicle",
                "limit": 1,
            },
        )
        assert result["entity_type"] == "Vehicle"
        assert result["count"] == 1
        assert len(result["entities"]) == 1

    def test_sample_empty_type(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
            },
        )
        result = call_tool(
            server,
            "cruxible_sample",
            {
                "instance_id": str(tmp_project),
                "entity_type": "Vehicle",
            },
        )
        assert result["count"] == 0
        assert result["entities"] == []


# ── E2E Gate Test ──────────────────────────────────────────────────────


# ── cruxible_add_relationship / cruxible_add_entity ───────────────────────────


class TestAddRelationship:
    def _init_and_ingest(self, server, tmp_project, vehicles_csv, parts_csv):
        """Helper: init + ingest vehicles and parts (no fitments)."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "parts",
                "file_path": str(parts_csv),
            },
        )

    def test_add_single_relationship(self, server, tmp_project, vehicles_csv, parts_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        result = call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": {
                            "source": "ai_classification",
                            "confidence": 0.9,
                        },
                    }
                ],
            },
        )
        assert result["added"] == 1
        assert result["updated"] == 0

    def test_add_batch_relationships(self, server, tmp_project, vehicles_csv, parts_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        result = call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                    },
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-ACCORD-SPORT",
                    },
                ],
            },
        )
        assert result["added"] == 2

    def test_missing_entity_raises(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "NONEXISTENT",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "ALSO-MISSING",
                    }
                ],
            },
        )
        assert "NONEXISTENT" in error_msg

    def test_bad_relationship_raises(self, server, tmp_project, vehicles_csv, parts_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "no_such_rel",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                    }
                ],
            },
        )
        assert "no_such_rel" in error_msg

    def test_wrong_endpoint_type_raises(self, server, tmp_project, vehicles_csv, parts_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        # fits is Part→Vehicle, try Vehicle→Part (reversed)
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Vehicle",
                        "from_id": "V-2024-CIVIC-EX",
                        "relationship": "fits",
                        "to_type": "Part",
                        "to_id": "BP-1001",
                    }
                ],
            },
        )
        assert "does not match" in error_msg

    def test_duplicate_in_batch_raises(self, server, tmp_project, vehicles_csv, parts_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        rel = {
            "from_type": "Part",
            "from_id": "BP-1001",
            "relationship": "fits",
            "to_type": "Vehicle",
            "to_id": "V-2024-CIVIC-EX",
        }
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [rel, rel],
            },
        )
        assert "duplicate" in error_msg.lower()

    def test_update_existing_relationship(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """Upsert: re-submitting existing edge replaces its properties."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "fitments",
                "file_path": str(fitments_csv),
            },
        )
        # Re-submit with new properties
        result = call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": {"confidence": 0.99, "source": "verified"},
                    }
                ],
            },
        )
        assert result["added"] == 0
        assert result["updated"] == 1
        # Verify properties changed
        from cruxible_core.cli.instance import CruxibleInstance

        instance = CruxibleInstance.load(tmp_project)
        graph = instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")
        assert rel is not None
        assert rel.properties["confidence"] == 0.99
        assert rel.properties["source"] == "verified"
        # Old properties should be gone (full replace, not merge)
        assert "verified" not in rel.properties or rel.properties.get("verified") is None

    def test_batch_atomicity(self, server, tmp_project, vehicles_csv, parts_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        # One valid edge + one invalid (missing entity)
        call_tool_expect_error(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                    },
                    {
                        "from_type": "Part",
                        "from_id": "NONEXISTENT",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                    },
                ],
            },
        )
        # Verify valid edge was NOT persisted
        from cruxible_core.cli.instance import CruxibleInstance

        instance = CruxibleInstance.load(tmp_project)
        graph = instance.load_graph()
        assert not graph.has_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")

    def test_relationship_properties_persisted(self, server, tmp_project, vehicles_csv, parts_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        props = {
            "source": "ai_classification",
            "confidence": 0.85,
            "evidence": {"reasoning": "matched on category"},
        }
        call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": props,
                    }
                ],
            },
        )
        # Reload graph directly and verify edge properties
        from cruxible_core.cli.instance import CruxibleInstance

        instance = CruxibleInstance.load(tmp_project)
        graph = instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")
        assert rel is not None
        assert rel.properties["source"] == "ai_classification"
        assert rel.properties["confidence"] == 0.85
        assert rel.properties["evidence"] == {"reasoning": "matched on category"}

    def test_add_relationship_provenance(self, server, tmp_project, vehicles_csv, parts_csv):
        """New edges via add_relationship get _provenance with source='mcp_add'."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": {"confidence": 0.9},
                    }
                ],
            },
        )
        from cruxible_core.cli.instance import CruxibleInstance

        instance = CruxibleInstance.load(tmp_project)
        graph = instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")
        prov = rel.properties.get("_provenance")
        assert prov is not None
        assert prov["source"] == "mcp_add"
        assert prov["source_ref"] == "cruxible_add_relationship"
        assert "created_at" in prov

    def test_add_relationship_strips_input_provenance(
        self, server, tmp_project, vehicles_csv, parts_csv
    ):
        """_provenance in MCP payload is stripped — system-owned field."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": {
                            "confidence": 0.9,
                            "_provenance": {"source": "spoofed"},
                        },
                    }
                ],
            },
        )
        from cruxible_core.cli.instance import CruxibleInstance

        instance = CruxibleInstance.load(tmp_project)
        graph = instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")
        prov = rel.properties.get("_provenance")
        assert prov["source"] == "mcp_add"  # Not "spoofed"

    def test_string_confidence_rejected(self, server, tmp_project, vehicles_csv, parts_csv):
        """Non-numeric string confidence in add_relationship is rejected."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": {"confidence": "high"},
                    }
                ],
            },
        )
        assert "confidence must be numeric" in error_msg

    def test_string_confidence_coerced(self, server, tmp_project, vehicles_csv, parts_csv):
        """Numeric string confidence is coerced to float."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        result = call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": {"confidence": "0.75"},
                    }
                ],
            },
        )
        assert result["added"] == 1

    def test_nan_inf_confidence_rejected(self, server, tmp_project, vehicles_csv, parts_csv):
        """Non-finite confidence values (nan, inf) are rejected."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        for bad_val in [float("nan"), float("inf")]:
            error_msg = call_tool_expect_error(
                server,
                "cruxible_add_relationship",
                {
                    "instance_id": str(tmp_project),
                    "relationships": [
                        {
                            "from_type": "Part",
                            "from_id": "BP-1001",
                            "relationship": "fits",
                            "to_type": "Vehicle",
                            "to_id": "V-2024-CIVIC-EX",
                            "properties": {"confidence": bad_val},
                        }
                    ],
                },
            )
            assert "finite" in error_msg


# ── cruxible_add_entity ──────────────────────────────────────────────


class TestAddEntity:
    def _init_and_ingest(self, server, tmp_project, vehicles_csv, parts_csv):
        """Helper: init + ingest vehicles and parts."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "parts",
                "file_path": str(parts_csv),
            },
        )

    def test_add_single_entity(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        result = call_tool(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {
                        "entity_type": "Vehicle",
                        "entity_id": "V-NEW",
                        "properties": {"make": "Toyota", "model": "Camry"},
                    }
                ],
            },
        )
        assert result["entities_added"] == 1
        assert result["entities_updated"] == 0

    def test_add_batch_entities(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        result = call_tool(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {"entity_type": "Vehicle", "entity_id": "V-1", "properties": {"make": "Honda"}},
                    {"entity_type": "Part", "entity_id": "P-1", "properties": {"name": "Pad"}},
                ],
            },
        )
        assert result["entities_added"] == 2
        assert result["entities_updated"] == 0

    def test_update_existing_entity(self, server, tmp_project, vehicles_csv, parts_csv):
        """Upsert: re-submitting entity replaces all properties."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        result = call_tool(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {
                        "entity_type": "Vehicle",
                        "entity_id": "V-2024-CIVIC-EX",
                        "properties": {"make": "Honda", "model": "Civic SI"},
                    }
                ],
            },
        )
        assert result["entities_added"] == 0
        assert result["entities_updated"] == 1

    def test_batch_mixed_add_and_update(self, server, tmp_project, vehicles_csv, parts_csv):
        """Batch with one existing entity (update) and one new entity (add)."""
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv)
        result = call_tool(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {
                        "entity_type": "Vehicle",
                        "entity_id": "V-2024-CIVIC-EX",
                        "properties": {"make": "Honda", "model": "Civic SI"},
                    },
                    {
                        "entity_type": "Vehicle",
                        "entity_id": "V-NEW",
                        "properties": {"make": "Toyota", "model": "Camry"},
                    },
                ],
            },
        )
        assert result["entities_added"] == 1
        assert result["entities_updated"] == 1

        # Verify updated entity has new properties
        sample = call_tool(
            server,
            "cruxible_sample",
            {"instance_id": str(tmp_project), "entity_type": "Vehicle", "limit": 50},
        )
        by_id = {e["entity_id"]: e for e in sample["entities"]}
        assert by_id["V-2024-CIVIC-EX"]["properties"]["model"] == "Civic SI"
        assert by_id["V-NEW"]["properties"]["make"] == "Toyota"

    def test_bad_entity_type_raises(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [{"entity_type": "Ghost", "entity_id": "G-1"}],
            },
        )
        assert "Ghost" in error_msg

    def test_empty_entity_id_raises(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [{"entity_type": "Vehicle", "entity_id": "  "}],
            },
        )
        assert "empty" in error_msg.lower()

    def test_batch_atomicity(self, server, tmp_project):
        """One valid + one invalid entity in batch → neither persisted."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool_expect_error(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {"entity_type": "Vehicle", "entity_id": "V-1", "properties": {"make": "Honda"}},
                    {"entity_type": "Ghost", "entity_id": "G-1", "properties": {}},
                ],
            },
        )
        # Valid entity should NOT have been persisted
        from cruxible_core.cli.instance import CruxibleInstance

        instance = CruxibleInstance.load(tmp_project)
        graph = instance.load_graph()
        assert not graph.has_entity("Vehicle", "V-1")

    def test_duplicate_in_batch_raises(self, server, tmp_project):
        """Same entity_type + entity_id twice in one batch → error."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {"entity_type": "Vehicle", "entity_id": "V-1", "properties": {"make": "Honda"}},
                    {
                        "entity_type": "Vehicle",
                        "entity_id": "V-1",
                        "properties": {"make": "Toyota"},
                    },
                ],
            },
        )
        assert "duplicate" in error_msg.lower()


# ── cruxible_add_constraint ────────────────────────────────────────────


class TestAddConstraint:
    def _init(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )

    def test_add_constraint_basic(self, server, tmp_project):
        self._init(server, tmp_project)
        result = call_tool(
            server,
            "cruxible_add_constraint",
            {
                "instance_id": str(tmp_project),
                "name": "category_match",
                "rule": "replaces.FROM.category == replaces.TO.category",
                "severity": "warning",
                "description": "Replacement parts must share category",
            },
        )
        assert result["name"] == "category_match"
        assert result["added"] is True
        assert result["config_updated"] is True

        # Verify in schema
        schema = call_tool(
            server,
            "cruxible_schema",
            {"instance_id": str(tmp_project)},
        )
        constraint_names = [c["name"] for c in schema["constraints"]]
        assert "category_match" in constraint_names

    def test_add_constraint_persists_to_yaml(self, server, tmp_project):
        """Constraint is written back to YAML and survives reload."""
        self._init(server, tmp_project)
        call_tool(
            server,
            "cruxible_add_constraint",
            {
                "instance_id": str(tmp_project),
                "name": "persist_test",
                "rule": "replaces.FROM.category == replaces.TO.category",
            },
        )
        # Read raw YAML
        raw = (tmp_project / "config.yaml").read_text()
        assert "persist_test" in raw

    def test_add_constraint_duplicate_name_errors(self, server, tmp_project):
        self._init(server, tmp_project)
        call_tool(
            server,
            "cruxible_add_constraint",
            {
                "instance_id": str(tmp_project),
                "name": "dup_test",
                "rule": "replaces.FROM.category == replaces.TO.category",
            },
        )
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_constraint",
            {
                "instance_id": str(tmp_project),
                "name": "dup_test",
                "rule": "replaces.FROM.category == replaces.TO.category",
            },
        )
        assert "already exists" in error_msg.lower()

    def test_add_constraint_bad_syntax_errors(self, server, tmp_project):
        self._init(server, tmp_project)
        error_msg = call_tool_expect_error(
            server,
            "cruxible_add_constraint",
            {
                "instance_id": str(tmp_project),
                "name": "bad_rule",
                "rule": "not a valid rule",
            },
        )
        assert "syntax" in error_msg.lower()

    def test_add_constraint_bad_relationship_warns(self, server, tmp_project):
        """Valid syntax but nonexistent relationship succeeds with warning."""
        self._init(server, tmp_project)
        result = call_tool(
            server,
            "cruxible_add_constraint",
            {
                "instance_id": str(tmp_project),
                "name": "ghost_rel",
                "rule": "ghost_rel.FROM.prop == ghost_rel.TO.prop",
            },
        )
        assert result["added"] is True
        assert any("ghost_rel" in w for w in result["warnings"])

    def test_add_constraint_bad_property_warns(self, server, tmp_project):
        """Valid syntax, nonexistent property name succeeds with warning."""
        self._init(server, tmp_project)
        result = call_tool(
            server,
            "cruxible_add_constraint",
            {
                "instance_id": str(tmp_project),
                "name": "bad_prop",
                "rule": "replaces.FROM.nonexistent == replaces.TO.nonexistent",
            },
        )
        assert result["added"] is True
        assert any("nonexistent" in w for w in result["warnings"])


# ── cruxible_get_entity ───────────────────────────────────────────────


class TestGetEntity:
    def _init_and_ingest(self, server, tmp_project, vehicles_csv):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )

    def test_get_entity_found(self, server, tmp_project, vehicles_csv):
        self._init_and_ingest(server, tmp_project, vehicles_csv)
        result = call_tool(
            server,
            "cruxible_get_entity",
            {
                "instance_id": str(tmp_project),
                "entity_type": "Vehicle",
                "entity_id": "V-2024-CIVIC-EX",
            },
        )
        assert result["found"] is True
        assert result["entity_type"] == "Vehicle"
        assert result["entity_id"] == "V-2024-CIVIC-EX"
        assert result["properties"]["make"] == "Honda"

    def test_get_entity_not_found(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        result = call_tool(
            server,
            "cruxible_get_entity",
            {
                "instance_id": str(tmp_project),
                "entity_type": "Vehicle",
                "entity_id": "MISSING",
            },
        )
        assert result["found"] is False


# ── cruxible_get_relationship ─────────────────────────────────────────


class TestGetRelationship:
    def _init_and_ingest(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )

    def test_get_relationship_found(
        self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        self._init_and_ingest(server, tmp_project, vehicles_csv, parts_csv, fitments_csv)
        result = call_tool(
            server,
            "cruxible_get_relationship",
            {
                "instance_id": str(tmp_project),
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship_type": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
            },
        )
        assert result["found"] is True
        assert result["relationship_type"] == "fits"
        assert result["edge_key"] is not None

    def test_get_relationship_not_found(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        result = call_tool(
            server,
            "cruxible_get_relationship",
            {
                "instance_id": str(tmp_project),
                "from_type": "Part",
                "from_id": "MISSING",
                "relationship_type": "fits",
                "to_type": "Vehicle",
                "to_id": "ALSO-MISSING",
            },
        )
        assert result["found"] is False

    def test_get_relationship_with_edge_key(self, server, tmp_project, vehicles_csv, parts_csv):
        """With multiple same-type edges, returns correct one by edge_key."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "parts",
                "file_path": str(parts_csv),
            },
        )
        # Add two fits edges between same endpoints
        call_tool(
            server,
            "cruxible_add_relationship",
            {
                "instance_id": str(tmp_project),
                "relationships": [
                    {
                        "from_type": "Part",
                        "from_id": "BP-1001",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-2024-CIVIC-EX",
                        "properties": {"source": "first"},
                    }
                ],
            },
        )
        # Get first edge to learn its key
        first = call_tool(
            server,
            "cruxible_get_relationship",
            {
                "instance_id": str(tmp_project),
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship_type": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
            },
        )
        first_key = first["edge_key"]

        # Add second edge (different properties, creates a new edge)
        # Use graph directly since add_relationship does upsert
        from cruxible_core.mcp.handlers import _manager

        instance = _manager.get(str(tmp_project))
        graph = instance.load_graph()
        from cruxible_core.graph.types import RelationshipInstance

        graph.add_relationship(
            RelationshipInstance(
                relationship_type="fits",
                from_entity_type="Part",
                from_entity_id="BP-1001",
                to_entity_type="Vehicle",
                to_entity_id="V-2024-CIVIC-EX",
                properties={"source": "second"},
            )
        )
        instance.save_graph(graph)

        # Now get by edge_key
        result = call_tool(
            server,
            "cruxible_get_relationship",
            {
                "instance_id": str(tmp_project),
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship_type": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
                "edge_key": first_key,
            },
        )
        assert result["found"] is True
        assert result["edge_key"] == first_key
        assert result["properties"]["source"] == "first"

    def test_get_relationship_without_edge_key_multi_edge_raises(
        self, server, tmp_project, vehicles_csv, parts_csv
    ):
        """Multiple same-type edges + no edge_key → error."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "parts",
                "file_path": str(parts_csv),
            },
        )
        # Add two edges directly
        from cruxible_core.mcp.handlers import _manager

        instance = _manager.get(str(tmp_project))
        graph = instance.load_graph()
        from cruxible_core.graph.types import RelationshipInstance

        for source in ("first", "second"):
            graph.add_relationship(
                RelationshipInstance(
                    relationship_type="fits",
                    from_entity_type="Part",
                    from_entity_id="BP-1001",
                    to_entity_type="Vehicle",
                    to_entity_id="V-2024-CIVIC-EX",
                    properties={"source": source},
                )
            )
        instance.save_graph(graph)

        error_msg = call_tool_expect_error(
            server,
            "cruxible_get_relationship",
            {
                "instance_id": str(tmp_project),
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship_type": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
            },
        )
        assert "ambiguous" in error_msg.lower()


# ── E2E Gate Test ──────────────────────────────────────────────────────


class TestE2EGate:
    def test_full_lifecycle(self, server, tmp_project, vehicles_csv, parts_csv, fitments_csv):
        """E2E gate: init → ingest → query → receipt → feedback → outcome → evaluate."""
        instance_id = str(tmp_project)

        # 1. Init
        init_result = call_tool(
            server,
            "cruxible_init",
            {
                "root_dir": instance_id,
                "config_path": "config.yaml",
            },
        )
        assert init_result["status"] == "initialized"

        # 2. Ingest
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            ingest_result = call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": instance_id,
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
            assert ingest_result["records_ingested"] > 0

        # 3. Query
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": instance_id,
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        assert query_result["total_results"] == 2
        receipt_id = query_result["receipt_id"]
        assert receipt_id is not None

        # 4. Verify inline receipt from query
        assert query_result["receipt"] is not None
        assert query_result["receipt"]["receipt_id"] == receipt_id

        # 4b. Look up receipt by ID
        receipt_result = call_tool(
            server,
            "cruxible_receipt",
            {
                "instance_id": instance_id,
                "receipt_id": receipt_id,
            },
        )
        assert receipt_result["receipt_id"] == receipt_id

        # 5. Feedback
        feedback_result = call_tool(
            server,
            "cruxible_feedback",
            {
                "instance_id": instance_id,
                "receipt_id": receipt_id,
                "action": "approve",
                "source": "human",
                "from_type": "Part",
                "from_id": "BP-1001",
                "relationship": "fits",
                "to_type": "Vehicle",
                "to_id": "V-2024-CIVIC-EX",
                "reason": "Confirmed fitment",
            },
        )
        assert feedback_result["applied"] is True

        # 6. Outcome
        outcome_result = call_tool(
            server,
            "cruxible_outcome",
            {
                "instance_id": instance_id,
                "receipt_id": receipt_id,
                "outcome": "correct",
            },
        )
        assert outcome_result["outcome_id"].startswith("OUT-")

        # 7. Evaluate
        eval_result = call_tool(
            server,
            "cruxible_evaluate",
            {
                "instance_id": instance_id,
            },
        )
        assert eval_result["entity_count"] > 0
        assert eval_result["edge_count"] > 0


# ── Permission Enforcement ────────────────────────────────────────────

# Minimal payloads that satisfy FastMCP schema validation.
# PermissionDeniedError fires before handler logic runs.
MUTATING_TOOL_PAYLOADS = {
    "cruxible_add_entity": {
        "instance_id": "fake",
        "entities": [{"entity_type": "X", "entity_id": "1"}],
    },
    "cruxible_add_relationship": {
        "instance_id": "fake",
        "relationships": [
            {
                "from_type": "X",
                "from_id": "1",
                "relationship": "r",
                "to_type": "Y",
                "to_id": "2",
            }
        ],
    },
    "cruxible_feedback": {
        "instance_id": "fake",
        "receipt_id": "RCP-fake",
        "action": "approve",
        "source": "human",
        "from_type": "X",
        "from_id": "1",
        "relationship": "r",
        "to_type": "Y",
        "to_id": "2",
    },
    "cruxible_outcome": {
        "instance_id": "fake",
        "receipt_id": "RCP-fake",
        "outcome": "correct",
    },
    "cruxible_ingest": {
        "instance_id": "fake",
        "mapping_name": "m",
        "file_path": "/fake.csv",
    },
    "cruxible_add_constraint": {
        "instance_id": "fake",
        "name": "c",
        "rule": "r.FROM.a == r.TO.b",
    },
}


class TestPermissionEnforcement:
    def test_read_only_blocks_new_init(self, server, monkeypatch, tmp_project):
        """read_only mode blocks cruxible_init with config_path (new instance)."""
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires ADMIN mode"):
            asyncio.run(
                server.call_tool(
                    "cruxible_init",
                    {
                        "root_dir": str(tmp_project),
                        "config_path": "config.yaml",
                    },
                )
            )

    def test_read_only_allows_reload_init(self, server, monkeypatch, tmp_project):
        """Create in admin, then reload in read_only succeeds."""
        # Create instance in admin mode
        asyncio.run(
            server.call_tool(
                "cruxible_init",
                {"root_dir": str(tmp_project), "config_path": "config.yaml"},
            )
        )
        # Switch to read_only
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        # Reload (no config_path) should work
        result = call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        assert result["status"] == "loaded"

    def test_read_only_allows_validate(self, server, monkeypatch, tmp_project):
        """read_only mode allows cruxible_validate."""
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        result = call_tool(
            server,
            "cruxible_validate",
            {"config_path": str(tmp_project / "config.yaml")},
        )
        assert result["valid"] is True

    def test_read_only_allows_query_after_reload(
        self, server, monkeypatch, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """Reload in read_only, then query succeeds."""
        # Set up in admin
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        # Switch to read_only and reload
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        assert result["total_results"] == 2

    def test_read_only_query_persists_receipt(
        self, server, monkeypatch, tmp_project, vehicles_csv, parts_csv, fitments_csv
    ):
        """In read_only mode, query still persists receipt to SQLite."""
        # Set up in admin
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        for mapping, path in [
            ("vehicles", vehicles_csv),
            ("parts", parts_csv),
            ("fitments", fitments_csv),
        ]:
            call_tool(
                server,
                "cruxible_ingest",
                {
                    "instance_id": str(tmp_project),
                    "mapping_name": mapping,
                    "file_path": str(path),
                },
            )
        # Switch to read_only and reload
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        query_result = call_tool(
            server,
            "cruxible_query",
            {
                "instance_id": str(tmp_project),
                "query_name": "parts_for_vehicle",
                "params": {"vehicle_id": "V-2024-CIVIC-EX"},
            },
        )
        receipt_id = query_result["receipt_id"]
        assert receipt_id is not None

        # Fetch receipt by ID
        receipt = call_tool(
            server,
            "cruxible_receipt",
            {"instance_id": str(tmp_project), "receipt_id": receipt_id},
        )
        assert receipt["receipt_id"] == receipt_id

    def test_graph_write_blocks_ingest(self, server, monkeypatch, tmp_project, vehicles_csv):
        """graph_write mode blocks cruxible_ingest."""
        # Init in admin
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        # Switch to graph_write
        monkeypatch.setenv("CRUXIBLE_MODE", "graph_write")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires ADMIN mode"):
            asyncio.run(
                server.call_tool(
                    "cruxible_ingest",
                    {
                        "instance_id": str(tmp_project),
                        "mapping_name": "vehicles",
                        "file_path": str(vehicles_csv),
                    },
                )
            )

    def test_graph_write_allows_add_entity(self, server, monkeypatch, tmp_project):
        """graph_write mode allows cruxible_add_entity."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        monkeypatch.setenv("CRUXIBLE_MODE", "graph_write")
        reset_permissions()
        # Reload instance in graph_write mode
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project)},
        )
        result = call_tool(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {
                        "entity_type": "Vehicle",
                        "entity_id": "V-NEW",
                        "properties": {"make": "Toyota"},
                    }
                ],
            },
        )
        assert result["entities_added"] == 1

    def test_graph_write_blocks_add_constraint(self, server, monkeypatch, tmp_project):
        """graph_write mode blocks cruxible_add_constraint."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        monkeypatch.setenv("CRUXIBLE_MODE", "graph_write")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires ADMIN mode"):
            asyncio.run(
                server.call_tool(
                    "cruxible_add_constraint",
                    {
                        "instance_id": str(tmp_project),
                        "name": "test",
                        "rule": "replaces.FROM.category == replaces.TO.category",
                    },
                )
            )

    def test_admin_allows_all(self, server, tmp_project, vehicles_csv, parts_csv):
        """admin mode allows the full init → ingest → add_entity flow."""
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
            },
        )
        result = call_tool(
            server,
            "cruxible_add_entity",
            {
                "instance_id": str(tmp_project),
                "entities": [
                    {
                        "entity_type": "Vehicle",
                        "entity_id": "V-NEW",
                        "properties": {"make": "Toyota"},
                    }
                ],
            },
        )
        assert result["entities_added"] == 1

    @pytest.mark.parametrize("tool_name", list(MUTATING_TOOL_PAYLOADS))
    def test_all_mutating_tools_blocked_in_read_only(self, server, monkeypatch, tool_name):
        """Exhaustive: every mutating tool is blocked in read_only mode."""
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires \w+ mode"):
            asyncio.run(server.call_tool(tool_name, MUTATING_TOOL_PAYLOADS[tool_name]))


# ── Validate inline ──────────────────────────────────────────────────


class TestValidateInline:
    def test_validate_config_yaml_works(self, server, tmp_project):
        """Inline YAML validates identically to file path."""
        config_yaml = (tmp_project / "config.yaml").read_text()
        file_result = call_tool(
            server,
            "cruxible_validate",
            {"config_path": str(tmp_project / "config.yaml")},
        )
        inline_result = call_tool(
            server,
            "cruxible_validate",
            {"config_yaml": config_yaml},
        )
        assert file_result["valid"] == inline_result["valid"]
        assert file_result["name"] == inline_result["name"]
        assert file_result["entity_types"] == inline_result["entity_types"]

    def test_validate_zero_sources_raises(self, server):
        """Neither config_path nor config_yaml → error."""
        error_msg = call_tool_expect_error(server, "cruxible_validate", {})
        assert "exactly one" in error_msg.lower()

    def test_validate_both_sources_raises(self, server, tmp_project):
        """Both config_path and config_yaml → error."""
        config_yaml = (tmp_project / "config.yaml").read_text()
        error_msg = call_tool_expect_error(
            server,
            "cruxible_validate",
            {
                "config_path": str(tmp_project / "config.yaml"),
                "config_yaml": config_yaml,
            },
        )
        assert "exactly one" in error_msg.lower()


# ── Init inline ──────────────────────────────────────────────────────


class TestInitInline:
    def test_init_config_yaml_creates_instance(self, server, tmp_path):
        """Inline YAML creates instance and writes config to disk."""
        from tests.test_cli.conftest import CAR_PARTS_YAML

        result = call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_path), "config_yaml": CAR_PARTS_YAML},
        )
        assert result["status"] == "initialized"
        # Config file should have been written to disk
        assert (tmp_path / "config.yaml").exists()

    def test_init_both_config_params_raises(self, server, tmp_project):
        """config_path + config_yaml → error."""
        from tests.test_cli.conftest import CAR_PARTS_YAML

        error_msg = call_tool_expect_error(
            server,
            "cruxible_init",
            {
                "root_dir": str(tmp_project),
                "config_path": "config.yaml",
                "config_yaml": CAR_PARTS_YAML,
            },
        )
        assert "exactly one" in error_msg.lower()

    def test_init_config_yaml_requires_admin(self, server, monkeypatch, tmp_path):
        """In READ_ONLY mode, config_yaml create → PermissionDeniedError."""
        from tests.test_cli.conftest import CAR_PARTS_YAML

        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires ADMIN mode"):
            asyncio.run(
                server.call_tool(
                    "cruxible_init",
                    {"root_dir": str(tmp_path), "config_yaml": CAR_PARTS_YAML},
                )
            )

    def test_init_existing_config_path_read_only(self, server, monkeypatch, tmp_project):
        """Existing instance + config_path in READ_ONLY → PermissionDeniedError."""
        # Create in admin
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires ADMIN mode"):
            asyncio.run(
                server.call_tool(
                    "cruxible_init",
                    {"root_dir": str(tmp_project), "config_path": "config.yaml"},
                )
            )

    def test_init_existing_config_yaml_read_only(self, server, monkeypatch, tmp_project):
        """Existing instance + config_yaml in READ_ONLY → PermissionDeniedError."""
        from tests.test_cli.conftest import CAR_PARTS_YAML

        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires ADMIN mode"):
            asyncio.run(
                server.call_tool(
                    "cruxible_init",
                    {"root_dir": str(tmp_project), "config_yaml": CAR_PARTS_YAML},
                )
            )


# ── Ingest mutual exclusivity ────────────────────────────────────────


class TestIngestMutualExclusivity:
    def _init(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )

    def test_ingest_zero_sources_raises(self, server, tmp_project):
        """No data source → ConfigError."""
        self._init(server, tmp_project)
        error_msg = call_tool_expect_error(
            server,
            "cruxible_ingest",
            {"instance_id": str(tmp_project), "mapping_name": "vehicles"},
        )
        assert "exactly one" in error_msg.lower()

    def test_ingest_multiple_sources_raises(self, server, tmp_project, vehicles_csv):
        """file_path + data_csv → ConfigError."""
        self._init(server, tmp_project)
        error_msg = call_tool_expect_error(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "file_path": str(vehicles_csv),
                "data_csv": "id,name\n1,x\n",
            },
        )
        assert "exactly one" in error_msg.lower()

    def test_ingest_upload_id_rejected_locally(self, server, tmp_project):
        """upload_id → 'not supported in local mode'."""
        self._init(server, tmp_project)
        error_msg = call_tool_expect_error(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "upload_id": "some-upload-id",
            },
        )
        assert "not supported in local mode" in error_msg.lower()

    def test_ingest_data_csv_works(self, server, tmp_project):
        """Inline CSV string ingests correctly."""
        self._init(server, tmp_project)
        csv_data = (
            "vehicle_id,year,make,model\n"
            "V-2024-CIVIC-EX,2024,Honda,Civic\n"
            "V-2024-ACCORD-SPORT,2024,Honda,Accord\n"
        )
        result = call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "data_csv": csv_data,
            },
        )
        assert result["records_ingested"] == 2
        assert result["mapping"] == "vehicles"

    def test_ingest_data_json_works(self, server, tmp_project):
        """Inline JSON string ingests correctly."""
        self._init(server, tmp_project)
        json_data = json.dumps(
            [
                {"vehicle_id": "V-2024-CIVIC-EX", "year": 2024, "make": "Honda", "model": "Civic"},
                {
                    "vehicle_id": "V-2024-ACCORD-SPORT",
                    "year": 2024,
                    "make": "Honda",
                    "model": "Accord",
                },
            ]
        )
        result = call_tool(
            server,
            "cruxible_ingest",
            {
                "instance_id": str(tmp_project),
                "mapping_name": "vehicles",
                "data_json": json_data,
            },
        )
        assert result["records_ingested"] == 2
        assert result["mapping"] == "vehicles"


# ── Edge-path regression tests ──────────────────────────────────────


class TestInitEdgePaths:
    """Regression tests for handle_init edge paths."""

    def test_dual_config_params_read_only_gets_permission_error(
        self, server, monkeypatch, tmp_path
    ):
        """config_path + config_yaml in READ_ONLY → PermissionDeniedError, not ConfigError.

        Verifies that the ADMIN permission gate fires before the mutual-exclusivity check.
        """
        from tests.test_cli.conftest import CAR_PARTS_YAML

        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        with pytest.raises(ToolError, match=r"requires ADMIN mode"):
            asyncio.run(
                server.call_tool(
                    "cruxible_init",
                    {
                        "root_dir": str(tmp_path),
                        "config_path": "config.yaml",
                        "config_yaml": CAR_PARTS_YAML,
                    },
                )
            )

    def test_existing_config_yaml_on_disk_guard(self, server, tmp_path):
        """config_yaml with pre-existing config.yaml file (but no instance) → ConfigError.

        Tests the guard at handler lines 112-116 where root/config.yaml exists
        but instance.json does not.
        """
        from tests.test_cli.conftest import CAR_PARTS_YAML

        # Create config.yaml on disk without initializing an instance
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "config.yaml").write_text("existing: true\n")

        error_msg = call_tool_expect_error(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_path), "config_yaml": CAR_PARTS_YAML},
        )
        assert "config.yaml already exists" in error_msg

    def test_init_cleanup_on_failure(self, server, tmp_path):
        """Orphaned config.yaml is cleaned up when CruxibleInstance.init() fails."""
        from unittest.mock import patch

        from tests.test_cli.conftest import CAR_PARTS_YAML

        with patch(
            "cruxible_core.mcp.handlers.CruxibleInstance.init",
            side_effect=RuntimeError("init failed"),
        ):
            call_tool_expect_error(
                server,
                "cruxible_init",
                {"root_dir": str(tmp_path), "config_yaml": CAR_PARTS_YAML},
            )
        # config.yaml should have been cleaned up
        assert not (tmp_path / "config.yaml").exists()


class TestIngestEdgePaths:
    """Regression tests for malformed inline data parse failures."""

    def _init(self, server, tmp_project):
        call_tool(
            server,
            "cruxible_init",
            {"root_dir": str(tmp_project), "config_path": "config.yaml"},
        )

    def test_malformed_csv_raises(self, server, tmp_project):
        """Malformed CSV (wrong columns) raises ToolError with detail."""
        self._init(server, tmp_project)
        bad_csv = "wrong_col,another_col\nfoo,bar\n"
        with pytest.raises(ToolError) as exc_info:
            asyncio.run(
                server.call_tool(
                    "cruxible_ingest",
                    {
                        "instance_id": str(tmp_project),
                        "mapping_name": "vehicles",
                        "data_csv": bad_csv,
                    },
                )
            )
        assert "vehicle_id" in str(exc_info.value).lower()

    def test_malformed_json_raises(self, server, tmp_project):
        """Malformed JSON string raises ToolError."""
        self._init(server, tmp_project)
        with pytest.raises(ToolError):
            asyncio.run(
                server.call_tool(
                    "cruxible_ingest",
                    {
                        "instance_id": str(tmp_project),
                        "mapping_name": "vehicles",
                        "data_json": "not valid json{{{",
                    },
                )
            )

    def test_json_wrong_columns_raises(self, server, tmp_project):
        """JSON with wrong column names raises ToolError with detail."""
        self._init(server, tmp_project)
        bad_json = json.dumps([{"wrong_col": "foo", "another_col": "bar"}])
        with pytest.raises(ToolError) as exc_info:
            asyncio.run(
                server.call_tool(
                    "cruxible_ingest",
                    {
                        "instance_id": str(tmp_project),
                        "mapping_name": "vehicles",
                        "data_json": bad_json,
                    },
                )
            )
        assert "vehicle_id" in str(exc_info.value).lower()
