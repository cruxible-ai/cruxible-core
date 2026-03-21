"""Shared test fixtures for cruxible-core."""

from pathlib import Path

import pytest

WORKFLOW_CONFIG_YAML = """\
version: "1.0"
name: promo_workflows

entity_types:
  Product:
    properties:
      sku:
        type: string
        primary_key: true
      category:
        type: string
      base_margin:
        type: float
        optional: true

relationships: []

named_queries:
  get_promo_context:
    entry_point: Product
    traversal: []
    returns: "list[Product]"

contracts:
  PromoInput:
    fields:
      sku:
        type: string
      start_date:
        type: date
      end_date:
        type: date
  PromoContext:
    fields:
      sku:
        type: string
      category:
        type: string
      start_date:
        type: date
      end_date:
        type: date
  LiftForecast:
    fields:
      predicted_lift_pct:
        type: float
      confidence_lower:
        type: float
      confidence_upper:
        type: float
      model_version:
        type: string
  MarginResult:
    fields:
      expected_margin_pct:
        type: float
      decision:
        type: string
      calculator_version:
        type: string

artifacts:
  promo_model:
    kind: model
    uri: file:///tmp/promo-model.bin
    sha256: abc123

providers:
  lift_predictor:
    kind: model
    contract_in: PromoContext
    contract_out: LiftForecast
    ref: tests.support.workflow_test_providers.lift_predictor
    version: 1.2.0
    deterministic: true
    artifact: promo_model
    runtime: python
  margin_calculator:
    kind: function
    contract_in: LiftForecast
    contract_out: MarginResult
    ref: tests.support.workflow_test_providers.margin_calculator
    version: 1.0.0
    deterministic: true
    runtime: python

workflows:
  evaluate_promo:
    contract_in: PromoInput
    steps:
      - id: context
        query: get_promo_context
        params:
          sku: $input.sku
        as: context
      - id: lift
        provider: lift_predictor
        input:
          sku: $steps.context.results[0].properties.sku
          category: $steps.context.results[0].properties.category
          start_date: $input.start_date
          end_date: $input.end_date
        as: lift
      - id: margin
        provider: margin_calculator
        input:
          predicted_lift_pct: $steps.lift.predicted_lift_pct
          confidence_lower: $steps.lift.confidence_lower
          confidence_upper: $steps.lift.confidence_upper
          model_version: $steps.lift.model_version
        as: margin
      - id: margin_gate
        assert:
          left: $steps.margin.expected_margin_pct
          op: gte
          right: 0.05
          message: Margin below threshold
    returns: margin

tests:
  - name: promo_margin_smoke
    workflow: evaluate_promo
    input:
      sku: SKU-123
      start_date: "2026-03-01"
      end_date: "2026-03-07"
    expect:
      output_contains:
        decision: approve
      receipt_contains_provider:
        - lift_predictor
        - margin_calculator
"""


@pytest.fixture
def configs_dir() -> Path:
    """Path to the configs directory."""
    return Path(__file__).parent.parent / "configs"


@pytest.fixture
def car_parts_config(configs_dir: Path) -> str:
    """Raw YAML string for car parts config."""
    return (configs_dir / "car_parts.yaml").read_text()


@pytest.fixture
def workflow_config_yaml() -> str:
    """Raw YAML string for terraform-primitives workflow tests."""
    return WORKFLOW_CONFIG_YAML
