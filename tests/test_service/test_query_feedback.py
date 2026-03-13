"""Tests for service layer query, feedback, and outcome functions."""

from __future__ import annotations

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.errors import (
    ConfigError,
    DataValidationError,
    QueryNotFoundError,
    ReceiptNotFoundError,
)
from cruxible_core.feedback.types import EdgeTarget
from cruxible_core.service import (
    service_feedback,
    service_outcome,
    service_query,
)

# ---------------------------------------------------------------------------
# service_query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_basic(self, populated_instance: CruxibleInstance) -> None:
        result = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert result.total_results >= 1
        assert result.receipt_id is not None
        assert result.steps_executed >= 1

    def test_persists_receipt(self, populated_instance: CruxibleInstance) -> None:
        result = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert result.receipt_id is not None
        store = populated_instance.get_receipt_store()
        try:
            receipt = store.get_receipt(result.receipt_id)
        finally:
            store.close()
        assert receipt is not None

    def test_bad_name(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(QueryNotFoundError):
            service_query(populated_instance, "nonexistent_query", {})


# ---------------------------------------------------------------------------
# service_feedback
# ---------------------------------------------------------------------------


def _edge_target() -> EdgeTarget:
    return EdgeTarget(
        from_type="Part",
        from_id="BP-1001",
        relationship="fits",
        to_type="Vehicle",
        to_id="V-2024-CIVIC-EX",
    )


class TestFeedback:
    def _run_query(self, instance: CruxibleInstance) -> str:
        """Run a query and return the receipt_id."""
        result = service_query(
            instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert result.receipt_id is not None
        return result.receipt_id

    def test_approve(self, populated_instance: CruxibleInstance) -> None:
        receipt_id = self._run_query(populated_instance)
        result = service_feedback(
            populated_instance,
            receipt_id=receipt_id,
            action="approve",
            source="human",
            target=_edge_target(),
        )
        assert result.feedback_id.startswith("FB-")
        assert result.applied is True

        graph = populated_instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")
        assert rel is not None
        assert rel.properties.get("review_status") == "human_approved"

    def test_validates_confidence(self, populated_instance: CruxibleInstance) -> None:
        receipt_id = self._run_query(populated_instance)
        with pytest.raises(DataValidationError, match="corrections.confidence"):
            service_feedback(
                populated_instance,
                receipt_id=receipt_id,
                action="correct",
                source="human",
                target=_edge_target(),
                corrections={"confidence": True},
            )

    def test_strips_provenance(self, populated_instance: CruxibleInstance) -> None:
        receipt_id = self._run_query(populated_instance)
        result = service_feedback(
            populated_instance,
            receipt_id=receipt_id,
            action="correct",
            source="human",
            target=_edge_target(),
            corrections={"_provenance": {"spoofed": True}, "confidence": 0.9},
        )
        assert result.applied is True

        graph = populated_instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1001", "Vehicle", "V-2024-CIVIC-EX", "fits")
        assert rel is not None
        # _provenance should not contain the spoofed value
        prov = rel.properties.get("_provenance", {})
        assert prov.get("spoofed") is None

    def test_missing_receipt(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ReceiptNotFoundError):
            service_feedback(
                populated_instance,
                receipt_id="nonexistent-receipt",
                action="approve",
                source="human",
                target=_edge_target(),
            )

    def test_store_lifecycle(self, populated_instance: CruxibleInstance) -> None:
        """Verify stores are closed even on error."""
        with pytest.raises(ReceiptNotFoundError):
            service_feedback(
                populated_instance,
                receipt_id="bad-id",
                action="approve",
                source="human",
                target=_edge_target(),
            )
        # Should be able to open stores again without issues
        store = populated_instance.get_receipt_store()
        store.close()

    def test_invalid_action(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="Invalid action"):
            service_feedback(
                populated_instance,
                receipt_id="any",
                action="bogus",  # type: ignore[arg-type]
                source="human",
                target=_edge_target(),
            )

    def test_invalid_source(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="Invalid source"):
            service_feedback(
                populated_instance,
                receipt_id="any",
                action="approve",
                source="bogus",  # type: ignore[arg-type]
                target=_edge_target(),
            )

    def test_invalid_corrections_type(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="corrections must be an object"):
            service_feedback(
                populated_instance,
                receipt_id="any",
                action="correct",
                source="human",
                target=_edge_target(),
                corrections="not a dict",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# service_outcome
# ---------------------------------------------------------------------------


class TestOutcome:
    def _run_query(self, instance: CruxibleInstance) -> str:
        result = service_query(
            instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert result.receipt_id is not None
        return result.receipt_id

    def test_basic(self, populated_instance: CruxibleInstance) -> None:
        receipt_id = self._run_query(populated_instance)
        result = service_outcome(
            populated_instance,
            receipt_id=receipt_id,
            outcome="correct",
        )
        assert result.outcome_id.startswith("OUT-")

    def test_missing_receipt(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ReceiptNotFoundError):
            service_outcome(
                populated_instance,
                receipt_id="nonexistent-receipt",
                outcome="correct",
            )

    def test_invalid_value(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="Invalid outcome"):
            service_outcome(
                populated_instance,
                receipt_id="any",
                outcome="bogus",  # type: ignore[arg-type]
            )

    def test_invalid_detail_type(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="detail must be an object"):
            service_outcome(
                populated_instance,
                receipt_id="any",
                outcome="correct",
                detail="not a dict",  # type: ignore[arg-type]
            )
