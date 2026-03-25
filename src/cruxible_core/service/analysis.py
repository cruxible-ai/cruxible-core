"""Analysis service functions — find_candidates, evaluate, analyze_feedback."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from cruxible_core.errors import ConfigError
from cruxible_core.evaluate import EvaluationReport, evaluate_graph
from cruxible_core.feedback.types import FeedbackRecord
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.query.candidates import CandidateMatch, MatchRule, find_candidates
from cruxible_core.service.types import (
    AnalyzeFeedbackResult,
    ConstraintSuggestion,
    DecisionPolicySuggestion,
    FeedbackGroupSummary,
    ProviderFixCandidate,
    QualityCheckCandidate,
    UncodedFeedbackExample,
)


def service_find_candidates(
    instance: InstanceProtocol,
    relationship_type: str,
    strategy: Literal["property_match", "shared_neighbors"],
    match_rules: list[MatchRule] | None = None,
    via_relationship: str | None = None,
    min_overlap: float = 0.5,
    min_confidence: float = 0.5,
    limit: int = 20,
    min_distinct_neighbors: int = 2,
) -> list[CandidateMatch]:
    """Find candidate relationships using a deterministic strategy."""
    _VALID_STRATEGIES = ("property_match", "shared_neighbors")
    if strategy not in _VALID_STRATEGIES:
        raise ConfigError(f"Invalid strategy '{strategy}'. Use: {', '.join(_VALID_STRATEGIES)}")

    if min_distinct_neighbors < 1:
        raise ConfigError("min_distinct_neighbors must be >= 1")

    config = instance.load_config()
    graph = instance.load_graph()

    return find_candidates(
        config,
        graph,
        relationship_type,
        strategy,
        match_rules=match_rules,
        via_relationship=via_relationship,
        min_overlap=min_overlap,
        min_confidence=min_confidence,
        limit=limit,
        min_distinct_neighbors=min_distinct_neighbors,
    )


def service_evaluate(
    instance: InstanceProtocol,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> EvaluationReport:
    """Evaluate graph quality with deterministic checks."""
    config = instance.load_config()
    graph = instance.load_graph()
    return evaluate_graph(
        config,
        graph,
        confidence_threshold=confidence_threshold,
        max_findings=max_findings,
        exclude_orphan_types=exclude_orphan_types,
    )


def service_analyze_feedback(
    instance: InstanceProtocol,
    relationship_type: str,
    *,
    limit: int = 200,
    min_support: int = 5,
    decision_surface_type: str | None = None,
    decision_surface_name: str | None = None,
    property_pairs: list[tuple[str, str]] | None = None,
) -> AnalyzeFeedbackResult:
    """Analyze structured feedback into deterministic remediation suggestions."""
    config = instance.load_config()
    rel = config.get_relationship(relationship_type)
    if rel is None:
        raise ConfigError(f"Relationship type '{relationship_type}' not found in config")

    profile = config.get_feedback_profile(relationship_type)
    store = instance.get_feedback_store()
    try:
        feedback_rows = store.list_feedback(
            relationship_type=relationship_type,
            decision_surface_type=decision_surface_type,
            decision_surface_name=decision_surface_name,
            limit=limit,
        )
    finally:
        store.close()

    action_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    reason_code_counts: dict[str, int] = {}
    warnings: list[str] = []
    warning_keys: set[str] = set()
    coded_groups: dict[
        tuple[str, tuple[tuple[str, Any], ...], tuple[tuple[str, Any], ...]],
        list[FeedbackRecord],
    ] = defaultdict(list)
    uncoded_feedback: list[FeedbackRecord] = []

    for row in feedback_rows:
        action_counts[row.action] = action_counts.get(row.action, 0) + 1
        source_counts[row.source] = source_counts.get(row.source, 0) + 1
        if row.reason_code:
            reason_code_counts[row.reason_code] = reason_code_counts.get(row.reason_code, 0) + 1
        if row.action != "reject":
            continue
        if row.reason_code is None:
            uncoded_feedback.append(row)
            continue
        group_key = (
            row.reason_code,
            _freeze_mapping(row.decision_context),
            _freeze_mapping(row.scope_hints),
        )
        coded_groups[group_key].append(row)

    coded_group_results: list[FeedbackGroupSummary] = []
    decision_policy_suggestions: list[DecisionPolicySuggestion] = []
    quality_check_candidates: list[QualityCheckCandidate] = []
    provider_fix_candidates: list[ProviderFixCandidate] = []
    used_policy_names: set[str] = {policy.name for policy in config.decision_policies}
    constraint_rows: list[FeedbackRecord] = []

    for (reason_code, frozen_context, frozen_scope), rows in coded_groups.items():
        decision_context = dict(frozen_context)
        scope_hints = dict(frozen_scope)
        remediation_hint = _resolve_group_remediation_hint(
            relationship_type=relationship_type,
            profile=profile,
            reason_code=reason_code,
            rows=rows,
            warnings=warnings,
            warning_keys=warning_keys,
        )
        coded_group_results.append(
            FeedbackGroupSummary(
                relationship_type=relationship_type,
                reason_code=reason_code,
                remediation_hint=remediation_hint,
                decision_context=decision_context,
                scope_hints=scope_hints,
                feedback_count=len(rows),
                feedback_ids=[row.feedback_id for row in rows[:5]],
                sample_reasons=[row.reason for row in rows if row.reason][:3],
            )
        )

        if len(rows) < min_support:
            continue
        if remediation_hint == "constraint":
            constraint_rows.extend(rows)
        elif remediation_hint == "decision_policy":
            suggestion = _build_decision_policy_suggestion(
                config=config,
                relationship_type=relationship_type,
                profile=profile,
                used_names=used_policy_names,
                reason_code=reason_code,
                decision_context=decision_context,
                scope_hints=scope_hints,
                rows=rows,
            )
            if suggestion is not None:
                used_policy_names.add(suggestion.name)
                decision_policy_suggestions.append(suggestion)
        elif remediation_hint == "quality_check":
            quality_check_candidates.append(
                QualityCheckCandidate(
                    relationship_type=relationship_type,
                    reason_code=reason_code,
                    support_count=len(rows),
                    description=(
                        f"Repeated rejected feedback for reason_code '{reason_code}' "
                        f"on relationship '{relationship_type}'"
                    ),
                    feedback_ids=[row.feedback_id for row in rows[:5]],
                )
            )
        elif remediation_hint == "provider_fix":
            provider_fix_candidates.append(
                ProviderFixCandidate(
                    relationship_type=relationship_type,
                    reason_code=reason_code,
                    support_count=len(rows),
                    description=(
                        f"Repeated rejected feedback for reason_code '{reason_code}' "
                        f"suggests a provider/workflow normalization issue"
                    ),
                    feedback_ids=[row.feedback_id for row in rows[:5]],
                )
            )

    constraint_suggestions = _build_constraint_suggestions(
        config=config,
        relationship_type=relationship_type,
        rows=constraint_rows,
        property_pairs=property_pairs,
        min_support=min_support,
        warnings=warnings,
        warning_keys=warning_keys,
    )

    uncoded_examples = [
        UncodedFeedbackExample(
            feedback_id=row.feedback_id,
            relationship_type=relationship_type,
            reason=row.reason,
            decision_context=row.decision_context,
            scope_hints=row.scope_hints,
            target=row.target.model_dump(mode="json"),
        )
        for row in uncoded_feedback[:5]
    ]

    return AnalyzeFeedbackResult(
        relationship_type=relationship_type,
        feedback_count=len(feedback_rows),
        action_counts=action_counts,
        source_counts=source_counts,
        reason_code_counts=reason_code_counts,
        coded_groups=sorted(
            coded_group_results,
            key=lambda item: item.feedback_count,
            reverse=True,
        ),
        uncoded_feedback_count=len(uncoded_feedback),
        uncoded_examples=uncoded_examples,
        constraint_suggestions=constraint_suggestions,
        decision_policy_suggestions=decision_policy_suggestions,
        quality_check_candidates=quality_check_candidates,
        provider_fix_candidates=provider_fix_candidates,
        warnings=warnings,
    )


def _freeze_mapping(mapping: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Build a stable tuple key for exact grouping."""
    return tuple(sorted((key, _freeze_value(value)) for key, value in mapping.items()))


def _freeze_value(value: Any) -> Any:
    """Normalize nested values into hashable tuples for grouping."""
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze_value(val)) for key, val in value.items()))
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value


def _build_decision_policy_suggestion(
    *,
    config,
    relationship_type: str,
    profile,
    used_names: set[str],
    reason_code: str,
    decision_context: dict[str, Any],
    scope_hints: dict[str, Any],
    rows: list[FeedbackRecord],
) -> DecisionPolicySuggestion | None:
    """Build a scoped decision policy suggestion from one coded feedback group."""
    if profile is None or not scope_hints:
        return None

    surface_type = decision_context.get("surface_type")
    surface_name = decision_context.get("surface_name")
    if surface_type not in {"query", "workflow"} or not surface_name:
        return None

    match: dict[str, Any] = {"from": {}, "to": {}, "edge": {}, "context": {}}
    for scope_key, value in scope_hints.items():
        path = profile.scope_keys.get(scope_key)
        if path is None:
            continue
        side, _, prop_name = path.partition(".")
        if side == "FROM":
            match["from"][prop_name] = value
        elif side == "TO":
            match["to"][prop_name] = value
        else:
            match["edge"][prop_name] = value

    if surface_type == "query":
        applies_to = "query"
        effect = "suppress"
        query_name = surface_name
        workflow_name = None
    else:
        applies_to = "workflow"
        effect = "require_review"
        query_name = None
        workflow_name = surface_name

    if not any(match[side] for side in ("from", "to", "edge")):
        return None

    match["context"]["relationship_type"] = relationship_type
    match["context"][f"{surface_type}_name"] = surface_name
    name = _dedupe_name(
        used_names,
        f"{relationship_type}_{reason_code}_{surface_type}",
    )
    return DecisionPolicySuggestion(
        name=name,
        description=(
            f"Suggested from {len(rows)} rejected feedback records for reason_code "
            f"'{reason_code}'"
        ),
        relationship_type=relationship_type,
        applies_to=applies_to,
        effect=effect,
        rationale=rows[0].reason or f"Repeated feedback for reason_code '{reason_code}'",
        match=match,
        query_name=query_name,
        workflow_name=workflow_name,
        support_count=len(rows),
        feedback_ids=[row.feedback_id for row in rows[:5]],
    )


def _build_constraint_suggestions(
    *,
    config,
    relationship_type: str,
    rows: list[FeedbackRecord],
    property_pairs: list[tuple[str, str]] | None,
    min_support: int,
    warnings: list[str],
    warning_keys: set[str],
) -> list[ConstraintSuggestion]:
    """Build constraint suggestions from repeated endpoint mismatches."""
    rel = config.get_relationship(relationship_type)
    if rel is None:
        return []
    from_schema = config.get_entity_type(rel.from_entity)
    to_schema = config.get_entity_type(rel.to_entity)
    if from_schema is None or to_schema is None:
        return []

    pairs = property_pairs or [
        (name, name)
        for name, prop in from_schema.properties.items()
        if name in to_schema.properties
        and prop.type != "json"
        and to_schema.properties[name].type != "json"
    ]
    existing_rules = {constraint.rule for constraint in config.constraints}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    missing_snapshot_counts: dict[tuple[str, str], int] = defaultdict(int)

    for row in rows:
        snapshot = row.context_snapshot or {}
        from_props = _snapshot_properties(snapshot, "from")
        to_props = _snapshot_properties(snapshot, "to")
        for from_prop, to_prop in pairs:
            if from_prop not in from_props or to_prop not in to_props:
                missing_snapshot_counts[(from_prop, to_prop)] += 1
                continue
            from_val = from_props[from_prop]
            to_val = to_props[to_prop]
            if from_val is None or to_val is None or from_val == to_val:
                continue
            grouped[(from_prop, to_prop)].append(
                {
                    "feedback_id": row.feedback_id,
                    "from_value": from_val,
                    "to_value": to_val,
                }
            )

    for (from_prop, to_prop), skipped in sorted(missing_snapshot_counts.items()):
        _append_warning_once(
            warnings=warnings,
            warning_keys=warning_keys,
            key=f"snapshot:{relationship_type}:{from_prop}:{to_prop}",
            message=(
                f"Feedback snapshots for relationship '{relationship_type}' do not include "
                f"properties needed for mismatch analysis ({from_prop} -> {to_prop}); "
                f"skipped {skipped} row(s)"
            ),
        )

    suggestions: list[ConstraintSuggestion] = []
    used_names = {constraint.name for constraint in config.constraints}
    for (from_prop, to_prop), items in sorted(grouped.items()):
        if len(items) < min_support:
            continue
        rule = f"{relationship_type}.FROM.{from_prop} == {relationship_type}.TO.{to_prop}"
        if rule in existing_rules:
            continue
        name = _dedupe_name(used_names, f"{relationship_type}_{from_prop}_eq_{to_prop}")
        suggestions.append(
            ConstraintSuggestion(
                name=name,
                description=(
                    f"Suggested from {len(items)} rejected feedback records showing "
                    f"{from_prop} != {to_prop}"
                ),
                relationship_type=relationship_type,
                rule=rule,
                severity="warning",
                support_count=len(items),
                feedback_ids=[item["feedback_id"] for item in items[:5]],
                sample_value_pairs=items[:3],
            )
        )
        used_names.add(name)
    return suggestions


def _resolve_group_remediation_hint(
    *,
    relationship_type: str,
    profile,
    reason_code: str,
    rows: list[FeedbackRecord],
    warnings: list[str],
    warning_keys: set[str],
) -> str:
    """Resolve one group's remediation lane without reinterpreting old rows."""
    hints = {
        hint
        for hint in (
            _resolve_row_remediation_hint(
                relationship_type=relationship_type,
                profile=profile,
                reason_code=reason_code,
                row=row,
                warnings=warnings,
                warning_keys=warning_keys,
            )
            for row in rows
        )
        if hint is not None
    }
    if not hints:
        return "unknown"
    if len(hints) > 1:
        _append_warning_once(
            warnings=warnings,
            warning_keys=warning_keys,
            key=(
                "mixed-remediation:"
                f"{relationship_type}:{reason_code}:{_freeze_mapping(rows[0].decision_context)}:"
                f"{_freeze_mapping(rows[0].scope_hints)}"
            ),
            message=(
                f"Feedback group '{relationship_type}/{reason_code}' has mixed remediation "
                "hints across stored feedback rows; automated suggestions were skipped"
            ),
        )
        return "unknown"
    return next(iter(hints))


def _resolve_row_remediation_hint(
    *,
    relationship_type: str,
    profile,
    reason_code: str,
    row: FeedbackRecord,
    warnings: list[str],
    warning_keys: set[str],
) -> str | None:
    """Resolve one row's remediation hint from stored metadata first."""
    if row.reason_remediation_hint is not None:
        if (
            profile is not None
            and row.feedback_profile_version is not None
            and row.feedback_profile_version != profile.version
        ):
            _append_warning_once(
                warnings=warnings,
                warning_keys=warning_keys,
                key=(
                    f"profile-version:{relationship_type}:{row.feedback_profile_version}:"
                    f"{profile.version}"
                ),
                message=(
                    f"Feedback for relationship '{relationship_type}' references profile "
                    f"version {row.feedback_profile_version} while current config is "
                    f"version {profile.version}; using stored remediation hints"
                ),
            )
        return row.reason_remediation_hint

    if profile is None:
        return None
    if row.feedback_profile_key not in (None, relationship_type):
        _append_warning_once(
            warnings=warnings,
            warning_keys=warning_keys,
            key=f"profile-key:{row.feedback_id}",
            message=(
                f"Feedback '{row.feedback_id}' references feedback profile "
                f"'{row.feedback_profile_key}', not '{relationship_type}'"
            ),
        )
        return None
    if (
        row.feedback_profile_version is not None
        and row.feedback_profile_version != profile.version
    ):
        _append_warning_once(
            warnings=warnings,
            warning_keys=warning_keys,
            key=(
                f"profile-version-nohint:{relationship_type}:{row.feedback_profile_version}:"
                f"{profile.version}"
            ),
            message=(
                f"Feedback for relationship '{relationship_type}' references profile "
                f"version {row.feedback_profile_version} but does not store a remediation hint; "
                "automated suggestions for those rows were skipped"
            ),
        )
        return None

    reason_schema = profile.reason_codes.get(reason_code)
    if reason_schema is None:
        _append_warning_once(
            warnings=warnings,
            warning_keys=warning_keys,
            key=f"reason-code:{relationship_type}:{reason_code}",
            message=(
                f"Feedback reason_code '{reason_code}' is not defined in the current "
                f"feedback profile for relationship '{relationship_type}'"
            ),
        )
        return None
    return reason_schema.remediation_hint


def _snapshot_properties(snapshot: dict[str, Any], side: str) -> dict[str, Any]:
    """Return stored snapshot properties for one endpoint side."""
    side_payload = snapshot.get(side)
    if not isinstance(side_payload, dict):
        return {}
    properties = side_payload.get("properties")
    if not isinstance(properties, dict):
        return {}
    return properties


def _append_warning_once(
    *,
    warnings: list[str],
    warning_keys: set[str],
    key: str,
    message: str,
) -> None:
    """Append a warning once per stable key."""
    if key in warning_keys:
        return
    warning_keys.add(key)
    warnings.append(message)


def _dedupe_name(existing_names: set[str], base_name: str) -> str:
    """Produce a deterministic non-colliding config name."""
    candidate = base_name
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate
