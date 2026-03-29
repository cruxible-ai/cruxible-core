"""CLI commands for published world-model releases and pullable forks."""

from __future__ import annotations

import click

from cruxible_client import contracts
from cruxible_core.cli.commands._common import _dispatch_cli, _dispatch_cli_instance
from cruxible_core.cli.main import handle_errors
from cruxible_core.service import (
    service_fork_model,
    service_model_status,
    service_publish_model,
    service_pull_model_apply,
    service_pull_model_preview,
)


@click.group("model")
def model_group() -> None:
    """Publish immutable world-model releases and manage pullable forks."""


@model_group.command("publish")
@click.option("--transport-ref", required=True, help="Transport ref, e.g. file://... or oci://...")
@click.option("--model-id", required=True, help="Stable published model identifier.")
@click.option("--release-id", required=True, help="User-supplied release identifier.")
@click.option(
    "--compatibility",
    type=click.Choice(["data_only", "additive_schema", "breaking"]),
    default="data_only",
    show_default=True,
    help="Compatibility classification for the published release.",
)
@handle_errors
def model_publish_cmd(
    transport_ref: str,
    model_id: str,
    release_id: str,
    compatibility: str,
) -> None:
    """Publish the current root world-model instance as an immutable release bundle."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.model_publish(
            instance_id,
            transport_ref=transport_ref,
            model_id=model_id,
            release_id=release_id,
            compatibility=compatibility,
        ),
        lambda instance: service_publish_model(
            instance,
            transport_ref=transport_ref,
            model_id=model_id,
            release_id=release_id,
            compatibility=compatibility,
        ),
    )
    click.echo(f"Published {result.manifest.model_id}:{result.manifest.release_id}")
    click.echo(f"  snapshot={result.manifest.snapshot_id}")
    click.echo(f"  compatibility={result.manifest.compatibility}")


@model_group.command("fork")
@click.option("--transport-ref", required=True, help="Transport ref, e.g. file://... or oci://...")
@click.option("--root-dir", required=True, help="Root directory for the new local fork.")
@handle_errors
def model_fork_cmd(transport_ref: str, root_dir: str) -> None:
    """Create a new local fork instance from a published model release."""
    result = _dispatch_cli(
        lambda client: client.model_fork(transport_ref=transport_ref, root_dir=root_dir),
        lambda: service_fork_model(transport_ref=transport_ref, root_dir=root_dir),
    )
    instance_id = result.instance_id if isinstance(result, contracts.ModelForkResult) else str(
        result.instance.get_root_path()
    )
    click.echo(f"Forked {result.manifest.model_id}:{result.manifest.release_id}")
    click.echo(f"Instance ID: {instance_id}")


@model_group.command("status")
@handle_errors
def model_status_cmd() -> None:
    """Show upstream tracking metadata for the current instance."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.model_status(instance_id),
        service_model_status,
    )
    if result.upstream is None:
        click.echo("This instance is not tracking an upstream published model.")
        return
    click.echo(f"Model: {result.upstream.model_id}")
    click.echo(f"Release: {result.upstream.release_id}")
    click.echo(f"Transport: {result.upstream.transport_ref}")
    click.echo(f"Snapshot: {result.upstream.snapshot_id}")


@model_group.command("pull-preview")
@handle_errors
def model_pull_preview_cmd() -> None:
    """Preview pulling a newer upstream release into the current fork."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.model_pull_preview(instance_id),
        service_pull_model_preview,
    )
    click.echo(f"Current release: {result.current_release_id or '(none)'}")
    click.echo(f"Target release: {result.target_release_id}")
    click.echo(f"Compatibility: {result.compatibility}")
    click.echo(f"Apply digest: {result.apply_digest}")
    click.echo(
        f"Upstream delta: entities={result.upstream_entity_delta:+d} "
        f"edges={result.upstream_edge_delta:+d}"
    )
    if result.lock_changed:
        click.echo("Lock will change.")
    for warning in result.warnings:
        click.secho(f"Warning: {warning}", fg="yellow")
    for conflict in result.conflicts:
        click.secho(f"Conflict: {conflict}", fg="red")


@model_group.command("pull-apply")
@click.option("--apply-digest", required=True, help="Apply digest returned by pull-preview.")
@handle_errors
def model_pull_apply_cmd(apply_digest: str) -> None:
    """Apply a previewed upstream release into the current fork."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.model_pull_apply(
            instance_id,
            expected_apply_digest=apply_digest,
        ),
        lambda instance: service_pull_model_apply(instance, expected_apply_digest=apply_digest),
    )
    click.echo(f"Pulled release {result.release_id}")
    click.echo(f"Pre-pull snapshot: {result.pre_pull_snapshot_id}")
