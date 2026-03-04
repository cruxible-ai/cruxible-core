"""Constraint rule parser shared by config validation and graph evaluation."""

from __future__ import annotations

import re

_TOKEN = r"[\w-]+"
_CONSTRAINT_PATTERN = re.compile(rf"^({_TOKEN})\.FROM\.({_TOKEN})\s*==\s*\1\.TO\.({_TOKEN})$")


def parse_constraint_rule(rule: str) -> tuple[str, str, str] | None:
    """Parse a constraint rule into (relationship, from_property, to_property).

    Returns None if the rule doesn't match the supported syntax.
    """
    match = _CONSTRAINT_PATTERN.match(rule)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)
