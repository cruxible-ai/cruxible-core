"""Feedback and outcome service functions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from cruxible_core.errors import (
    ConfigError,
    DataValidationError,
    EdgeAmbiguityError,
    ReceiptNotFoundError,
)
from cruxible_core.feedback.applier import apply_feedback
from cruxible_core.feedback.types import (
    EdgeTarget,
    FeedbackBatchItem,
    FeedbackRecord,
    OutcomeRecord,
)
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.service._helpers import MutationReceiptContext, _save_graph, mutation_receipt
from cruxible_core.service.types import (
    FeedbackBatchServiceResult,
    FeedbackServiceResult,
    OutcomeServiceResult,
)

_VALID_ACTIONS = ("approve", "reject", "correct", "flag")
_VALID_SOURCES = ("human", "ai_review", "system")


def _normalize_feedback_record(
    *,
    graph,
    receipt_id: str,
    action: Literal["approve", "reject", "correct", "flag"],
    source: Literal["human", "ai_review", "system"],
    target: EdgeTarget,
    reason: str,
    corrections: dict[str, Any] | None,
    group_override: bool,
) -> FeedbackRecord:
    """Validate and normalize one feedback request into a record."""
    if action not in _VALID_ACTIONS:
        raise ConfigError(f"Invalid action '{action}'. Use: {', '.join(_VALID_ACTIONS)}")

    if source not in _VALID_SOURCES:
        raise ConfigError(f"Invalid source '{source}'. Use: {', '.join(_VALID_SOURCES)}")

    if corrections is not None and not isinstance(corrections, dict):
        raise ConfigError("corrections must be an object")

    normalized_corrections = corrections or {}
    confidence = normalized_corrections.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise DataValidationError(
                f"corrections.confidence must be numeric (float). "
                f"Got {confidence!r}. "
                f"Suggested: low=0.3, medium=0.5, high=0.7, very_high=0.9"
            )
    normalized_corrections = {
        key: value for key, value in normalized_corrections.items() if key != "_provenance"
    }

    if group_override:
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

    return FeedbackRecord(
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        corrections=normalized_corrections,
    )


def _ensure_receipts_exist(instance: InstanceProtocol, receipt_ids: Iterable[str]) -> None:
    """Fail if any referenced receipt IDs do not exist."""
    receipt_store = instance.get_receipt_store()
    try:
        for receipt_id in receipt_ids:
            if receipt_store.get_receipt(receipt_id) is None:
                raise ReceiptNotFoundError(receipt_id)
    finally:
        receipt_store.close()


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
    graph = instance.load_graph()
    record = _normalize_feedback_record(
        graph=graph,
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        corrections=corrections,
        group_override=group_override,
    )
    _ensure_receipts_exist(instance, [receipt_id])

    target_str = (
        f"{target.from_type}:{target.from_id}:{target.relationship}:{target.to_type}:{target.to_id}"
    )
    feedback_store = instance.get_feedback_store()
    ctx: MutationReceiptContext[FeedbackServiceResult]
    with mutation_receipt(
        instance,
        "feedback",
        {"receipt_id": receipt_id, "action": action, "source": source},
        store=feedback_store,
    ) as ctx:
        assert ctx.builder is not None
        feedback_store.save_feedback(record)

        applied = apply_feedback(graph, record)
        ctx.builder.record_feedback_applied(target_str, action, applied)

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
        ctx.set_result(FeedbackServiceResult(feedback_id=record.feedback_id, applied=applied))

    result = ctx.result
    assert result is not None
    return result


def service_feedback_batch(
    instance: InstanceProtocol,
    items: list[FeedbackBatchItem],
    *,
    source: Literal["human", "ai_review", "system"],
) -> FeedbackBatchServiceResult:
    """Record a batch of edge feedback with one top-level receipt."""
    if not items:
        raise ConfigError("Batch feedback items must not be empty")

    graph = instance.load_graph()
    _ensure_receipts_exist(instance, {item.receipt_id for item in items})

    records = [
        _normalize_feedback_record(
            graph=graph,
            receipt_id=item.receipt_id,
            action=item.action,
            source=source,
            target=item.target,
            reason=item.reason,
            corrections=item.corrections,
            group_override=item.group_override,
        )
        for item in items
    ]

    feedback_store = instance.get_feedback_store()
    ctx: MutationReceiptContext[FeedbackBatchServiceResult]
    with mutation_receipt(
        instance,
        "feedback_batch",
        {"count": len(items), "source": source},
        store=feedback_store,
    ) as ctx:
        assert ctx.builder is not None
        for index, record in enumerate(records, start=1):
            ctx.builder.record_validation(
                passed=True,
                detail={
                    "index": index,
                    "receipt_id": record.receipt_id,
                    "action": record.action,
                },
            )

        with feedback_store.transaction():
            feedback_store.save_feedback_batch(records)

            applied_count = 0
            for record, item in zip(records, items, strict=True):
                target = record.target
                target_str = (
                    f"{target.from_type}:{target.from_id}:"
                    f"{target.relationship}:{target.to_type}:{target.to_id}"
                )
                applied = apply_feedback(graph, record)
                if applied:
                    applied_count += 1
                ctx.builder.record_feedback_applied(target_str, record.action, applied)
                if item.group_override:
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

        ctx.set_result(
            FeedbackBatchServiceResult(
                feedback_ids=[record.feedback_id for record in records],
                applied_count=applied_count,
                total=len(records),
            )
        )

    result = ctx.result
    assert result is not None
    return result


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
