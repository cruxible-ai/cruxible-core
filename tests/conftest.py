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

PROPOSAL_WORKFLOW_CONFIG_YAML = """\
version: "1.0"
name: campaign_relationship_workflows
kind: world_model

entity_types:
  Campaign:
    properties:
      campaign_id:
        type: string
        primary_key: true
      region:
        type: string
  Product:
    properties:
      sku:
        type: string
        primary_key: true
      category:
        type: string

relationships:
  - name: recommended_for
    from: Campaign
    to: Product
    matching:
      integrations:
        catalog:
          role: required
          always_review_on_unsure: true

named_queries:
  get_campaign_context:
    entry_point: Campaign
    traversal: []
    returns: "list[Campaign]"

contracts:
  CampaignInput:
    fields:
      campaign_id:
        type: string
  CampaignContext:
    fields:
      campaign_id:
        type: string
      region:
        type: string
  RecommendationRows:
    fields:
      items:
        type: json

integrations:
  catalog:
    kind: heuristic
    contract:
      output: support|unsure|contradict

providers:
  campaign_recommendations:
    kind: function
    contract_in: CampaignContext
    contract_out: RecommendationRows
    ref: tests.support.workflow_test_providers.campaign_recommendations
    version: 1.0.0
    deterministic: true
    runtime: python

workflows:
  propose_campaign_recommendations:
    contract_in: CampaignInput
    steps:
      - id: campaign
        query: get_campaign_context
        params:
          campaign_id: $input.campaign_id
        as: campaign
      - id: recommend
        provider: campaign_recommendations
        input:
          campaign_id: $steps.campaign.results[0].properties.campaign_id
          region: $steps.campaign.results[0].properties.region
        as: recommendations
      - id: candidates
        make_candidates:
          relationship_type: recommended_for
          items: $steps.recommendations.items
          from_type: Campaign
          from_id: $steps.campaign.results[0].properties.campaign_id
          to_type: Product
          to_id: $item.product_sku
          properties:
            reason: $item.reason
        as: candidates
      - id: catalog_signals
        map_signals:
          integration: catalog
          items: $steps.recommendations.items
          from_id: $steps.campaign.results[0].properties.campaign_id
          to_id: $item.product_sku
          evidence: $item.reason
          enum:
            path: verdict
            map:
              match: support
              fallback: unsure
              reject: contradict
        as: catalog_signals
      - id: proposal
        propose_relationship_group:
          relationship_type: recommended_for
          candidates_from: candidates
          signals_from:
            - catalog_signals
          thesis_text: Recommend products for regional campaign
          thesis_facts:
            campaign_id: $input.campaign_id
            region: $steps.campaign.results[0].properties.region
          analysis_state:
            source: campaign_recommendations
          suggested_priority: high
        as: proposal
    returns: proposal

tests:
  - name: campaign_proposal_smoke
    workflow: propose_campaign_recommendations
    input:
      campaign_id: CMP-1
    expect:
      output_contains:
        thesis_text: Recommend products for regional campaign
      receipt_contains_provider: campaign_recommendations
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


@pytest.fixture
def proposal_workflow_config_yaml() -> str:
    """Raw YAML string for relationship proposal workflow tests."""
    return PROPOSAL_WORKFLOW_CONFIG_YAML
