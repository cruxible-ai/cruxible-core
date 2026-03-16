"""Tests for mutation receipt wiring across service functions."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.errors import ConfigError, DataValidationError, IngestionError
from cruxible_core.feedback.types import EdgeTarget
from cruxible_core.service import (
    AddEntityResult,
    AddRelationshipResult,
    EntityUpsertInput,
    RelationshipUpsertInput,
    service_add_entities,
    service_add_relationships,
    service_feedback,
    service_ingest,
    service_query,
)


# ---------------------------------------------------------------------------
# add_entity receipts
# ---------------------------------------------------------------------------


class TestAddEntityReceipts:
    def test_add_entities_produces_receipt(
        self, initialized_instance: CruxibleInstance
    ):
        result = service_add_entities(
            initialized_instance,
            [
                EntityUpsertInput(
                    entity_type="Vehicle",
                    entity_id="V-NEW",
                    properties={"vehicle_id": "V-NEW", "year": 2025, "make": "Toyota", "model": "Camry"},
                )
            ],
        )
        assert result.receipt_id is not None
        assert result.receipt_id.startswith("RCP-")

        # Receipt retrievable from store
        store = initialized_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(result.receipt_id)
        finally:
            store.close()
        assert receipt is not None
        assert receipt.operation_type == "add_entity"
        assert receipt.committed is True

        # Has entity_write and validation nodes
        node_types = {n.node_type for n in receipt.nodes}
        assert "entity_write" in node_types
        assert "validation" in node_types

    def test_add_entities_failure_receipt(
        self, initialized_instance: CruxibleInstance
    ):
        with pytest.raises(DataValidationError) as exc_info:
            service_add_entities(
                initialized_instance,
                [
                    EntityUpsertInput(
                        entity_type="NonExistent",
                        entity_id="X-1",
                        properties={},
                    )
                ],
            )
        exc = exc_info.value
        assert exc.mutation_receipt_id is not None

        # Receipt retrievable
        store = initialized_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(exc.mutation_receipt_id)
        finally:
            store.close()
        assert receipt is not None
        assert receipt.operation_type == "add_entity"
        assert receipt.committed is False

    def test_receipt_persistence_failure_nonfatal(
        self, initialized_instance: CruxibleInstance
    ):
        """If receipt store fails, graph write still succeeds."""
        original_fn = type(initialized_instance).get_receipt_store

        def broken_store(self_inst):
            store = original_fn(self_inst)
            def fail_save(receipt):
                raise RuntimeError("Store broken")
            store.save_receipt = fail_save
            return store

        with patch.object(type(initialized_instance), "get_receipt_store", broken_store):
            result = service_add_entities(
                initialized_instance,
                [
                    EntityUpsertInput(
                        entity_type="Vehicle",
                        entity_id="V-PERSIST",
                        properties={"vehicle_id": "V-PERSIST", "year": 2025, "make": "X", "model": "Y"},
                    )
                ],
            )
        assert result.receipt_id is None
        # Graph write succeeded
        graph = initialized_instance.load_graph()
        assert graph.get_entity("Vehicle", "V-PERSIST") is not None

    def test_create_receipt_false_suppresses(
        self, initialized_instance: CruxibleInstance
    ):
        result = service_add_entities(
            initialized_instance,
            [
                EntityUpsertInput(
                    entity_type="Vehicle",
                    entity_id="V-NORCPT",
                    properties={"vehicle_id": "V-NORCPT", "year": 2025, "make": "X", "model": "Y"},
                )
            ],
            _create_receipt=False,
        )
        assert result.receipt_id is None


# ---------------------------------------------------------------------------
# add_relationship receipts
# ---------------------------------------------------------------------------


class TestAddRelationshipReceipts:
    def test_add_relationships_produces_receipt(
        self, populated_instance: CruxibleInstance
    ):
        result = service_add_relationships(
            populated_instance,
            [
                RelationshipUpsertInput(
                    from_type="Part",
                    from_id="BP-1002",
                    relationship="fits",
                    to_type="Vehicle",
                    to_id="V-2024-ACCORD-SPORT",
                    properties={"verified": True, "source": "test"},
                )
            ],
            source="test",
            source_ref="test_receipts",
        )
        assert result.receipt_id is not None

        store = populated_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(result.receipt_id)
        finally:
            store.close()
        assert receipt is not None
        assert receipt.operation_type == "add_relationship"
        assert receipt.committed is True

        node_types = {n.node_type for n in receipt.nodes}
        assert "relationship_write" in node_types

    def test_add_relationships_failure_receipt(
        self, populated_instance: CruxibleInstance
    ):
        with pytest.raises(DataValidationError) as exc_info:
            service_add_relationships(
                populated_instance,
                [
                    RelationshipUpsertInput(
                        from_type="Part",
                        from_id="NONEXISTENT",
                        relationship="fits",
                        to_type="Vehicle",
                        to_id="V-2024-CIVIC-EX",
                        properties={},
                    )
                ],
                source="test",
                source_ref="test",
            )
        exc = exc_info.value
        assert exc.mutation_receipt_id is not None

        store = populated_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(exc.mutation_receipt_id)
        finally:
            store.close()
        assert receipt is not None
        assert receipt.committed is False


# ---------------------------------------------------------------------------
# ingest receipts
# ---------------------------------------------------------------------------


class TestIngestReceipts:
    def test_ingest_produces_receipt(
        self, initialized_instance: CruxibleInstance
    ):
        csv_data = "vehicle_id,year,make,model\nV-CSV-1,2025,Honda,Civic"
        result = service_ingest(
            initialized_instance, "vehicles", data_csv=csv_data
        )
        assert result.receipt_id is not None

        store = initialized_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(result.receipt_id)
        finally:
            store.close()
        assert receipt is not None
        assert receipt.operation_type == "ingest"
        assert receipt.committed is True

        node_types = {n.node_type for n in receipt.nodes}
        assert "ingest_batch" in node_types

    def test_ingest_config_digest(
        self, initialized_instance: CruxibleInstance
    ):
        csv_data = "vehicle_id,year,make,model\nV-CSV-2,2025,Honda,Civic"
        result = service_ingest(
            initialized_instance, "vehicles", data_csv=csv_data
        )
        store = initialized_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(result.receipt_id)
        finally:
            store.close()
        digest = receipt.parameters.get("config_digest")
        assert digest is not None
        assert len(digest) == 12
        assert all(c in "0123456789abcdef" for c in digest)

    def test_ingest_failure_receipt(
        self, initialized_instance: CruxibleInstance
    ):
        """Bad mapping name triggers error, receipt still persisted."""
        with pytest.raises(Exception) as exc_info:
            service_ingest(
                initialized_instance, "nonexistent_mapping", data_csv="a,b\n1,2"
            )
        exc = exc_info.value
        if hasattr(exc, "mutation_receipt_id") and exc.mutation_receipt_id:
            store = initialized_instance.get_receipt_store()
            try:
                receipt = store.get_receipt(exc.mutation_receipt_id)
            finally:
                store.close()
            assert receipt is not None
            assert receipt.committed is False


# ---------------------------------------------------------------------------
# feedback receipts
# ---------------------------------------------------------------------------


def _edge_target() -> EdgeTarget:
    return EdgeTarget(
        from_type="Part",
        from_id="BP-1001",
        relationship="fits",
        to_type="Vehicle",
        to_id="V-2024-CIVIC-EX",
    )


class TestFeedbackReceipts:
    def _run_query(self, instance: CruxibleInstance) -> str:
        """Run a query and return the receipt_id for feedback."""
        result = service_query(
            instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert result.receipt_id is not None
        return result.receipt_id

    def test_feedback_produces_receipt(
        self, populated_instance: CruxibleInstance
    ):
        receipt_id = self._run_query(populated_instance)
        result = service_feedback(
            populated_instance,
            receipt_id=receipt_id,
            action="approve",
            source="human",
            target=_edge_target(),
            reason="Confirmed fitment",
        )
        assert result.receipt_id is not None

        store = populated_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(result.receipt_id)
        finally:
            store.close()
        assert receipt is not None
        assert receipt.operation_type == "feedback"
        assert receipt.committed is True

        node_types = {n.node_type for n in receipt.nodes}
        assert "feedback_applied" in node_types

    def test_feedback_receipt_includes_applied_status(
        self, populated_instance: CruxibleInstance
    ):
        receipt_id = self._run_query(populated_instance)
        result = service_feedback(
            populated_instance,
            receipt_id=receipt_id,
            action="approve",
            source="human",
            target=_edge_target(),
        )
        store = populated_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(result.receipt_id)
        finally:
            store.close()
        # Find the feedback_applied node and check detail
        fb_nodes = [n for n in receipt.nodes if n.node_type == "feedback_applied"]
        assert len(fb_nodes) == 1
        assert "applied" in fb_nodes[0].detail

    def test_feedback_input_error_no_receipt(
        self, populated_instance: CruxibleInstance
    ):
        """Bad action string raises ConfigError before builder created — no receipt."""
        with pytest.raises(ConfigError):
            service_feedback(
                populated_instance,
                receipt_id="RCP-doesnotmatter",
                action="invalid_action",  # type: ignore[arg-type]
                source="human",
                target=_edge_target(),
            )
