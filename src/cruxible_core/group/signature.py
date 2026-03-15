"""Deterministic group signature hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_group_signature(
    relationship_type: str,
    thesis_facts: dict[str, Any],
) -> str:
    """SHA-256 of relationship_type + canonical JSON of thesis_facts.

    Only thesis_facts is hashed, not analysis_state. This ensures signature
    stability — LLM rationales and varying centroids don't break auto-resolve.
    """
    payload = json.dumps(
        {"relationship_type": relationship_type, "thesis_facts": thesis_facts},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
