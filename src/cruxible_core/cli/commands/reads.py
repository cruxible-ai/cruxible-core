"""CLI commands for query, explain, schema, stats, sample, evaluate,
inspect, analysis, and lookups."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

import click
import yaml

from cruxible_client import CruxibleClient, contracts
from cruxible_core.cli.commands import _common
from cruxible_core.cli.commands._common import (
    _candidates_from_payload,
    _dispatch_cli_instance,
    _emit_json,
    _entities_from_payload,
    _get_client,
    _lookup_query_param_hints_local,
    _lookup_query_param_hints_server,
    _parse_params,
    _print_query_param_hints,
    _require_instance_id,
    _require_local_instance,
    console,
    json_option,
)
from cruxible_core.cli.formatting import (
    candidates_table,
    entities_table,
    inspect_neighbors_table,
    relationship_table,
    schema_table,
    stats_table,
)
from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.cli.main import handle_errors
from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import CoreError
from cruxible_core.graph.types import EntityInstance, RelationshipInstance
from cruxible_core.query.candidates import MatchRule
from cruxible_core.receipt import serializer
from cruxible_core.service import (
    InspectEntityResult,
    service_analyze_feedback,
    service_analyze_outcomes,
    service_evaluate,
    service_find_candidates,
    service_get_entity,
    service_get_receipt,
    service_get_relationship,
    service_inspect_entity,
    service_lint,
    service_query,
    service_sample,
    service_schema,
    service_stats,
)


@click.command()
@click.option("--query", "query_name", required=True, help="Named query from config.")
@click.option("--param", multiple=True, help="Query parameter as KEY=VALUE.")
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Max results to display.")
@click.option("--count", "count_only", is_flag=True, help="Show only summary metadata.")
@json_option
@handle_errors
def query(
    query_name: str,
    param: tuple[str, ...],
    limit: int | None,
    count_only: bool,
    output_json: bool,
) -> None:
    """Execute a named query and save the receipt."""
    params = _parse_params(param)
    client = _common._get_client()
    if client is not None:
        effective_limit = 1 if count_only and limit is None else limit
        instance_id = _require_instance_id()
        try:
            result = client.query(instance_id, query_name, params, limit=effective_limit)
        except CoreError:
            hints = _lookup_query_param_hints_server(
                client, instance_id, query_name,
            )
            _print_query_param_hints(hints)
            raise
        results = _entities_from_payload(result.results)
        total = result.total_results
        if output_json:
            items = [] if count_only else [r.model_dump(mode="python") for r in results]
            if limit is not None and not count_only:
                items = items[:limit]
            _emit_json({
                "results": items,
                "total_results": total,
                "steps_executed": result.steps_executed,
                "receipt_id": result.receipt_id,
                "param_hints": (
                    result.param_hints.model_dump(mode="python")
                    if result.param_hints
                    else None
                ),
                "policy_summary": (
                    result.policy_summary.model_dump(mode="python")
                    if hasattr(result, "policy_summary") and result.policy_summary
                    else None
                ),
            })
            return
        click.echo(f"{total} result(s), {result.steps_executed} step(s) executed.")
        if count_only:
            _print_query_param_hints(result.param_hints)
        elif limit is not None and result.truncated:
            console.print(entities_table(results, query_name))
            click.echo(f"Showing {len(results)} of {total} results (use --limit to adjust).")
        else:
            console.print(entities_table(results, query_name))
        if total == 0 and not count_only:
            _print_query_param_hints(result.param_hints)
        if result.receipt_id:
            click.echo(f"Receipt: {result.receipt_id}")
        return

    instance = CruxibleInstance.load()
    try:
        result = service_query(instance, query_name, params)
    except CoreError:
        _print_query_param_hints(_lookup_query_param_hints_local(instance, query_name))
        raise

    results = result.results
    total = result.total_results
    if output_json:
        items = (
            []
            if count_only
            else [
                {
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "properties": dict(e.properties),
                }
                for e in results
            ]
        )
        if limit is not None and not count_only:
            items = items[:limit]
        _emit_json({
            "results": items,
            "total_results": total,
            "steps_executed": result.steps_executed,
            "receipt_id": result.receipt_id,
            "param_hints": asdict(result.param_hints) if result.param_hints is not None else None,
            "policy_summary": result.policy_summary if result.policy_summary else None,
        })
        return
    click.echo(f"{total} result(s), {result.steps_executed} step(s) executed.")
    if count_only:
        hints = None
        if result.param_hints is not None:
            hints = contracts.QueryParamHints(
                entry_point=result.param_hints.entry_point,
                required_params=result.param_hints.required_params,
                primary_key=result.param_hints.primary_key,
                example_ids=result.param_hints.example_ids,
            )
        _print_query_param_hints(hints)
    elif limit is not None and len(results) > limit:
        results = results[:limit]
        console.print(entities_table(results, query_name))
        click.echo(f"Showing {limit} of {total} results (use --limit to adjust).")
    else:
        console.print(entities_table(results, query_name))
    if total == 0 and not count_only and result.param_hints is not None:
        _print_query_param_hints(
            contracts.QueryParamHints(
                entry_point=result.param_hints.entry_point,
                required_params=result.param_hints.required_params,
                primary_key=result.param_hints.primary_key,
                example_ids=result.param_hints.example_ids,
            )
        )
    if result.receipt_id:
        click.echo(f"Receipt: {result.receipt_id}")


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
    instance = _require_local_instance("explain")
    receipt = service_get_receipt(instance, receipt_id)

    if fmt == "json":
        click.echo(serializer.to_json(receipt))
    elif fmt == "mermaid":
        click.echo(serializer.to_mermaid(receipt))
    else:
        click.echo(serializer.to_markdown(receipt))


@click.command()
@json_option
@handle_errors
def schema(output_json: bool) -> None:
    """Display the config schema for this instance."""
    config = _dispatch_cli_instance(
        lambda client, instance_id: CoreConfig.model_validate(client.schema(instance_id)),
        service_schema,
    )
    if output_json:
        _emit_json(config.model_dump(mode="python"))
        return
    console.print(schema_table(config))


@click.command("stats")
@json_option
@handle_errors
def stats_cmd(output_json: bool) -> None:
    """Display entity and relationship counts for this instance."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.stats(instance_id),
        service_stats,
    )
    entity_count = result.entity_count
    edge_count = result.edge_count
    entity_counts = result.entity_counts
    relationship_counts = result.relationship_counts
    head_snapshot_id = result.head_snapshot_id
    if output_json:
        _emit_json({
            "entity_count": entity_count,
            "edge_count": edge_count,
            "entity_counts": entity_counts,
            "relationship_counts": relationship_counts,
            "head_snapshot_id": head_snapshot_id,
        })
        return
    click.echo(f"Graph: {entity_count} entities, {edge_count} edges")
    if head_snapshot_id:
        click.echo(f"Head snapshot: {head_snapshot_id}")
    console.print(stats_table(entity_counts, relationship_counts))


@click.command()
@click.option("--type", "entity_type", required=True, help="Entity type to sample.")
@click.option("--limit", default=5, help="Number of entities to show.")
@json_option
@handle_errors
def sample(entity_type: str, limit: int, output_json: bool) -> None:
    """Show a sample of entities of a given type."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.sample(instance_id, entity_type, limit=limit),
        lambda instance: service_sample(instance, entity_type, limit=limit),
    )
    entities = (
        _entities_from_payload(result.entities)
        if isinstance(result, contracts.SampleResult)
        else result
    )
    if output_json:
        _emit_json({
            "entities": [e.model_dump(mode="python") for e in entities],
            "entity_type": entity_type,
        })
        return
    console.print(entities_table(entities, entity_type))


@click.command()
@click.option(
    "--threshold", default=0.5, type=float, help="Confidence threshold for flagging edges."
)
@click.option("--limit", default=100, type=int, help="Max findings to show.")
@json_option
@handle_errors
def evaluate(threshold: float, limit: int, output_json: bool) -> None:
    """Assess graph quality: orphans, gaps, violations, unreviewed co-members."""
    report = _dispatch_cli_instance(
        lambda client, instance_id: client.evaluate(
            instance_id,
            confidence_threshold=threshold,
            max_findings=limit,
        ),
        lambda instance: service_evaluate(
            instance,
            confidence_threshold=threshold,
            max_findings=limit,
        ),
    )
    findings = (
        report.findings
        if isinstance(report, contracts.EvaluateResult)
        else [finding.model_dump(mode="json") for finding in report.findings]
    )
    entity_count = report.entity_count
    edge_count = report.edge_count
    summary = report.summary
    quality_summary = report.quality_summary
    constraint_summary = getattr(report, "constraint_summary", {})

    if output_json:
        _emit_json({
            "findings": findings,
            "entity_count": entity_count,
            "edge_count": edge_count,
            "summary": summary,
            "quality_summary": quality_summary,
            "constraint_summary": constraint_summary,
        })
        return

    click.echo(f"Graph: {entity_count} entities, {edge_count} edges")
    click.echo(f"Findings: {len(findings)}")
    if summary:
        for category, count in sorted(summary.items()):
            click.echo(f"  {category}: {count}")
    if quality_summary:
        click.echo("Quality checks:")
        for check_name, count in quality_summary.items():
            click.echo(f"  {check_name}: {count}")

    for finding in findings:
        severity = finding["severity"]
        message = finding["message"]
        severity_color = {"error": "red", "warning": "yellow", "info": "blue"}.get(
            severity, "white"
        )
        click.secho(f"  [{severity.upper()}] {message}", fg=severity_color)


@click.command("lint")
@click.option(
    "--threshold",
    default=0.5,
    type=float,
    help="Confidence threshold for graph evaluation findings.",
)
@click.option("--max-findings", default=100, type=int, help="Max graph findings to include.")
@click.option(
    "--analysis-limit",
    default=200,
    type=int,
    help="Rows to inspect for feedback and outcome analysis.",
)
@click.option(
    "--min-support",
    default=5,
    type=int,
    help="Minimum support for lint suggestions.",
)
@click.option(
    "--exclude-orphan-type",
    "exclude_orphan_types",
    multiple=True,
    help="Entity type to exclude from orphan checks.",
)
@json_option
@handle_errors
def lint_cmd(
    threshold: float,
    max_findings: int,
    analysis_limit: int,
    min_support: int,
    exclude_orphan_types: tuple[str, ...],
    output_json: bool,
) -> None:
    """Run the aggregate read-only corpus lint pass."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.lint(
            instance_id,
            confidence_threshold=threshold,
            max_findings=max_findings,
            analysis_limit=analysis_limit,
            min_support=min_support,
            exclude_orphan_types=list(exclude_orphan_types) or None,
        ),
        lambda instance: service_lint(
            instance,
            confidence_threshold=threshold,
            max_findings=max_findings,
            analysis_limit=analysis_limit,
            min_support=min_support,
            exclude_orphan_types=list(exclude_orphan_types) or None,
        ),
    )

    payload = (
        result.model_dump(mode="python")
        if isinstance(result, contracts.LintResult)
        else asdict(result)
    )

    if output_json:
        _emit_json(payload)
        if payload["has_issues"]:
            raise SystemExit(1)
        return

    summary = payload["summary"]
    click.echo(f"Lint report for '{payload['config_name']}'")
    click.echo(
        "Summary: "
        f"config_warnings={summary['config_warning_count']}, "
        f"compatibility_warnings={summary['compatibility_warning_count']}, "
        f"graph_findings={summary['evaluation_finding_count']}, "
        f"feedback_reports={summary['feedback_report_count']}, "
        f"feedback_issues={summary['feedback_issue_count']}, "
        f"outcome_reports={summary['outcome_report_count']}, "
        f"outcome_issues={summary['outcome_issue_count']}"
    )

    if payload["config_warnings"]:
        click.echo("Config warnings:")
        for warning in payload["config_warnings"]:
            click.secho(f"  Warning: {warning}", fg="yellow")

    if payload["compatibility_warnings"]:
        click.echo("Compatibility warnings:")
        for warning in payload["compatibility_warnings"]:
            click.secho(f"  Warning: {warning}", fg="yellow")

    evaluation = payload["evaluation"]
    if evaluation["findings"]:
        click.echo("Graph findings:")
        for finding in evaluation["findings"]:
            severity = finding["severity"]
            severity_color = {"error": "red", "warning": "yellow", "info": "blue"}.get(
                severity,
                "white",
            )
            click.secho(
                f"  [{severity.upper()}] {finding['message']}",
                fg=severity_color,
            )

    if payload["feedback_reports"]:
        click.echo("Feedback maintenance suggestions:")
        for report in payload["feedback_reports"]:
            click.echo(f"  {report['relationship_type']}:")
            if report["warnings"]:
                click.echo(f"    warnings={len(report['warnings'])}")
            if report["uncoded_feedback_count"]:
                click.echo(f"    uncoded_feedback={report['uncoded_feedback_count']}")
            for suggestion in report["constraint_suggestions"]:
                click.echo(
                    f"    constraint {suggestion['name']}: {suggestion['rule']} "
                    f"(support={suggestion['support_count']})"
                )
            for suggestion in report["decision_policy_suggestions"]:
                click.echo(
                    f"    policy {suggestion['name']}: {suggestion['applies_to']}/"
                    f"{suggestion['effect']} (support={suggestion['support_count']})"
                )
            for candidate in report["quality_check_candidates"]:
                click.echo(
                    f"    quality_check {candidate['reason_code']} "
                    f"(support={candidate['support_count']})"
                )
            for candidate in report["provider_fix_candidates"]:
                click.echo(
                    f"    provider_fix {candidate['reason_code']} "
                    f"(support={candidate['support_count']})"
                )

    if payload["outcome_reports"]:
        click.echo("Outcome maintenance suggestions:")
        for report in payload["outcome_reports"]:
            click.echo(f"  {report['anchor_type']}:")
            if report["warnings"]:
                click.echo(f"    warnings={len(report['warnings'])}")
            if report["uncoded_outcome_count"]:
                click.echo(f"    uncoded_outcomes={report['uncoded_outcome_count']}")
            for suggestion in report["trust_adjustment_suggestions"]:
                click.echo(
                    f"    trust_adjustment {suggestion['resolution_id']} -> "
                    f"{suggestion['suggested_trust_status']} "
                    f"(support={suggestion['support_count']})"
                )
            for suggestion in report["workflow_review_policy_suggestions"]:
                click.echo(
                    f"    workflow_review {suggestion['name']} "
                    f"(support={suggestion['support_count']})"
                )
            for suggestion in report["query_policy_suggestions"]:
                click.echo(
                    f"    query_policy {suggestion['surface_name']}:{suggestion['outcome_code']} "
                    f"(support={suggestion['support_count']})"
                )
            for candidate in report["provider_fix_candidates"]:
                click.echo(
                    f"    provider_fix {candidate['surface_name']}:{candidate['outcome_code']} "
                    f"(support={candidate['support_count']})"
                )
            if report["debug_packages"]:
                click.echo(f"    debug_packages={len(report['debug_packages'])}")
            if report["workflow_debug_packages"]:
                click.echo(f"    workflow_debug_packages={len(report['workflow_debug_packages'])}")

    if payload["has_issues"]:
        click.secho("Lint found issues.", fg="yellow")
        raise SystemExit(1)

    click.secho("Lint clean.", fg="green")


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
    match_rules = None
    if rule:
        match_rules = []
        for r in rule:
            parts = r.split("=", 1)
            if len(parts) != 2:
                raise click.BadParameter(f"Rule must be FROM_PROP=TO_PROP, got: {r}")
            match_rules.append(MatchRule(from_property=parts[0], to_property=parts[1]))

    result = _dispatch_cli_instance(
        lambda client, instance_id: client.find_candidates(
            instance_id,
            relationship_type=relationship,
            strategy=cast(contracts.CandidateStrategy, strategy),
            match_rules=(
                [item.model_dump(mode="json") for item in match_rules] if match_rules else None
            ),
            via_relationship=via_relationship,
            limit=limit,
        ),
        lambda instance: service_find_candidates(
            instance,
            relationship,
            cast(contracts.CandidateStrategy, strategy),
            match_rules=match_rules,
            via_relationship=via_relationship,
            limit=limit,
        ),
    )
    candidates = (
        _candidates_from_payload(result.candidates)
        if isinstance(result, contracts.CandidatesResult)
        else result
    )

    console.print(candidates_table(candidates))
    click.echo(f"{len(candidates)} candidate(s) found.")


@click.group("inspect")
def inspect_group() -> None:
    """Inspect entities and their immediate graph context."""


@inspect_group.command("entity")
@click.option("--type", "entity_type", required=True, help="Entity type.")
@click.option("--id", "entity_id", required=True, help="Entity ID.")
@click.option(
    "--direction",
    type=click.Choice(["incoming", "outgoing", "both"]),
    default="both",
    show_default=True,
    help="Neighbor traversal direction.",
)
@click.option(
    "--relationship", "relationship_type",
    default=None, help="Optional relationship filter.",
)
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Max neighbors to show.")
@json_option
@handle_errors
def inspect_entity_cmd(
    entity_type: str,
    entity_id: str,
    direction: str,
    relationship_type: str | None,
    limit: int | None,
    output_json: bool,
) -> None:
    """Inspect an entity and its immediate neighbors."""
    def _remote_fetch(
        client: CruxibleClient,
        instance_id: str,
    ) -> tuple[InspectEntityResult, list[dict[str, Any]]]:
        result = client.inspect_entity(
            instance_id,
            entity_type,
            entity_id,
            direction=direction,
            relationship_type=relationship_type,
            limit=limit,
        )
        inspect_result = InspectEntityResult(
            found=result.found,
            entity_type=result.entity_type,
            entity_id=result.entity_id,
            properties=result.properties,
            neighbors=[],
            total_neighbors=result.total_neighbors,
        )
        neighbor_rows = [
            {
                "direction": neighbor.direction,
                "relationship_type": neighbor.relationship_type,
                "edge_key": neighbor.edge_key,
                "properties": neighbor.properties,
                "entity": neighbor.entity,
            }
            for neighbor in result.neighbors
        ]
        return inspect_result, neighbor_rows

    def _local_fetch(
        instance: CruxibleInstance,
    ) -> tuple[InspectEntityResult, list[dict[str, Any]]]:
        inspect_result = service_inspect_entity(
            instance,
            entity_type,
            entity_id,
            direction=cast(Any, direction),
            relationship_type=relationship_type,
            limit=limit,
        )
        neighbor_rows = [
            {
                "direction": neighbor.direction,
                "relationship_type": neighbor.relationship_type,
                "edge_key": neighbor.edge_key,
                "properties": neighbor.properties,
                "entity": neighbor.entity.model_dump(mode="json") if neighbor.entity else {},
            }
            for neighbor in inspect_result.neighbors
        ]
        return inspect_result, neighbor_rows

    inspect_result, neighbor_rows = _dispatch_cli_instance(
        _remote_fetch,
        _local_fetch,
    )
    if output_json:
        _emit_json({
            "found": inspect_result.found,
            "entity_type": inspect_result.entity_type,
            "entity_id": inspect_result.entity_id,
            "properties": inspect_result.properties,
            "neighbors": neighbor_rows,
            "total_neighbors": inspect_result.total_neighbors,
        })
        return
    if not inspect_result.found:
        click.echo("Not found.")
        return
    console.print(
        entities_table(
            [
                EntityInstance(
                    entity_type=inspect_result.entity_type,
                    entity_id=inspect_result.entity_id,
                    properties=inspect_result.properties,
                )
            ],
            inspect_result.entity_type,
        )
    )
    click.echo(f"Neighbors: {inspect_result.total_neighbors}")
    if neighbor_rows:
        console.print(inspect_neighbors_table(neighbor_rows))


@click.command("get-entity")
@click.option("--type", "entity_type", required=True, help="Entity type.")
@click.option("--id", "entity_id", required=True, help="Entity ID.")
@json_option
@handle_errors
def get_entity_cmd(entity_type: str, entity_id: str, output_json: bool) -> None:
    """Look up a specific entity by type and ID."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.get_entity(instance_id, entity_type, entity_id),
        lambda instance: service_get_entity(instance, entity_type, entity_id),
    )
    if isinstance(result, contracts.GetEntityResult):
        if not result.found:
            if output_json:
                _emit_json({"found": False, "entity_type": entity_type, "entity_id": entity_id})
                return
            click.echo("Not found.")
            return
        entity = EntityInstance(
            entity_type=result.entity_type,
            entity_id=result.entity_id,
            properties=result.properties,
        )
    else:
        if result is None:
            if output_json:
                _emit_json({"found": False, "entity_type": entity_type, "entity_id": entity_id})
                return
            click.echo("Not found.")
            return
        entity = result
    if output_json:
        _emit_json({
            "entity_type": entity.entity_type,
            "entity_id": entity.entity_id,
            "properties": dict(entity.properties),
        })
        return
    console.print(entities_table([entity], entity_type))


@click.command("get-relationship")
@click.option("--from-type", required=True, help="Source entity type.")
@click.option("--from-id", required=True, help="Source entity ID.")
@click.option("--relationship", required=True, help="Relationship type.")
@click.option("--to-type", required=True, help="Target entity type.")
@click.option("--to-id", required=True, help="Target entity ID.")
@click.option("--edge-key", default=None, type=int, help="Edge key (multi-edge disambiguation).")
@json_option
@handle_errors
def get_relationship_cmd(
    from_type: str,
    from_id: str,
    relationship: str,
    to_type: str,
    to_id: str,
    edge_key: int | None,
    output_json: bool,
) -> None:
    """Look up a specific relationship by its endpoints and type."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.get_relationship(
            instance_id,
            from_type=from_type,
            from_id=from_id,
            relationship_type=relationship,
            to_type=to_type,
            to_id=to_id,
            edge_key=edge_key,
        ),
        lambda instance: service_get_relationship(
            instance,
            from_type=from_type,
            from_id=from_id,
            relationship_type=relationship,
            to_type=to_type,
            to_id=to_id,
            edge_key=edge_key,
        ),
    )
    if isinstance(result, contracts.GetRelationshipResult):
        if not result.found:
            if output_json:
                _emit_json({"found": False, "relationship_type": relationship})
                return
            click.echo("Not found.")
            return
        rel = RelationshipInstance(
            relationship_type=result.relationship_type,
            from_type=result.from_type,
            from_id=result.from_id,
            to_type=result.to_type,
            to_id=result.to_id,
            edge_key=result.edge_key,
            properties=result.properties,
        )
    else:
        if result is None:
            if output_json:
                _emit_json({"found": False, "relationship_type": relationship})
                return
            click.echo("Not found.")
            return
        rel = result
    if output_json:
        _emit_json(rel.model_dump(mode="python"))
        return
    console.print(relationship_table(rel))


@click.command("analyze-feedback")
@click.option("--relationship", "relationship_type", required=True, help="Relationship type.")
@click.option("--limit", default=200, type=click.IntRange(min=1), help="Rows to inspect.")
@click.option(
    "--min-support",
    default=5,
    type=click.IntRange(min=1),
    help="Minimum support for suggestions.",
)
@click.option(
    "--decision-surface-type",
    default=None,
    type=click.Choice(["query", "workflow", "operation"]),
    help="Optional decision surface type filter.",
)
@click.option(
    "--decision-surface-name",
    default=None,
    help="Optional decision surface name filter.",
)
@click.option(
    "--pair",
    "pair_values",
    multiple=True,
    help="Explicit mismatch pair as FROM_PROP=TO_PROP.",
)
@handle_errors
def analyze_feedback_cmd(
    relationship_type: str,
    limit: int,
    min_support: int,
    decision_surface_type: str | None,
    decision_surface_name: str | None,
    pair_values: tuple[str, ...],
) -> None:
    """Analyze structured feedback and print remediation suggestions."""
    property_pairs = []
    for raw_pair in pair_values:
        parts = raw_pair.split("=", 1)
        if len(parts) != 2:
            raise click.BadParameter(f"--pair must be FROM_PROP=TO_PROP, got: {raw_pair}")
        property_pairs.append(
            contracts.PropertyPairInput(from_property=parts[0], to_property=parts[1])
        )

    client = _get_client()
    if client is not None:
        result = client.analyze_feedback(
            _require_instance_id(),
            relationship_type=relationship_type,
            limit=limit,
            min_support=min_support,
            decision_surface_type=decision_surface_type,
            decision_surface_name=decision_surface_name,
            property_pairs=property_pairs or None,
        )
        payload = result.model_dump(mode="json")
    else:
        instance = CruxibleInstance.load()
        result = service_analyze_feedback(
            instance,
            relationship_type,
            limit=limit,
            min_support=min_support,
            decision_surface_type=decision_surface_type,
            decision_surface_name=decision_surface_name,
            property_pairs=[(pair.from_property, pair.to_property) for pair in property_pairs]
            or None,
        )
        payload = asdict(result)

    click.echo(f"Feedback analyzed: {payload['feedback_count']} row(s)")
    if payload["action_counts"]:
        click.echo(
            "Actions: "
            + ", ".join(
                f"{name}={count}" for name, count in sorted(payload["action_counts"].items())
            )
        )
    if payload["reason_code_counts"]:
        click.echo(
            "Reason codes: "
            + ", ".join(
                f"{name}={count}" for name, count in sorted(payload["reason_code_counts"].items())
            )
        )
    if payload["constraint_suggestions"]:
        click.echo("Constraint suggestions:")
        for suggestion in payload["constraint_suggestions"]:
            click.echo(
                f"  {suggestion['name']}: {suggestion['rule']} "
                f"(support={suggestion['support_count']})"
            )
    if payload["decision_policy_suggestions"]:
        click.echo("Decision policy suggestions:")
        for suggestion in payload["decision_policy_suggestions"]:
            click.echo(
                f"  {suggestion['name']}: {suggestion['applies_to']}/{suggestion['effect']} "
                f"(support={suggestion['support_count']})"
            )
    if payload["quality_check_candidates"]:
        click.echo("Quality check candidates:")
        for candidate in payload["quality_check_candidates"]:
            click.echo(
                f"  {candidate['reason_code']}: support={candidate['support_count']}"
            )
    if payload["provider_fix_candidates"]:
        click.echo("Provider fix candidates:")
        for candidate in payload["provider_fix_candidates"]:
            click.echo(
                f"  {candidate['reason_code']}: support={candidate['support_count']}"
            )
    if payload["uncoded_feedback_count"]:
        click.echo(f"Uncoded feedback: {payload['uncoded_feedback_count']}")
        for example in payload["uncoded_examples"]:
            click.echo(f"  {example['feedback_id']}: {example['reason']}")
    for warning in payload["warnings"]:
        click.secho(f"Warning: {warning}", fg="yellow")


@click.command("analyze-outcomes")
@click.option(
    "--anchor-type",
    required=True,
    type=click.Choice(["receipt", "resolution"]),
    help="Outcome anchor type to analyze.",
)
@click.option("--relationship", "relationship_type", default=None, help="Relationship type.")
@click.option("--workflow", "workflow_name", default=None, help="Workflow name filter.")
@click.option("--query", "query_name", default=None, help="Query name filter.")
@click.option(
    "--surface-type",
    default=None,
    type=click.Choice(["query", "workflow", "operation"]),
    help="Explicit surface type filter.",
)
@click.option("--surface-name", default=None, help="Explicit surface name filter.")
@click.option("--limit", default=200, type=click.IntRange(min=1), help="Rows to inspect.")
@click.option(
    "--min-support",
    default=5,
    type=click.IntRange(min=1),
    help="Minimum support for suggestions.",
)
@handle_errors
def analyze_outcomes_cmd(
    anchor_type: str,
    relationship_type: str | None,
    workflow_name: str | None,
    query_name: str | None,
    surface_type: str | None,
    surface_name: str | None,
    limit: int,
    min_support: int,
) -> None:
    """Analyze structured outcomes and print trust/debugging suggestions."""
    client = _get_client()
    if client is not None:
        result = client.analyze_outcomes(
            _require_instance_id(),
            anchor_type=cast(contracts.OutcomeAnchorType, anchor_type),
            relationship_type=relationship_type,
            workflow_name=workflow_name,
            query_name=query_name,
            surface_type=surface_type,
            surface_name=surface_name,
            limit=limit,
            min_support=min_support,
        )
        payload = result.model_dump(mode="json")
    else:
        instance = CruxibleInstance.load()
        result = service_analyze_outcomes(
            instance,
            anchor_type=cast(contracts.OutcomeAnchorType, anchor_type),
            relationship_type=relationship_type,
            workflow_name=workflow_name,
            query_name=query_name,
            surface_type=surface_type,
            surface_name=surface_name,
            limit=limit,
            min_support=min_support,
        )
        payload = asdict(result)

    click.echo(yaml.safe_dump(payload, sort_keys=False))
