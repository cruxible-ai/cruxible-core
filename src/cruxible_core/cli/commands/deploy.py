"""Remote deploy/bootstrap and runtime-key CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from cruxible_client import CruxibleClient, contracts
from cruxible_core.cli.commands._common import (
    _emit_json,
    _get_client,
    _remember_server_context,
    _root_ctx_obj,
    json_option,
)
from cruxible_core.deploy import build_deploy_bundle
from cruxible_core.errors import ConfigError


def _client_from_context(*, token: str | None = None) -> CruxibleClient:
    obj = _root_ctx_obj()
    server_url = obj.get("server_url")
    server_socket = obj.get("server_socket")
    if not server_url and not server_socket:
        raise click.UsageError("Server mode is required for deploy commands")
    return CruxibleClient(base_url=server_url, socket_path=server_socket, token=token)


@click.group("deploy")
def deploy_group() -> None:
    """Remote deploy/bootstrap operations."""


@deploy_group.command("init")
@click.option("--system-id", required=True, help="Cloud/system identifier for the deployment.")
@click.option(
    "--root-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Workspace or instance root used to build the deploy bundle.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Config file to bundle for plain deployments. Defaults to <root-dir>/config.yaml.",
)
@click.option("--instance-slug", default=None, help="Optional deployment instance slug.")
@click.option(
    "--bootstrap-token",
    envvar="CRUXIBLE_BOOTSTRAP_TOKEN",
    required=True,
    help="Short-lived bootstrap JWT issued by the control plane.",
)
@json_option
def deploy_init(
    system_id: str,
    root_dir: Path,
    config_path: Path | None,
    instance_slug: str | None,
    bootstrap_token: str,
    output_json: bool,
) -> None:
    """Build a self-contained deploy bundle, upload it, and bootstrap the remote instance."""
    bundle = build_deploy_bundle(
        root_dir=root_dir,
        config_path=str(config_path) if config_path is not None else None,
    )
    client = _client_from_context(token=bootstrap_token)
    try:
        upload = client.deploy_upload_bundle(str(bundle.bundle_path))
        result = client.deploy_bootstrap(
            system_id=system_id,
            upload_id=upload.upload_id,
            instance_slug=instance_slug,
        )
    finally:
        client.close()
        bundle.bundle_path.unlink(missing_ok=True)

    if result.instance_id is not None:
        _remember_server_context(instance_id=result.instance_id)

    if output_json:
        _emit_json(result.model_dump(mode="json"))
        return
    click.echo(f"Deploy status: {result.status}")
    if result.server_url:
        click.echo(f"Server URL: {result.server_url}")
    if result.instance_id:
        click.echo(f"Instance ID: {result.instance_id}")
    if result.admin_bearer_token:
        click.echo(f"Admin bearer token: {result.admin_bearer_token}")


@deploy_group.command("status")
@click.option("--system-id", required=True, help="System identifier to inspect.")
@click.option(
    "--bootstrap-token",
    envvar="CRUXIBLE_BOOTSTRAP_TOKEN",
    default=None,
    help="Optional bootstrap token for pre-admin deploy status checks.",
)
@json_option
def deploy_status(system_id: str, bootstrap_token: str | None, output_json: bool) -> None:
    """Read deploy/bootstrap status for a system."""
    client = _client_from_context(token=bootstrap_token) if bootstrap_token else _get_client()
    if client is None:
        raise click.UsageError(
            "Provide an admin runtime bearer token or a bootstrap token to read deploy status."
        )
    result = client.deploy_status(system_id=system_id)
    if output_json:
        _emit_json(result.model_dump(mode="json"))
        return
    click.echo(f"Status: {result.status}")
    if result.instance_id:
        click.echo(f"Instance ID: {result.instance_id}")
    if result.server_url:
        click.echo(f"Server URL: {result.server_url}")


@click.group("keys")
def deploy_keys_group() -> None:
    """Runtime bearer credential management."""


@deploy_keys_group.command("create")
@click.option(
    "--role",
    type=click.Choice(["viewer", "editor", "admin"]),
    required=True,
    help="Role for the new runtime bearer credential.",
)
@click.option("--subject", "subject_label", required=True, help="Human-readable key label.")
@json_option
def deploy_keys_create(role: str, subject_label: str, output_json: bool) -> None:
    client = _get_client()
    if client is None:
        raise click.UsageError("Server mode with an admin bearer token is required.")
    result = client.create_runtime_key(
        role=cast(contracts.RuntimeCredentialRole, role),
        subject_label=subject_label,
    )
    if output_json:
        _emit_json(result.model_dump(mode="json"))
        return
    click.echo(f"Key ID: {result.credential.key_id}")
    click.echo(f"Role: {result.credential.role}")
    click.echo(f"Bearer token: {result.bearer_token}")


@deploy_keys_group.command("list")
@json_option
def deploy_keys_list(output_json: bool) -> None:
    client = _get_client()
    if client is None:
        raise click.UsageError("Server mode with an admin bearer token is required.")
    result = client.list_runtime_keys()
    if output_json:
        _emit_json(result.model_dump(mode="json"))
        return
    if not result.credentials:
        click.echo("No runtime credentials found.")
        return
    for credential in result.credentials:
        revoked = " revoked" if credential.revoked_at else ""
        click.echo(
            f"{credential.key_id} {credential.role} {credential.subject_label}{revoked}"
        )


@deploy_keys_group.command("revoke")
@click.argument("key_id")
@json_option
def deploy_keys_revoke(key_id: str, output_json: bool) -> None:
    client = _get_client()
    if client is None:
        raise click.UsageError("Server mode with an admin bearer token is required.")
    result = client.revoke_runtime_key(key_id)
    if output_json:
        _emit_json(result.model_dump(mode="json"))
        return
    if not result.revoked:
        raise ConfigError(f"Failed to revoke runtime credential '{key_id}'")
    click.echo(f"Revoked: {result.key_id}")


deploy_group.add_command(deploy_keys_group, "keys")
