"""CLI commands for list subgroup and export."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import click

from cruxible_core.cli.commands._common import (
    _dispatch_cli_instance,
    _entities_from_payload,
    _feedback_from_payload,
    _outcomes_from_payload,
    _require_local_instance,
    console,
)
from cruxible_core.cli.formatting import (
    edges_table,
    entities_table,
    feedback_table,
    outcomes_table,
    receipts_table,
)
from cruxible_core.cli.main import handle_errors
from cruxible_core.errors import ConfigError
from cruxible_core.graph.types import REJECTED_STATUSES
from cruxible_core.mcp import contracts
from cruxible_core.service import service_list


@click.group("list")
def list_group() -> None:
    """List entities, receipts, or feedback."""


@list_group.command("entities")
@click.option("--type", "entity_type", required=True, help="Entity type to list.")
@click.option("--limit", default=50, help="Max entities to show.")
@handle_errors
def list_entities(entity_type: str, limit: int) -> None:
    """List entities of a given type."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list(
            instance_id,
            resource_type="entities",
            entity_type=entity_type,
            limit=limit,
        ),
        lambda instance: service_list(instance, "entities", entity_type=entity_type, limit=limit),
    )
    entities = (
        _entities_from_payload(result.items)
        if isinstance(result, contracts.ListResult)
        else result.items
    )
    console.print(entities_table(entities, entity_type))
    click.echo(f"{len(entities)} entity(ies) shown.")


@list_group.command("receipts")
@click.option("--query-name", default=None, help="Filter by query name.")
@click.option("--operation-type", default=None, help="Filter by operation type.")
@click.option("--limit", default=50, help="Max receipts to show.")
@handle_errors
def list_receipts(query_name: str | None, operation_type: str | None, limit: int) -> None:
    """List receipt summaries."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list(
            instance_id,
            resource_type="receipts",
            query_name=query_name,
            operation_type=operation_type,
            limit=limit,
        ),
        lambda instance: service_list(
            instance,
            "receipts",
            query_name=query_name,
            operation_type=operation_type,
            limit=limit,
        ),
    )
    console.print(receipts_table(result.items))
    click.echo(f"{len(result.items)} receipt(s) shown.")


@list_group.command("feedback")
@click.option("--receipt", "receipt_id", default=None, help="Filter by receipt ID.")
@click.option("--limit", default=50, help="Max records to show.")
@handle_errors
def list_feedback(receipt_id: str | None, limit: int) -> None:
    """List feedback records."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list(
            instance_id,
            resource_type="feedback",
            receipt_id=receipt_id,
            limit=limit,
        ),
        lambda instance: service_list(instance, "feedback", receipt_id=receipt_id, limit=limit),
    )
    records = (
        _feedback_from_payload(result.items)
        if isinstance(result, contracts.ListResult)
        else result.items
    )
    console.print(feedback_table(records))
    click.echo(f"{len(records)} record(s) shown.")


@list_group.command("outcomes")
@click.option("--receipt", "receipt_id", default=None, help="Filter by receipt ID.")
@click.option("--limit", default=50, help="Max records to show.")
@handle_errors
def list_outcomes(receipt_id: str | None, limit: int) -> None:
    """List outcome records."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list(
            instance_id,
            resource_type="outcomes",
            receipt_id=receipt_id,
            limit=limit,
        ),
        lambda instance: service_list(instance, "outcomes", receipt_id=receipt_id, limit=limit),
    )
    records = (
        _outcomes_from_payload(result.items)
        if isinstance(result, contracts.ListResult)
        else result.items
    )
    console.print(outcomes_table(records))
    click.echo(f"{len(records)} record(s) shown.")


@list_group.command("edges")
@click.option("--relationship", default=None, help="Filter by relationship type.")
@click.option("--limit", default=50, help="Max edges to show.")
@handle_errors
def list_edges(relationship: str | None, limit: int) -> None:
    """List edges in the graph."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list(
            instance_id,
            resource_type="edges",
            relationship_type=relationship,
            limit=limit,
        ),
        lambda instance: service_list(
            instance,
            "edges",
            relationship_type=relationship,
            limit=limit,
        ),
    )
    console.print(edges_table(result.items))
    click.echo(f"{len(result.items)} edge(s) shown.")


@click.group("export")
def export_group() -> None:
    """Export graph data to files."""


@export_group.command("edges")
@click.option(
    "--output",
    "-o",
    required=True,
    type=click.Path(dir_okay=False, writable=True),
    help="Output file path.",
)
@click.option("--relationship", default=None, help="Filter by relationship type.")
@click.option(
    "--exclude-rejected",
    is_flag=True,
    default=False,
    help="Exclude edges with rejected review_status.",
)
@handle_errors
def export_edges(output: str, relationship: str | None, exclude_rejected: bool) -> None:
    """Export all edges to CSV."""
    instance = _require_local_instance("export edges")
    graph = instance.load_graph()

    path = Path(output)
    fieldnames = [
        "from_type",
        "from_id",
        "to_type",
        "to_id",
        "relationship_type",
        "edge_key",
        "properties_json",
    ]
    count = 0
    try:
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for edge in graph.iter_edges(relationship_type=relationship):
                if exclude_rejected:
                    status = edge["properties"].get("review_status", "")
                    if status in REJECTED_STATUSES:
                        continue
                writer.writerow(
                    {
                        "from_type": edge["from_type"],
                        "from_id": edge["from_id"],
                        "to_type": edge["to_type"],
                        "to_id": edge["to_id"],
                        "relationship_type": edge["relationship_type"],
                        "edge_key": edge["edge_key"],
                        "properties_json": json.dumps(edge["properties"], sort_keys=True),
                    }
                )
                count += 1
    except OSError as exc:
        raise ConfigError(f"Failed to write {path}: {exc}") from exc

    click.echo(f"Exported {count} edge(s) to {path}")
