"""Tests for service layer validate, find_candidates, and evaluate functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.config.schema import (
    ConstraintSchema,
    FeedbackProfileSchema,
    FeedbackReasonCodeSchema,
)
from cruxible_core.errors import ConfigError
from cruxible_core.feedback.types import EdgeTarget
from cruxible_core.query.candidates import MatchRule
from cruxible_core.service import (
    service_analyze_feedback,
    service_evaluate,
    service_feedback,
    service_find_candidates,
    service_query,
    service_validate,
)
from tests.test_cli.conftest import CAR_PARTS_YAML

# ---------------------------------------------------------------------------
# service_validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_file(self, tmp_project: Path) -> None:
        result = service_validate(config_path=str(tmp_project / "config.yaml"))
        assert result.config is not None
        assert result.config.name == "car_parts_compatibility"

    def test_yaml_string(self) -> None:
        result = service_validate(config_yaml=CAR_PARTS_YAML)
        assert result.config is not None
        assert "Vehicle" in result.config.entity_types

    def test_semantic_errors(self, tmp_path: Path) -> None:
        bad_yaml = """\
version: "1.0"
name: broken
entity_types:
  Thing:
    properties:
      id:
        type: string
        primary_key: true
relationships:
  - name: links
    from: Thing
    to: Nonexistent
"""
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(bad_yaml)
        with pytest.raises(ConfigError, match="cross-reference"):
            service_validate(config_path=str(config_file))

    def test_no_source_error(self) -> None:
        with pytest.raises(ConfigError, match="Provide exactly one"):
            service_validate()

    def test_returns_warnings(self, tmp_path: Path) -> None:
        """Config with unverifiable constraint rule produces a warning."""
        yaml_with_constraint = """\
version: "1.0"
name: with_constraints
entity_types:
  Vehicle:
    properties:
      vehicle_id:
        type: string
        primary_key: true
  Part:
    properties:
      part_number:
        type: string
        primary_key: true
relationships:
  - name: fits
    from: Part
    to: Vehicle
constraints:
  - name: weird_rule
    rule: "some_unparseable_thing"
    severity: warning
ingestion: {}
"""
        config_file = tmp_path / "constraints.yaml"
        config_file.write_text(yaml_with_constraint)
        result = service_validate(config_path=str(config_file))
        assert len(result.warnings) >= 1
        assert any("could not verify" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# service_find_candidates
# ---------------------------------------------------------------------------


class TestFindCandidates:
    def test_property_match(self, populated_instance: CruxibleInstance) -> None:
        candidates = service_find_candidates(
            populated_instance,
            relationship_type="replaces",
            strategy="property_match",
            match_rules=[MatchRule(from_property="category", to_property="category")],
            min_confidence=0.5,
        )
        # Both parts have category=brakes, and BP-1002->BP-1001 replaces exists,
        # so we may or may not get candidates depending on existing edges
        assert isinstance(candidates, list)

    def test_shared_neighbors(self, populated_instance: CruxibleInstance) -> None:
        candidates = service_find_candidates(
            populated_instance,
            relationship_type="replaces",
            strategy="shared_neighbors",
            via_relationship="fits",
            min_overlap=0.1,
            min_distinct_neighbors=1,
        )
        assert isinstance(candidates, list)

    def test_bad_relationship(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(Exception):  # RelationshipNotFoundError
            service_find_candidates(
                populated_instance,
                relationship_type="nonexistent",
                strategy="property_match",
                match_rules=[MatchRule(from_property="name", to_property="name")],
            )

    def test_invalid_strategy(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="Invalid strategy"):
            service_find_candidates(
                populated_instance,
                relationship_type="replaces",
                strategy="bogus",  # type: ignore[arg-type]
            )

    def test_invalid_min_neighbors(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="min_distinct_neighbors"):
            service_find_candidates(
                populated_instance,
                relationship_type="replaces",
                strategy="shared_neighbors",
                via_relationship="fits",
                min_distinct_neighbors=0,
            )


# ---------------------------------------------------------------------------
# service_evaluate
# ---------------------------------------------------------------------------


class TestEvaluate:
    def test_basic(self, populated_instance: CruxibleInstance) -> None:
        report = service_evaluate(populated_instance)
        assert report.entity_count >= 4
        assert report.edge_count >= 3
        assert isinstance(report.findings, list)
        assert isinstance(report.summary, dict)
        assert isinstance(report.quality_summary, dict)

    def test_constraint_summary_includes_zero_count_constraints(
        self, populated_instance: CruxibleInstance
    ) -> None:
        config = populated_instance.load_config()
        config.constraints.append(
            ConstraintSchema(
                name="replaces_category_match",
                rule="replaces.FROM.category == replaces.TO.category",
            )
        )
        populated_instance.save_config(config)

        report = service_evaluate(populated_instance)
        assert report.constraint_summary["replaces_category_match"] == 0

    def test_with_threshold(self, populated_instance: CruxibleInstance) -> None:
        report = service_evaluate(populated_instance, confidence_threshold=0.99)
        # With a very high threshold, the replaces edge (0.95) should be flagged
        low_conf = [f for f in report.findings if f.category == "low_confidence_edge"]
        assert len(low_conf) >= 1

    def test_exclude_orphan_types(self, populated_instance: CruxibleInstance) -> None:
        report_all = service_evaluate(populated_instance)
        report_excl = service_evaluate(populated_instance, exclude_orphan_types=["Vehicle", "Part"])
        orphans_all = sum(1 for f in report_all.findings if f.category == "orphan_entity")
        orphans_excl = sum(1 for f in report_excl.findings if f.category == "orphan_entity")
        assert orphans_excl <= orphans_all


class TestAnalyzeFeedback:
    def test_decision_policy_suggestion_and_uncoded_feedback(
        self, populated_instance: CruxibleInstance
    ) -> None:
        config = populated_instance.load_config()
        config.feedback_profiles["fits"] = FeedbackProfileSchema(
            version=2,
            reason_codes={
                "legacy_unsupported": FeedbackReasonCodeSchema(
                    description="Legacy environment is unsupported",
                    remediation_hint="decision_policy",
                    required_scope_keys=["category", "make"],
                )
            },
            scope_keys={
                "category": "FROM.category",
                "make": "TO.make",
            },
        )
        populated_instance.save_config(config)

        query_one = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        query_two = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert query_one.receipt_id is not None
        assert query_two.receipt_id is not None

        service_feedback(
            populated_instance,
            receipt_id=query_one.receipt_id,
            action="reject",
            source="system",
            target=_feedback_target("BP-1001"),
            reason="Legacy unsupported",
            reason_code="legacy_unsupported",
            scope_hints={"category": "brakes", "make": "Honda"},
        )
        service_feedback(
            populated_instance,
            receipt_id=query_two.receipt_id,
            action="reject",
            source="system",
            target=_feedback_target("BP-1002"),
            reason="Legacy unsupported",
            reason_code="legacy_unsupported",
            scope_hints={"category": "brakes", "make": "Honda"},
        )
        service_feedback(
            populated_instance,
            receipt_id=query_two.receipt_id,
            action="reject",
            source="human",
            target=_feedback_target("BP-1002"),
            reason="freeform uncoded reason",
        )

        result = service_analyze_feedback(
            populated_instance,
            "fits",
            min_support=2,
            decision_surface_type="query",
            decision_surface_name="parts_for_vehicle",
        )

        assert result.feedback_count == 3
        assert result.uncoded_feedback_count == 1
        assert len(result.coded_groups) == 1
        assert result.coded_groups[0].reason_code == "legacy_unsupported"
        assert len(result.decision_policy_suggestions) == 1
        suggestion = result.decision_policy_suggestions[0]
        assert suggestion.applies_to == "query"
        assert suggestion.effect == "suppress"
        assert suggestion.query_name == "parts_for_vehicle"
        assert suggestion.match["from"] == {"category": "brakes"}
        assert suggestion.match["to"] == {"make": "Honda"}
        assert result.constraint_suggestions == []

    def test_analysis_uses_stored_remediation_hint_across_profile_versions(
        self, populated_instance: CruxibleInstance
    ) -> None:
        config = populated_instance.load_config()
        config.feedback_profiles["fits"] = FeedbackProfileSchema(
            version=1,
            reason_codes={
                "legacy_unsupported": FeedbackReasonCodeSchema(
                    description="Legacy environment is unsupported",
                    remediation_hint="decision_policy",
                    required_scope_keys=["category", "make"],
                )
            },
            scope_keys={
                "category": "FROM.category",
                "make": "TO.make",
            },
        )
        populated_instance.save_config(config)

        query_one = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        query_two = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert query_one.receipt_id is not None
        assert query_two.receipt_id is not None

        service_feedback(
            populated_instance,
            receipt_id=query_one.receipt_id,
            action="reject",
            source="system",
            target=_feedback_target("BP-1001"),
            reason="Legacy unsupported",
            reason_code="legacy_unsupported",
            scope_hints={"category": "brakes", "make": "Honda"},
        )
        service_feedback(
            populated_instance,
            receipt_id=query_two.receipt_id,
            action="reject",
            source="system",
            target=_feedback_target("BP-1002"),
            reason="Legacy unsupported",
            reason_code="legacy_unsupported",
            scope_hints={"category": "brakes", "make": "Honda"},
        )

        config = populated_instance.load_config()
        config.feedback_profiles["fits"] = FeedbackProfileSchema(
            version=2,
            reason_codes={
                "legacy_unsupported": FeedbackReasonCodeSchema(
                    description="Legacy environment is unsupported",
                    remediation_hint="constraint",
                    required_scope_keys=["category", "make"],
                )
            },
            scope_keys={
                "category": "FROM.category",
                "make": "TO.make",
            },
        )
        populated_instance.save_config(config)

        result = service_analyze_feedback(
            populated_instance,
            "fits",
            min_support=2,
            decision_surface_type="query",
            decision_surface_name="parts_for_vehicle",
        )

        assert len(result.decision_policy_suggestions) == 1
        assert result.constraint_suggestions == []
        assert any("using stored remediation hints" in warning for warning in result.warnings)

    def test_constraint_suggestions_use_feedback_snapshot_not_current_graph(
        self, populated_instance: CruxibleInstance
    ) -> None:
        config = populated_instance.load_config()
        config.feedback_profiles["fits"] = FeedbackProfileSchema(
            version=1,
            reason_codes={
                "fitment_mismatch": FeedbackReasonCodeSchema(
                    description="Part category mismatches vehicle make",
                    remediation_hint="constraint",
                    required_scope_keys=["category", "make"],
                )
            },
            scope_keys={
                "category": "FROM.category",
                "make": "TO.make",
            },
        )
        populated_instance.save_config(config)

        query_one = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        query_two = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert query_one.receipt_id is not None
        assert query_two.receipt_id is not None

        service_feedback(
            populated_instance,
            receipt_id=query_one.receipt_id,
            action="reject",
            source="system",
            target=_feedback_target("BP-1001"),
            reason="Mismatch",
            reason_code="fitment_mismatch",
            scope_hints={"category": "brakes", "make": "Honda"},
        )
        service_feedback(
            populated_instance,
            receipt_id=query_two.receipt_id,
            action="reject",
            source="system",
            target=_feedback_target("BP-1002"),
            reason="Mismatch",
            reason_code="fitment_mismatch",
            scope_hints={"category": "brakes", "make": "Honda"},
        )

        graph = populated_instance.load_graph()
        part = graph.get_entity("Part", "BP-1001")
        vehicle = graph.get_entity("Vehicle", "V-2024-CIVIC-EX")
        assert part is not None
        assert vehicle is not None
        part.properties["category"] = "Honda"
        vehicle.properties["make"] = "Honda"
        populated_instance.save_graph(graph)

        result = service_analyze_feedback(
            populated_instance,
            "fits",
            min_support=2,
            decision_surface_type="query",
            decision_surface_name="parts_for_vehicle",
            property_pairs=[("category", "make")],
        )

        assert len(result.constraint_suggestions) == 1
        assert result.constraint_suggestions[0].rule == "fits.FROM.category == fits.TO.make"


def _feedback_target(part_id: str) -> EdgeTarget:
    return EdgeTarget(
        from_type="Part",
        from_id=part_id,
        relationship="fits",
        to_type="Vehicle",
        to_id="V-2024-CIVIC-EX",
    )
