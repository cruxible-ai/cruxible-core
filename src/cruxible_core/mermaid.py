"""Shared Mermaid rendering helpers."""

from __future__ import annotations

import re


def escape_mermaid_label(value: str) -> str:
    """Escape user-controlled text for use inside a Mermaid quoted label."""
    return value.replace('"', '\\"').replace("\n", "<br/>")


def mermaid_id(raw: str) -> str:
    """Return a Mermaid-safe identifier."""
    return re.sub(r"[^A-Za-z0-9_]", "_", raw)

