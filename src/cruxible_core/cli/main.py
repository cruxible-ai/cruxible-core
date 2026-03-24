"""CLI entry point and error handling."""

from __future__ import annotations

import functools
import sys
from typing import Any

import click

from cruxible_core.errors import ConfigError, CoreError
from cruxible_core.server.config import resolve_server_settings


def handle_errors(f: Any) -> Any:
    """Decorator that catches CoreError and prints a friendly message."""

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return f(*args, **kwargs)
        except CoreError as e:
            click.secho(f"Error: {e}", fg="red", err=True)
            sys.exit(1)

    return wrapper


@click.group()
@click.version_option(package_name="cruxible-core")
@click.option("--server-url", default=None, help="Remote Cruxible server base URL.")
@click.option(
    "--server-socket",
    default=None,
    help="Local Cruxible server Unix socket path.",
)
@click.option(
    "--instance-id",
    default=None,
    envvar="CRUXIBLE_INSTANCE_ID",
    help="Opaque server-mode instance ID.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    server_url: str | None,
    server_socket: str | None,
    instance_id: str | None,
) -> None:
    """Cruxible — deterministic decision engine with receipts."""
    try:
        settings = resolve_server_settings(server_url=server_url, server_socket=server_socket)
    except ConfigError as exc:
        raise click.UsageError(str(exc)) from exc

    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "server_url": settings.server_url,
            "server_socket": settings.server_socket,
            "instance_id": instance_id,
            "require_server": settings.require_server,
        }
    )


# Import and register commands after cli group is defined
from cruxible_core.cli.commands import (  # noqa: E402
    add_constraint_cmd,
    add_entity_cmd,
    add_relationship_cmd,
    apply_cmd,
    entity_proposal_group,
    evaluate,
    explain,
    export_group,
    feedback_batch_cmd,
    feedback_cmd,
    find_candidates_cmd,
    fork_cmd,
    get_entity_cmd,
    get_relationship_cmd,
    group_group,
    ingest,
    init,
    list_group,
    lock_cmd,
    outcome_cmd,
    plan_cmd,
    propose_cmd,
    query,
    run_cmd,
    sample,
    schema,
    snapshot_group,
    test_cmd,
    validate,
)

cli.add_command(init)  # type: ignore[has-type]
cli.add_command(validate)  # type: ignore[has-type]
cli.add_command(lock_cmd)  # type: ignore[has-type]
cli.add_command(plan_cmd)  # type: ignore[has-type]
cli.add_command(run_cmd)  # type: ignore[has-type]
cli.add_command(apply_cmd)  # type: ignore[has-type]
cli.add_command(test_cmd)  # type: ignore[has-type]
cli.add_command(propose_cmd)  # type: ignore[has-type]
cli.add_command(snapshot_group, "snapshot")  # type: ignore[has-type]
cli.add_command(fork_cmd, "fork")  # type: ignore[has-type]
cli.add_command(ingest)  # type: ignore[has-type]
cli.add_command(query)  # type: ignore[has-type]
cli.add_command(explain)  # type: ignore[has-type]
cli.add_command(feedback_cmd, "feedback")  # type: ignore[has-type]
cli.add_command(feedback_batch_cmd, "feedback-batch")  # type: ignore[has-type]
cli.add_command(outcome_cmd, "outcome")  # type: ignore[has-type]
cli.add_command(list_group, "list")  # type: ignore[has-type]
cli.add_command(find_candidates_cmd, "find-candidates")  # type: ignore[has-type]
cli.add_command(schema)  # type: ignore[has-type]
cli.add_command(sample)  # type: ignore[has-type]
cli.add_command(evaluate)  # type: ignore[has-type]
cli.add_command(get_entity_cmd, "get-entity")  # type: ignore[has-type]
cli.add_command(get_relationship_cmd, "get-relationship")  # type: ignore[has-type]
cli.add_command(add_entity_cmd, "add-entity")  # type: ignore[has-type]
cli.add_command(add_relationship_cmd, "add-relationship")  # type: ignore[has-type]
cli.add_command(add_constraint_cmd, "add-constraint")  # type: ignore[has-type]
cli.add_command(export_group, "export")  # type: ignore[has-type]
cli.add_command(entity_proposal_group, "entity-proposal")  # type: ignore[has-type]
cli.add_command(group_group, "group")  # type: ignore[has-type]
