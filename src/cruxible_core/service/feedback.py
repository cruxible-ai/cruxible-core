"""Feedback and outcome service functions."""

from __future__ import annotations

from typing import Any, Literal

from cruxible_core.errors import (
    ConfigError,
    CoreError,
    DataValidationError,
    EdgeAmbiguityError,
    MutationError,
    ReceiptNotFoundError,
)
from cruxible_core.feedback.applier import apply_feedback
from cruxible_core.feedback.types import EdgeTarget, FeedbackRecord, OutcomeRecord
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.service._helpers import _persist_receipt, _save_graph
from cruxible_core.service.types import FeedbackServiceResult, OutcomeServiceResult


def service_feedback(
    instance: InstanceProtocol,
    receipt_id: str,
    action: Literal["approve", "reject", "correct", "flag"],
    source: Literal["human", "ai_review", "system"],
    target: EdgeTarget,
    reason: str = "",
    corrections: dict[str, Any] | None = None,
    group_override: bool = False,
) -> FeedbackServiceResult:
    """Record feedback on an edge.

    Validates corrections, checks receipt existence, persists feedback,
    and applies to the graph. If group_override=True, stamps the edge
    with group_override property after applying feedback.
    """
    _VALID_ACTIONS = ("approve", "reject", "correct", "flag")
    if action not in _VALID_ACTIONS:
        raise ConfigError(f"Invalid action '{action}'. Use: {', '.join(_VALID_ACTIONS)}")

    _VALID_SOURCES = ("human", "ai_review", "system")
    if source not in _VALID_SOURCES:
        raise ConfigError(f"Invalid source '{source}'. Use: {', '.join(_VALID_SOURCES)}")

    if corrections is not None and not isinstance(corrections, dict):
        raise ConfigError("corrections must be an object")

    # Fail-fast: validate confidence in corrections BEFORE persisting
    if corrections is not None:
        confidence = corrections.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise DataValidationError(
                    f"corrections.confidence must be numeric (float). "
                    f"Got {confidence!r}. "
                    f"Suggested: low=0.3, medium=0.5, high=0.7, very_high=0.9"
                )
        # Strip _provenance from corrections (prevent spoofing in audit trail)
        corrections = {k: v for k, v in corrections.items() if k != "_provenance"}

    graph = instance.load_graph()

    # Preflight check for group_override
    if group_override:
        # Verify edge exists
        rel = graph.get_relationship(
            target.from_type,
            target.from_id,
            target.to_type,
            target.to_id,
            target.relationship,
            edge_key=target.edge_key,
        )
        if rel is None:
            raise ConfigError("group_override requires the edge to exist in the graph")
        # Check edge ambiguity
        if target.edge_key is None:
            count = graph.relationship_count_between(
                target.from_type,
                target.from_id,
                target.to_type,
                target.to_id,
                target.relationship,
            )
            if count > 1:
                raise EdgeAmbiguityError(
                    from_type=target.from_type,
                    from_id=target.from_id,
                    to_type=target.to_type,
                    to_id=target.to_id,
                    relationship=target.relationship,
                )

    receipt_store = instance.get_receipt_store()

    try:
        if receipt_store.get_receipt(receipt_id) is None:
            raise ReceiptNotFoundError(receipt_id)
    finally:
        receipt_store.close()

    record = FeedbackRecord(
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        corrections=corrections or {},
    )

    target_str = (
        f"{target.from_type}:{target.from_id}:{target.relationship}:{target.to_type}:{target.to_id}"
    )
    builder = ReceiptBuilder(
        operation_type="feedback",
        parameters={"receipt_id": receipt_id, "action": action, "source": source},
    )

    result: FeedbackServiceResult | None = None
    _exc: CoreError | None = None
    feedback_store = instance.get_feedback_store()
    try:
        feedback_store.save_feedback(record)

        applied = apply_feedback(graph, record)
        builder.record_feedback_applied(target_str, action, applied)

        # Stamp group_override on the edge after applying feedback
        if group_override:
            graph.update_edge_properties(
                target.from_type,
                target.from_id,
                target.to_type,
                target.to_id,
                target.relationship,
                {"group_override": True},
                edge_key=target.edge_key,
            )

        _save_graph(instance, graph)
        builder.mark_committed()
        result = FeedbackServiceResult(feedback_id=record.feedback_id, applied=applied)
    except CoreError as e:
        _exc = e
        raise
    except Exception as exc:
        _exc = MutationError(f"Unexpected failure: {exc}")
        raise _exc from exc
    finally:
        feedback_store.close()
        receipt = builder.build()
        if _persist_receipt(instance, receipt):
            if _exc is not None:
                _exc.mutation_receipt_id = receipt.receipt_id
            elif result is not None:
                result.receipt_id = receipt.receipt_id
    return result  # type: ignore[return-value]


def service_outcome(
    instance: InstanceProtocol,
    receipt_id: str,
    outcome: Literal["correct", "incorrect", "partial", "unknown"],
    detail: dict[str, Any] | None = None,
) -> OutcomeServiceResult:
    """Record an outcome for a query.

    Validates receipt existence, persists the outcome record.
    """
    _VALID_OUTCOMES = ("correct", "incorrect", "partial", "unknown")
    if outcome not in _VALID_OUTCOMES:
        raise ConfigError(f"Invalid outcome '{outcome}'. Use: {', '.join(_VALID_OUTCOMES)}")

    if detail is not None and not isinstance(detail, dict):
        raise ConfigError("detail must be an object")

    receipt_store = instance.get_receipt_store()
    try:
        if receipt_store.get_receipt(receipt_id) is None:
            raise ReceiptNotFoundError(receipt_id)
    finally:
        receipt_store.close()

    record = OutcomeRecord(
        receipt_id=receipt_id,
        outcome=outcome,
        detail=detail or {},
    )
    feedback_store = instance.get_feedback_store()
    try:
        feedback_store.save_outcome(record)
    finally:
        feedback_store.close()

    return OutcomeServiceResult(outcome_id=record.outcome_id)
