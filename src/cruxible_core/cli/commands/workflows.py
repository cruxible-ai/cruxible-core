"""CLI commands for init, validate, workflows, snapshots, and ingest."""

from __future__ import annotations

import json
from pathlib import Path

import click

from cruxible_core.cli.commands import _common
from cruxible_core.cli.commands._common import (
    _dispatch_cli,
    _dispatch_cli_instance,
    _print_apply_previews,
    _read_text_or_error,
    _resolve_workflow_input,
)
from cruxible_core.cli.main import handle_errors
from cruxible_core.mcp import contracts
from cruxible_core.service import (
    service_apply_workflow,
    service_create_snapshot,
    service_fork_snapshot,
    service_ingest,
    service_init,
    service_list_snapshots,
    service_lock,
    service_plan,
    service_propose_workflow,
    service_run,
    service_test,
    service_validate,
)


@click.command()
@click.option("--config", "config_path", required=True, help="Path to config YAML file.")
@click.option("--root-dir", default=None, help="Root directory for the instance.")
@click.option("--data-dir", default=None, help="Directory for data files.")
@handle_errors
def init(config_path: str, root_dir: str | None, data_dir: str | None) -> None:
    """Initialize a new .cruxible/ instance in the current directory."""
    if _common._get_client() is not None and root_dir is None:
        raise click.UsageError("--root-dir is required in server mode")
    result = _dispatch_cli(
        lambda client: client.init(
            root_dir=root_dir,
            config_yaml=_read_text_or_error(config_path),
            data_dir=data_dir,
        ),
        lambda: service_init(
            Path(root_dir) if root_dir is not None else Path.cwd(),
            config_path=config_path,
            data_dir=data_dir,
        ),
    )
    if isinstance(result, contracts.InitResult):
        click.echo(f"Instance {result.status}.")
        click.echo(f"Instance ID: {result.instance_id}")
        for warning in result.warnings:
            click.secho(f"  Warning: {warning}", fg="yellow")
        return

    root = Path(root_dir) if root_dir is not None else Path.cwd()
    click.echo(f"Initialized .cruxible/ in {root}")
    for warning in result.warnings:
        click.secho(f"  Warning: {warning}", fg="yellow")


@click.command()
@click.option("--config", "config_path", required=True, help="Path to config YAML file.")
@handle_errors
def validate(config_path: str) -> None:
    """Validate a config YAML file without creating an instance."""
    result = _dispatch_cli(
        lambda client: client.validate(config_yaml=_common._read_validation_yaml_or_error(config_path)),
        lambda: service_validate(config_path=config_path),
    )
    if isinstance(result, contracts.ValidateResult):
        click.echo(f"Config '{result.name}' is valid.")
        click.echo(
            f"  {len(result.entity_types)} entity types, "
            f"{len(result.relationships)} relationships, "
            f"{len(result.named_queries)} queries"
        )
        for warning in result.warnings:
            click.secho(f"  Warning: {warning}", fg="yellow")
        return

    config = result.config
    click.echo(f"Config '{config.name}' is valid.")
    click.echo(
        f"  {len(config.entity_types)} entity types, "
        f"{len(config.relationships)} relationships, "
        f"{len(config.named_queries)} queries"
    )
    for warning in result.warnings:
        click.secho(f"  Warning: {warning}", fg="yellow")


@click.command("lock")
@handle_errors
def lock_cmd() -> None:
    """Generate a workflow lock file for the current instance config."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.workflow_lock(instance_id),
        service_lock,
    )
    click.echo(f"Wrote lock file to {result.lock_path}")
    click.echo(
        f"  digest={result.config_digest} providers={result.providers_locked} "
        f"artifacts={result.artifacts_locked}"
    )


@click.command("plan")
@click.option("--workflow", "workflow_name", required=True, help="Workflow name from config.")
@click.option("--input", "input_text", default=None, help="Inline JSON or YAML workflow input.")
@click.option(
    "--input-file",
    default=None,
    type=click.Path(exists=True),
    help="JSON or YAML file providing workflow input.",
)
@handle_errors
def plan_cmd(workflow_name: str, input_text: str | None, input_file: str | None) -> None:
    """Compile a workflow plan for the current instance."""
    payload = _resolve_workflow_input(input_text=input_text, input_file=input_file)
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.workflow_plan(
            instance_id,
            workflow_name=workflow_name,
            input_payload=payload,
        ),
        lambda instance: service_plan(instance, workflow_name, payload),
    )
    if isinstance(result, contracts.WorkflowPlanResult):
        click.echo(json.dumps(result.plan, indent=2, sort_keys=True))
        return
    click.echo(result.plan.model_dump_json(indent=2))


@click.command("run")
@click.option("--workflow", "workflow_name", required=True, help="Workflow name from config.")
@click.option("--input", "input_text", default=None, help="Inline JSON or YAML workflow input.")
@click.option(
    "--input-file",
    default=None,
    type=click.Path(exists=True),
    help="JSON or YAML file providing workflow input.",
)
@handle_errors
def run_cmd(workflow_name: str, input_text: str | None, input_file: str | None) -> None:
    """Execute a workflow for the current instance."""
    payload = _resolve_workflow_input(input_text=input_text, input_file=input_file)
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.workflow_run(
            instance_id,
            workflow_name=workflow_name,
            input_payload=payload,
        ),
        lambda instance: service_run(instance, workflow_name, payload),
    )
    click.echo(f"Workflow {result.workflow} completed.")
    if result.mode != "run":
        click.echo(f"Mode: {result.mode}")
    if result.apply_digest:
        click.echo(f"Apply digest: {result.apply_digest}")
    if result.head_snapshot_id:
        click.echo(f"Head snapshot: {result.head_snapshot_id}")
    _print_apply_previews(result.apply_previews)
    click.echo(f"Receipt ID: {result.receipt_id}")
    if result.query_receipt_ids:
        click.echo(f"Query receipt IDs: {', '.join(result.query_receipt_ids)}")
    if result.trace_ids:
        click.echo(f"Trace IDs: {', '.join(result.trace_ids)}")
    click.echo(json.dumps(result.output, indent=2, sort_keys=True))


@click.command("apply")
@click.option("--workflow", "workflow_name", required=True, help="Workflow name from config.")
@click.option("--input", "input_text", default=None, help="Inline JSON or YAML workflow input.")
@click.option(
    "--input-file",
    default=None,
    type=click.Path(exists=True),
    help="JSON or YAML file providing workflow input.",
)
@click.option("--apply-digest", required=True, help="Preview apply digest from workflow run.")
@click.option(
    "--head-snapshot",
    default=None,
    help="Expected head snapshot ID from workflow preview.",
)
@handle_errors
def apply_cmd(
    workflow_name: str,
    input_text: str | None,
    input_file: str | None,
    apply_digest: str,
    head_snapshot: str | None,
) -> None:
    """Apply a canonical workflow after verifying preview identity."""
    payload = _resolve_workflow_input(input_text=input_text, input_file=input_file)
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.workflow_apply(
            instance_id,
            workflow_name=workflow_name,
            expected_apply_digest=apply_digest,
            expected_head_snapshot_id=head_snapshot,
            input_payload=payload,
        ),
        lambda instance: service_apply_workflow(
            instance,
            workflow_name,
            payload,
            expected_apply_digest=apply_digest,
            expected_head_snapshot_id=head_snapshot,
        ),
    )
    click.echo(f"Workflow {result.workflow} applied.")
    if result.committed_snapshot_id:
        click.echo(f"Committed snapshot: {result.committed_snapshot_id}")
    _print_apply_previews(result.apply_previews)
    click.echo(f"Receipt ID: {result.receipt_id}")
    if result.trace_ids:
        click.echo(f"Trace IDs: {', '.join(result.trace_ids)}")
    click.echo(json.dumps(result.output, indent=2, sort_keys=True))


@click.command("test")
@click.option("--name", "test_name", default=None, help="Run only a named workflow test.")
@handle_errors
def test_cmd(test_name: str | None) -> None:
    """Execute config-defined workflow tests for the current instance."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.workflow_test(instance_id, name=test_name),
        lambda instance: service_test(instance, test_name=test_name),
    )
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
@click.option("--input", "input_text", default=None, help="Inline JSON or YAML workflow input.")
@click.option(
    "--input-file",
    default=None,
    type=click.Path(exists=True),
    help="JSON or YAML file providing workflow input.",
)
@handle_errors
def propose_cmd(workflow_name: str, input_text: str | None, input_file: str | None) -> None:
    """Execute a workflow and bridge its output into a candidate group."""
    payload = _resolve_workflow_input(input_text=input_text, input_file=input_file)
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.propose_workflow(
            instance_id,
            workflow_name=workflow_name,
            input_payload=payload,
        ),
        lambda instance: service_propose_workflow(instance, workflow_name, payload),
    )

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
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.create_snapshot(instance_id, label=label),
        lambda instance: service_create_snapshot(instance, label=label),
    )

    click.echo(f"Created snapshot {result.snapshot.snapshot_id}")
    if result.snapshot.label:
        click.echo(f"  label={result.snapshot.label}")
    click.echo(f"  graph={result.snapshot.graph_sha256}")


@snapshot_group.command("list")
@handle_errors
def snapshot_list_cmd() -> None:
    """List snapshots for the current instance."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list_snapshots(instance_id),
        service_list_snapshots,
    )

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
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.fork_snapshot(
            instance_id,
            snapshot_id=snapshot_id,
            root_dir=root_dir,
        ),
        lambda instance: service_fork_snapshot(instance, snapshot_id, root_dir),
    )
    if isinstance(result, contracts.ForkSnapshotResult):
        click.echo(
            f"Forked snapshot {result.snapshot.snapshot_id} into instance {result.instance_id}"
        )
        return
    click.echo(
        f"Forked snapshot {result.snapshot.snapshot_id} into {result.instance.get_root_path()}"
    )


@click.command()
@click.option("--mapping", required=True, help="Ingestion mapping name from config.")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Data file.")
@handle_errors
def ingest(mapping: str, file_path: str) -> None:
    """Ingest data from a file using a named mapping."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.ingest(instance_id, mapping, file_path=file_path),
        lambda instance: service_ingest(instance, mapping, file_path=file_path),
    )

    parts = [f"{result.records_ingested} added"]
    if result.records_updated:
        parts.append(f"{result.records_updated} updated")
    click.echo(f"Ingested {', '.join(parts)} via mapping '{mapping}'.")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")
