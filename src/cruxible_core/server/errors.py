"""Serialize CoreError instances across the HTTP boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cruxible_core.errors import (
    ConfigError,
    ConstraintViolationError,
    CoreError,
    DataValidationError,
    EdgeAmbiguityError,
    EntityNotFoundError,
    EntityProposalNotFoundError,
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


class ErrorResponse(BaseModel):
    """Structured error payload returned by the HTTP server."""

    error_type: str
    message: str
    errors: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    mutation_receipt_id: str | None = None


def _message_for_error(exc: CoreError) -> str:
    if exc.args:
        return str(exc.args[0])
    return exc.__class__.__name__


def _status_for_error(exc: CoreError) -> int:
    if isinstance(exc, (ConfigError, DataValidationError, QueryExecutionError, IngestionError)):
        return 400
    if isinstance(exc, PermissionDeniedError):
        return 403
    if isinstance(
        exc,
        (
            EntityTypeNotFoundError,
            RelationshipNotFoundError,
            QueryNotFoundError,
            EntityNotFoundError,
            EntityProposalNotFoundError,
            ReceiptNotFoundError,
            OutcomeNotFoundError,
            InstanceNotFoundError,
            GroupNotFoundError,
        ),
    ):
        return 404
    if isinstance(exc, EdgeAmbiguityError):
        return 409
    if isinstance(exc, ConstraintViolationError):
        return 422
    if isinstance(exc, MutationError):
        return 500
    return 500


def error_to_response(exc: CoreError) -> tuple[int, ErrorResponse]:
    """Convert a CoreError into an HTTP status code and structured payload."""
    context: dict[str, Any] = {}
    errors: list[str] = []

    if isinstance(exc, ConfigError | DataValidationError):
        errors = list(exc.errors)
    if isinstance(exc, ConstraintViolationError):
        context["violations"] = list(exc.violations)
    if isinstance(exc, PermissionDeniedError):
        context["tool_name"] = exc.tool_name
        context["current_mode"] = exc.current_mode
        context["required_mode"] = exc.required_mode
    if isinstance(exc, EntityTypeNotFoundError):
        context["entity_type"] = exc.entity_type
    if isinstance(exc, RelationshipNotFoundError):
        context["relationship_name"] = exc.relationship_name
    if isinstance(exc, QueryNotFoundError):
        context["query_name"] = exc.query_name
    if isinstance(exc, EntityNotFoundError):
        context["entity_type"] = exc.entity_type
        context["entity_id"] = exc.entity_id
    if isinstance(exc, EntityProposalNotFoundError):
        context["proposal_id"] = exc.proposal_id
    if isinstance(exc, EdgeAmbiguityError):
        context["from_type"] = exc.from_type
        context["from_id"] = exc.from_id
        context["to_type"] = exc.to_type
        context["to_id"] = exc.to_id
        context["relationship"] = exc.relationship
    if isinstance(exc, ReceiptNotFoundError | OutcomeNotFoundError):
        context["receipt_id"] = exc.receipt_id
    if isinstance(exc, InstanceNotFoundError):
        context["instance_id"] = exc.instance_id
    if isinstance(exc, GroupNotFoundError):
        context["group_id"] = exc.group_id

    body = ErrorResponse(
        error_type=exc.__class__.__name__,
        message=_message_for_error(exc),
        errors=errors,
        context=context,
        mutation_receipt_id=exc.mutation_receipt_id,
    )
    return _status_for_error(exc), body


def response_to_error(_status: int, body: ErrorResponse) -> CoreError:
    """Reconstruct a CoreError from an HTTP error response."""
    context = body.context

    if body.error_type == "ConfigError":
        exc = ConfigError(body.message, errors=body.errors)
    elif body.error_type == "DataValidationError":
        exc = DataValidationError(body.message, errors=body.errors)
    elif body.error_type == "ConstraintViolationError":
        exc = ConstraintViolationError(body.message, violations=context.get("violations", []))
    elif body.error_type == "PermissionDeniedError":
        exc = PermissionDeniedError(
            context.get("tool_name", "unknown"),
            context.get("current_mode", "unknown"),
            context.get("required_mode", "unknown"),
        )
    elif body.error_type == "EntityTypeNotFoundError":
        exc = EntityTypeNotFoundError(context.get("entity_type", body.message))
    elif body.error_type == "RelationshipNotFoundError":
        exc = RelationshipNotFoundError(context.get("relationship_name", body.message))
    elif body.error_type == "QueryNotFoundError":
        exc = QueryNotFoundError(context.get("query_name", body.message))
    elif body.error_type == "EntityNotFoundError":
        exc = EntityNotFoundError(
            context.get("entity_type", "unknown"),
            context.get("entity_id", "unknown"),
        )
    elif body.error_type == "EntityProposalNotFoundError":
        exc = EntityProposalNotFoundError(context.get("proposal_id", "unknown"))
    elif body.error_type == "EdgeAmbiguityError":
        exc = EdgeAmbiguityError(
            from_type=context.get("from_type", "unknown"),
            from_id=context.get("from_id", "unknown"),
            to_type=context.get("to_type", "unknown"),
            to_id=context.get("to_id", "unknown"),
            relationship=context.get("relationship", "unknown"),
        )
    elif body.error_type == "ReceiptNotFoundError":
        exc = ReceiptNotFoundError(context.get("receipt_id", "unknown"))
    elif body.error_type == "OutcomeNotFoundError":
        exc = OutcomeNotFoundError(context.get("receipt_id", "unknown"))
    elif body.error_type == "InstanceNotFoundError":
        exc = InstanceNotFoundError(context.get("instance_id", "unknown"))
    elif body.error_type == "GroupNotFoundError":
        exc = GroupNotFoundError(context.get("group_id", "unknown"))
    elif body.error_type == "QueryExecutionError":
        exc = QueryExecutionError(body.message)
    elif body.error_type == "IngestionError":
        exc = IngestionError(body.message)
    elif body.error_type == "MutationError":
        exc = MutationError(body.message)
    else:
        exc = CoreError(body.message)

    exc.mutation_receipt_id = body.mutation_receipt_id
    return exc
