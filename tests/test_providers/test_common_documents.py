"""Tests for common document providers."""

from __future__ import annotations

from pathlib import Path

from cruxible_core.provider.types import ProviderContext, ResolvedArtifact
from cruxible_core.providers.common.documents import (
    document_to_markdown,
    extract_document_tables,
)


def _context(path: Path | None = None) -> ProviderContext:
    artifact = None
    if path is not None:
        artifact = ResolvedArtifact(
            name="doc",
            kind="file",
            uri=str(path),
            local_path=str(path),
            sha256="sha256:test",
        )
    return ProviderContext(
        workflow_name="wf",
        step_id="step",
        provider_name="provider",
        provider_version="1.0.0",
        artifact=artifact,
    )


def test_document_to_markdown_converts_simple_html(tmp_path: Path) -> None:
    source = tmp_path / "brief.html"
    source.write_text("<h1>Title</h1><p>Hello <strong>world</strong>.</p>")

    payload = document_to_markdown({}, _context(source))

    assert "# Title" in payload["markdown"]
    assert "Hello world." in payload["markdown"]
    assert payload["source"]["media_type"] == "text/html"


def test_extract_document_tables_parses_markdown_tables() -> None:
    markdown = """
Intro

| Product | Price |
| --- | ---: |
| Widget | 12.00 |
| Gizmo | 9.50 |
"""

    payload = extract_document_tables({"markdown": markdown}, _context())

    table = payload["tables"]["table_1"]
    assert table["columns"] == ["product", "price"]
    assert table["rows"][0]["product"] == "Widget"
    assert table["rows"][0]["_source_line"] == 6
    assert payload["diagnostics"] == []
