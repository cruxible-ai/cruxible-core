"""CLI command for deterministic wiki rendering."""

from __future__ import annotations

from pathlib import Path

import click

from cruxible_core.cli.commands import _common
from cruxible_core.cli.main import handle_errors
from cruxible_core.wiki import WikiOptions, render_wiki, write_wiki_pages
from cruxible_core.wiki.generator import SubjectRef, parse_subject_ref


def _parse_focus_values(values: tuple[str, ...]) -> tuple[SubjectRef, ...]:
    refs = []
    for raw in values:
        try:
            refs.append(parse_subject_ref(raw))
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--focus") from exc
    return tuple(refs)


@click.command("render-wiki")
@click.option(
    "--output",
    "output_dir",
    required=True,
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="Directory to write the rendered wiki into.",
)
@click.option(
    "--focus",
    "focus_values",
    multiple=True,
    help="Render a focused wiki around EntityType:EntityId.",
)
@click.option(
    "--include-type",
    "include_types",
    multiple=True,
    help="Limit rendered subject pages to specific entity types.",
)
@click.option(
    "--all-subjects",
    is_flag=True,
    default=False,
    help="Render all subjects instead of only evidence-backed subjects.",
)
@handle_errors
def render_wiki_cmd(
    output_dir: Path,
    focus_values: tuple[str, ...],
    include_types: tuple[str, ...],
    all_subjects: bool,
) -> None:
    """Render a deterministic Markdown wiki from the current world state."""
    focus = _parse_focus_values(focus_values)
    client = _common._get_client()
    if client is not None:
        result = client.render_wiki(
            _common._require_instance_id(),
            focus=[ref.key for ref in focus],
            include_types=list(include_types),
            all_subjects=all_subjects,
        )
        pages = {Path(page.path): page.content for page in result.pages}
        written = write_wiki_pages(output_dir, pages)
        click.echo(f"Rendered {len(written)} files into {output_dir}")
        return

    instance = _common._require_local_instance("render-wiki")
    options = WikiOptions(
        output_dir=output_dir,
        focus=focus,
        include_types=tuple(include_types),
        all_subjects=all_subjects,
    )
    written = render_wiki(instance, options)
    click.echo(f"Rendered {len(written)} files into {output_dir}")
