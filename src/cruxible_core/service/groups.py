"""Group service functions — propose, resolve, list, trust."""

from __future__ import annotations

import json as _json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from cruxible_core.config.schema import MatchingSchema
from cruxible_core.errors import (
    ConfigError,
    DataValidationError,
    GroupNotFoundError,
)
from cruxible_core.graph.operations import validate_relationship
from cruxible_core.graph.types import RelationshipInstance
from cruxible_core.group.signature import compute_group_signature
from cruxible_core.group.types import CandidateGroup, CandidateMember
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.query.filters import matches_exact_filter
from cruxible_core.service._helpers import MutationReceiptContext, mutation_receipt
from cruxible_core.service.mutations import service_add_relationships
from cruxible_core.service.types import (
    GetGroupResult,
    ListGroupsResult,
    ListResolutionsResult,
    ProposeGroupResult,
    ResolveGroupResult,
)


def derive_review_priority(
    members: list[CandidateMember],
    matching: MatchingSchema | None,
    prior_resolution: dict[str, Any] | None,
) -> str:
    """Derive review_priority mechanically from universal states.

    Returns: "critical", "review", or "normal".
    Highest-severity bucket wins.
    """
    if matching is None:
        # No matching config → default to review (first-time, no guardrails)
        return "review" if prior_resolution is None else "normal"

    has_critical = False
    has_review = False

    # Check prior resolution trust
    if prior_resolution is not None:
        if prior_resolution.get("trust_status") == "invalidated":
            has_critical = True
        elif prior_resolution.get("trust_status") == "watch":
            has_review = True

    # Check signals on members
    for m in members:
        for sig in m.signals:
            icfg = matching.integrations.get(sig.integration)
            if icfg is None:
                continue
            if icfg.role == "advisory":
                continue  # Advisory signals ignored for priority

            if sig.signal == "contradict" and icfg.role == "blocking":
                has_critical = True
            elif sig.signal == "unsure":
                if icfg.always_review_on_unsure:
                    has_review = True
                if icfg.role in ("blocking", "required"):
                    has_review = True

    # No prior approved resolution → review
    if prior_resolution is None:
        has_review = True

    if has_critical:
        return "critical"
    if has_review:
        return "review"
    return "normal"


def service_propose_group(
    instance: InstanceProtocol,
    relationship_type: str,
    members: list[CandidateMember],
    thesis_text: str = "",
    thesis_facts: dict[str, Any] | None = None,
    analysis_state: dict[str, Any] | None = None,
    integrations_used: list[str] | None = None,
    proposed_by: Literal["human", "agent"] = "agent",
    suggested_priority: str | None = None,
    source_workflow_name: str | None = None,
    source_workflow_receipt_id: str | None = None,
    source_trace_ids: list[str] | None = None,
    source_step_ids: list[str] | None = None,
) -> ProposeGroupResult:
    """Propose a group of candidate edges for batch review/approval."""
    config = instance.load_config()
    graph = instance.load_graph()
    thesis_facts = thesis_facts or {}
    analysis_state = analysis_state or {}
    integrations_used = integrations_used or []
    source_trace_ids = source_trace_ids or []
    source_step_ids = source_step_ids or []
    policy_summary: dict[str, int] = {}

    # 1. Validate relationship_type
    rel_schema = config.get_relationship(relationship_type)
    if rel_schema is None:
        raise ConfigError(f"Relationship type '{relationship_type}' not found in config")

    # 2. Validate members not empty
    if not members:
        raise ConfigError("Members list must not be empty")

    # 3. Validate each member
    for m in members:
        if m.relationship_type != relationship_type:
            raise ConfigError(
                f"Member {m.from_id}\u2192{m.to_id} has relationship_type "
                f"'{m.relationship_type}' but group is for '{relationship_type}'"
            )
        if m.from_type != rel_schema.from_entity:
            raise ConfigError(
                f"Member {m.from_id} from_type '{m.from_type}' does not match "
                f"relationship '{relationship_type}' which expects '{rel_schema.from_entity}'"
            )
        if m.to_type != rel_schema.to_entity:
            raise ConfigError(
                f"Member {m.to_id} to_type '{m.to_type}' does not match "
                f"relationship '{relationship_type}' which expects '{rel_schema.to_entity}'"
            )

    # 4. thesis_facts serialization check
    try:
        _json.dumps(thesis_facts, sort_keys=True)
    except TypeError as exc:
        raise ConfigError(f"thesis_facts must be JSON-serializable: {exc}") from exc

    # 5. Duplicate member check
    seen_members: set[tuple[str, str, str, str, str]] = set()
    for m in members:
        key = (m.from_type, m.from_id, m.to_type, m.to_id, m.relationship_type)
        if key in seen_members:
            raise ConfigError(
                f"Duplicate member: {m.from_type}:{m.from_id} \u2192 "
                f"{m.to_type}:{m.to_id} via {m.relationship_type}"
            )
        seen_members.add(key)

    members, force_review = _apply_workflow_policies(
        config=config,
        graph=graph,
        relationship_type=relationship_type,
        members=members,
        workflow_name=source_workflow_name,
        thesis_facts=thesis_facts,
        policy_summary=policy_summary,
    )

    matching = rel_schema.matching

    # 6. Signal validation (all members)
    for m in members:
        seen_integrations: set[str] = set()
        for sig in m.signals:
            if sig.integration in seen_integrations:
                raise ConfigError(
                    f"Member {m.from_id}\u2192{m.to_id} has duplicate signals "
                    f"from integration '{sig.integration}'"
                )
            seen_integrations.add(sig.integration)

            if matching is not None and matching.integrations:
                if sig.integration not in matching.integrations:
                    declared = ", ".join(sorted(matching.integrations.keys()))
                    raise ConfigError(
                        f"Signal from undeclared integration '{sig.integration}'; "
                        f"declared: {declared}"
                    )

    # 7. Config guardrails (if matching section exists)
    if matching is not None and matching.integrations:
        # Blocking + required integrations: every member must have a signal
        for iname, icfg in matching.integrations.items():
            if icfg.role in ("blocking", "required"):
                for m in members:
                    member_integrations = {s.integration for s in m.signals}
                    if iname not in member_integrations:
                        raise ConfigError(
                            f"Member {m.from_id}\u2192{m.to_id} missing signal "
                            f"from {icfg.role} integration '{iname}'"
                        )

        # integrations_used validation
        for iname in integrations_used:
            if iname not in matching.integrations:
                raise ConfigError(f"Integration '{iname}' not declared in matching.integrations")

        # max_group_size
        if len(members) > matching.max_group_size:
            raise ConfigError(
                f"Group size {len(members)} exceeds max_group_size {matching.max_group_size}"
            )

    # 8. Compute signature
    signature = compute_group_signature(relationship_type, thesis_facts)
    if not members:
        return ProposeGroupResult(
            group_id=None,
            signature=signature,
            status="suppressed",
            review_priority="review",
            member_count=0,
            prior_resolution=None,
            suppressed=True,
            policy_summary=policy_summary,
        )

    # 9. Check for prior confirmed approved resolution
    group_store = instance.get_group_store()
    try:
        prior = group_store.find_resolution(
            relationship_type, signature, action="approve", confirmed=True
        )

        status = "pending_review"
        if prior is not None:
            # Trust status gate
            if prior.get("trust_status") != "invalidated":
                # Prior trust gate
                trust_ok = False
                if matching is not None:
                    policy = matching.auto_resolve_requires_prior_trust
                    prior_trust = prior.get("trust_status", "watch")
                    if policy == "trusted_only" and prior_trust == "trusted":
                        trust_ok = True
                    elif policy == "trusted_or_watch" and prior_trust in (
                        "trusted",
                        "watch",
                    ):
                        trust_ok = True

                if trust_ok and matching is not None:
                    # Signal policy check
                    auto_resolve = _check_auto_resolve_signals(members, matching)
                    if auto_resolve:
                        status = "auto_resolved"

        # 10. Derive review_priority
        review_priority = derive_review_priority(members, matching, prior)
        if force_review and review_priority == "normal":
            review_priority = "review"
        if force_review:
            status = "pending_review"

        # 11. Create and save group
        group_id = f"GRP-{uuid.uuid4().hex[:12]}"
        group = CandidateGroup(
            group_id=group_id,
            relationship_type=relationship_type,
            signature=signature,
            status=status,
            thesis_text=thesis_text,
            thesis_facts=thesis_facts,
            analysis_state=analysis_state,
            integrations_used=integrations_used,
            proposed_by=proposed_by,
            member_count=len(members),
            review_priority=review_priority,
            suggested_priority=suggested_priority,
            source_workflow_name=source_workflow_name,
            source_workflow_receipt_id=source_workflow_receipt_id,
            source_trace_ids=source_trace_ids,
            source_step_ids=source_step_ids,
            created_at=datetime.now(timezone.utc),
        )

        with group_store.transaction():
            group_store.save_group(group)
            group_store.save_members(group_id, members)

        return ProposeGroupResult(
            group_id=group_id,
            signature=signature,
            status=status,
            review_priority=review_priority,
            member_count=len(members),
            prior_resolution=prior,
            policy_summary=policy_summary,
        )
    finally:
        group_store.close()


def _apply_workflow_policies(
    *,
    config,
    graph,
    relationship_type: str,
    members: list[CandidateMember],
    workflow_name: str | None,
    thesis_facts: dict[str, Any],
    policy_summary: dict[str, int],
) -> tuple[list[CandidateMember], bool]:
    """Apply workflow-side decision policies to candidate members."""
    if workflow_name is None:
        return members, False

    policies = [
        policy
        for policy in config.decision_policies
        if policy.applies_to == "workflow"
        and policy.workflow_name == workflow_name
        and policy.relationship_type == relationship_type
        and not _policy_expired(policy.expires_at)
    ]
    if not policies:
        return members, False

    kept: list[CandidateMember] = []
    force_review = False
    for member in members:
        from_entity = graph.get_entity(member.from_type, member.from_id)
        to_entity = graph.get_entity(member.to_type, member.to_id)
        matched_effects: list[str] = []
        for policy in policies:
            if from_entity is None or to_entity is None:
                continue
            if not matches_exact_filter(from_entity.properties, policy.match.from_match):
                continue
            if not matches_exact_filter(to_entity.properties, policy.match.to):
                continue
            if not matches_exact_filter(member.properties, policy.match.edge):
                continue
            if not matches_exact_filter(
                {
                    "workflow_name": workflow_name,
                    "relationship_type": relationship_type,
                    **thesis_facts,
                },
                policy.match.context,
            ):
                continue
            policy_summary[policy.name] = policy_summary.get(policy.name, 0) + 1
            matched_effects.append(policy.effect)

        if "suppress" in matched_effects:
            continue
        if "require_review" in matched_effects:
            force_review = True
        kept.append(member)
    return kept, force_review


def _policy_expired(expires_at: str | None) -> bool:
    """Return True when a workflow policy should no longer apply."""
    if not expires_at:
        return False
    try:
        normalized = expires_at.replace("Z", "+00:00")
        expiry = datetime.fromisoformat(normalized)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry < datetime.now(timezone.utc)
    except ValueError:
        return False


def _check_auto_resolve_signals(
    members: list[CandidateMember],
    matching: MatchingSchema,
) -> bool:
    """Check if signals meet the auto_resolve_when policy.

    Returns True if auto-resolve is eligible based on signals alone.
    """
    policy = matching.auto_resolve_when

    for m in members:
        for sig in m.signals:
            icfg = matching.integrations.get(sig.integration)
            if icfg is None or icfg.role == "advisory":
                continue

            # always_review_on_unsure override
            if sig.signal == "unsure" and icfg.always_review_on_unsure:
                return False

            if policy == "all_support":
                if sig.signal != "support":
                    return False
            elif policy == "no_contradict":
                if sig.signal == "contradict" and icfg.role == "blocking":
                    return False

    return True


def service_resolve_group(
    instance: InstanceProtocol,
    group_id: str,
    action: Literal["approve", "reject"],
    rationale: str = "",
    resolved_by: Literal["human", "agent"] = "human",
) -> ResolveGroupResult:
    """Resolve a candidate group — approve creates edges, reject records decision."""
    # 1. Validate inputs
    _VALID_ACTIONS = ("approve", "reject")
    if action not in _VALID_ACTIONS:
        raise ConfigError(f"Invalid action '{action}'. Use: {', '.join(_VALID_ACTIONS)}")
    _VALID_SOURCES = ("human", "agent")
    if resolved_by not in _VALID_SOURCES:
        raise ConfigError(f"Invalid resolved_by '{resolved_by}'. Use: {', '.join(_VALID_SOURCES)}")

    group_store = instance.get_group_store()

    # 2. Load group — close store on failure before builder exists
    try:
        group = group_store.get_group(group_id)
        if group is None:
            raise GroupNotFoundError(group_id)

        # 3. Status guard
        if group.status == "resolved":
            raise ConfigError("Group already resolved")
        if group.status == "applying" and action != "approve":
            raise ConfigError("Group is in applying state from a prior approve — cannot reject")

        is_retry = group.status == "applying"

        # 4. Load members
        members = group_store.get_members(group_id)
    except Exception:
        group_store.close()
        raise

    ctx: MutationReceiptContext[ResolveGroupResult]
    with mutation_receipt(
        instance,
        "group_resolve",
        {"group_id": group_id, "action": action},
        store=group_store,
    ) as ctx:
        assert ctx.builder is not None
        # 6. Reject path — no graph mutation
        if action == "reject":
            ctx.builder.record_validation(
                passed=True,
                detail={"action": "reject", "members": len(members)},
            )
            with group_store.transaction():
                res_id = group_store.save_resolution(
                    group.relationship_type,
                    group.signature,
                    "reject",
                    rationale,
                    group.thesis_text,
                    group.thesis_facts,
                    group.analysis_state,
                    resolved_by,
                    trust_status="watch",
                    confirmed=True,
                )
                group_store.update_group_status(group_id, "resolved", resolution_id=res_id)
            ctx.set_result(
                ResolveGroupResult(
                    group_id=group_id,
                    action="reject",
                    edges_created=0,
                    edges_skipped=0,
                    resolution_id=res_id,
                )
            )
        else:
            # 5. Approve — per-member validation
            instance.invalidate_graph_cache()
            config = instance.load_config()
            graph = instance.load_graph()

            valid_inputs: list[RelationshipInstance] = []
            edges_skipped = 0

            for m in members:
                # 5a. Count-based existence check
                count = graph.relationship_count_between(
                    m.from_type, m.from_id, m.to_type, m.to_id, m.relationship_type
                )
                if count > 0:
                    ctx.builder.record_validation(
                        passed=False,
                        detail={
                            "member": f"{m.from_type}:{m.from_id}->{m.to_type}:{m.to_id}",
                            "reason": "edge_exists",
                        },
                    )
                    edges_skipped += 1
                    continue

                # 5b. Validate
                try:
                    validate_relationship(
                        config,
                        graph,
                        m.from_type,
                        m.from_id,
                        m.relationship_type,
                        m.to_type,
                        m.to_id,
                        m.properties,
                    )
                except DataValidationError:
                    ctx.builder.record_validation(
                        passed=False,
                        detail={
                            "member": f"{m.from_type}:{m.from_id}->{m.to_type}:{m.to_id}",
                            "reason": "validation_failed",
                        },
                    )
                    edges_skipped += 1
                    continue

                ctx.builder.record_validation(
                    passed=True,
                    detail={
                        "member": f"{m.from_type}:{m.from_id}->{m.to_type}:{m.to_id}",
                    },
                )

                # 5c. Valid — add to batch
                valid_inputs.append(
                    RelationshipInstance(
                        from_type=m.from_type,
                        from_id=m.from_id,
                        relationship_type=m.relationship_type,
                        to_type=m.to_type,
                        to_id=m.to_id,
                        properties=m.properties,
                    )
                )

            # 7. Approve — store-first, then graph
            resolution_id: str
            if not is_retry:
                # 7a. First attempt: create resolution
                if not valid_inputs:
                    raise ConfigError("Cannot approve: no creatable edges (all members skipped)")

                # Inherit trust from prior confirmed approval
                prior = group_store.find_resolution(
                    group.relationship_type,
                    group.signature,
                    action="approve",
                    confirmed=True,
                )
                inherited_trust = "watch"
                if prior is not None:
                    prior_trust = prior.get("trust_status", "watch")
                    if prior_trust in ("trusted", "watch"):
                        inherited_trust = prior_trust

                with group_store.transaction():
                    resolution_id = group_store.save_resolution(
                        group.relationship_type,
                        group.signature,
                        "approve",
                        rationale,
                        group.thesis_text,
                        group.thesis_facts,
                        group.analysis_state,
                        resolved_by,
                        trust_status=inherited_trust,
                        confirmed=False,
                    )
                    group_store.update_group_status(
                        group_id, "applying", resolution_id=resolution_id
                    )
            else:
                # 7b. Retry path: reuse existing resolution_id
                resolution_id = group.resolution_id  # type: ignore[assignment]

            # Record relationship_write nodes before inner call
            for inp in valid_inputs:
                ctx.builder.record_relationship_write(
                    from_type=inp.from_type,
                    from_id=inp.from_id,
                    to_type=inp.to_type,
                    to_id=inp.to_id,
                    relationship=inp.relationship_type,
                    is_update=False,
                )

            # 7c. Graph write — suppress inner receipt
            edges_created = 0
            if valid_inputs:
                add_result = service_add_relationships(
                    instance,
                    valid_inputs,
                    source="group_resolve",
                    source_ref=f"group:{group_id}",
                    _create_receipt=False,
                )
                edges_created = add_result.added

            # 7d. Confirm + transition to resolved
            # Revalidate inherited trust
            prior = group_store.find_resolution(
                group.relationship_type,
                group.signature,
                action="approve",
                confirmed=True,
            )
            revalidated_trust: str | None = None
            if prior is not None:
                prior_trust = prior.get("trust_status", "watch")
                if prior_trust == "invalidated":
                    revalidated_trust = "watch"

            with group_store.transaction():
                group_store.confirm_resolution(resolution_id, trust_status=revalidated_trust)
                group_store.update_group_status(group_id, "resolved")

            ctx.set_result(
                ResolveGroupResult(
                    group_id=group_id,
                    action="approve",
                    edges_created=edges_created,
                    edges_skipped=edges_skipped,
                    resolution_id=resolution_id,
                )
            )

    result = ctx.result
    assert result is not None
    return result


def service_get_group(
    instance: InstanceProtocol,
    group_id: str,
) -> GetGroupResult:
    """Load a candidate group with its members and resolution details."""
    group_store = instance.get_group_store()
    try:
        group = group_store.get_group(group_id)
        if group is None:
            raise GroupNotFoundError(group_id)
        members = group_store.get_members(group_id)
        # Populate transient resolution dict
        if group.resolution_id is not None:
            group.resolution = group_store.get_resolution(group.resolution_id)
        return GetGroupResult(group=group, members=members)
    finally:
        group_store.close()


def service_list_groups(
    instance: InstanceProtocol,
    relationship_type: str | None = None,
    status: (Literal["pending_review", "auto_resolved", "applying", "resolved"] | None) = None,
    limit: int = 50,
) -> ListGroupsResult:
    """List candidate groups with optional filters, sorted by review_priority."""
    _VALID_STATUSES = ("pending_review", "auto_resolved", "applying", "resolved")
    if status is not None and status not in _VALID_STATUSES:
        raise ConfigError(f"Invalid status '{status}'. Use: {', '.join(_VALID_STATUSES)}")

    group_store = instance.get_group_store()
    try:
        groups = group_store.list_groups(
            relationship_type=relationship_type,
            status=status,
            limit=limit,
        )
        total = group_store.count_groups(
            relationship_type=relationship_type,
            status=status,
        )
        # Sort by review_priority descending (critical > review > normal)
        priority_order = {"critical": 0, "review": 1, "normal": 2}
        groups.sort(key=lambda g: priority_order.get(g.review_priority, 9))
        return ListGroupsResult(groups=groups, total=total)
    finally:
        group_store.close()


def service_list_resolutions(
    instance: InstanceProtocol,
    relationship_type: str | None = None,
    action: Literal["approve", "reject"] | None = None,
    limit: int = 50,
) -> ListResolutionsResult:
    """List resolutions — the reuse interface for agents querying prior analysis_state."""
    group_store = instance.get_group_store()
    try:
        resolutions = group_store.list_resolutions(
            relationship_type=relationship_type,
            action=action,
            limit=limit,
        )
        total = len(resolutions)
        return ListResolutionsResult(resolutions=resolutions, total=total)
    finally:
        group_store.close()


def service_update_trust_status(
    instance: InstanceProtocol,
    resolution_id: str,
    trust_status: Literal["trusted", "watch", "invalidated"],
    reason: str = "",
) -> None:
    """Update trust_status on a confirmed approved resolution (thesis-scoped)."""
    _VALID = ("trusted", "watch", "invalidated")
    if trust_status not in _VALID:
        raise ConfigError(f"Invalid trust_status '{trust_status}'. Use: {', '.join(_VALID)}")

    group_store = instance.get_group_store()
    try:
        # 1. Load resolution
        res = group_store.get_resolution(resolution_id)
        if res is None:
            raise ConfigError(f"Resolution '{resolution_id}' not found")

        # 2. Approved-only guard
        if res["action"] != "approve":
            raise ConfigError("Trust status can only be set on approved resolutions")

        # 3. Confirmed guard
        if not res["confirmed"]:
            raise ConfigError(
                "Trust status can only be set on confirmed resolutions (group must be resolved)"
            )

        # 4. Latest-approval guard
        latest = group_store.find_resolution(
            res["relationship_type"],
            res["group_signature"],
            action="approve",
            confirmed=True,
        )
        if latest is None or latest["resolution_id"] != resolution_id:
            latest_id = latest["resolution_id"] if latest else "none"
            raise ConfigError(
                "Can only update trust on the latest confirmed approval "
                f"for this signature. Latest: {latest_id}"
            )

        # 5. Update
        with group_store.transaction():
            group_store.update_resolution_trust_status(resolution_id, trust_status, reason)
    finally:
        group_store.close()
