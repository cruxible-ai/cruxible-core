"""Tests for workflow helper modules and provider registry."""

from __future__ import annotations

from datetime import date
from math import pi

import pytest

from cruxible_core.config.schema import (
    ContractSchema,
    CoreConfig,
    EntityTypeSchema,
    PropertySchema,
    ProviderSchema,
)
from cruxible_core.errors import ConfigError, QueryExecutionError
from cruxible_core.provider.registry import resolve_provider
from cruxible_core.workflow.contracts import validate_contract_payload
from cruxible_core.workflow.refs import preview_value, resolve_value


def _base_config(**overrides: object) -> CoreConfig:
    config = CoreConfig(
        name="workflow_helpers",
        entity_types={
            "Thing": EntityTypeSchema(
                properties={"id": PropertySchema(type="string", primary_key=True)}
            )
        },
        relationships=[],
        **overrides,
    )
    return config


class TestContractValidation:
    def test_applies_defaults_and_normalizes_dates(self) -> None:
        config = _base_config(
            contracts={
                "Input": ContractSchema(
                    fields={
                        "name": PropertySchema(type="string"),
                        "run_date": PropertySchema(type="date"),
                        "score": PropertySchema(type="float", default=1.25),
                        "tag": PropertySchema(type="string", optional=True),
                    }
                )
            }
        )

        payload = validate_contract_payload(
            config,
            "Input",
            {"name": "alpha", "run_date": date(2026, 3, 21)},
            subject="Workflow input",
            error_factory=ConfigError,
        )

        assert payload == {
            "name": "alpha",
            "run_date": "2026-03-21",
            "score": 1.25,
        }

    def test_rejects_extra_fields(self) -> None:
        config = _base_config(
            contracts={"Input": ContractSchema(fields={"name": PropertySchema(type="string")})}
        )

        with pytest.raises(ConfigError, match="unexpected field 'extra'"):
            validate_contract_payload(
                config,
                "Input",
                {"name": "alpha", "extra": True},
                subject="Workflow input",
                error_factory=ConfigError,
            )

    def test_accepts_json_contract_fields(self) -> None:
        config = _base_config(
            contracts={
                "Input": ContractSchema(
                    fields={
                        "members": PropertySchema(type="json"),
                        "facts": PropertySchema(type="json", optional=True),
                    }
                )
            }
        )

        payload = validate_contract_payload(
            config,
            "Input",
            {
                "members": [{"from_id": "A", "to_id": "B"}],
                "facts": {"source": "catalog"},
            },
            subject="Provider output",
            error_factory=ConfigError,
        )

        assert payload["members"][0]["from_id"] == "A"


class TestProviderRegistry:
    def test_rejects_unsupported_runtime(self) -> None:
        provider = ProviderSchema(
            kind="function",
            contract_in="Input",
            contract_out="Output",
            ref="tests.support.workflow_test_providers.lift_predictor",
            version="1.0.0",
            runtime="node",
        )

        with pytest.raises(ConfigError, match="unsupported runtime 'node'"):
            resolve_provider("provider", provider)

    def test_rejects_invalid_ref_without_module_separator(self) -> None:
        provider = ProviderSchema(
            kind="function",
            contract_in="Input",
            contract_out="Output",
            ref="not_a_valid_ref",
            version="1.0.0",
        )

        with pytest.raises(ConfigError, match="invalid ref"):
            resolve_provider("provider", provider)

    def test_rejects_non_callable_ref(self) -> None:
        provider = ProviderSchema(
            kind="function",
            contract_in="Input",
            contract_out="Output",
            ref="math.pi",
            version="1.0.0",
        )

        assert pi == 3.141592653589793
        with pytest.raises(ConfigError, match="is not callable"):
            resolve_provider("provider", provider)


class TestWorkflowRefs:
    def test_preview_value_only_resolves_input_refs(self) -> None:
        value = {
            "sku": "$input.sku",
            "nested": ["$input.dates[1]", "$steps.lift.predicted_lift_pct"],
        }

        preview = preview_value(
            value,
            {"sku": "SKU-123", "dates": ["2026-03-01", "2026-03-07"]},
        )

        assert preview == {
            "sku": "SKU-123",
            "nested": ["2026-03-07", "$steps.lift.predicted_lift_pct"],
        }

    def test_resolve_value_supports_nested_step_paths_and_indices(self) -> None:
        resolved = resolve_value(
            {
                "sku": "$input.sku",
                "category": "$steps.context.results[0].properties.category",
                "lift": "$steps.lift.predicted_lift_pct",
            },
            {"sku": "SKU-123"},
            {
                "context": {
                    "results": [
                        {"properties": {"category": "soda"}},
                    ]
                },
                "lift": {"predicted_lift_pct": 0.12},
            },
        )

        assert resolved == {"sku": "SKU-123", "category": "soda", "lift": 0.12}

    def test_resolve_value_rejects_unknown_alias(self) -> None:
        with pytest.raises(QueryExecutionError, match="Unknown workflow step alias 'missing'"):
            resolve_value("$steps.missing.score", {}, {})

    def test_resolve_value_rejects_out_of_range_index(self) -> None:
        with pytest.raises(QueryExecutionError, match="index \\[1\\] is out of range"):
            resolve_value(
                "$steps.context.results[1].properties.category",
                {},
                {"context": {"results": [{"properties": {"category": "soda"}}]}},
            )

    def test_resolve_value_supports_item_refs_when_enabled(self) -> None:
        resolved = resolve_value(
            {
                "sku": "$item.product_sku",
                "reason": "$item.reason",
                "campaign_id": "$input.campaign_id",
            },
            {"campaign_id": "CMP-1"},
            {},
            item_payload={"product_sku": "SKU-123", "reason": "north bestseller"},
            allow_item=True,
        )

        assert resolved == {
            "sku": "SKU-123",
            "reason": "north bestseller",
            "campaign_id": "CMP-1",
        }

    def test_resolve_value_rejects_item_ref_when_disabled(self) -> None:
        with pytest.raises(
            QueryExecutionError,
            match="Unsupported workflow reference '\\$item.id'",
        ):
            resolve_value("$item.id", {}, {})
