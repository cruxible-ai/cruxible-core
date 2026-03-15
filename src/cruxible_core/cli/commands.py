"""CLI commands delegating to service layer."""

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
    group_detail_table,
    groups_table,
    outcomes_table,
    receipts_table,
    relationship_table,
    resolutions_table,
    schema_table,
)
from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.cli.main import handle_errors
from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.schema import ConstraintSchema
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import ConfigError
from cruxible_core.feedback.types import EdgeTarget
from cruxible_core.graph.types import REJECTED_STATUSES
from cruxible_core.group.types import CandidateMember, CandidateSignal
from cruxible_core.mcp import contracts
from cruxible_core.query.candidates import MatchRule
from cruxible_core.receipt import serializer
from cruxible_core.service import (
    EntityUpsertInput,
    RelationshipUpsertInput,
    service_add_entities,
    service_add_relationships,
    service_evaluate,
    service_feedback,
    service_find_candidates,
    service_get_entity,
    service_get_group,
    service_get_receipt,
    service_get_relationship,
    service_ingest,
    service_init,
    service_list,
    service_list_groups,
    service_list_resolutions,
    service_outcome,
    service_propose_group,
    service_query,
    service_resolve_group,
    service_sample,
    service_schema,
    service_update_trust_status,
    service_validate,
)

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
    result = service_init(root, config_path=config_path, data_dir=data_dir)
    click.echo(f"Initialized .cruxible/ in {root}")
    for w in result.warnings:
        click.secho(f"  Warning: {w}", fg="yellow")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@click.command()
@click.option("--config", "config_path", required=True, help="Path to config YAML file.")
@handle_errors
def validate(config_path: str) -> None:
    """Validate a config YAML file without creating an instance."""
    result = service_validate(config_path=config_path)
    config = result.config
    click.echo(f"Config '{config.name}' is valid.")
    click.echo(
        f"  {len(config.entity_types)} entity types, "
        f"{len(config.relationships)} relationships, "
        f"{len(config.named_queries)} queries"
    )
    for w in result.warnings:
        click.secho(f"  Warning: {w}", fg="yellow")


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
    result = service_ingest(instance, mapping, file_path=file_path)

    parts = [f"{result.records_ingested} added"]
    if result.records_updated:
        parts.append(f"{result.records_updated} updated")
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
    params = _parse_params(param)
    result = service_query(instance, query_name, params)

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
    if result.receipt_id:
        click.echo(f"Receipt: {result.receipt_id}")


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
    receipt = service_get_receipt(instance, receipt_id)

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
@click.option(
    "--group-override",
    is_flag=True,
    default=False,
    help="Stamp edge with group_override property (edge must exist).",
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
    group_override: bool,
) -> None:
    """Submit feedback on a specific edge from a query result."""
    try:
        corrections_dict = json.loads(corrections) if corrections else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--corrections must be valid JSON") from exc
    if corrections_dict is not None and not isinstance(corrections_dict, dict):
        raise click.BadParameter("--corrections must be a JSON object")

    target = EdgeTarget(
        from_type=from_type,
        from_id=from_id,
        relationship=relationship,
        to_type=to_type,
        to_id=to_id,
        edge_key=edge_key,
    )

    instance = CruxibleInstance.load()
    result = service_feedback(
        instance,
        receipt_id=receipt_id,
        action=cast(contracts.FeedbackAction, action),
        source=cast(contracts.FeedbackSource, source),
        target=target,
        reason=reason,
        corrections=corrections_dict,
        group_override=group_override,
    )

    if result.applied:
        click.echo(f"Feedback {result.feedback_id} applied to graph.")
    else:
        click.echo(f"Feedback {result.feedback_id} saved (edge not found in graph).")


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
        detail_dict = json.loads(detail) if detail else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--detail must be valid JSON") from exc
    if detail_dict is not None and not isinstance(detail_dict, dict):
        raise click.BadParameter("--detail must be a JSON object")

    instance = CruxibleInstance.load()
    result = service_outcome(
        instance,
        receipt_id=receipt_id,
        outcome=cast(contracts.OutcomeValue, outcome_value),
        detail=detail_dict,
    )
    click.echo(f"Outcome {result.outcome_id} recorded.")


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
    result = service_list(instance, "entities", entity_type=entity_type, limit=limit)
    console.print(entities_table(result.items, entity_type))
    click.echo(f"{len(result.items)} entity(ies) shown.")


@list_group.command("receipts")
@click.option("--query-name", default=None, help="Filter by query name.")
@click.option("--limit", default=50, help="Max receipts to show.")
@handle_errors
def list_receipts(query_name: str | None, limit: int) -> None:
    """List receipt summaries."""
    instance = CruxibleInstance.load()
    result = service_list(instance, "receipts", query_name=query_name, limit=limit)
    console.print(receipts_table(result.items))
    click.echo(f"{len(result.items)} receipt(s) shown.")


@list_group.command("feedback")
@click.option("--receipt", "receipt_id", default=None, help="Filter by receipt ID.")
@click.option("--limit", default=50, help="Max records to show.")
@handle_errors
def list_feedback(receipt_id: str | None, limit: int) -> None:
    """List feedback records."""
    instance = CruxibleInstance.load()
    result = service_list(instance, "feedback", receipt_id=receipt_id, limit=limit)
    console.print(feedback_table(result.items))
    click.echo(f"{len(result.items)} record(s) shown.")


@list_group.command("outcomes")
@click.option("--receipt", "receipt_id", default=None, help="Filter by receipt ID.")
@click.option("--limit", default=50, help="Max records to show.")
@handle_errors
def list_outcomes(receipt_id: str | None, limit: int) -> None:
    """List outcome records."""
    instance = CruxibleInstance.load()
    result = service_list(instance, "outcomes", receipt_id=receipt_id, limit=limit)
    console.print(outcomes_table(result.items))
    click.echo(f"{len(result.items)} record(s) shown.")


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

    match_rules = None
    if rule:
        match_rules = []
        for r in rule:
            parts = r.split("=", 1)
            if len(parts) != 2:
                raise click.BadParameter(f"Rule must be FROM_PROP=TO_PROP, got: {r}")
            match_rules.append(MatchRule(from_property=parts[0], to_property=parts[1]))

    candidates = service_find_candidates(
        instance,
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
    config = service_schema(instance)
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
    entities = service_sample(instance, entity_type, limit=limit)
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
    report = service_evaluate(instance, confidence_threshold=threshold, max_findings=limit)

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
    entity = service_get_entity(instance, entity_type, entity_id)
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
    rel = service_get_relationship(
        instance,
        from_type=from_type,
        from_id=from_id,
        relationship_type=relationship,
        to_type=to_type,
        to_id=to_id,
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
    result = service_add_entities(
        instance,
        [EntityUpsertInput(entity_type=entity_type, entity_id=entity_id, properties=properties)],
    )

    label = f"{entity_type}:{entity_id}"
    if result.updated:
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
    result = service_add_relationships(
        instance,
        [
            RelationshipUpsertInput(
                from_type=from_type,
                from_id=from_id,
                relationship=relationship,
                to_type=to_type,
                to_id=to_id,
                properties=properties,
            )
        ],
        source="cli_add",
        source_ref="add-relationship",
    )

    edge_label = f"{from_type}:{from_id} -[{relationship}]-> {to_type}:{to_id}"
    if result.updated:
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
    result = service_list(instance, "edges", relationship_type=relationship, limit=limit)
    console.print(edges_table(result.items))
    click.echo(f"{len(result.items)} edge(s) shown.")


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
@click.option(
    "--exclude-rejected",
    is_flag=True,
    default=False,
    help="Exclude edges with rejected review_status.",
)
@handle_errors
def export_edges(output: str, relationship: str | None, exclude_rejected: bool) -> None:
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
# group (subgroup)
# ---------------------------------------------------------------------------


@click.group("group")
def group_group() -> None:
    """Manage candidate groups for batch edge review."""


@group_group.command("propose")
@click.option("--relationship", required=True, help="Relationship type for the group.")
@click.option(
    "--members-file",
    type=click.Path(exists=True),
    default=None,
    help="JSON file with member list.",
)
@click.option("--members", "members_json", default=None, help="Inline JSON array of members.")
@click.option("--thesis", default="", help="Human-readable thesis text.")
@click.option("--thesis-facts", default=None, help="JSON object of structured thesis facts.")
@click.option("--analysis-state", default=None, help="JSON object of opaque analysis state.")
@click.option("--integration", multiple=True, help="Integration name used in this proposal.")
@handle_errors
def group_propose(
    relationship: str,
    members_file: str | None,
    members_json: str | None,
    thesis: str,
    thesis_facts: str | None,
    analysis_state: str | None,
    integration: tuple[str, ...],
) -> None:
    """Propose a candidate group of edges for batch review."""
    if members_file and members_json:
        raise click.BadParameter("Provide --members-file or --members, not both.")
    if not members_file and not members_json:
        raise click.BadParameter("Provide --members-file or --members.")

    try:
        if members_file:
            raw_members = json.loads(Path(members_file).read_text())
        else:
            raw_members = json.loads(members_json)  # type: ignore[arg-type]
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"Members must be valid JSON: {exc}") from exc

    if not isinstance(raw_members, list):
        raise click.BadParameter("Members must be a JSON array.")

    domain_members = [
        CandidateMember(
            from_type=m["from_type"],
            from_id=m["from_id"],
            to_type=m["to_type"],
            to_id=m["to_id"],
            relationship_type=m["relationship_type"],
            signals=[
                CandidateSignal(
                    integration=s["integration"],
                    signal=s["signal"],
                    evidence=s.get("evidence", ""),
                )
                for s in m.get("signals", [])
            ],
            properties=m.get("properties", {}),
        )
        for m in raw_members
    ]

    try:
        facts = json.loads(thesis_facts) if thesis_facts else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--thesis-facts must be valid JSON") from exc

    try:
        state = json.loads(analysis_state) if analysis_state else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--analysis-state must be valid JSON") from exc

    instance = CruxibleInstance.load()
    result = service_propose_group(
        instance,
        relationship,
        domain_members,
        thesis_text=thesis,
        thesis_facts=facts,
        analysis_state=state,
        integrations_used=list(integration) if integration else None,
    )

    click.echo(f"Group {result.group_id} proposed.")
    click.echo(f"  Status: {result.status}")
    click.echo(f"  Priority: {result.review_priority}")
    click.echo(f"  Members: {result.member_count}")
    click.echo(f"  Signature: {result.signature[:16]}...")


@group_group.command("resolve")
@click.option("--group", "group_id", required=True, help="Group ID to resolve.")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["approve", "reject"]),
    help="Resolution action.",
)
@click.option("--rationale", default="", help="Rationale for this resolution.")
@click.option(
    "--source",
    type=click.Choice(["human", "ai_review"]),
    default="human",
    help="Who resolved (default: human).",
)
@handle_errors
def group_resolve(group_id: str, action: str, rationale: str, source: str) -> None:
    """Resolve a candidate group (approve or reject)."""
    instance = CruxibleInstance.load()
    result = service_resolve_group(
        instance,
        group_id,
        action,  # type: ignore[arg-type]
        rationale=rationale,
        resolved_by=source,  # type: ignore[arg-type]
    )

    click.echo(f"Group {result.group_id} {result.action}d.")
    if result.action == "approve":
        click.echo(f"  Edges created: {result.edges_created}")
        if result.edges_skipped:
            click.echo(f"  Edges skipped: {result.edges_skipped}")


@group_group.command("trust")
@click.option("--resolution", "resolution_id", required=True, help="Resolution ID.")
@click.option(
    "--status",
    "trust_status",
    required=True,
    type=click.Choice(["watch", "trusted", "invalidated"]),
    help="Trust status to set.",
)
@click.option("--reason", default="", help="Reason for trust status change.")
@handle_errors
def group_trust(resolution_id: str, trust_status: str, reason: str) -> None:
    """Update trust status on a resolution."""
    instance = CruxibleInstance.load()
    service_update_trust_status(
        instance,
        resolution_id,
        trust_status,  # type: ignore[arg-type]
        reason=reason,
    )
    click.echo(f"Resolution {resolution_id} trust status set to '{trust_status}'.")


@group_group.command("get")
@click.option("--group", "group_id", required=True, help="Group ID.")
@handle_errors
def group_get(group_id: str) -> None:
    """Get details of a candidate group."""
    instance = CruxibleInstance.load()
    result = service_get_group(instance, group_id)
    console.print(group_detail_table(result.group, result.members))


@group_group.command("list")
@click.option("--relationship", default=None, help="Filter by relationship type.")
@click.option(
    "--status",
    default=None,
    type=click.Choice(["pending_review", "auto_resolved", "applying", "resolved"]),
    help="Filter by status.",
)
@click.option("--limit", default=50, help="Max groups to show.")
@handle_errors
def group_list(relationship: str | None, status: str | None, limit: int) -> None:
    """List candidate groups."""
    instance = CruxibleInstance.load()
    result = service_list_groups(
        instance,
        relationship_type=relationship,
        status=status,
        limit=limit,
    )
    console.print(groups_table(result.groups))
    click.echo(f"{len(result.groups)} of {result.total} group(s) shown.")


@group_group.command("resolutions")
@click.option("--relationship", default=None, help="Filter by relationship type.")
@click.option(
    "--action",
    default=None,
    type=click.Choice(["approve", "reject"]),
    help="Filter by action.",
)
@click.option("--limit", default=50, help="Max resolutions to show.")
@handle_errors
def group_resolutions(relationship: str | None, action: str | None, limit: int) -> None:
    """List group resolutions."""
    instance = CruxibleInstance.load()
    result = service_list_resolutions(
        instance,
        relationship_type=relationship,
        action=action,
        limit=limit,
    )
    console.print(resolutions_table(result.resolutions))
    click.echo(f"{len(result.resolutions)} of {result.total} resolution(s) shown.")


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
