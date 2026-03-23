"""Tests for batch feedback and governed entity proposals."""

from __future__ import annotations

import pytest

from cruxible_core.entity_proposal.types import EntityChangeMember
from cruxible_core.errors import DataValidationError, ReceiptNotFoundError
from cruxible_core.feedback.types import EdgeTarget, FeedbackBatchItem
from cruxible_core.graph.types import EntityInstance
from cruxible_core.service import (
    service_feedback_batch,
    service_get_entity_proposal,
    service_propose_entity_changes,
    service_query,
    service_resolve_entity_proposal,
)


def test_service_feedback_batch_applies_atomically(populated_instance):
    query_result = service_query(
        populated_instance,
        "parts_for_vehicle",
        {"vehicle_id": "V-2024-CIVIC-EX"},
    )
    receipt_id = query_result.receipt_id
    assert receipt_id is not None

    result = service_feedback_batch(
        populated_instance,
        [
            FeedbackBatchItem(
                receipt_id=receipt_id,
                action="approve",
                target=EdgeTarget(
                    from_type="Part",
                    from_id="BP-1001",
                    relationship="fits",
                    to_type="Vehicle",
                    to_id="V-2024-CIVIC-EX",
                ),
            ),
            FeedbackBatchItem(
                receipt_id=receipt_id,
                action="reject",
                target=EdgeTarget(
                    from_type="Part",
                    from_id="BP-1002",
                    relationship="fits",
                    to_type="Vehicle",
                    to_id="V-2024-CIVIC-EX",
                ),
                reason="bad fitment",
            ),
        ],
        source="human",
    )

    assert result.total == 2
    assert result.applied_count == 2
    assert len(result.feedback_ids) == 2
    assert result.receipt_id is not None

    graph = populated_instance.load_graph()
    approved = graph.get_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")
    rejected = graph.get_relationship("Part", "BP-1002", "Vehicle", "V-2024-CIVIC-EX", "fits")
    assert approved is not None
    assert approved.properties["review_status"] == "human_approved"
    assert rejected is not None
    assert rejected.properties["review_status"] == "human_rejected"

    feedback_store = populated_instance.get_feedback_store()
    try:
        records = feedback_store.list_feedback(limit=10)
    finally:
        feedback_store.close()
    assert len(records) == 2
    assert {record.receipt_id for record in records} == {receipt_id}


def test_service_feedback_batch_invalid_receipt_rolls_back(populated_instance):
    with pytest.raises(ReceiptNotFoundError):
        service_feedback_batch(
            populated_instance,
            [
                FeedbackBatchItem(
                    receipt_id="RCP-missing",
                    action="approve",
                    target=EdgeTarget(
                        from_type="Part",
                        from_id="BP-1001",
                        relationship="fits",
                        to_type="Vehicle",
                        to_id="V-2024-CIVIC-EX",
                    ),
                )
            ],
            source="human",
        )

    feedback_store = populated_instance.get_feedback_store()
    try:
        assert feedback_store.count_feedback() == 0
    finally:
        feedback_store.close()


def test_entity_proposal_create_and_patch_flow(populated_instance):
    propose = service_propose_entity_changes(
        populated_instance,
        [
            EntityChangeMember(
                entity_type="Vehicle",
                entity_id="V-2025-PILOT-ELITE",
                operation="create",
                properties={
                    "vehicle_id": "V-2025-PILOT-ELITE",
                    "year": 2025,
                    "make": "Honda",
                    "model": "Pilot",
                },
            ),
            EntityChangeMember(
                entity_type="Part",
                entity_id="BP-1001",
                operation="patch",
                properties={"price": 59.99},
            ),
        ],
        thesis_text="Curated entity changes",
        proposed_by="human",
    )
    assert propose.status == "pending_review"

    loaded = service_get_entity_proposal(populated_instance, propose.proposal_id)
    assert loaded.proposal.member_count == 2
    assert len(loaded.members) == 2

    resolved = service_resolve_entity_proposal(
        populated_instance,
        propose.proposal_id,
        "approve",
        rationale="looks good",
        resolved_by="human",
    )
    assert resolved.entities_created == 1
    assert resolved.entities_patched == 1
    assert resolved.receipt_id is not None

    graph = populated_instance.load_graph()
    created = graph.get_entity("Vehicle", "V-2025-PILOT-ELITE")
    assert created == EntityInstance(
        entity_type="Vehicle",
        entity_id="V-2025-PILOT-ELITE",
        properties={
            "vehicle_id": "V-2025-PILOT-ELITE",
            "year": 2025,
            "make": "Honda",
            "model": "Pilot",
        },
    )
    patched = graph.get_entity("Part", "BP-1001")
    assert patched is not None
    assert patched.properties["price"] == 59.99
    assert patched.properties["name"] == "Ceramic Brake Pads"


def test_entity_proposal_invalid_approval_leaves_pending(populated_instance):
    propose = service_propose_entity_changes(
        populated_instance,
        [
            EntityChangeMember(
                entity_type="Part",
                entity_id="BP-1001",
                operation="create",
                properties={"part_number": "BP-1001", "name": "Duplicate"},
            )
        ],
    )

    with pytest.raises(DataValidationError, match="already exists"):
        service_resolve_entity_proposal(
            populated_instance,
            propose.proposal_id,
            "approve",
        )

    loaded = service_get_entity_proposal(populated_instance, propose.proposal_id)
    assert loaded.proposal.status == "pending_review"
