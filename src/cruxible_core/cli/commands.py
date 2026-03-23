"""CLI commands delegating to service layer."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, cast

import click
import yaml
from rich.console import Console

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
from cruxible_core.client import CruxibleClient
from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.schema import ConstraintSchema, CoreConfig
from cruxible_core.config.validator import validate_config
from cruxible_core.entity_proposal.types import EntityChangeMember, EntityChangeProposal
from cruxible_core.errors import ConfigError
from cruxible_core.feedback.types import (
    EdgeTarget,
    FeedbackBatchItem,
    FeedbackRecord,
    OutcomeRecord,
)
from cruxible_core.graph.types import REJECTED_STATUSES, EntityInstance, RelationshipInstance
from cruxible_core.group.types import CandidateGroup, CandidateMember, CandidateSignal
from cruxible_core.mcp import contracts
from cruxible_core.query.candidates import CandidateMatch, MatchRule
from cruxible_core.receipt import serializer
from cruxible_core.server.config import get_server_token
from cruxible_core.service import (
    EntityUpsertInput,
    RelationshipUpsertInput,
    service_add_entities,
    service_add_relationships,
    service_create_snapshot,
    service_evaluate,
    service_feedback,
    service_feedback_batch,
    service_find_candidates,
    service_fork_snapshot,
    service_get_entity,
    service_get_entity_proposal,
    service_get_group,
    service_get_receipt,
    service_get_relationship,
    service_ingest,
    service_init,
    service_list,
    service_list_entity_proposals,
    service_list_groups,
    service_list_resolutions,
    service_list_snapshots,
    service_lock,
    service_outcome,
    service_plan,
    service_propose_entity_changes,
    service_propose_group,
    service_propose_workflow,
    service_query,
    service_resolve_entity_proposal,
    service_resolve_group,
    service_run,
    service_sample,
    service_schema,
    service_test,
    service_update_trust_status,
    service_validate,
)

console = Console()


def _root_ctx_obj() -> dict[str, Any]:
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return {}
    root = ctx.find_root()
    root.ensure_object(dict)
    return root.obj


def _get_client() -> CruxibleClient | None:
    obj = _root_ctx_obj()
    server_url = obj.get("server_url")
    server_socket = obj.get("server_socket")
    if not server_url and not server_socket:
        return None
    client = obj.get("_client")
    if isinstance(client, CruxibleClient):
        return client
    client = CruxibleClient(
        base_url=server_url,
        socket_path=server_socket,
        token=get_server_token(),
    )
    obj["_client"] = client
    return client


def _require_instance_id() -> str:
    obj = _root_ctx_obj()
    instance_id = obj.get("instance_id")
    if not instance_id:
        raise click.UsageError("--instance-id is required in server mode")
    return str(instance_id)


def _raise_server_mode_unsupported(command_name: str) -> None:
    raise click.UsageError(
        f"{command_name} is not available in server mode. Use it locally or wait for v2."
    )


def _read_text_or_error(path_str: str) -> str:
    path = Path(path_str)
    try:
        return path.read_text()
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc


def _read_input_payload(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    try:
        raw = path.read_text()
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc

    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse input file {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigError(f"Input file {path} must contain a top-level mapping")
    return payload


def _entities_from_payload(items: list[dict[str, Any]]) -> list[EntityInstance]:
    return [EntityInstance.model_validate(item) for item in items]


def _feedback_from_payload(items: list[dict[str, Any]]) -> list[FeedbackRecord]:
    return [FeedbackRecord.model_validate(item) for item in items]


def _outcomes_from_payload(items: list[dict[str, Any]]) -> list[OutcomeRecord]:
    return [OutcomeRecord.model_validate(item) for item in items]


def _candidates_from_payload(items: list[dict[str, Any]]) -> list[CandidateMatch]:
    return [CandidateMatch.model_validate(item) for item in items]


def _groups_from_payload(items: list[dict[str, Any]]) -> list[CandidateGroup]:
    return [CandidateGroup.model_validate(item) for item in items]


def _members_from_payload(items: list[dict[str, Any]]) -> list[CandidateMember]:
    return [CandidateMember.model_validate(item) for item in items]


def _entity_change_members_from_payload(items: list[dict[str, Any]]) -> list[EntityChangeMember]:
    return [EntityChangeMember.model_validate(item) for item in items]


def _entity_proposals_from_payload(items: list[dict[str, Any]]) -> list[EntityChangeProposal]:
    return [EntityChangeProposal.model_validate(item) for item in items]


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@click.command()
@click.option("--config", "config_path", required=True, help="Path to config YAML file.")
@click.option("--root-dir", default=None, help="Root directory for the instance.")
@click.option("--data-dir", default=None, help="Directory for data files.")
@handle_errors
def init(config_path: str, root_dir: str | None, data_dir: str | None) -> None:
    """Initialize a new .cruxible/ instance in the current directory."""
    client = _get_client()
    if client is not None:
        if root_dir is None:
            raise click.UsageError("--root-dir is required in server mode")
        config_yaml = _read_text_or_error(config_path)
        result = client.init(root_dir=root_dir, config_yaml=config_yaml, data_dir=data_dir)
        click.echo(f"Instance {result.status}.")
        click.echo(f"Instance ID: {result.instance_id}")
        for warning in result.warnings:
            click.secho(f"  Warning: {warning}", fg="yellow")
        return

    root = Path(root_dir) if root_dir is not None else Path.cwd()
    result = service_init(root, config_path=config_path, data_dir=data_dir)
    click.echo(f"Initialized .cruxible/ in {root}")
    for warning in result.warnings:
        click.secho(f"  Warning: {warning}", fg="yellow")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@click.command()
@click.option("--config", "config_path", required=True, help="Path to config YAML file.")
@handle_errors
def validate(config_path: str) -> None:
    """Validate a config YAML file without creating an instance."""
    client = _get_client()
    if client is not None:
        result = client.validate(config_yaml=_read_text_or_error(config_path))
        click.echo(f"Config '{result.name}' is valid.")
        click.echo(
            f"  {len(result.entity_types)} entity types, "
            f"{len(result.relationships)} relationships, "
            f"{len(result.named_queries)} queries"
        )
        for warning in result.warnings:
            click.secho(f"  Warning: {warning}", fg="yellow")
        return

    result = service_validate(config_path=config_path)
    config = result.config
    click.echo(f"Config '{config.name}' is valid.")
    click.echo(
        f"  {len(config.entity_types)} entity types, "
        f"{len(config.relationships)} relationships, "
        f"{len(config.named_queries)} queries"
    )
    for warning in result.warnings:
        click.secho(f"  Warning: {warning}", fg="yellow")


# ---------------------------------------------------------------------------
# lock / plan / run / test
# ---------------------------------------------------------------------------


@click.command("lock")
@handle_errors
def lock_cmd() -> None:
    """Generate a workflow lock file for the current instance config."""
    client = _get_client()
    if client is not None:
        result = client.workflow_lock(_require_instance_id())
    else:
        instance = CruxibleInstance.load()
        result = service_lock(instance)
    click.echo(f"Wrote lock file to {result.lock_path}")
    click.echo(
        f"  digest={result.config_digest} providers={result.providers_locked} "
        f"artifacts={result.artifacts_locked}"
    )


@click.command("plan")
@click.option("--workflow", "workflow_name", required=True, help="Workflow name from config.")
@click.option(
    "--input-file",
    required=True,
    type=click.Path(exists=True),
    help="JSON or YAML file providing workflow input.",
)
@handle_errors
def plan_cmd(workflow_name: str, input_file: str) -> None:
    """Compile a workflow plan for the current instance."""
    client = _get_client()
    if client is not None:
        result = client.workflow_plan(
            _require_instance_id(),
            workflow_name=workflow_name,
            input_payload=_read_input_payload(input_file),
        )
        click.echo(json.dumps(result.plan, indent=2, sort_keys=True))
        return

    instance = CruxibleInstance.load()
    result = service_plan(instance, workflow_name, _read_input_payload(input_file))
    click.echo(result.plan.model_dump_json(indent=2))


@click.command("run")
@click.option("--workflow", "workflow_name", required=True, help="Workflow name from config.")
@click.option(
    "--input-file",
    required=True,
    type=click.Path(exists=True),
    help="JSON or YAML file providing workflow input.",
)
@handle_errors
def run_cmd(workflow_name: str, input_file: str) -> None:
    """Execute a workflow for the current instance."""
    client = _get_client()
    if client is not None:
        result = client.workflow_run(
            _require_instance_id(),
            workflow_name=workflow_name,
            input_payload=_read_input_payload(input_file),
        )
    else:
        instance = CruxibleInstance.load()
        result = service_run(instance, workflow_name, _read_input_payload(input_file))
    click.echo(f"Workflow {result.workflow} completed.")
    click.echo(f"Receipt ID: {result.receipt_id}")
    if result.query_receipt_ids:
        click.echo(f"Query receipt IDs: {', '.join(result.query_receipt_ids)}")
    if result.trace_ids:
        click.echo(f"Trace IDs: {', '.join(result.trace_ids)}")
    click.echo(json.dumps(result.output, indent=2, sort_keys=True))


@click.command("test")
@click.option("--name", "test_name", default=None, help="Run only a named workflow test.")
@handle_errors
def test_cmd(test_name: str | None) -> None:
    """Execute config-defined workflow tests for the current instance."""
    client = _get_client()
    if client is not None:
        result = client.workflow_test(_require_instance_id(), name=test_name)
    else:
        instance = CruxibleInstance.load()
        result = service_test(instance, test_name=test_name)
    click.echo(f"Tests: {result.passed} passed, {result.failed} failed, {result.total} total")
    for case in result.cases:
        status = "PASS" if case.passed else "FAIL"
        click.echo(f"[{status}] {case.name} ({case.workflow})")
        if case.error:
            click.echo(f"  {case.error}")
        elif case.receipt_id:
            click.echo(f"  receipt={case.receipt_id}")


@click.command("propose")
@click.option("--workflow", "workflow_name", required=True, help="Workflow name from config.")
@click.option(
    "--input-file",
    required=True,
    type=click.Path(exists=True),
    help="JSON or YAML file providing workflow input.",
)
@handle_errors
def propose_cmd(workflow_name: str, input_file: str) -> None:
    """Execute a workflow and bridge its output into a candidate group."""
    payload = _read_input_payload(input_file)
    client = _get_client()
    if client is not None:
        result = client.propose_workflow(
            _require_instance_id(),
            workflow_name=workflow_name,
            input_payload=payload,
        )
    else:
        instance = CruxibleInstance.load()
        result = service_propose_workflow(instance, workflow_name, payload)

    click.echo(f"Workflow {result.workflow} proposed group {result.group_id}.")
    click.echo(f"Receipt ID: {result.receipt_id}")
    click.echo(f"Group status: {result.group_status} ({result.review_priority})")
    if result.trace_ids:
        click.echo(f"Trace IDs: {', '.join(result.trace_ids)}")
    click.echo(json.dumps(result.output, indent=2, sort_keys=True))


@click.group("snapshot")
def snapshot_group() -> None:
    """Manage immutable world-model snapshots."""


@snapshot_group.command("create")
@click.option("--label", default=None, help="Optional human label for the snapshot.")
@handle_errors
def snapshot_create_cmd(label: str | None) -> None:
    """Create an immutable full snapshot for the current instance."""
    client = _get_client()
    if client is not None:
        result = client.create_snapshot(_require_instance_id(), label=label)
    else:
        instance = CruxibleInstance.load()
        result = service_create_snapshot(instance, label=label)

    click.echo(f"Created snapshot {result.snapshot.snapshot_id}")
    if result.snapshot.label:
        click.echo(f"  label={result.snapshot.label}")
    click.echo(f"  graph={result.snapshot.graph_sha256}")


@snapshot_group.command("list")
@handle_errors
def snapshot_list_cmd() -> None:
    """List snapshots for the current instance."""
    client = _get_client()
    if client is not None:
        result = client.list_snapshots(_require_instance_id())
    else:
        instance = CruxibleInstance.load()
        result = service_list_snapshots(instance)

    if not result.snapshots:
        click.echo("No snapshots found.")
        return

    for snapshot in result.snapshots:
        label = f" label={snapshot.label}" if snapshot.label else ""
        click.echo(f"{snapshot.snapshot_id} {snapshot.created_at}{label}")


@click.command("fork")
@click.option("--snapshot", "snapshot_id", required=True, help="Snapshot ID to fork from.")
@click.option("--root-dir", required=True, help="Root directory for the new forked instance.")
@handle_errors
def fork_cmd(snapshot_id: str, root_dir: str) -> None:
    """Create a new local instance from a chosen snapshot."""
    client = _get_client()
    if client is not None:
        result = client.fork_snapshot(
            _require_instance_id(),
            snapshot_id=snapshot_id,
            root_dir=root_dir,
        )
        click.echo(
            f"Forked snapshot {result.snapshot.snapshot_id} into instance {result.instance_id}"
        )
        return

    instance = CruxibleInstance.load()
    result = service_fork_snapshot(instance, snapshot_id, root_dir)
    click.echo(
        f"Forked snapshot {result.snapshot.snapshot_id} into {result.instance.get_root_path()}"
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
    client = _get_client()
    if client is not None:
        result = client.ingest(_require_instance_id(), mapping, file_path=file_path)
    else:
        instance = CruxibleInstance.load()
        result = service_ingest(instance, mapping, file_path=file_path)

    parts = [f"{result.records_ingested} added"]
    if result.records_updated:
        parts.append(f"{result.records_updated} updated")
    click.echo(f"Ingested {', '.join(parts)} via mapping '{mapping}'.")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


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
    params = _parse_params(param)
    client = _get_client()
    if client is not None:
        result = client.query(_require_instance_id(), query_name, params, limit=limit)
        results = _entities_from_payload(result.results)
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
        return

    instance = CruxibleInstance.load()
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
    if _get_client() is not None:
        _raise_server_mode_unsupported("explain")
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

    client = _get_client()
    if client is not None:
        result = client.feedback(
            _require_instance_id(),
            receipt_id=receipt_id,
            action=cast(contracts.FeedbackAction, action),
            source=cast(contracts.FeedbackSource, source),
            from_type=from_type,
            from_id=from_id,
            relationship=relationship,
            to_type=to_type,
            to_id=to_id,
            edge_key=edge_key,
            reason=reason,
            corrections=corrections_dict,
            group_override=group_override,
        )
    else:
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
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


@click.command("feedback-batch")
@click.option(
    "--items-file",
    type=click.Path(exists=True),
    default=None,
    help="JSON or YAML file with batch feedback items.",
)
@click.option("--items", "items_json", default=None, help="Inline JSON array of feedback items.")
@click.option(
    "--source",
    type=click.Choice(["human", "ai_review", "system"]),
    default="human",
    help="Who produced this feedback batch (default: human).",
)
@handle_errors
def feedback_batch_cmd(
    items_file: str | None,
    items_json: str | None,
    source: str,
) -> None:
    """Submit a batch of edge feedback with one top-level receipt."""
    if items_file and items_json:
        raise click.BadParameter("Provide --items-file or --items, not both.")
    if not items_file and not items_json:
        raise click.BadParameter("Provide --items-file or --items.")

    try:
        if items_file:
            raw_items = yaml.safe_load(Path(items_file).read_text())
        else:
            raw_items = json.loads(items_json)  # type: ignore[arg-type]
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise click.BadParameter(f"Items must be valid JSON or YAML: {exc}") from exc

    if not isinstance(raw_items, list):
        raise click.BadParameter("Items must be a top-level array.")

    batch_items = [
        contracts.FeedbackBatchItemInput(
            receipt_id=item["receipt_id"],
            action=item["action"],
            target=contracts.EdgeTargetInput.model_validate(item["target"]),
            reason=item.get("reason", ""),
            corrections=item.get("corrections"),
            group_override=item.get("group_override", False),
        )
        for item in raw_items
    ]

    client = _get_client()
    if client is not None:
        result = client.feedback_batch(
            _require_instance_id(),
            items=batch_items,
            source=cast(contracts.FeedbackSource, source),
        )
    else:
        instance = CruxibleInstance.load()
        result = service_feedback_batch(
            instance,
            [
                FeedbackBatchItem(
                    receipt_id=item.receipt_id,
                    action=item.action,
                    target=EdgeTarget(
                        from_type=item.target.from_type,
                        from_id=item.target.from_id,
                        relationship=item.target.relationship,
                        to_type=item.target.to_type,
                        to_id=item.target.to_id,
                        edge_key=item.target.edge_key,
                    ),
                    reason=item.reason,
                    corrections=item.corrections or {},
                    group_override=item.group_override,
                )
                for item in batch_items
            ],
            source=cast(contracts.FeedbackSource, source),
        )

    click.echo(f"Batch feedback recorded for {result.applied_count}/{result.total} item(s).")
    click.echo(f"  Feedback IDs: {', '.join(result.feedback_ids)}")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


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

    client = _get_client()
    if client is not None:
        result = client.outcome(
            _require_instance_id(),
            receipt_id=receipt_id,
            outcome=cast(contracts.OutcomeValue, outcome_value),
            detail=detail_dict,
        )
    else:
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
    client = _get_client()
    if client is not None:
        result = client.list(
            _require_instance_id(),
            resource_type="entities",
            entity_type=entity_type,
            limit=limit,
        )
        entities = _entities_from_payload(result.items)
        console.print(entities_table(entities, entity_type))
        click.echo(f"{len(entities)} entity(ies) shown.")
        return

    instance = CruxibleInstance.load()
    result = service_list(instance, "entities", entity_type=entity_type, limit=limit)
    console.print(entities_table(result.items, entity_type))
    click.echo(f"{len(result.items)} entity(ies) shown.")


@list_group.command("receipts")
@click.option("--query-name", default=None, help="Filter by query name.")
@click.option("--operation-type", default=None, help="Filter by operation type.")
@click.option("--limit", default=50, help="Max receipts to show.")
@handle_errors
def list_receipts(query_name: str | None, operation_type: str | None, limit: int) -> None:
    """List receipt summaries."""
    client = _get_client()
    if client is not None:
        result = client.list(
            _require_instance_id(),
            resource_type="receipts",
            query_name=query_name,
            operation_type=operation_type,
            limit=limit,
        )
        console.print(receipts_table(result.items))
        click.echo(f"{len(result.items)} receipt(s) shown.")
        return

    instance = CruxibleInstance.load()
    result = service_list(
        instance, "receipts", query_name=query_name, operation_type=operation_type, limit=limit
    )
    console.print(receipts_table(result.items))
    click.echo(f"{len(result.items)} receipt(s) shown.")


@list_group.command("feedback")
@click.option("--receipt", "receipt_id", default=None, help="Filter by receipt ID.")
@click.option("--limit", default=50, help="Max records to show.")
@handle_errors
def list_feedback(receipt_id: str | None, limit: int) -> None:
    """List feedback records."""
    client = _get_client()
    if client is not None:
        result = client.list(
            _require_instance_id(),
            resource_type="feedback",
            receipt_id=receipt_id,
            limit=limit,
        )
        records = _feedback_from_payload(result.items)
        console.print(feedback_table(records))
        click.echo(f"{len(records)} record(s) shown.")
        return

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
    client = _get_client()
    if client is not None:
        result = client.list(
            _require_instance_id(),
            resource_type="outcomes",
            receipt_id=receipt_id,
            limit=limit,
        )
        records = _outcomes_from_payload(result.items)
        console.print(outcomes_table(records))
        click.echo(f"{len(records)} record(s) shown.")
        return

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
    match_rules = None
    if rule:
        match_rules = []
        for r in rule:
            parts = r.split("=", 1)
            if len(parts) != 2:
                raise click.BadParameter(f"Rule must be FROM_PROP=TO_PROP, got: {r}")
            match_rules.append(MatchRule(from_property=parts[0], to_property=parts[1]))

    client = _get_client()
    if client is not None:
        result = client.find_candidates(
            _require_instance_id(),
            relationship_type=relationship,
            strategy=cast(contracts.CandidateStrategy, strategy),
            match_rules=(
                [item.model_dump(mode="json") for item in match_rules] if match_rules else None
            ),
            via_relationship=via_relationship,
            limit=limit,
        )
        candidates = _candidates_from_payload(result.candidates)
        console.print(candidates_table(candidates))
        click.echo(f"{len(candidates)} candidate(s) found.")
        return

    instance = CruxibleInstance.load()
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
    client = _get_client()
    if client is not None:
        config = CoreConfig.model_validate(client.schema(_require_instance_id()))
    else:
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
    client = _get_client()
    if client is not None:
        result = client.sample(_require_instance_id(), entity_type, limit=limit)
        entities = _entities_from_payload(result.entities)
    else:
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
    client = _get_client()
    if client is not None:
        report = client.evaluate(
            _require_instance_id(),
            confidence_threshold=threshold,
            max_findings=limit,
        )
        findings = report.findings
        entity_count = report.entity_count
        edge_count = report.edge_count
        summary = report.summary
    else:
        instance = CruxibleInstance.load()
        report = service_evaluate(instance, confidence_threshold=threshold, max_findings=limit)
        findings = [finding.model_dump(mode="json") for finding in report.findings]
        entity_count = report.entity_count
        edge_count = report.edge_count
        summary = report.summary

    # Summary
    click.echo(f"Graph: {entity_count} entities, {edge_count} edges")
    click.echo(f"Findings: {len(findings)}")
    if summary:
        for category, count in sorted(summary.items()):
            click.echo(f"  {category}: {count}")

    # Findings
    for finding in findings:
        severity = finding["severity"]
        message = finding["message"]
        severity_color = {"error": "red", "warning": "yellow", "info": "blue"}.get(
            severity, "white"
        )
        click.secho(f"  [{severity.upper()}] {message}", fg=severity_color)


# ---------------------------------------------------------------------------
# get-entity
# ---------------------------------------------------------------------------


@click.command("get-entity")
@click.option("--type", "entity_type", required=True, help="Entity type.")
@click.option("--id", "entity_id", required=True, help="Entity ID.")
@handle_errors
def get_entity_cmd(entity_type: str, entity_id: str) -> None:
    """Look up a specific entity by type and ID."""
    client = _get_client()
    if client is not None:
        result = client.get_entity(_require_instance_id(), entity_type, entity_id)
        if not result.found:
            click.echo("Not found.")
            return
        entity = EntityInstance(
            entity_type=result.entity_type,
            entity_id=result.entity_id,
            properties=result.properties,
        )
    else:
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
    client = _get_client()
    if client is not None:
        result = client.get_relationship(
            _require_instance_id(),
            from_type=from_type,
            from_id=from_id,
            relationship_type=relationship,
            to_type=to_type,
            to_id=to_id,
            edge_key=edge_key,
        )
        if not result.found:
            click.echo("Not found.")
            return
        rel = RelationshipInstance(
            relationship_type=result.relationship_type,
            from_entity_type=result.from_type,
            from_entity_id=result.from_id,
            to_entity_type=result.to_type,
            to_entity_id=result.to_id,
            edge_key=result.edge_key,
            properties=result.properties,
        )
    else:
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

    client = _get_client()
    if client is not None:
        result = client.add_entities(
            _require_instance_id(),
            [
                contracts.EntityInput(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    properties=properties,
                )
            ],
        )
    else:
        instance = CruxibleInstance.load()
        result = service_add_entities(
            instance,
            [
                EntityUpsertInput(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    properties=properties,
                )
            ],
        )

    label = f"{entity_type}:{entity_id}"
    if result.updated:
        click.echo(f"Entity {label} updated.")
    else:
        click.echo(f"Entity {label} added.")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


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

    client = _get_client()
    if client is not None:
        result = client.add_relationships(
            _require_instance_id(),
            [
                contracts.RelationshipInput(
                    from_type=from_type,
                    from_id=from_id,
                    relationship=relationship,
                    to_type=to_type,
                    to_id=to_id,
                    properties=properties,
                )
            ],
        )
    else:
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
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


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
    client = _get_client()
    if client is not None:
        result = client.add_constraint(
            _require_instance_id(),
            name=name,
            rule=rule,
            severity=cast(contracts.ConstraintSeverity, severity),
            description=description,
        )
        click.echo(f"Constraint '{result.name}' added to config.")
        for warning in result.warnings:
            click.secho(f"  Warning: {warning}", fg="yellow")
        return

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
    client = _get_client()
    if client is not None:
        result = client.list(
            _require_instance_id(),
            resource_type="edges",
            relationship_type=relationship,
            limit=limit,
        )
        console.print(edges_table(result.items))
        click.echo(f"{len(result.items)} edge(s) shown.")
        return

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
    if _get_client() is not None:
        _raise_server_mode_unsupported("export edges")
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
# entity-proposal (subgroup)
# ---------------------------------------------------------------------------


@click.group("entity-proposal")
def entity_proposal_group() -> None:
    """Manage governed entity create and patch proposals."""


@entity_proposal_group.command("propose")
@click.option(
    "--members-file",
    type=click.Path(exists=True),
    default=None,
    help="JSON or YAML file with proposal members.",
)
@click.option("--members", "members_json", default=None, help="Inline JSON array of members.")
@click.option("--thesis", default="", help="Human-readable thesis text.")
@click.option("--thesis-facts", default=None, help="JSON object of structured thesis facts.")
@click.option("--analysis-state", default=None, help="JSON object of opaque analysis state.")
@click.option(
    "--source",
    "proposed_by",
    type=click.Choice(["human", "ai_review"]),
    default="ai_review",
    help="Who proposed the entity changes (default: ai_review).",
)
@click.option("--suggested-priority", default=None, help="Optional suggested priority.")
@click.option("--source-workflow", default=None, help="Optional source workflow name.")
@click.option(
    "--source-workflow-receipt",
    default=None,
    help="Optional source workflow receipt ID.",
)
@click.option(
    "--source-trace-id",
    "source_trace_ids",
    multiple=True,
    help="Optional source execution trace ID (repeatable).",
)
@click.option(
    "--source-step-id",
    "source_step_ids",
    multiple=True,
    help="Optional source workflow step ID (repeatable).",
)
@handle_errors
def entity_proposal_propose(
    members_file: str | None,
    members_json: str | None,
    thesis: str,
    thesis_facts: str | None,
    analysis_state: str | None,
    proposed_by: str,
    suggested_priority: str | None,
    source_workflow: str | None,
    source_workflow_receipt: str | None,
    source_trace_ids: tuple[str, ...],
    source_step_ids: tuple[str, ...],
) -> None:
    """Propose a governed batch of entity creates or patches."""
    if members_file and members_json:
        raise click.BadParameter("Provide --members-file or --members, not both.")
    if not members_file and not members_json:
        raise click.BadParameter("Provide --members-file or --members.")

    try:
        if members_file:
            raw_members = yaml.safe_load(Path(members_file).read_text())
        else:
            raw_members = json.loads(members_json)  # type: ignore[arg-type]
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise click.BadParameter(f"Members must be valid JSON or YAML: {exc}") from exc
    if not isinstance(raw_members, list):
        raise click.BadParameter("Members must be a top-level array.")

    try:
        facts = json.loads(thesis_facts) if thesis_facts else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--thesis-facts must be valid JSON") from exc
    try:
        state = json.loads(analysis_state) if analysis_state else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--analysis-state must be valid JSON") from exc

    members = [
        contracts.EntityChangeInput(
            entity_type=item["entity_type"],
            entity_id=item["entity_id"],
            operation=item["operation"],
            properties=item.get("properties", {}),
        )
        for item in raw_members
    ]

    client = _get_client()
    if client is not None:
        result = client.propose_entity_changes(
            _require_instance_id(),
            members=members,
            thesis_text=thesis,
            thesis_facts=facts,
            analysis_state=state,
            proposed_by=cast(contracts.GroupProposedBy, proposed_by),
            suggested_priority=suggested_priority,
            source_workflow_name=source_workflow,
            source_workflow_receipt_id=source_workflow_receipt,
            source_trace_ids=list(source_trace_ids) or None,
            source_step_ids=list(source_step_ids) or None,
        )
    else:
        instance = CruxibleInstance.load()
        result = service_propose_entity_changes(
            instance,
            [
                EntityChangeMember(
                    entity_type=member.entity_type,
                    entity_id=member.entity_id,
                    operation=member.operation,
                    properties=member.properties,
                )
                for member in members
            ],
            thesis_text=thesis,
            thesis_facts=facts,
            analysis_state=state,
            proposed_by=cast(contracts.GroupProposedBy, proposed_by),
            suggested_priority=suggested_priority,
            source_workflow_name=source_workflow,
            source_workflow_receipt_id=source_workflow_receipt,
            source_trace_ids=list(source_trace_ids),
            source_step_ids=list(source_step_ids),
        )

    click.echo(f"Entity proposal {result.proposal_id} created.")
    click.echo(f"  Status: {result.status}")
    click.echo(f"  Members: {result.member_count}")


@entity_proposal_group.command("get")
@click.option("--proposal", "proposal_id", required=True, help="Entity proposal ID.")
@handle_errors
def entity_proposal_get(proposal_id: str) -> None:
    """Get details of a governed entity proposal."""
    client = _get_client()
    if client is not None:
        result = client.get_entity_proposal(_require_instance_id(), proposal_id)
        proposal = EntityChangeProposal.model_validate(result.proposal)
        members = _entity_change_members_from_payload(result.members)
    else:
        instance = CruxibleInstance.load()
        loaded = service_get_entity_proposal(instance, proposal_id)
        proposal = loaded.proposal
        members = loaded.members

    click.echo(f"Entity proposal {proposal.proposal_id}")
    click.echo(f"  Status: {proposal.status}")
    click.echo(f"  Proposed by: {proposal.proposed_by}")
    click.echo(f"  Members: {proposal.member_count}")
    for member in members:
        click.echo(
            f"  - {member.operation}: {member.entity_type}:{member.entity_id} "
            f"({len(member.properties)} property updates)"
        )


@entity_proposal_group.command("list")
@click.option(
    "--status",
    default=None,
    type=click.Choice(["pending_review", "applying", "resolved"]),
    help="Filter by status.",
)
@click.option("--limit", default=50, help="Max proposals to show.")
@handle_errors
def entity_proposal_list(status: str | None, limit: int) -> None:
    """List governed entity proposals."""
    client = _get_client()
    if client is not None:
        result = client.list_entity_proposals(
            _require_instance_id(),
            status=cast(contracts.EntityProposalStatus | None, status),
            limit=limit,
        )
        proposals = _entity_proposals_from_payload(result.proposals)
        total = result.total
    else:
        instance = CruxibleInstance.load()
        loaded = service_list_entity_proposals(instance, status=status, limit=limit)
        proposals = loaded.proposals
        total = loaded.total

    for proposal in proposals:
        click.echo(
            f"{proposal.proposal_id}  {proposal.status}  "
            f"{proposal.member_count} member(s)  proposed_by={proposal.proposed_by}"
        )
    click.echo(f"{len(proposals)} of {total} proposal(s) shown.")


@entity_proposal_group.command("resolve")
@click.option("--proposal", "proposal_id", required=True, help="Entity proposal ID.")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["approve", "reject"]),
    help="Resolution action.",
)
@click.option("--rationale", default="", help="Rationale for this resolution.")
@click.option(
    "--source",
    "resolved_by",
    type=click.Choice(["human", "ai_review"]),
    default="human",
    help="Who resolved the proposal (default: human).",
)
@handle_errors
def entity_proposal_resolve(
    proposal_id: str,
    action: str,
    rationale: str,
    resolved_by: str,
) -> None:
    """Resolve a governed entity proposal."""
    client = _get_client()
    if client is not None:
        result = client.resolve_entity_proposal(
            _require_instance_id(),
            proposal_id,
            action=cast(contracts.GroupAction, action),
            rationale=rationale,
            resolved_by=cast(contracts.GroupResolvedBy, resolved_by),
        )
    else:
        instance = CruxibleInstance.load()
        result = service_resolve_entity_proposal(
            instance,
            proposal_id,
            cast(contracts.GroupAction, action),
            rationale=rationale,
            resolved_by=cast(contracts.GroupResolvedBy, resolved_by),
        )

    click.echo(f"Entity proposal {result.proposal_id} {result.action}d.")
    if result.action == "approve":
        click.echo(f"  Entities created: {result.entities_created}")
        click.echo(f"  Entities patched: {result.entities_patched}")
    if result.resolution_id:
        click.echo(f"  Resolution: {result.resolution_id}")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


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

    try:
        facts = json.loads(thesis_facts) if thesis_facts else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--thesis-facts must be valid JSON") from exc

    try:
        state = json.loads(analysis_state) if analysis_state else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--analysis-state must be valid JSON") from exc

    client = _get_client()
    if client is not None:
        members = [
            contracts.MemberInput(
                from_type=m["from_type"],
                from_id=m["from_id"],
                to_type=m["to_type"],
                to_id=m["to_id"],
                relationship_type=m["relationship_type"],
                signals=[
                    contracts.SignalInput(
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
        result = client.propose_group(
            _require_instance_id(),
            relationship_type=relationship,
            members=members,
            thesis_text=thesis,
            thesis_facts=facts,
            analysis_state=state,
            integrations_used=list(integration) if integration else None,
        )
    else:
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
    client = _get_client()
    if client is not None:
        result = client.resolve_group(
            _require_instance_id(),
            group_id,
            action=cast(contracts.GroupAction, action),
            rationale=rationale,
            resolved_by=cast(contracts.GroupResolvedBy, source),
        )
    else:
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
    if result.resolution_id:
        click.echo(f"  Resolution: {result.resolution_id}")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


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
    client = _get_client()
    if client is not None:
        client.update_trust_status(
            _require_instance_id(),
            resolution_id,
            trust_status=cast(contracts.GroupTrustStatus, trust_status),
            reason=reason,
        )
    else:
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
    client = _get_client()
    if client is not None:
        result = client.get_group(_require_instance_id(), group_id)
        console.print(
            group_detail_table(
                CandidateGroup.model_validate(result.group),
                _members_from_payload(result.members),
            )
        )
        return

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
    client = _get_client()
    if client is not None:
        result = client.list_groups(
            _require_instance_id(),
            relationship_type=relationship,
            status=cast(contracts.GroupStatus | None, status),
            limit=limit,
        )
        groups = _groups_from_payload(result.groups)
        console.print(groups_table(groups))
        click.echo(f"{len(groups)} of {result.total} group(s) shown.")
        return

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
    client = _get_client()
    if client is not None:
        result = client.list_resolutions(
            _require_instance_id(),
            relationship_type=relationship,
            action=cast(contracts.GroupAction | None, action),
            limit=limit,
        )
        console.print(resolutions_table(result.resolutions))
        click.echo(f"{len(result.resolutions)} of {result.total} resolution(s) shown.")
        return

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
