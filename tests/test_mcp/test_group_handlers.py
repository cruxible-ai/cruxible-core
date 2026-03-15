"""Tests for MCP group write tools (propose, resolve, update_trust_status)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from cruxible_core.mcp.permissions import reset_permissions
from cruxible_core.mcp.server import create_server

GROUP_CONFIG_YAML = """\
version: "1.0"
name: group_mcp_tests
description: For MCP group tool tests

integrations:
  check_v1:
    kind: generic
    contract: {}

entity_types:
  Vehicle:
    properties:
      vehicle_id:
        type: string
        primary_key: true
      year:
        type: int
      make:
        type: string
      model:
        type: string
  Part:
    properties:
      part_number:
        type: string
        primary_key: true
      name:
        type: string
      category:
        type: string
        enum: [brakes, suspension, engine, electrical, body, interior]
      price:
        type: float
        optional: true

relationships:
  - name: fits
    from: Part
    to: Vehicle
    properties:
      verified:
        type: bool
        default: false
      source:
        type: string
        optional: true
    matching:
      integrations:
        check_v1:
          role: required
      auto_resolve_when: all_support
      auto_resolve_requires_prior_trust: trusted_only

constraints: []
ingestion: {}
"""


def call_tool(server, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and parse the JSON result."""
    result = asyncio.run(server.call_tool(name, args))
    if isinstance(result, tuple):
        return result[1]
    text = result[0].text
    return json.loads(text)


def call_tool_expect_error(server, name: str, args: dict[str, Any]) -> str:
    """Call a tool expecting failure. Returns the error message."""
    with pytest.raises(ToolError) as exc_info:
        asyncio.run(server.call_tool(name, args))
    return str(exc_info.value)


@pytest.fixture
def server():
    return create_server()


@pytest.fixture
def group_project(tmp_path):
    """Create a project with matching config + seeded entities."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GROUP_CONFIG_YAML)
    return tmp_path


@pytest.fixture
def instance_id(server, group_project):
    """Initialize instance and add entities for group tests."""
    iid = str(group_project)
    call_tool(
        server,
        "cruxible_init",
        {"root_dir": iid, "config_path": "config.yaml"},
    )
    # Add entities
    call_tool(
        server,
        "cruxible_add_entity",
        {
            "instance_id": iid,
            "entities": [
                {
                    "entity_type": "Part",
                    "entity_id": "BP-1",
                    "properties": {
                        "part_number": "BP-1",
                        "name": "Pads",
                        "category": "brakes",
                    },
                },
                {
                    "entity_type": "Part",
                    "entity_id": "BP-2",
                    "properties": {
                        "part_number": "BP-2",
                        "name": "Pads 2",
                        "category": "brakes",
                    },
                },
                {
                    "entity_type": "Vehicle",
                    "entity_id": "V-1",
                    "properties": {
                        "vehicle_id": "V-1",
                        "year": 2024,
                        "make": "Honda",
                        "model": "Civic",
                    },
                },
                {
                    "entity_type": "Vehicle",
                    "entity_id": "V-2",
                    "properties": {
                        "vehicle_id": "V-2",
                        "year": 2024,
                        "make": "Toyota",
                        "model": "Camry",
                    },
                },
            ],
        },
    )
    return iid


def _member(from_id="BP-1", to_id="V-1"):
    return {
        "from_type": "Part",
        "from_id": from_id,
        "to_type": "Vehicle",
        "to_id": to_id,
        "relationship_type": "fits",
        "signals": [{"integration": "check_v1", "signal": "support"}],
    }


class TestProposeGroup:
    def test_propose_basic(self, server, instance_id):
        result = call_tool(
            server,
            "cruxible_propose_group",
            {
                "instance_id": instance_id,
                "relationship_type": "fits",
                "members": [_member("BP-1", "V-1")],
                "thesis_facts": {"k": "v"},
            },
        )
        assert result["group_id"].startswith("GRP-")
        assert result["status"] == "pending_review"
        assert result["member_count"] == 1
        assert result["signature"]

    def test_propose_with_thesis(self, server, instance_id):
        result = call_tool(
            server,
            "cruxible_propose_group",
            {
                "instance_id": instance_id,
                "relationship_type": "fits",
                "members": [_member()],
                "thesis_text": "these fit because they're brake pads",
                "thesis_facts": {"category": "brakes"},
                "analysis_state": {"centroid": [0.1, 0.2]},
            },
        )
        assert result["status"] == "pending_review"
        assert result["review_priority"] == "review"

    def test_propose_invalid_relationship(self, server, instance_id):
        error = call_tool_expect_error(
            server,
            "cruxible_propose_group",
            {
                "instance_id": instance_id,
                "relationship_type": "nonexistent",
                "members": [_member()],
                "thesis_facts": {"k": "v"},
            },
        )
        assert "nonexistent" in error


class TestResolveGroup:
    def test_approve_creates_edges(self, server, instance_id):
        pr = call_tool(
            server,
            "cruxible_propose_group",
            {
                "instance_id": instance_id,
                "relationship_type": "fits",
                "members": [_member("BP-1", "V-1")],
                "thesis_facts": {"k": "v"},
            },
        )
        result = call_tool(
            server,
            "cruxible_resolve_group",
            {
                "instance_id": instance_id,
                "group_id": pr["group_id"],
                "action": "approve",
            },
        )
        assert result["action"] == "approve"
        assert result["edges_created"] == 1
        assert result["edges_skipped"] == 0

    def test_reject_no_edges(self, server, instance_id):
        pr = call_tool(
            server,
            "cruxible_propose_group",
            {
                "instance_id": instance_id,
                "relationship_type": "fits",
                "members": [_member("BP-1", "V-1")],
                "thesis_facts": {"k": "v"},
            },
        )
        result = call_tool(
            server,
            "cruxible_resolve_group",
            {
                "instance_id": instance_id,
                "group_id": pr["group_id"],
                "action": "reject",
            },
        )
        assert result["action"] == "reject"
        assert result["edges_created"] == 0

    def test_resolve_not_found(self, server, instance_id):
        error = call_tool_expect_error(
            server,
            "cruxible_resolve_group",
            {
                "instance_id": instance_id,
                "group_id": "GRP-nonexistent",
                "action": "approve",
            },
        )
        assert "GRP-nonexistent" in error


class TestUpdateTrustStatus:
    def test_promote_to_trusted(self, server, instance_id):
        pr = call_tool(
            server,
            "cruxible_propose_group",
            {
                "instance_id": instance_id,
                "relationship_type": "fits",
                "members": [_member("BP-1", "V-1")],
                "thesis_facts": {"k": "v"},
            },
        )
        call_tool(
            server,
            "cruxible_resolve_group",
            {
                "instance_id": instance_id,
                "group_id": pr["group_id"],
                "action": "approve",
            },
        )
        # Get resolution_id from the group
        from cruxible_core.mcp.handlers import _manager

        inst = _manager.get(instance_id)
        store = inst.get_group_store()
        try:
            group = store.get_group(pr["group_id"])
            res_id = group.resolution_id
        finally:
            store.close()

        result = call_tool(
            server,
            "cruxible_update_trust_status",
            {
                "instance_id": instance_id,
                "resolution_id": res_id,
                "trust_status": "trusted",
                "reason": "reviewed",
            },
        )
        assert result["resolution_id"] == res_id
        assert result["trust_status"] == "trusted"

    def test_invalid_trust_status(self, server, instance_id):
        error = call_tool_expect_error(
            server,
            "cruxible_update_trust_status",
            {
                "instance_id": instance_id,
                "resolution_id": "RES-whatever",
                "trust_status": "bogus",
            },
        )
        # FastMCP validates the Literal type
        assert error


class TestGroupPermissions:
    def test_propose_requires_graph_write(self, server, instance_id, monkeypatch):
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        error = call_tool_expect_error(
            server,
            "cruxible_propose_group",
            {
                "instance_id": instance_id,
                "relationship_type": "fits",
                "members": [_member()],
                "thesis_facts": {"k": "v"},
            },
        )
        assert "GRAPH_WRITE" in error

    def test_resolve_requires_graph_write(self, server, instance_id, monkeypatch):
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        error = call_tool_expect_error(
            server,
            "cruxible_resolve_group",
            {
                "instance_id": instance_id,
                "group_id": "GRP-xxx",
                "action": "approve",
            },
        )
        assert "GRAPH_WRITE" in error

    def test_update_trust_requires_graph_write(self, server, instance_id, monkeypatch):
        monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
        reset_permissions()
        error = call_tool_expect_error(
            server,
            "cruxible_update_trust_status",
            {
                "instance_id": instance_id,
                "resolution_id": "RES-xxx",
                "trust_status": "trusted",
            },
        )
        assert "GRAPH_WRITE" in error
