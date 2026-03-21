"""Tests for workflow execution service functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.errors import ConfigError
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance
from cruxible_core.service import service_lock, service_plan, service_run, service_test


@pytest.fixture
def workflow_instance(tmp_path: Path, workflow_config_yaml: str) -> CruxibleInstance:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(workflow_config_yaml)
    instance = CruxibleInstance.init(tmp_path, "config.yaml")

    graph = EntityGraph()
    graph.add_entity(
        EntityInstance(
            entity_type="Product",
            entity_id="SKU-123",
            properties={
                "sku": "SKU-123",
                "category": "soda",
                "base_margin": 0.2,
            },
        )
    )
    instance.save_graph(graph)
    return instance


class TestWorkflowExecutionServices:
    def test_service_lock_writes_lock_and_counts_dependencies(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        result = service_lock(workflow_instance)

        assert result.lock_path.endswith("cruxible.lock.yaml")
        assert result.config_digest.startswith("sha256:")
        assert result.providers_locked == 2
        assert result.artifacts_locked == 1
        assert Path(result.lock_path).exists()

    def test_service_plan_returns_compiled_plan(self, workflow_instance: CruxibleInstance) -> None:
        service_lock(workflow_instance)

        result = service_plan(
            workflow_instance,
            "evaluate_promo",
            {
                "sku": "SKU-123",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
        )

        assert result.plan.workflow == "evaluate_promo"
        assert result.plan.steps[0].kind == "query"
        assert result.plan.steps[1].provider_name == "lift_predictor"

    def test_service_run_returns_receipt_and_trace_ids(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        service_lock(workflow_instance)

        result = service_run(
            workflow_instance,
            "evaluate_promo",
            {
                "sku": "SKU-123",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
        )

        assert result.workflow == "evaluate_promo"
        assert result.output["decision"] == "approve"
        assert result.receipt_id.startswith("RCP-")
        assert len(result.query_receipt_ids) == 1
        assert len(result.trace_ids) == 2
        assert all(trace_id.startswith("TRC-") for trace_id in result.trace_ids)

    def test_service_test_supports_expected_error_cases(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        config = workflow_instance.load_config()
        config.providers[
            "margin_calculator"
        ].ref = "tests.support.workflow_test_providers.broken_provider"
        config.tests[0].expect.output_contains = None
        config.tests[0].expect.receipt_contains_provider = None
        config.tests[0].expect.error_contains = "output failed contract"
        workflow_instance.save_config(config)
        service_lock(workflow_instance)

        result = service_test(workflow_instance)

        assert result.total == 1
        assert result.passed == 1
        assert result.failed == 0
        assert result.cases[0].passed is True
        assert "output failed contract" in (result.cases[0].error or "")

    def test_service_test_rejects_unknown_test_name(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        service_lock(workflow_instance)

        with pytest.raises(ConfigError, match="Test 'missing' not found in config"):
            service_test(workflow_instance, test_name="missing")
