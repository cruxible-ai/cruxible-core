"""CLI commands delegating to core modules."""

from __future__ import annotations

import csv
import inspect
import json
from pathlib import Path
from typing import cast

import click
from rich.console import Console
from rich.table import Table

from cruxible_core.cli.formatting import (
    candidates_table,
    edges_table,
    entities_table,
    feedback_table,
    outcomes_table,
    receipts_table,
    relationship_table,
    schema_table,
)
from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.cli.main import handle_errors
from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.loader import load_config
from cruxible_core.config.schema import ConstraintSchema
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import ConfigError, EdgeAmbiguityError, ReceiptNotFoundError
from cruxible_core.evaluate import evaluate_graph
from cruxible_core.feedback.applier import apply_feedback
from cruxible_core.feedback.types import EdgeTarget, FeedbackRecord, OutcomeRecord
from cruxible_core.graph.operations import (
    apply_entity,
    apply_relationship,
    validate_entity,
    validate_relationship,
)
from cruxible_core.ingest import ingest_file
from cruxible_core.mcp import contracts
from cruxible_core.query.candidates import MatchRule, find_candidates
from cruxible_core.query.engine import execute_query
from cruxible_core.receipt import serializer

console = Console()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@click.command()
@click.option("--config", "config_path", required=True, help="Path to config YAML file.")
@click.option("--data-dir", default=None, help="Directory for data files.")
@handle_errors
def init(config_path: str, data_dir: str | None) -> None:
    """Initialize a new .cruxible/ instance in the current directory."""
    root = Path.cwd()
    instance = CruxibleInstance.init(root, config_path, data_dir)
    click.echo(f"Initialized .cruxible/ in {instance.root}")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@click.command()
@click.option("--config", "config_path", required=True, help="Path to config YAML file.")
@handle_errors
def validate(config_path: str) -> None:
    """Validate a config YAML file without creating an instance."""
    config = load_config(config_path)
    click.echo(f"Config '{config.name}' is valid.")
    click.echo(
        f"  {len(config.entity_types)} entity types, "
        f"{len(config.relationships)} relationships, "
        f"{len(config.named_queries)} queries"
    )


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


@click.command()
@click.option("--mapping", required=True, help="Ingestion mapping name from config.")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Data file.")
@handle_errors
def ingest(mapping: str, file_path: str) -> None:
    """Ingest data from a file using a named mapping."""
    instance = CruxibleInstance.load()
    config = instance.load_config()
    graph = instance.load_graph()

    added, updated = ingest_file(config, graph, mapping, file_path)
    instance.save_graph(graph)

    parts = [f"{added} added"]
    if updated:
        parts.append(f"{updated} updated")
    click.echo(f"Ingested {', '.join(parts)} via mapping '{mapping}'.")


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


@click.command()
@click.option("--query", "query_name", required=True, help="Named query from config.")
@click.option("--param", multiple=True, help="Query parameter as KEY=VALUE.")
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Max results to display.")
@handle_errors
def query(query_name: str, param: tuple[str, ...], limit: int | None) -> None:
    """Execute a named query and save the receipt."""
    instance = CruxibleInstance.load()
    config = instance.load_config()
    graph = instance.load_graph()

    params = _parse_params(param)
    result = execute_query(config, graph, query_name, params)

    # Save receipt
    if result.receipt is not None:
        store = instance.get_receipt_store()
        receipt_id = store.save_receipt(result.receipt)
        store.close()
    else:
        receipt_id = None

    # Display results (apply limit if set)
    results = result.results
    total = result.total_results
    if limit is not None and len(results) > limit:
        results = results[:limit]
        console.print(entities_table(results, query_name))
        click.echo(f"\nShowing {limit} of {total} results (use --limit to adjust).")
    else:
        console.print(entities_table(results, query_name))
        click.echo(f"\n{total} result(s), {result.steps_executed} step(s) executed.")
    if receipt_id:
        click.echo(f"Receipt: {receipt_id}")


# ---------------------------------------------------------------------------
# explain
# ---------------------------------------------------------------------------


@click.command()
@click.option("--receipt", "receipt_id", required=True, help="Receipt ID to explain.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown", "mermaid"]),
    default="markdown",
    help="Output format.",
)
@handle_errors
def explain(receipt_id: str, fmt: str) -> None:
    """Explain a query result using its receipt."""
    instance = CruxibleInstance.load()
    store = instance.get_receipt_store()
    receipt = store.get_receipt(receipt_id)
    store.close()

    if receipt is None:
        raise ReceiptNotFoundError(receipt_id)

    if fmt == "json":
        click.echo(serializer.to_json(receipt))
    elif fmt == "mermaid":
        click.echo(serializer.to_mermaid(receipt))
    else:
        click.echo(serializer.to_markdown(receipt))


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


@click.command("feedback")
@click.option("--receipt", "receipt_id", required=True, help="Receipt ID.")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["approve", "reject", "correct", "flag"]),
    help="Feedback action.",
)
@click.option("--from-type", required=True, help="Source entity type.")
@click.option("--from-id", required=True, help="Source entity ID.")
@click.option("--relationship", required=True, help="Relationship type.")
@click.option("--to-type", required=True, help="Target entity type.")
@click.option("--to-id", required=True, help="Target entity ID.")
@click.option("--edge-key", default=None, type=int, help="Edge key (multi-edge disambiguation).")
@click.option("--reason", default="", help="Reason for feedback.")
@click.option(
    "--corrections",
    default=None,
    help="JSON object of edge property corrections (for action=correct).",
)
@click.option(
    "--source",
    type=click.Choice(["human", "ai_review", "system"]),
    default="human",
    help="Who produced this feedback (default: human).",
)
@handle_errors
def feedback_cmd(
    receipt_id: str,
    action: str,
    from_type: str,
    from_id: str,
    relationship: str,
    to_type: str,
    to_id: str,
    edge_key: int | None,
    reason: str,
    corrections: str | None,
    source: str,
) -> None:
    """Submit feedback on a specific edge from a query result."""
    edge_target = EdgeTarget(
        from_type=from_type,
        from_id=from_id,
        relationship=relationship,
        to_type=to_type,
        to_id=to_id,
        edge_key=edge_key,
    )
    try:
        corrections_dict = json.loads(corrections) if corrections else {}
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--corrections must be valid JSON") from exc
    if not isinstance(corrections_dict, dict):
        raise click.BadParameter("--corrections must be a JSON object")

    record = FeedbackRecord(
        receipt_id=receipt_id,
        action=cast(contracts.FeedbackAction, action),
        source=cast(contracts.FeedbackSource, source),
        target=edge_target,
        reason=reason,
        corrections=corrections_dict,
    )

    instance = CruxibleInstance.load()
    graph = instance.load_graph()
    receipt_store = instance.get_receipt_store()
    receipt = receipt_store.get_receipt(receipt_id)
    receipt_store.close()
    if receipt is None:
        raise ReceiptNotFoundError(receipt_id)

    # Save feedback record
    fb_store = instance.get_feedback_store()
    fb_id = fb_store.save_feedback(record)
    fb_store.close()

    # Apply to graph and save
    applied = apply_feedback(graph, record)
    instance.save_graph(graph)

    if applied:
        click.echo(f"Feedback {fb_id} applied to graph.")
    else:
        click.echo(f"Feedback {fb_id} saved (edge not found in graph).")


# ---------------------------------------------------------------------------
# outcome
# ---------------------------------------------------------------------------


@click.command("outcome")
@click.option("--receipt", "receipt_id", required=True, help="Receipt ID.")
@click.option(
    "--outcome",
    "outcome_value",
    required=True,
    type=click.Choice(["correct", "incorrect", "partial", "unknown"]),
    help="Outcome of the decision.",
)
@click.option("--detail", default=None, help="JSON string with outcome details.")
@handle_errors
def outcome_cmd(receipt_id: str, outcome_value: str, detail: str | None) -> None:
    """Record the outcome of a decision."""
    try:
        detail_dict = json.loads(detail) if detail else {}
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--detail must be valid JSON") from exc
    if not isinstance(detail_dict, dict):
        raise click.BadParameter("--detail must be a JSON object")

    record = OutcomeRecord(
        receipt_id=receipt_id,
        outcome=cast(contracts.OutcomeValue, outcome_value),
        detail=detail_dict,
    )

    instance = CruxibleInstance.load()
    receipt_store = instance.get_receipt_store()
    receipt = receipt_store.get_receipt(receipt_id)
    receipt_store.close()
    if receipt is None:
        raise ReceiptNotFoundError(receipt_id)
    fb_store = instance.get_feedback_store()
    out_id = fb_store.save_outcome(record)
    fb_store.close()

    click.echo(f"Outcome {out_id} recorded.")


# ---------------------------------------------------------------------------
# list (subgroup)
# ---------------------------------------------------------------------------


@click.group("list")
def list_group() -> None:
    """List entities, receipts, or feedback."""


@list_group.command("entities")
@click.option("--type", "entity_type", required=True, help="Entity type to list.")
@click.option("--limit", default=50, help="Max entities to show.")
@handle_errors
def list_entities(entity_type: str, limit: int) -> None:
    """List entities of a given type."""
    instance = CruxibleInstance.load()
    graph = instance.load_graph()
    entities = graph.list_entities(entity_type)[:limit]
    console.print(entities_table(entities, entity_type))
    click.echo(f"{len(entities)} entity(ies) shown.")


@list_group.command("receipts")
@click.option("--query-name", default=None, help="Filter by query name.")
@click.option("--limit", default=50, help="Max receipts to show.")
@handle_errors
def list_receipts(query_name: str | None, limit: int) -> None:
    """List receipt summaries."""
    instance = CruxibleInstance.load()
    store = instance.get_receipt_store()
    receipts = store.list_receipts(query_name=query_name, limit=limit)
    store.close()
    console.print(receipts_table(receipts))
    click.echo(f"{len(receipts)} receipt(s) shown.")


@list_group.command("feedback")
@click.option("--receipt", "receipt_id", default=None, help="Filter by receipt ID.")
@click.option("--limit", default=50, help="Max records to show.")
@handle_errors
def list_feedback(receipt_id: str | None, limit: int) -> None:
    """List feedback records."""
    instance = CruxibleInstance.load()
    fb_store = instance.get_feedback_store()
    records = fb_store.list_feedback(receipt_id=receipt_id, limit=limit)
    fb_store.close()
    console.print(feedback_table(records))
    click.echo(f"{len(records)} record(s) shown.")


@list_group.command("outcomes")
@click.option("--receipt", "receipt_id", default=None, help="Filter by receipt ID.")
@click.option("--limit", default=50, help="Max records to show.")
@handle_errors
def list_outcomes(receipt_id: str | None, limit: int) -> None:
    """List outcome records."""
    instance = CruxibleInstance.load()
    fb_store = instance.get_feedback_store()
    records = fb_store.list_outcomes(receipt_id=receipt_id, limit=limit)
    fb_store.close()
    console.print(outcomes_table(records))
    click.echo(f"{len(records)} record(s) shown.")


# ---------------------------------------------------------------------------
# find-candidates
# ---------------------------------------------------------------------------


@click.command("find-candidates")
@click.option("--relationship", required=True, help="Relationship type to find candidates for.")
@click.option(
    "--strategy",
    required=True,
    type=click.Choice(["property_match", "shared_neighbors"]),
    help="Detection strategy.",
)
@click.option(
    "--rule",
    multiple=True,
    help="Match rule as FROM_PROP=TO_PROP (for property_match strategy).",
)
@click.option("--via", "via_relationship", default=None, help="Via relationship (shared_neighbors)")
@click.option("--limit", default=20, help="Max candidates to show.")
@handle_errors
def find_candidates_cmd(
    relationship: str,
    strategy: str,
    rule: tuple[str, ...],
    via_relationship: str | None,
    limit: int,
) -> None:
    """Find candidate relationships using a deterministic strategy."""
    instance = CruxibleInstance.load()
    config = instance.load_config()
    graph = instance.load_graph()

    match_rules = None
    if rule:
        match_rules = []
        for r in rule:
            parts = r.split("=", 1)
            if len(parts) != 2:
                raise click.BadParameter(f"Rule must be FROM_PROP=TO_PROP, got: {r}")
            match_rules.append(MatchRule(from_property=parts[0], to_property=parts[1]))

    candidates = find_candidates(
        config,
        graph,
        relationship,
        cast(contracts.CandidateStrategy, strategy),
        match_rules=match_rules,
        via_relationship=via_relationship,
        limit=limit,
    )

    console.print(candidates_table(candidates))
    click.echo(f"{len(candidates)} candidate(s) found.")


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


@click.command()
@handle_errors
def schema() -> None:
    """Display the config schema for this instance."""
    instance = CruxibleInstance.load()
    config = instance.load_config()
    console.print(schema_table(config))


# ---------------------------------------------------------------------------
# sample
# ---------------------------------------------------------------------------


@click.command()
@click.option("--type", "entity_type", required=True, help="Entity type to sample.")
@click.option("--limit", default=5, help="Number of entities to show.")
@handle_errors
def sample(entity_type: str, limit: int) -> None:
    """Show a sample of entities of a given type."""
    instance = CruxibleInstance.load()
    graph = instance.load_graph()
    entities = graph.list_entities(entity_type)[:limit]
    console.print(entities_table(entities, entity_type))


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--threshold", default=0.5, type=float, help="Confidence threshold for flagging edges."
)
@click.option("--limit", default=100, type=int, help="Max findings to show.")
@handle_errors
def evaluate(threshold: float, limit: int) -> None:
    """Assess graph quality: orphans, gaps, violations, unreviewed co-members."""
    instance = CruxibleInstance.load()
    config = instance.load_config()
    graph = instance.load_graph()
    report = evaluate_graph(config, graph, confidence_threshold=threshold, max_findings=limit)

    # Summary
    click.echo(f"Graph: {report.entity_count} entities, {report.edge_count} edges")
    click.echo(f"Findings: {len(report.findings)}")
    if report.summary:
        for category, count in sorted(report.summary.items()):
            click.echo(f"  {category}: {count}")

    # Findings
    for finding in report.findings:
        severity_color = {"error": "red", "warning": "yellow", "info": "blue"}.get(
            finding.severity, "white"
        )
        click.secho(f"  [{finding.severity.upper()}] {finding.message}", fg=severity_color)


# ---------------------------------------------------------------------------
# get-entity
# ---------------------------------------------------------------------------


@click.command("get-entity")
@click.option("--type", "entity_type", required=True, help="Entity type.")
@click.option("--id", "entity_id", required=True, help="Entity ID.")
@handle_errors
def get_entity_cmd(entity_type: str, entity_id: str) -> None:
    """Look up a specific entity by type and ID."""
    instance = CruxibleInstance.load()
    graph = instance.load_graph()
    entity = graph.get_entity(entity_type, entity_id)
    if entity is None:
        click.echo("Not found.")
        return
    console.print(entities_table([entity], entity_type))


# ---------------------------------------------------------------------------
# get-relationship
# ---------------------------------------------------------------------------


@click.command("get-relationship")
@click.option("--from-type", required=True, help="Source entity type.")
@click.option("--from-id", required=True, help="Source entity ID.")
@click.option("--relationship", required=True, help="Relationship type.")
@click.option("--to-type", required=True, help="Target entity type.")
@click.option("--to-id", required=True, help="Target entity ID.")
@click.option("--edge-key", default=None, type=int, help="Edge key (multi-edge disambiguation).")
@handle_errors
def get_relationship_cmd(
    from_type: str,
    from_id: str,
    relationship: str,
    to_type: str,
    to_id: str,
    edge_key: int | None,
) -> None:
    """Look up a specific relationship by its endpoints and type."""
    instance = CruxibleInstance.load()
    graph = instance.load_graph()

    # When no edge_key, check for ambiguity
    if edge_key is None:
        count = graph.relationship_count_between(
            from_type,
            from_id,
            to_type,
            to_id,
            relationship,
        )
        if count > 1:
            raise EdgeAmbiguityError(
                from_type=from_type,
                from_id=from_id,
                to_type=to_type,
                to_id=to_id,
                relationship=relationship,
            )

    rel = graph.get_relationship(
        from_type,
        from_id,
        to_type,
        to_id,
        relationship,
        edge_key=edge_key,
    )
    if rel is None:
        click.echo("Not found.")
        return
    console.print(relationship_table(rel))


# ---------------------------------------------------------------------------
# add-entity
# ---------------------------------------------------------------------------


@click.command("add-entity")
@click.option("--type", "entity_type", required=True, help="Entity type.")
@click.option("--id", "entity_id", required=True, help="Entity ID.")
@click.option("--props", default=None, help="JSON object of properties.")
@handle_errors
def add_entity_cmd(entity_type: str, entity_id: str, props: str | None) -> None:
    """Add or update an entity in the graph."""
    try:
        properties = json.loads(props) if props else {}
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--props must be valid JSON") from exc
    if not isinstance(properties, dict):
        raise click.BadParameter("--props must be a JSON object")

    instance = CruxibleInstance.load()
    config = instance.load_config()
    graph = instance.load_graph()

    validated = validate_entity(config, graph, entity_type, entity_id, properties)
    apply_entity(graph, validated)
    instance.save_graph(graph)

    label = f"{entity_type}:{entity_id}"
    if validated.is_update:
        click.echo(f"Entity {label} updated.")
    else:
        click.echo(f"Entity {label} added.")


# ---------------------------------------------------------------------------
# add-relationship
# ---------------------------------------------------------------------------


@click.command("add-relationship")
@click.option("--from-type", required=True, help="Source entity type.")
@click.option("--from-id", required=True, help="Source entity ID.")
@click.option("--relationship", required=True, help="Relationship type.")
@click.option("--to-type", required=True, help="Target entity type.")
@click.option("--to-id", required=True, help="Target entity ID.")
@click.option("--props", default=None, help="JSON object of edge properties.")
@handle_errors
def add_relationship_cmd(
    from_type: str,
    from_id: str,
    relationship: str,
    to_type: str,
    to_id: str,
    props: str | None,
) -> None:
    """Add or update a relationship in the graph."""
    try:
        properties = json.loads(props) if props else {}
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--props must be valid JSON") from exc
    if not isinstance(properties, dict):
        raise click.BadParameter("--props must be a JSON object")

    instance = CruxibleInstance.load()
    config = instance.load_config()
    graph = instance.load_graph()

    validated = validate_relationship(
        config,
        graph,
        from_type,
        from_id,
        relationship,
        to_type,
        to_id,
        properties,
    )
    apply_relationship(graph, validated, "cli_add", "add-relationship")
    instance.save_graph(graph)

    edge_label = f"{from_type}:{from_id} -[{relationship}]-> {to_type}:{to_id}"
    if validated.is_update:
        click.echo(f"Relationship updated: {edge_label}")
    else:
        click.echo(f"Relationship added: {edge_label}")


# ---------------------------------------------------------------------------
# add-constraint
# ---------------------------------------------------------------------------


@click.command("add-constraint")
@click.option("--name", required=True, help="Constraint name.")
@click.option("--rule", required=True, help="Constraint rule expression.")
@click.option(
    "--severity",
    type=click.Choice(["warning", "error"]),
    default="warning",
    help="Severity level (default: warning).",
)
@click.option("--description", default=None, help="Optional description.")
@handle_errors
def add_constraint_cmd(
    name: str,
    rule: str,
    severity: str,
    description: str | None,
) -> None:
    """Add a constraint rule to the config."""
    instance = CruxibleInstance.load()
    config = instance.load_config()

    # Check for duplicate name
    for existing in config.constraints:
        if existing.name == name:
            raise ConfigError(f"Constraint '{name}' already exists in config")

    # Validate rule syntax
    parsed = parse_constraint_rule(rule)
    if parsed is None:
        raise ConfigError(
            f"Rule syntax not supported: {rule!r}. "
            "Expected: RELATIONSHIP.FROM.property == RELATIONSHIP.TO.property"
        )

    constraint = ConstraintSchema(
        name=name,
        rule=rule,
        severity=cast(contracts.ConstraintSeverity, severity),
        description=description,
    )
    config.constraints.append(constraint)

    warnings = validate_config(config)
    instance.save_config(config)

    click.echo(f"Constraint '{name}' added to config.")
    for w in warnings:
        click.secho(f"  Warning: {w}", fg="yellow")


# ---------------------------------------------------------------------------
# list edges (subcommand)
# ---------------------------------------------------------------------------


@list_group.command("edges")
@click.option("--relationship", default=None, help="Filter by relationship type.")
@click.option("--limit", default=50, help="Max edges to show.")
@handle_errors
def list_edges(relationship: str | None, limit: int) -> None:
    """List edges in the graph."""
    instance = CruxibleInstance.load()
    graph = instance.load_graph()
    edges = graph.list_edges(relationship_type=relationship)[:limit]
    console.print(edges_table(edges))
    click.echo(f"{len(edges)} edge(s) shown.")


# ---------------------------------------------------------------------------
# export (subgroup)
# ---------------------------------------------------------------------------


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
@handle_errors
def export_edges(output: str, relationship: str | None) -> None:
    """Export all edges to CSV."""
    instance = CruxibleInstance.load()
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


# ---------------------------------------------------------------------------
# prompt (subgroup)
# ---------------------------------------------------------------------------


@click.group("prompt")
def prompt_group() -> None:
    """List or read workflow prompts."""


@prompt_group.command("list")
def prompt_list() -> None:
    """List available workflow prompts."""
    from cruxible_core.mcp.prompts import PROMPT_REGISTRY

    table = Table(title="Available Prompts")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Args", style="green")

    for name in sorted(PROMPT_REGISTRY):
        fn, desc = PROMPT_REGISTRY[name]
        sig = inspect.signature(fn)
        args = ", ".join(
            f"{p.name}: {p.annotation.__name__}" if hasattr(p.annotation, "__name__") else p.name
            for p in sig.parameters.values()
        )
        table.add_row(name, desc, args or "(none)")

    console.print(table)


@prompt_group.command("read")
@click.option("--name", "prompt_name", required=True, help="Prompt name.")
@click.option("--arg", multiple=True, help="Prompt argument as KEY=VALUE.")
def prompt_read(prompt_name: str, arg: tuple[str, ...]) -> None:
    """Read a workflow prompt with the given arguments."""
    from cruxible_core.mcp.prompts import PROMPT_REGISTRY

    # Validate prompt exists
    if prompt_name not in PROMPT_REGISTRY:
        available = ", ".join(sorted(PROMPT_REGISTRY.keys()))
        raise click.ClickException(f"Unknown prompt '{prompt_name}'. Available: {available}")

    # Parse and validate args
    args_dict = _parse_params(arg)

    fn, _desc = PROMPT_REGISTRY[prompt_name]
    sig = inspect.signature(fn)

    required = [p.name for p in sig.parameters.values() if p.default is inspect.Parameter.empty]
    missing = [r for r in required if r not in args_dict]
    if missing:
        raise click.ClickException(f"Prompt '{prompt_name}' requires: {', '.join(missing)}")

    extra = set(args_dict.keys()) - set(sig.parameters.keys())
    if extra:
        raise click.ClickException(f"Unknown args for '{prompt_name}': {', '.join(sorted(extra))}")

    content = fn(**args_dict)
    click.echo(content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_params(params: tuple[str, ...]) -> dict[str, str]:
    """Parse KEY=VALUE pairs into a dict."""
    result: dict[str, str] = {}
    for p in params:
        parts = p.split("=", 1)
        if len(parts) != 2:
            raise click.BadParameter(f"Parameter must be KEY=VALUE, got: {p}")
        result[parts[0]] = parts[1]
    return result
