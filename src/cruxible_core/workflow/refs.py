"""Reference resolution for workflow input and step outputs."""

from __future__ import annotations

import re
from typing import Any

from cruxible_core.errors import QueryExecutionError

_SEGMENT_RE = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


def preview_value(value: Any, input_payload: dict[str, Any]) -> Any:
    """Resolve only $input refs for plan preview output."""
    if isinstance(value, str) and value.startswith("$input."):
        return _extract_path(input_payload, value[len("$input.") :], value)
    if isinstance(value, dict):
        return {k: preview_value(v, input_payload) for k, v in value.items()}
    if isinstance(value, list):
        return [preview_value(v, input_payload) for v in value]
    return value


def resolve_value(
    value: Any,
    input_payload: dict[str, Any],
    step_outputs: dict[str, Any],
    *,
    item_payload: Any | None = None,
    allow_item: bool = False,
) -> Any:
    """Resolve $input and $steps refs during workflow execution."""
    if isinstance(value, str):
        if value == "$input":
            return input_payload
        if value.startswith("$input."):
            return _extract_path(input_payload, value[len("$input.") :], value)
        if value == "$item":
            if allow_item and item_payload is not None:
                return item_payload
            raise QueryExecutionError(f"Unsupported workflow reference '{value}'")
        if value.startswith("$item."):
            if allow_item and item_payload is not None:
                return _extract_path(item_payload, value[len("$item.") :], value)
            raise QueryExecutionError(f"Unsupported workflow reference '{value}'")
        if value.startswith("$steps."):
            ref = value[len("$steps.") :]
            alias, _, remainder = ref.partition(".")
            if alias not in step_outputs:
                raise QueryExecutionError(
                    f"Unknown workflow step alias '{alias}' in reference '{value}'"
                )
            target = step_outputs[alias]
            if not remainder:
                return target
            return _extract_path(target, remainder, value)
        return value

    if isinstance(value, dict):
        return {
            k: resolve_value(
                v,
                input_payload,
                step_outputs,
                item_payload=item_payload,
                allow_item=allow_item,
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_value(
                v,
                input_payload,
                step_outputs,
                item_payload=item_payload,
                allow_item=allow_item,
            )
            for v in value
        ]
    return value


def _extract_path(root: Any, path: str, original_ref: str) -> Any:
    current = root
    for match in _SEGMENT_RE.finditer(path):
        key, index = match.groups()
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                raise QueryExecutionError(
                    f"Reference '{original_ref}' could not resolve path '{path}'"
                )
            current = current[key]
            continue
        assert index is not None
        if not isinstance(current, list):
            raise QueryExecutionError(
                f"Reference '{original_ref}' expected a list before '[{index}]'"
            )
        idx = int(index)
        try:
            current = current[idx]
        except IndexError as exc:
            raise QueryExecutionError(
                f"Reference '{original_ref}' index [{idx}] is out of range"
            ) from exc
    return current
