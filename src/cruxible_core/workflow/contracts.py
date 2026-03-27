"""Contract validation helpers for workflow/provider payloads."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable

from cruxible_core.config.schema import CoreConfig, PropertySchema
from cruxible_core.errors import ConfigError, QueryExecutionError


def validate_contract_payload(
    config: CoreConfig,
    contract_name: str,
    payload: dict[str, Any],
    *,
    subject: str,
    error_factory: Callable[[str], Exception],
    empty_payload_hint: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize a payload against a named contract."""
    contract = config.contracts.get(contract_name)
    if contract is None:
        raise ConfigError(f"Contract '{contract_name}' not found for {subject}")

    required_missing: list[str] = []
    errors: list[str] = []
    normalized: dict[str, Any] = {}

    for field_name, field_schema in contract.fields.items():
        if field_name not in payload:
            if field_schema.default is not None:
                normalized[field_name] = field_schema.default
                continue
            if field_schema.optional:
                continue
            required_missing.append(field_name)
            continue
        try:
            normalized[field_name] = _normalize_value(payload[field_name], field_schema)
        except ValueError as exc:
            errors.append(f"field '{field_name}': {exc}")

    extra = sorted(set(payload.keys()) - set(contract.fields.keys()))
    for field_name in extra:
        errors.append(f"unexpected field '{field_name}'")

    if not payload and required_missing:
        missing = ", ".join(f"'{field_name}'" for field_name in required_missing)
        message = f"{subject} failed contract '{contract_name}': empty input payload provided"
        message = f"{message}; required fields: {missing}"
        if empty_payload_hint:
            message = f"{message}. {empty_payload_hint}"
        raise error_factory(message)

    for field_name in required_missing:
        errors.append(f"missing required field '{field_name}'")

    if errors:
        raise error_factory(f"{subject} failed contract '{contract_name}': {'; '.join(errors)}")

    return normalized


def query_execution_error(message: str) -> QueryExecutionError:
    """Factory used by runtime validation helpers."""
    return QueryExecutionError(message)


def _normalize_value(value: Any, schema: PropertySchema) -> Any:
    """Normalize a value to the property-schema contract type."""
    type_name = schema.type

    if value is None:
        if schema.optional:
            return None
        raise ValueError("value may not be null")

    if schema.enum is not None and value not in schema.enum:
        allowed = ", ".join(str(item) for item in schema.enum)
        raise ValueError(f"value must be one of: {allowed}")

    if type_name == "string":
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value

    if type_name == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be an int")
        return value

    if type_name == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a float")
        return float(value)

    if type_name == "bool":
        if not isinstance(value, bool):
            raise ValueError("must be a bool")
        return value

    if type_name == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("must be an ISO date string (YYYY-MM-DD)") from exc
            return value
        raise ValueError("must be an ISO date string")

    if type_name == "json":
        try:
            json.dumps(value, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("must be JSON-serializable") from exc
        return value

    raise ValueError(f"unsupported contract type '{type_name}'")
