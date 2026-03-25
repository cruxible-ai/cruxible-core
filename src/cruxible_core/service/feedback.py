"""Feedback and outcome service functions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from cruxible_core.config.schema import CoreConfig, FeedbackProfileSchema
from cruxible_core.errors import (
    ConfigError,
    CoreError,
    DataValidationError,
    EdgeAmbiguityError,
    MutationError,
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
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.receipt.types import Receipt
from cruxible_core.service._helpers import _persist_receipt, _save_graph
from cruxible_core.service.types import (
    FeedbackBatchServiceResult,
    FeedbackServiceResult,
    OutcomeServiceResult,
)

_VALID_ACTIONS = ("approve", "reject", "correct", "flag")
_VALID_SOURCES = ("human", "ai_review", "system")


def _validate_feedback_request_values(
    *,
    action: str,
    source: str,
    corrections: Any,
) -> None:
    """Validate the basic feedback payload before loading external state."""
    if action not in _VALID_ACTIONS:
        raise ConfigError(f"Invalid action '{action}'. Use: {', '.join(_VALID_ACTIONS)}")

    if source not in _VALID_SOURCES:
        raise ConfigError(f"Invalid source '{source}'. Use: {', '.join(_VALID_SOURCES)}")

    if corrections is not None and not isinstance(corrections, dict):
        raise ConfigError("corrections must be an object")


def _normalize_feedback_record(
    *,
    config: CoreConfig,
    graph,
    receipt: Receipt,
    receipt_id: str,
    action: Literal["approve", "reject", "correct", "flag"],
    source: Literal["human", "ai_review", "system"],
    target: EdgeTarget,
    reason: str,
    reason_code: str | None,
    scope_hints: dict[str, Any] | None,
    corrections: dict[str, Any] | None,
    group_override: bool,
) -> FeedbackRecord:
    """Validate and normalize one feedback request into a record."""
    _validate_feedback_request_values(
        action=action,
        source=source,
        corrections=corrections,
    )

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
    normalized_scope_hints = dict(scope_hints or {})

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

    profile = config.get_feedback_profile(target.relationship)
    reason_remediation_hint: str | None = None
    if profile is not None:
        _validate_feedback_inputs(
            profile=profile,
            relationship_type=target.relationship,
            source=source,
            reason_code=reason_code,
            scope_hints=normalized_scope_hints,
        )
        if reason_code is not None:
            reason_schema = profile.reason_codes[reason_code]
            reason_remediation_hint = reason_schema.remediation_hint

    decision_context = _build_decision_context(receipt)
    context_snapshot = _build_context_snapshot(
        graph=graph,
        profile=profile,
        target=target,
        decision_context=decision_context,
    )

    return FeedbackRecord(
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        reason_code=reason_code,
        reason_remediation_hint=reason_remediation_hint,
        scope_hints=normalized_scope_hints,
        feedback_profile_key=target.relationship if profile is not None else None,
        feedback_profile_version=profile.version if profile is not None else None,
        decision_context=decision_context,
        context_snapshot=context_snapshot,
        corrections=normalized_corrections,
    )


def _load_receipts(instance: InstanceProtocol, receipt_ids: Iterable[str]) -> dict[str, Receipt]:
    """Load receipt objects, failing if any referenced receipt IDs do not exist."""
    receipt_store = instance.get_receipt_store()
    receipts: dict[str, Receipt] = {}
    try:
        for receipt_id in receipt_ids:
            receipt = receipt_store.get_receipt(receipt_id)
            if receipt is None:
                raise ReceiptNotFoundError(receipt_id)
            receipts[receipt_id] = receipt
    finally:
        receipt_store.close()
    return receipts


def _validate_feedback_inputs(
    *,
    profile: FeedbackProfileSchema,
    relationship_type: str,
    source: Literal["human", "ai_review", "system"],
    reason_code: str | None,
    scope_hints: dict[str, Any],
) -> None:
    """Validate feedback inputs against the configured feedback profile."""
    if source in {"ai_review", "system"} and not reason_code:
        raise ConfigError(
            f"Feedback for relationship '{relationship_type}' requires reason_code for "
            f"source '{source}'"
        )

    if reason_code is not None:
        reason_schema = profile.reason_codes.get(reason_code)
        if reason_schema is None:
            raise ConfigError(
                f"Feedback for relationship '{relationship_type}' uses unknown reason_code "
                f"'{reason_code}'"
            )
        missing_scope = [
            key for key in reason_schema.required_scope_keys if key not in scope_hints
        ]
        if missing_scope:
            missing_str = ", ".join(sorted(missing_scope))
            raise ConfigError(
                f"Feedback reason_code '{reason_code}' requires scope_hints for: {missing_str}"
            )

    unexpected_scope = sorted(set(scope_hints) - set(profile.scope_keys))
    if unexpected_scope:
        unexpected_str = ", ".join(unexpected_scope)
        raise ConfigError(
            f"Feedback for relationship '{relationship_type}' uses undeclared scope_hints: "
            f"{unexpected_str}"
        )


def _build_decision_context(receipt: Receipt) -> dict[str, Any]:
    """Derive stable decision-surface metadata from the anchored receipt."""
    if receipt.operation_type == "query":
        surface_type = "query"
        surface_name = receipt.query_name
    elif receipt.operation_type == "workflow":
        surface_type = "workflow"
        surface_name = receipt.query_name
    else:
        surface_type = "operation"
        surface_name = receipt.operation_type

    return {
        "surface_type": surface_type,
        "surface_name": surface_name,
        "operation_type": receipt.operation_type,
    }


def _build_context_snapshot(
    *,
    graph,
    profile: FeedbackProfileSchema | None,
    target: EdgeTarget,
    decision_context: dict[str, Any],
) -> dict[str, Any]:
    """Capture a bounded feedback-time snapshot for deterministic grouping."""
    from_entity = graph.get_entity(target.from_type, target.from_id)
    to_entity = graph.get_entity(target.to_type, target.to_id)
    relationship = graph.get_relationship(
        target.from_type,
        target.from_id,
        target.to_type,
        target.to_id,
        target.relationship,
        edge_key=target.edge_key,
    )

    from_props: dict[str, Any] = {}
    to_props: dict[str, Any] = {}
    edge_props: dict[str, Any] = {}
    if profile is not None:
        for path in profile.scope_keys.values():
            side, _, prop_name = path.partition(".")
            if side == "FROM" and from_entity is not None and prop_name in from_entity.properties:
                from_props[prop_name] = from_entity.properties[prop_name]
            elif side == "TO" and to_entity is not None and prop_name in to_entity.properties:
                to_props[prop_name] = to_entity.properties[prop_name]
            elif (
                side == "EDGE"
                and relationship is not None
                and prop_name in relationship.properties
            ):
                edge_props[prop_name] = relationship.properties[prop_name]

    return {
        "from": {
            "entity_type": target.from_type,
            "entity_id": target.from_id,
            "properties": from_props,
        },
        "to": {
            "entity_type": target.to_type,
            "entity_id": target.to_id,
            "properties": to_props,
        },
        "edge": {
            "relationship": target.relationship,
            "edge_key": target.edge_key,
            "properties": edge_props,
        },
        "context": decision_context,
    }


def service_feedback(
    instance: InstanceProtocol,
    receipt_id: str,
    action: Literal["approve", "reject", "correct", "flag"],
    source: Literal["human", "ai_review", "system"],
    target: EdgeTarget,
    reason: str = "",
    reason_code: str | None = None,
    scope_hints: dict[str, Any] | None = None,
    corrections: dict[str, Any] | None = None,
    group_override: bool = False,
) -> FeedbackServiceResult:
    """Record feedback on an edge.

    Validates corrections, checks receipt existence, persists feedback,
    and applies to the graph. If group_override=True, stamps the edge
    with group_override property after applying feedback.
    """
    _validate_feedback_request_values(
        action=action,
        source=source,
        corrections=corrections,
    )
    config = instance.load_config()
    graph = instance.load_graph()
    receipts = _load_receipts(instance, [receipt_id])
    record = _normalize_feedback_record(
        config=config,
        graph=graph,
        receipt=receipts[receipt_id],
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        reason_code=reason_code,
        scope_hints=scope_hints,
        corrections=corrections,
        group_override=group_override,
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


def service_feedback_batch(
    instance: InstanceProtocol,
    items: list[FeedbackBatchItem],
    *,
    source: Literal["human", "ai_review", "system"],
) -> FeedbackBatchServiceResult:
    """Record a batch of edge feedback with one top-level receipt."""
    if not items:
        raise ConfigError("Batch feedback items must not be empty")

    for item in items:
        _validate_feedback_request_values(
            action=item.action,
            source=source,
            corrections=item.corrections,
        )

    graph = instance.load_graph()
    config = instance.load_config()
    receipts = _load_receipts(instance, {item.receipt_id for item in items})

    records = [
        _normalize_feedback_record(
            config=config,
            graph=graph,
            receipt=receipts[item.receipt_id],
            receipt_id=item.receipt_id,
            action=item.action,
            source=source,
            target=item.target,
            reason=item.reason,
            reason_code=item.reason_code,
            scope_hints=item.scope_hints,
            corrections=item.corrections,
            group_override=item.group_override,
        )
        for item in items
    ]

    builder = ReceiptBuilder(
        operation_type="feedback_batch",
        parameters={"count": len(items), "source": source},
    )

    result: FeedbackBatchServiceResult | None = None
    _exc: CoreError | None = None
    feedback_store = instance.get_feedback_store()
    try:
        for index, record in enumerate(records, start=1):
            builder.record_validation(
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
                builder.record_feedback_applied(target_str, record.action, applied)
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

        builder.mark_committed()
        result = FeedbackBatchServiceResult(
            feedback_ids=[record.feedback_id for record in records],
            applied_count=applied_count,
            total=len(records),
        )
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
