"""CLI entry point and error handling."""

from __future__ import annotations

import functools
import sys
from typing import Any

import click

from cruxible_core.errors import CoreError


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
def cli() -> None:
    """Cruxible — deterministic decision engine with receipts."""


# Import and register commands after cli group is defined
from cruxible_core.cli.commands import (  # noqa: E402
    add_constraint_cmd,
    add_entity_cmd,
    add_relationship_cmd,
    evaluate,
    explain,
    feedback_cmd,
    find_candidates_cmd,
    get_entity_cmd,
    get_relationship_cmd,
    ingest,
    init,
    list_group,
    outcome_cmd,
    prompt_group,
    query,
    sample,
    schema,
    validate,
)

cli.add_command(init)  # type: ignore[has-type]
cli.add_command(validate)  # type: ignore[has-type]
cli.add_command(ingest)  # type: ignore[has-type]
cli.add_command(query)  # type: ignore[has-type]
cli.add_command(explain)  # type: ignore[has-type]
cli.add_command(feedback_cmd, "feedback")  # type: ignore[has-type]
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
cli.add_command(prompt_group, "prompt")  # type: ignore[has-type]
