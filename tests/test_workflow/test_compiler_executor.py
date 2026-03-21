"""Tests for workflow lock, compilation, and execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.errors import ConfigError, QueryExecutionError
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance
from cruxible_core.receipt.serializer import to_markdown
from cruxible_core.workflow import (
    build_lock,
    compile_workflow,
    execute_workflow,
    get_lock_path,
    write_lock,
)


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


def _write_lock_for_instance(instance: CruxibleInstance) -> None:
    config = instance.load_config()
    write_lock(build_lock(config), get_lock_path(instance))


class TestWorkflowCompiler:
    def test_compile_workflow_success(self, workflow_instance: CruxibleInstance) -> None:
        _write_lock_for_instance(workflow_instance)
        config = workflow_instance.load_config()

        plan = compile_workflow(
            config,
            build_lock(config),
            "evaluate_promo",
            {
                "sku": "SKU-123",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
        )

        assert plan.workflow == "evaluate_promo"
        assert plan.contract_in == "PromoInput"
        assert plan.steps[0].kind == "query"
        assert plan.steps[0].params_preview["sku"] == "SKU-123"
        assert plan.steps[1].provider_version == "1.2.0"
        assert plan.steps[1].artifact_sha256 == "abc123"

    def test_compile_workflow_rejects_bad_input_contract(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        _write_lock_for_instance(workflow_instance)
        config = workflow_instance.load_config()

        with pytest.raises(ConfigError, match="missing required field 'end_date'"):
            compile_workflow(
                config,
                build_lock(config),
                "evaluate_promo",
                {"sku": "SKU-123", "start_date": "2026-03-01"},
            )

    def test_compile_workflow_rejects_lock_digest_mismatch(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        config = workflow_instance.load_config()
        lock = build_lock(config)
        lock.config_digest = "sha256:bad"

        with pytest.raises(ConfigError, match="Lock file config digest does not match"):
            compile_workflow(
                config,
                lock,
                "evaluate_promo",
                {
                    "sku": "SKU-123",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
            )


class TestWorkflowExecutor:
    def test_execute_workflow_success(self, workflow_instance: CruxibleInstance) -> None:
        _write_lock_for_instance(workflow_instance)

        result = execute_workflow(
            workflow_instance,
            workflow_instance.load_config(),
            "evaluate_promo",
            {
                "sku": "SKU-123",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
        )

        assert result.output["decision"] == "approve"
        assert result.receipt.operation_type == "workflow"
        assert len(result.query_receipt_ids) == 1
        assert len(result.traces) == 2
        trace_ids = {trace.trace_id for trace in result.traces}
        plan_steps = [node for node in result.receipt.nodes if node.node_type == "plan_step"]
        assert any(node.detail.get("receipt_id") in result.query_receipt_ids for node in plan_steps)
        assert any(node.detail.get("trace_id") in trace_ids for node in plan_steps)
        rendered = to_markdown(result.receipt)
        assert "**Workflow:** evaluate_promo" in rendered
        assert "## Plan Steps" in rendered

    def test_execute_workflow_rejects_provider_output_contract(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        config = workflow_instance.load_config()
        config.providers[
            "margin_calculator"
        ].ref = "tests.support.workflow_test_providers.broken_provider"
        workflow_instance.save_config(config)
        _write_lock_for_instance(workflow_instance)

        with pytest.raises(QueryExecutionError, match="output failed contract"):
            execute_workflow(
                workflow_instance,
                workflow_instance.load_config(),
                "evaluate_promo",
                {
                    "sku": "SKU-123",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
            )

    def test_execute_workflow_assert_failure_records_workflow_receipt(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        config = workflow_instance.load_config()
        for step in config.workflows["evaluate_promo"].steps:
            if step.assert_spec is not None:
                step.assert_spec.right = 0.90
        workflow_instance.save_config(config)
        _write_lock_for_instance(workflow_instance)

        with pytest.raises(QueryExecutionError, match="Margin below threshold"):
            execute_workflow(
                workflow_instance,
                workflow_instance.load_config(),
                "evaluate_promo",
                {
                    "sku": "SKU-123",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-07",
                },
            )

        store = workflow_instance.get_receipt_store()
        try:
            receipts = store.list_receipts(operation_type="workflow")
        finally:
            store.close()
        assert receipts
