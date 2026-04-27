"""Render canonical Cruxible config diagrams from a YAML config.

This is intentionally a thin wrapper around cruxible_core.canonical_views so
README drafts and agent harnesses exercise the same renderers as the CLI.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cruxible_core.canonical_views import (
    build_governance_view,
    build_ontology_view,
    build_overview_view,
    build_query_view,
    build_workflow_view,
    render_governed_relationship_table_markdown,
    render_ontology_mermaid,
    render_overview_markdown,
    render_query_catalog_markdown,
    render_query_map_mermaid,
    render_query_mermaid,
    render_query_mermaid_blocks,
    render_workflow_dependency_mermaid,
    render_workflow_mermaid,
    render_workflow_pipeline_mermaid,
    render_workflow_steps_mermaid,
    render_workflow_steps_mermaid_blocks,
    render_workflow_summary_markdown,
    render_workflow_table_markdown,
)
from cruxible_core.config.composer import compose_config_sequence, resolve_config_layers
from cruxible_core.config.loader import load_config
from cruxible_core.config.schema import CoreConfig


@dataclass(frozen=True)
class ViewSpec:
    key: str
    title: str
    render: Callable[[CoreConfig], str]
    fenced: bool = True
    render_readme: Callable[[CoreConfig], str] | None = None


def _render_ontology(config: CoreConfig) -> str:
    return render_ontology_mermaid(build_ontology_view(config))


def _render_workflow_story(config: CoreConfig) -> str:
    return render_workflow_mermaid(build_workflow_view(config))


def _render_workflow_pipeline(config: CoreConfig) -> str:
    return render_workflow_pipeline_mermaid(build_workflow_view(config))


def _render_workflow_summary(config: CoreConfig) -> str:
    return render_workflow_summary_markdown(build_workflow_view(config))


def _render_workflow_table(config: CoreConfig) -> str:
    return render_workflow_table_markdown(build_workflow_view(config))


def _render_governance_table(config: CoreConfig) -> str:
    return render_governed_relationship_table_markdown(config)


def _render_workflow_steps(config: CoreConfig) -> str:
    return render_workflow_steps_mermaid(build_workflow_view(config))


def _render_workflow_steps_readme(config: CoreConfig) -> str:
    blocks = render_workflow_steps_mermaid_blocks(build_workflow_view(config))
    return _render_titled_mermaid_blocks(blocks)


def _render_workflow_dependencies(config: CoreConfig) -> str:
    return render_workflow_dependency_mermaid(build_workflow_view(config))


def _render_queries(config: CoreConfig) -> str:
    return render_query_mermaid(build_query_view(config, query_infos=[]))


def _render_query_map(config: CoreConfig) -> str:
    return render_query_map_mermaid(build_query_view(config, query_infos=[]))


def _render_query_catalog(config: CoreConfig) -> str:
    return render_query_catalog_markdown(build_query_view(config, query_infos=[]))


def _render_queries_readme(config: CoreConfig) -> str:
    blocks = render_query_mermaid_blocks(build_query_view(config, query_infos=[]))
    return _render_titled_mermaid_blocks(blocks)


def _render_overview(config: CoreConfig) -> str:
    ontology = build_ontology_view(config)
    workflows = build_workflow_view(config)
    queries = build_query_view(config, query_infos=[])
    governance = build_governance_view(
        config,
        pending_groups=[],
        pending_total=0,
        resolutions=[],
        resolution_total=0,
    )
    return render_overview_markdown(
        build_overview_view(
            ontology=ontology,
            workflows=workflows,
            queries=queries,
            governance=governance,
        )
    )


VIEW_SPECS: dict[str, ViewSpec] = {
    "ontology": ViewSpec("ontology", "Ontology", _render_ontology),
    "workflow-story": ViewSpec(
        "workflow-story",
        "Workflow Story",
        _render_workflow_story,
    ),
    "workflow-pipeline": ViewSpec(
        "workflow-pipeline",
        "Workflow Pipeline",
        _render_workflow_pipeline,
    ),
    "workflow-summary": ViewSpec(
        "workflow-summary",
        "Workflow Summary",
        _render_workflow_summary,
        fenced=False,
    ),
    "workflow-table": ViewSpec(
        "workflow-table",
        "Workflow Summary",
        _render_workflow_table,
        fenced=False,
    ),
    "governance-table": ViewSpec(
        "governance-table",
        "Governed Relationships",
        _render_governance_table,
        fenced=False,
    ),
    "workflow-steps": ViewSpec(
        "workflow-steps",
        "Workflow Steps",
        _render_workflow_steps,
        render_readme=_render_workflow_steps_readme,
    ),
    "workflow-dependencies": ViewSpec(
        "workflow-dependencies",
        "Workflow Dependencies",
        _render_workflow_dependencies,
    ),
    "queries": ViewSpec(
        "queries",
        "Query Surface",
        _render_queries,
        render_readme=_render_queries_readme,
    ),
    "query-map": ViewSpec("query-map", "Query Map", _render_query_map),
    "query-catalog": ViewSpec(
        "query-catalog",
        "Query Catalog",
        _render_query_catalog,
        fenced=False,
    ),
    "overview": ViewSpec("overview", "Config Overview", _render_overview, fenced=False),
}
DEFAULT_VIEW_ORDER = (
    "ontology",
    "workflow-pipeline",
    "workflow-summary",
    "governance-table",
    "query-map",
    "query-catalog",
)
BEGIN_MARKER = "<!-- CRUXIBLE:BEGIN {key} -->"
END_MARKER = "<!-- CRUXIBLE:END {key} -->"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render canonical Mermaid/Markdown views for a Cruxible config."
    )
    parser.add_argument("config", type=Path, help="Path to config.yaml.")
    parser.add_argument(
        "--view",
        choices=("all", *VIEW_SPECS),
        default="all",
        help="View to render. 'all' emits the standard config-drafting diagrams.",
    )
    parser.add_argument(
        "--bare",
        action="store_true",
        help="Emit the raw selected view without Markdown wrapping.",
    )
    parser.add_argument(
        "--update-readme",
        type=Path,
        help="Replace matching CRUXIBLE marker blocks in a README.",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help=(
            "Compose extends overlays as a runtime composed view. This includes inherited "
            "ontology/query surfaces but strips upstream build-only workflows."
        ),
    )
    args = parser.parse_args()

    config = _load_config_for_rendering(args.config, runtime=args.runtime)
    selected_keys = DEFAULT_VIEW_ORDER if args.view == "all" else (args.view,)
    if args.update_readme is not None:
        _update_readme(args.update_readme, config, selected_keys)
        print(f"Updated {args.update_readme}")
        return

    sections = [
        _render_section(
            spec=VIEW_SPECS[key],
            config=config,
            bare=args.bare and args.view != "all",
        )
        for key in selected_keys
    ]

    if args.view == "all" and not args.bare:
        header = f"# Cruxible Config Diagrams\n\nSource: `{args.config}`"
        sections.insert(0, header)

    print("\n\n".join(sections))


def _load_config_for_rendering(config_path: Path, *, runtime: bool = False) -> CoreConfig:
    config = load_config(config_path)
    return compose_config_sequence(
        resolve_config_layers(config, config_path=config_path.resolve()),
        runtime=runtime,
    )


def _update_readme(
    readme_path: Path,
    config: CoreConfig,
    selected_keys: tuple[str, ...],
) -> None:
    text = readme_path.read_text()
    updated = text
    missing_keys: list[str] = []
    for key in selected_keys:
        begin = BEGIN_MARKER.format(key=key)
        end = END_MARKER.format(key=key)
        block = _render_readme_block(spec=VIEW_SPECS[key], config=config)
        pattern = re.compile(
            rf"{re.escape(begin)}\n.*?{re.escape(end)}",
            flags=re.DOTALL,
        )
        replacement = f"{begin}\n{block}\n{end}"
        updated, replacement_count = pattern.subn(replacement, updated)
        if replacement_count == 0:
            missing_keys.append(key)

    if missing_keys:
        missing = ", ".join(missing_keys)
        raise SystemExit(f"Missing README marker block(s): {missing}")

    readme_path.write_text(updated)


def _render_readme_block(*, spec: ViewSpec, config: CoreConfig) -> str:
    if spec.render_readme is not None:
        return spec.render_readme(config)
    body = spec.render(config)
    if not spec.fenced:
        return body
    return f"```mermaid\n{body}\n```"


def _render_titled_mermaid_blocks(blocks: list[tuple[str, str]]) -> str:
    sections: list[str] = []
    for title, mermaid in blocks:
        sections.append(f"### {title}\n\n```mermaid\n{mermaid}\n```")
    return "\n\n".join(sections)


def _render_section(*, spec: ViewSpec, config: CoreConfig, bare: bool) -> str:
    body = spec.render(config)
    if bare:
        return body
    if not spec.fenced:
        return body
    return f"## {spec.title}\n\n```mermaid\n{body}\n```"


if __name__ == "__main__":
    main()
