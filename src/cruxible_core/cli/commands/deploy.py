"""Remote deploy/bootstrap and runtime-key CLI commands."""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

import click

from cruxible_client import CruxibleClient, contracts
from cruxible_client.errors import ConfigError as ClientConfigError
from cruxible_core.cli.commands._common import (
    _emit_json,
    _get_client,
    _remember_server_context,
    _root_ctx_obj,
    json_option,
)
from cruxible_core.cli.context import (
    DeploySessionState,
    clear_deploy_session,
    load_deploy_session,
    save_deploy_session,
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


def _operation_client(
    *,
    operation_id: str,
    bootstrap_token: str | None = None,
) -> tuple[CruxibleClient, bool]:
    session = load_deploy_session(operation_id)
    if session is not None:
        return _client_from_context(token=session.deploy_session_token), True
    if bootstrap_token:
        return _client_from_context(token=bootstrap_token), True
    client = _get_client()
    if client is not None:
        return client, False
    raise click.UsageError(
        "Provide a deploy session, bootstrap token, or admin runtime bearer token."
    )


def _persist_deploy_session(
    *,
    operation_id: str,
    system_id: str,
    deploy_session_token: str | None,
) -> None:
    if not deploy_session_token:
        return
    save_deploy_session(
        DeploySessionState(
            operation_id=operation_id,
            system_id=system_id,
            deploy_session_token=deploy_session_token,
        )
    )


def _print_operation_status(status: contracts.DeployOperationStatus) -> None:
    click.echo(f"Operation: {status.operation_id}")
    click.echo(f"Status: {status.status}")
    if status.phase:
        click.echo(f"Phase: {status.phase}")
    if status.current_workflow:
        click.echo(f"Workflow: {status.current_workflow}")
    if status.current_step_id:
        click.echo(f"Step: {status.current_step_id}")
    if status.current_provider:
        click.echo(f"Provider: {status.current_provider}")
    if status.progress_message:
        click.echo(f"Progress: {status.progress_message}")
    if status.instance_id:
        click.echo(f"Instance ID: {status.instance_id}")
    if status.server_url:
        click.echo(f"Server URL: {status.server_url}")
    if status.failure_reason == "stale_operation_recovery":
        click.echo("Failure reason: stale heartbeat recovery")
    elif status.failure_reason == "server_restart_or_worker_crash":
        click.echo("Failure reason: server restart or worker crash")
    elif status.failure_reason:
        click.echo(f"Failure reason: {status.failure_reason}")
    if status.error_message:
        click.echo(f"Error: {status.error_message}")


def _resume_command(operation_id: str, bootstrap_token: str | None) -> str:
    base = f"cruxible deploy wait --operation-id {operation_id}"
    if bootstrap_token:
        return f"{base} --bootstrap-token <token>"
    return base


def _wait_for_operation(
    *,
    operation_id: str,
    bootstrap_token: str | None,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> tuple[contracts.DeployOperationStatus, contracts.ClaimAdminKeyResult | None]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        client, should_close = _operation_client(
            operation_id=operation_id,
            bootstrap_token=bootstrap_token,
        )
        try:
            status = client.deploy_operation_status(operation_id=operation_id)
            if status.status == "succeeded":
                claimed = _claim_or_recover_admin_key(
                    operation_id=operation_id,
                    bootstrap_token=bootstrap_token,
                    primary_client=client,
                )
                clear_deploy_session(operation_id)
                return status, claimed
            if status.status == "failed":
                return status, None
        finally:
            if should_close:
                client.close()

        if time.monotonic() >= deadline:
            return status, None
        time.sleep(poll_interval_seconds)


def _claim_or_recover_admin_key(
    *,
    operation_id: str,
    bootstrap_token: str | None,
    primary_client: CruxibleClient,
) -> contracts.ClaimAdminKeyResult:
    try:
        return primary_client.claim_deploy_admin_key(operation_id=operation_id)
    except ClientConfigError as exc:
        if "Initial admin key is no longer available" not in str(exc):
            raise
        recovery_client: CruxibleClient | None = None
        should_close = False
        if bootstrap_token:
            recovery_client = _client_from_context(token=bootstrap_token)
            should_close = True
        else:
            recovery_client = _get_client()
        if recovery_client is None:
            raise
        try:
            return recovery_client.recover_deploy_admin_key(operation_id=operation_id)
        finally:
            if should_close:
                recovery_client.close()


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
@click.option(
    "--wait-timeout-seconds",
    type=float,
    default=300.0,
    show_default=True,
    help="How long to poll the async bootstrap before returning resumable instructions.",
)
@click.option(
    "--poll-interval-seconds",
    type=float,
    default=2.0,
    show_default=True,
    help="Polling interval for deploy operation status checks.",
)
@json_option
def deploy_init(
    system_id: str,
    root_dir: Path,
    config_path: Path | None,
    instance_slug: str | None,
    bootstrap_token: str,
    wait_timeout_seconds: float,
    poll_interval_seconds: float,
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
        started = client.deploy_bootstrap_start(
            system_id=system_id,
            upload_id=upload.upload_id,
            instance_slug=instance_slug,
        )
    finally:
        client.close()
        bundle.bundle_path.unlink(missing_ok=True)

    if started.instance_id is not None and started.status == "already_initialized":
        _remember_server_context(instance_id=started.instance_id)
        if output_json:
            _emit_json(started.model_dump(mode="json"))
            return
        click.echo(f"Deploy status: {started.status}")
        if started.server_url:
            click.echo(f"Server URL: {started.server_url}")
        click.echo(f"Instance ID: {started.instance_id}")
        return

    if started.operation_id is None:
        raise click.ClickException("Deploy bootstrap did not return an operation ID")

    _persist_deploy_session(
        operation_id=started.operation_id,
        system_id=system_id,
        deploy_session_token=started.deploy_session_token,
    )

    if started.status == "in_progress" and not output_json:
        click.echo(
            "Deploy operation "
            f"{started.operation_id} is already in progress for system {system_id}."
        )

    status, claimed = _wait_for_operation(
        operation_id=started.operation_id,
        bootstrap_token=bootstrap_token,
        timeout_seconds=wait_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )

    if output_json:
        payload = status.model_dump(mode="json")
        if claimed is not None:
            payload["claimed_admin_key"] = claimed.model_dump(mode="json")
        _emit_json(payload)
        return

    if status.status == "failed":
        _print_operation_status(status)
        raise click.ClickException("Deploy bootstrap failed")

    if claimed is None:
        click.echo(
            f"Deploy operation {started.operation_id} is still running. Resume with:"
        )
        click.echo(f"  {_resume_command(started.operation_id, bootstrap_token)}")
        _print_operation_status(status)
        return

    _remember_server_context(instance_id=claimed.instance_id)
    click.echo("Deploy status: bootstrapped")
    if claimed.server_url:
        click.echo(f"Server URL: {claimed.server_url}")
    click.echo(f"Instance ID: {claimed.instance_id}")
    click.echo(f"Admin bearer token: {claimed.admin_bearer_token}")


@deploy_group.command("wait")
@click.option("--operation-id", required=True, help="Deploy operation identifier to poll.")
@click.option(
    "--bootstrap-token",
    envvar="CRUXIBLE_BOOTSTRAP_TOKEN",
    default=None,
    help="Optional bootstrap token when no persisted deploy session is available.",
)
@click.option(
    "--wait-timeout-seconds",
    type=float,
    default=300.0,
    show_default=True,
    help="How long to poll before returning the current status.",
)
@click.option(
    "--poll-interval-seconds",
    type=float,
    default=2.0,
    show_default=True,
    help="Polling interval for deploy operation status checks.",
)
@json_option
def deploy_wait(
    operation_id: str,
    bootstrap_token: str | None,
    wait_timeout_seconds: float,
    poll_interval_seconds: float,
    output_json: bool,
) -> None:
    """Wait for a deploy operation to finish and claim the initial admin key."""
    status, claimed = _wait_for_operation(
        operation_id=operation_id,
        bootstrap_token=bootstrap_token,
        timeout_seconds=wait_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    if output_json:
        payload = status.model_dump(mode="json")
        if claimed is not None:
            payload["claimed_admin_key"] = claimed.model_dump(mode="json")
        _emit_json(payload)
        return
    if status.status == "failed":
        _print_operation_status(status)
        raise click.ClickException("Deploy bootstrap failed")
    if claimed is None:
        click.echo(f"Deploy operation {operation_id} is still running.")
        _print_operation_status(status)
        return
    _remember_server_context(instance_id=claimed.instance_id)
    click.echo("Deploy status: bootstrapped")
    click.echo(f"Instance ID: {claimed.instance_id}")
    if claimed.server_url:
        click.echo(f"Server URL: {claimed.server_url}")
    click.echo(f"Admin bearer token: {claimed.admin_bearer_token}")


@deploy_group.command("claim-admin-key")
@click.option("--operation-id", required=True, help="Deploy operation identifier to finalize.")
@click.option(
    "--bootstrap-token",
    envvar="CRUXIBLE_BOOTSTRAP_TOKEN",
    default=None,
    help="Optional bootstrap token when no persisted deploy session is available.",
)
@json_option
def deploy_claim_admin_key(
    operation_id: str,
    bootstrap_token: str | None,
    output_json: bool,
) -> None:
    """Claim the one-time initial admin bearer token for a completed deploy."""
    client, should_close = _operation_client(
        operation_id=operation_id,
        bootstrap_token=bootstrap_token,
    )
    try:
        result = _claim_or_recover_admin_key(
            operation_id=operation_id,
            bootstrap_token=bootstrap_token,
            primary_client=client,
        )
    finally:
        if should_close:
            client.close()
    clear_deploy_session(operation_id)
    _remember_server_context(instance_id=result.instance_id)
    if output_json:
        _emit_json(result.model_dump(mode="json"))
        return
    if result.server_url:
        click.echo(f"Server URL: {result.server_url}")
    click.echo(f"Instance ID: {result.instance_id}")
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
    """Read deploy/bootstrap summary status for a system."""
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
