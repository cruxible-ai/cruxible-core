from __future__ import annotations

from pathlib import Path

from scripts.render_config_views import DEFAULT_VIEW_ORDER, _update_readme

from cruxible_core.config.loader import load_config_from_string


def test_update_readme_replaces_empty_marker_block(
    tmp_path: Path,
    proposal_workflow_config_yaml: str,
) -> None:
    config = load_config_from_string(proposal_workflow_config_yaml)
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Demo\n\n"
        "<!-- CRUXIBLE:BEGIN ontology -->\n"
        "<!-- CRUXIBLE:END ontology -->\n"
    )

    _update_readme(readme, config, ("ontology",))

    updated = readme.read_text()
    assert "<!-- CRUXIBLE:BEGIN ontology -->" in updated
    assert "<!-- CRUXIBLE:END ontology -->" in updated
    assert "```mermaid" in updated
    assert "Recommended For" in updated
    assert "stroke:#e74c3c" in updated


def test_update_readme_splits_large_sections_into_titled_blocks(
    tmp_path: Path,
    proposal_workflow_config_yaml: str,
) -> None:
    config = load_config_from_string(proposal_workflow_config_yaml)
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Demo\n\n"
        "<!-- CRUXIBLE:BEGIN workflow-steps -->\n"
        "<!-- CRUXIBLE:END workflow-steps -->\n"
        "\n\n"
        "<!-- CRUXIBLE:BEGIN queries -->\n"
        "<!-- CRUXIBLE:END queries -->\n"
    )

    _update_readme(readme, config, ("workflow-steps", "queries"))

    updated = readme.read_text()
    assert "### Propose Campaign Recommendations" in updated
    assert "### Get Campaign Context" in updated
    assert updated.count("```mermaid") == 2


def test_update_readme_default_sections_are_comprehension_views(
    tmp_path: Path,
    proposal_workflow_config_yaml: str,
) -> None:
    config = load_config_from_string(proposal_workflow_config_yaml)
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Demo\n\n"
        "<!-- CRUXIBLE:BEGIN ontology -->\n"
        "<!-- CRUXIBLE:END ontology -->\n\n"
        "<!-- CRUXIBLE:BEGIN workflow-pipeline -->\n"
        "<!-- CRUXIBLE:END workflow-pipeline -->\n\n"
        "<!-- CRUXIBLE:BEGIN workflow-summary -->\n"
        "<!-- CRUXIBLE:END workflow-summary -->\n\n"
        "<!-- CRUXIBLE:BEGIN governance-table -->\n"
        "<!-- CRUXIBLE:END governance-table -->\n\n"
        "<!-- CRUXIBLE:BEGIN query-map -->\n"
        "<!-- CRUXIBLE:END query-map -->\n\n"
        "<!-- CRUXIBLE:BEGIN query-catalog -->\n"
        "<!-- CRUXIBLE:END query-catalog -->\n"
    )

    _update_readme(readme, config, DEFAULT_VIEW_ORDER)

    updated = readme.read_text()
    assert "Recommended For" in updated
    assert "Governed proposal" in updated
    assert "### 1. Propose Campaign Recommendations" in updated
    assert "**Input context**" in updated
    assert "**Result**" in updated
    assert "**Provider source**" in updated
    assert (
        "tests/support/workflow_test_providers.py::campaign_recommendations"
        in updated
    )
    assert (
        "| Relationship | Scope | Signals | Auto-resolve Gate | "
        "Review Policy | Feedback | Outcomes |"
    ) in updated
    assert "query_entity_Campaign" in updated
    assert "### Campaign" in updated
