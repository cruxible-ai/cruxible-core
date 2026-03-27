"""Tests for config composition (base + overlay merge)."""

from __future__ import annotations

import pytest

from cruxible_core.config.composer import compose_configs
from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError

_BASE_YAML = {
    "version": "1.0",
    "name": "base",
    "kind": "world_model",
    "entity_types": {
        "Case": {
            "properties": {
                "case_id": {"type": "string", "primary_key": True},
            },
        },
    },
    "relationships": [
        {"name": "cites", "from": "Case", "to": "Case"},
    ],
}


def _base() -> CoreConfig:
    return CoreConfig.model_validate(_BASE_YAML)


def _overlay(extra: dict) -> CoreConfig:
    data = {
        "version": "1.0",
        "name": "fork",
        "extends": "base.yaml",
        "entity_types": {},
        "relationships": [],
        **extra,
    }
    return CoreConfig.model_validate(data)


# --- feedback_profiles (keyed-map merge) ---


class TestFeedbackProfilesComposition:
    def test_overlay_adds_new_feedback_profile(self) -> None:
        overlay = _overlay({
            "feedback_profiles": {
                "cites": {
                    "version": 1,
                    "reason_codes": {
                        "bad_cite": {
                            "description": "Citation is wrong",
                            "remediation_hint": "constraint",
                        },
                    },
                    "scope_keys": {},
                },
            },
        })
        composed = compose_configs(_base(), overlay)
        assert "cites" in composed.feedback_profiles
        assert "bad_cite" in composed.feedback_profiles["cites"].reason_codes

    def test_overlay_cannot_redefine_base_feedback_profile(self) -> None:
        base = _base()
        base_data = _BASE_YAML.copy()
        base_data["feedback_profiles"] = {
            "cites": {"version": 1, "reason_codes": {}, "scope_keys": {}},
        }
        base = CoreConfig.model_validate(base_data)

        overlay = _overlay({
            "feedback_profiles": {
                "cites": {"version": 2, "reason_codes": {}, "scope_keys": {}},
            },
        })
        with pytest.raises(ConfigError, match="redefine upstream.*feedback_profiles.*cites"):
            compose_configs(base, overlay)

    def test_both_base_and_overlay_feedback_profiles_merged(self) -> None:
        base_data = {**_BASE_YAML, "feedback_profiles": {
            "cites": {"version": 1, "reason_codes": {}, "scope_keys": {}},
        }}
        base = CoreConfig.model_validate(base_data)

        overlay = _overlay({
            "feedback_profiles": {
                "follows": {"version": 1, "reason_codes": {}, "scope_keys": {}},
            },
        })
        composed = compose_configs(base, overlay)
        assert "cites" in composed.feedback_profiles
        assert "follows" in composed.feedback_profiles


# --- outcome_profiles (keyed-map merge) ---


class TestOutcomeProfilesComposition:
    def test_overlay_adds_new_outcome_profile(self) -> None:
        overlay = _overlay({
            "outcome_profiles": {
                "cites_resolution": {
                    "anchor_type": "resolution",
                    "relationship_type": "cites",
                    "version": 1,
                    "outcome_codes": {},
                    "scope_keys": {},
                },
            },
        })
        composed = compose_configs(_base(), overlay)
        assert "cites_resolution" in composed.outcome_profiles

    def test_overlay_cannot_redefine_base_outcome_profile(self) -> None:
        base_data = {**_BASE_YAML, "outcome_profiles": {
            "cites_resolution": {
                "anchor_type": "resolution",
                "relationship_type": "cites",
                "version": 1,
            },
        }}
        base = CoreConfig.model_validate(base_data)

        overlay = _overlay({
            "outcome_profiles": {
                "cites_resolution": {
                    "anchor_type": "resolution",
                    "relationship_type": "cites",
                    "version": 2,
                },
            },
        })
        with pytest.raises(ConfigError, match="redefine upstream.*outcome_profiles.*cites_resolution"):
            compose_configs(base, overlay)


# --- decision_policies (safe-list append) ---


class TestDecisionPoliciesComposition:
    def test_overlay_appends_decision_policies(self) -> None:
        base_data = {**_BASE_YAML, "decision_policies": [
            {
                "name": "base_policy",
                "applies_to": "query",
                "query_name": "find_cases",
                "relationship_type": "cites",
                "effect": "suppress",
            },
        ], "named_queries": {
            "find_cases": {
                "entry_point": "Case",
                "returns": "Case",
                "traversal": [{"relationship": "cites", "direction": "outgoing"}],
            },
        }}
        base = CoreConfig.model_validate(base_data)

        overlay = _overlay({
            "decision_policies": [
                {
                    "name": "fork_policy",
                    "applies_to": "query",
                    "query_name": "find_cases",
                    "relationship_type": "cites",
                    "effect": "suppress",
                    "match": {"from": {"case_id": "CASE-X"}},
                },
            ],
        })
        composed = compose_configs(base, overlay)
        names = [p.name for p in composed.decision_policies]
        assert names == ["base_policy", "fork_policy"]

    def test_overlay_decision_policies_without_base(self) -> None:
        overlay = _overlay({
            "decision_policies": [
                {
                    "name": "fork_only",
                    "applies_to": "query",
                    "query_name": "find_cases",
                    "relationship_type": "cites",
                    "effect": "suppress",
                },
            ],
        })
        composed = compose_configs(_base(), overlay)
        assert len(composed.decision_policies) == 1
        assert composed.decision_policies[0].name == "fork_only"
