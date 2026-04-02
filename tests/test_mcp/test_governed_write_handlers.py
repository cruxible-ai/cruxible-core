"""Tests for governed-write MCP tools."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from cruxible_core.mcp.server import create_server

CONFIG_YAML = """\
version: "1.0"
name: governed_write_tools
description: MCP governed-write coverage

entity_types:
  Vehicle:
    properties:
      vehicle_id: {type: string, primary_key: true}
      year: {type: int}
      make: {type: string}
      model: {type: string}
  Part:
    properties:
      part_number: {type: string, primary_key: true}
      name: {type: string}
      category: {type: string}
      price: {type: float, optional: true}

relationships:
  - name: fits
    from: Part
    to: Vehicle
    properties:
      verified: {type: bool}
      source: {type: string, optional: true}

named_queries:
  parts_for_vehicle:
    description: Find parts for vehicle
    entry_point: Vehicle
    traversal:
      - relationship: fits
        direction: incoming
    returns: "list[Part]"

constraints: []
ingestion: {}
"""


def call_tool(server, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(name, args))
    if isinstance(result, tuple):
        return result[1]
    return json.loads(result[0].text)


def call_tool_expect_error(server, name: str, args: dict[str, Any]) -> str:
    with pytest.raises(ToolError) as exc_info:
        asyncio.run(server.call_tool(name, args))
    return str(exc_info.value)


@pytest.fixture
def server(governed_client):
    del governed_client
    return create_server()


@pytest.fixture
def instance_id(server, tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG_YAML)
    result = call_tool(
        server, "cruxible_init", {"root_dir": str(tmp_path), "config_path": "config.yaml"},
    )
    iid = result["instance_id"]
    call_tool(
        server,
        "cruxible_add_entity",
        {
            "instance_id": iid,
            "entities": [
                {
                    "entity_type": "Part",
                    "entity_id": "BP-1",
                    "properties": {"part_number": "BP-1", "name": "Pads", "category": "brakes"},
                },
                {
                    "entity_type": "Part",
                    "entity_id": "BP-2",
                    "properties": {"part_number": "BP-2", "name": "Rotor", "category": "brakes"},
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
            ],
        },
    )
    call_tool(
        server,
        "cruxible_add_relationship",
        {
            "instance_id": iid,
            "relationships": [
                {
                    "from_type": "Part",
                    "from_id": "BP-1",
                    "relationship": "fits",
                    "to_type": "Vehicle",
                    "to_id": "V-1",
                    "properties": {"verified": True, "source": "catalog"},
                },
                {
                    "from_type": "Part",
                    "from_id": "BP-2",
                    "relationship": "fits",
                    "to_type": "Vehicle",
                    "to_id": "V-1",
                    "properties": {"verified": True, "source": "catalog"},
                },
            ],
        },
    )
    return iid


def test_feedback_batch_tool(server, instance_id):
    query = call_tool(
        server,
        "cruxible_query",
        {
            "instance_id": instance_id,
            "query_name": "parts_for_vehicle",
            "params": {"vehicle_id": "V-1"},
        },
    )
    receipt_id = query["receipt_id"]
    result = call_tool(
        server,
        "cruxible_feedback_batch",
        {
            "instance_id": instance_id,
            "source": "human",
            "items": [
                {
                    "receipt_id": receipt_id,
                    "action": "approve",
                    "target": {
                        "from_type": "Part",
                        "from_id": "BP-1",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-1",
                    },
                },
                {
                    "receipt_id": receipt_id,
                    "action": "reject",
                    "target": {
                        "from_type": "Part",
                        "from_id": "BP-2",
                        "relationship": "fits",
                        "to_type": "Vehicle",
                        "to_id": "V-1",
                    },
                },
            ],
        },
    )
    assert result["total"] == 2
    assert result["applied_count"] == 2
    assert len(result["feedback_ids"]) == 2
    assert result["receipt_id"]
