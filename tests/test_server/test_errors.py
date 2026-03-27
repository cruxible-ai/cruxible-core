"""Tests for HTTP error serialization."""

from __future__ import annotations

import pytest

from cruxible_core.errors import (
    ConfigError,
    ConstraintViolationError,
    CoreError,
    DataValidationError,
    EdgeAmbiguityError,
    EntityNotFoundError,
    EntityTypeNotFoundError,
    GroupNotFoundError,
    IngestionError,
    InstanceNotFoundError,
    MutationError,
    OutcomeNotFoundError,
    PermissionDeniedError,
    QueryExecutionError,
    QueryNotFoundError,
    ReceiptNotFoundError,
    RelationshipNotFoundError,
)
from cruxible_core.server.errors import ErrorResponse, error_to_response, response_to_error


@pytest.mark.parametrize(
    ("error", "attrs"),
    [
        (
            ConfigError("bad config", errors=["missing relationship"]),
            {"errors": ["missing relationship"]},
        ),
        (
            DataValidationError("bad data", errors=["wrong type"]),
            {"errors": ["wrong type"]},
        ),
        (
            ConstraintViolationError("constraint failed", violations=["mismatch"]),
            {"violations": ["mismatch"]},
        ),
        (
            PermissionDeniedError("cruxible_query", "READ_ONLY", "ADMIN"),
            {
                "tool_name": "cruxible_query",
                "current_mode": "READ_ONLY",
                "required_mode": "ADMIN",
            },
        ),
        (EntityTypeNotFoundError("Vehicle"), {"entity_type": "Vehicle"}),
        (RelationshipNotFoundError("fits"), {"relationship_name": "fits"}),
        (QueryNotFoundError("parts_for_vehicle"), {"query_name": "parts_for_vehicle"}),
        (
            EntityNotFoundError("Vehicle", "V-1"),
            {"entity_type": "Vehicle", "entity_id": "V-1"},
        ),
        (
            EdgeAmbiguityError("Part", "P-1", "Vehicle", "V-1", "fits"),
            {
                "from_type": "Part",
                "from_id": "P-1",
                "to_type": "Vehicle",
                "to_id": "V-1",
                "relationship": "fits",
            },
        ),
        (ReceiptNotFoundError("RCPT-1"), {"receipt_id": "RCPT-1"}),
        (OutcomeNotFoundError("RCPT-2"), {"receipt_id": "RCPT-2"}),
        (InstanceNotFoundError("inst_123"), {"instance_id": "inst_123"}),
        (GroupNotFoundError("GRP-1"), {"group_id": "GRP-1"}),
        (QueryExecutionError("query failed"), {}),
        (IngestionError("ingest failed"), {}),
        (MutationError("mutation failed"), {}),
    ],
)
def test_error_round_trip_preserves_subclass_and_context(
    error: CoreError,
    attrs: dict[str, object],
):
    error.mutation_receipt_id = "RCPT-xyz"

    status, body = error_to_response(error)
    restored = response_to_error(status, body)

    assert type(restored) is type(error)
    assert restored.mutation_receipt_id == "RCPT-xyz"
    for key, value in attrs.items():
        assert getattr(restored, key) == value


def test_unknown_error_type_falls_back_to_core_error():
    restored = response_to_error(
        500,
        ErrorResponse(
            error_type="UnknownCustomError",
            message="boom",
            context={"extra": "ignored"},
        ),
    )

    assert type(restored) is CoreError
    assert str(restored) == "boom"
