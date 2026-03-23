"""Governed entity change proposal service functions."""

from __future__ import annotations

import json as _json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from cruxible_core.entity_proposal.types import EntityChangeMember, EntityChangeProposal
from cruxible_core.errors import (
    ConfigError,
    CoreError,
    DataValidationError,
    EntityProposalNotFoundError,
    MutationError,
)
from cruxible_core.graph.types import EntityInstance
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.service._helpers import _persist_receipt, _save_graph
from cruxible_core.service.types import (
    GetEntityProposalResult,
    ListEntityProposalsResult,
    ProposeEntityChangesResult,
    ResolveEntityProposalResult,
)


def service_propose_entity_changes(
    instance: InstanceProtocol,
    members: list[EntityChangeMember],
    *,
    thesis_text: str = "",
    thesis_facts: dict[str, Any] | None = None,
    analysis_state: dict[str, Any] | None = None,
    proposed_by: Literal["human", "ai_review"] = "ai_review",
    suggested_priority: str | None = None,
    source_workflow_name: str | None = None,
    source_workflow_receipt_id: str | None = None,
    source_trace_ids: list[str] | None = None,
    source_step_ids: list[str] | None = None,
) -> ProposeEntityChangesResult:
    """Create a governed proposal for entity creates or property patches."""
    config = instance.load_config()
    thesis_facts = thesis_facts or {}
    analysis_state = analysis_state or {}
    source_trace_ids = source_trace_ids or []
    source_step_ids = source_step_ids or []

    if not members:
        raise ConfigError("Members list must not be empty")
    if proposed_by not in ("human", "ai_review"):
        raise ConfigError("proposed_by must be one of: human, ai_review")

    try:
        _json.dumps(thesis_facts, sort_keys=True)
        _json.dumps(analysis_state, sort_keys=True)
    except TypeError as exc:
        raise ConfigError(f"Proposal metadata must be JSON-serializable: {exc}") from exc

    seen: set[tuple[str, str]] = set()
    for member in members:
        if member.entity_type not in config.entity_types:
            raise ConfigError(f"Entity type '{member.entity_type}' not found in config")
        if not member.entity_id.strip():
            raise ConfigError("entity_id must not be empty")
        if not isinstance(member.properties, dict):
            raise ConfigError("member.properties must be an object")
        key = (member.entity_type, member.entity_id)
        if key in seen:
            raise ConfigError(
                f"Duplicate member for entity {member.entity_type}:{member.entity_id}"
            )
        seen.add(key)

    proposal = EntityChangeProposal(
        proposal_id=f"EPR-{uuid.uuid4().hex[:12]}",
        status="pending_review",
        thesis_text=thesis_text,
        thesis_facts=thesis_facts,
        analysis_state=analysis_state,
        proposed_by=proposed_by,
        suggested_priority=suggested_priority,
        source_workflow_name=source_workflow_name,
        source_workflow_receipt_id=source_workflow_receipt_id,
        source_trace_ids=source_trace_ids,
        source_step_ids=source_step_ids,
        member_count=len(members),
        created_at=datetime.now(timezone.utc),
    )

    store = instance.get_entity_proposal_store()
    try:
        with store.transaction():
            store.save_proposal(proposal)
            store.save_members(proposal.proposal_id, members)
    finally:
        store.close()

    return ProposeEntityChangesResult(
        proposal_id=proposal.proposal_id,
        status=proposal.status,
        member_count=proposal.member_count,
    )


def service_get_entity_proposal(
    instance: InstanceProtocol,
    proposal_id: str,
) -> GetEntityProposalResult:
    """Load an entity proposal with its members and resolution details."""
    store = instance.get_entity_proposal_store()
    try:
        proposal = store.get_proposal(proposal_id)
        if proposal is None:
            raise EntityProposalNotFoundError(proposal_id)
        members = store.get_members(proposal_id)
        if proposal.resolution_id is not None:
            proposal.resolution = store.get_resolution(proposal.resolution_id)
        return GetEntityProposalResult(proposal=proposal, members=members)
    finally:
        store.close()


def service_list_entity_proposals(
    instance: InstanceProtocol,
    *,
    status: Literal["pending_review", "applying", "resolved"] | None = None,
    limit: int = 50,
) -> ListEntityProposalsResult:
    """List entity proposals with optional status filter."""
    if status is not None and status not in ("pending_review", "applying", "resolved"):
        raise ConfigError("Invalid status. Use: pending_review, applying, resolved")

    store = instance.get_entity_proposal_store()
    try:
        proposals = store.list_proposals(status=status, limit=limit)
        total = store.count_proposals(status=status)
        return ListEntityProposalsResult(proposals=proposals, total=total)
    finally:
        store.close()


def service_resolve_entity_proposal(
    instance: InstanceProtocol,
    proposal_id: str,
    action: Literal["approve", "reject"],
    *,
    rationale: str = "",
    resolved_by: Literal["human", "ai_review"] = "human",
) -> ResolveEntityProposalResult:
    """Resolve an entity proposal — approve applies changes, reject records the decision."""
    if action not in ("approve", "reject"):
        raise ConfigError("action must be one of: approve, reject")
    if resolved_by not in ("human", "ai_review"):
        raise ConfigError("resolved_by must be one of: human, ai_review")

    store = instance.get_entity_proposal_store()
    try:
        proposal = store.get_proposal(proposal_id)
        if proposal is None:
            raise EntityProposalNotFoundError(proposal_id)
        members = store.get_members(proposal_id)
        if proposal.status == "resolved":
            raise ConfigError("Entity proposal already resolved")
        if proposal.status == "applying":
            raise ConfigError("Entity proposal is already applying")
    except Exception:
        store.close()
        raise

    builder = ReceiptBuilder(
        operation_type="entity_proposal_resolve",
        parameters={"proposal_id": proposal_id, "action": action},
    )

    result: ResolveEntityProposalResult | None = None
    _exc: CoreError | None = None
    try:
        if action == "reject":
            with store.transaction():
                resolution_id = store.save_resolution(proposal_id, "reject", rationale, resolved_by)
                store.update_proposal_status(proposal_id, "resolved", resolution_id)
            builder.mark_committed()
            result = ResolveEntityProposalResult(
                proposal_id=proposal_id,
                action="reject",
                entities_created=0,
                entities_patched=0,
                resolution_id=resolution_id,
            )
        else:
            instance.invalidate_graph_cache()
            config = instance.load_config()
            graph = instance.load_graph()

            errors: list[str] = []
            for index, member in enumerate(members, start=1):
                if member.entity_type not in config.entity_types:
                    errors.append(
                        f"Member {index}: type '{member.entity_type}' not found in config"
                    )
                    builder.record_validation(
                        passed=False,
                        detail={"member": index, "error": "type not found"},
                    )
                    continue
                if member.operation == "create" and graph.has_entity(
                    member.entity_type, member.entity_id
                ):
                    errors.append(
                        f"Member {index}: entity "
                        f"{member.entity_type}:{member.entity_id} already exists"
                    )
                    builder.record_validation(
                        passed=False,
                        detail={"member": index, "error": "entity already exists"},
                    )
                    continue
                if member.operation == "patch" and not graph.has_entity(
                    member.entity_type, member.entity_id
                ):
                    errors.append(
                        f"Member {index}: entity {member.entity_type}:{member.entity_id} not found"
                    )
                    builder.record_validation(
                        passed=False,
                        detail={"member": index, "error": "entity not found"},
                    )
                    continue
                builder.record_validation(
                    passed=True,
                    detail={
                        "member": index,
                        "entity_type": member.entity_type,
                        "entity_id": member.entity_id,
                        "operation": member.operation,
                    },
                )

            if errors:
                raise DataValidationError(
                    f"Entity proposal approval failed with {len(errors)} error(s)",
                    errors=errors,
                )

            entities_created = 0
            entities_patched = 0
            with store.transaction():
                resolution_id = store.save_resolution(
                    proposal_id,
                    "approve",
                    rationale,
                    resolved_by,
                )
                store.update_proposal_status(proposal_id, "applying", resolution_id)

                for member in members:
                    if member.operation == "create":
                        graph.add_entity(
                            EntityInstance(
                                entity_type=member.entity_type,
                                entity_id=member.entity_id,
                                properties=dict(member.properties),
                            )
                        )
                        builder.record_entity_write(
                            member.entity_type,
                            member.entity_id,
                            is_update=False,
                        )
                        entities_created += 1
                    else:
                        graph.update_entity_properties(
                            member.entity_type,
                            member.entity_id,
                            dict(member.properties),
                        )
                        builder.record_entity_write(
                            member.entity_type,
                            member.entity_id,
                            is_update=True,
                        )
                        entities_patched += 1

                _save_graph(instance, graph)
                store.update_proposal_status(proposal_id, "resolved", resolution_id)

            builder.mark_committed()
            result = ResolveEntityProposalResult(
                proposal_id=proposal_id,
                action="approve",
                entities_created=entities_created,
                entities_patched=entities_patched,
                resolution_id=resolution_id,
            )
    except CoreError as e:
        _exc = e
        raise
    except Exception as exc:
        _exc = MutationError(f"Unexpected failure: {exc}")
        raise _exc from exc
    finally:
        store.close()
        receipt = builder.build()
        if _persist_receipt(instance, receipt):
            if _exc is not None:
                _exc.mutation_receipt_id = receipt.receipt_id
            elif result is not None:
                result.receipt_id = receipt.receipt_id

    return result  # type: ignore[return-value]
