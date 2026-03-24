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
    get_legacy_lock_path,
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


@pytest.fixture
def proposal_workflow_instance(
    tmp_path: Path, proposal_workflow_config_yaml: str
) -> CruxibleInstance:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(proposal_workflow_config_yaml)
    instance = CruxibleInstance.init(tmp_path, "config.yaml")

    graph = EntityGraph()
    graph.add_entity(
        EntityInstance(
            entity_type="Campaign",
            entity_id="CMP-1",
            properties={"campaign_id": "CMP-1", "region": "north"},
        )
    )
    for sku in ("SKU-123", "SKU-456"):
        graph.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id=sku,
                properties={"sku": sku, "category": "beverages"},
            )
        )
    instance.save_graph(graph)
    return instance


def _write_lock_for_instance(instance: CruxibleInstance) -> None:
    config = instance.load_config()
    write_lock(build_lock(config, instance.get_config_path().parent), get_lock_path(instance))


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

    def test_compile_workflow_empty_input_error_mentions_cli_flags(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        _write_lock_for_instance(workflow_instance)
        config = workflow_instance.load_config()

        with pytest.raises(ConfigError, match="empty input payload provided"):
            compile_workflow(
                config,
                build_lock(config),
                "evaluate_promo",
                {},
            )

        with pytest.raises(ConfigError, match="Use --input or --input-file"):
            compile_workflow(
                config,
                build_lock(config),
                "evaluate_promo",
                {},
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

    def test_compile_workflow_includes_built_in_proposal_steps(
        self, proposal_workflow_instance: CruxibleInstance
    ) -> None:
        _write_lock_for_instance(proposal_workflow_instance)
        config = proposal_workflow_instance.load_config()

        plan = compile_workflow(
            config,
            build_lock(config),
            "propose_campaign_recommendations",
            {"campaign_id": "CMP-1"},
        )

        assert [step.kind for step in plan.steps] == [
            "query",
            "provider",
            "make_candidates",
            "map_signals",
            "propose_relationship_group",
        ]
        assert plan.steps[2].make_candidates_spec is not None
        assert plan.steps[2].make_candidates_spec.relationship_type == "recommended_for"
        assert plan.steps[3].map_signals_spec is not None
        assert plan.steps[3].map_signals_spec.integration == "catalog"
        assert plan.steps[4].propose_relationship_group_spec is not None
        assert plan.steps[4].propose_relationship_group_spec.signals_from == ["catalog_signals"]

    def test_compile_canonical_workflow_carries_canonical_metadata(
        self, canonical_workflow_instance: CruxibleInstance
    ) -> None:
        _write_lock_for_instance(canonical_workflow_instance)
        config = canonical_workflow_instance.load_config()
        lock = build_lock(config, canonical_workflow_instance.get_config_path().parent)

        plan = compile_workflow(
            config,
            lock,
            "build_reference",
            {},
            config_base_path=canonical_workflow_instance.get_config_path().parent,
        )

        assert plan.canonical is True
        assert plan.lock_digest == lock.lock_digest
        assert plan.steps[0].provider_entrypoint_sha256 is not None
        assert "apply_entities" in [step.kind for step in plan.steps]

    def test_compile_rejects_apply_steps_in_non_canonical_workflow(
        self, canonical_workflow_instance: CruxibleInstance
    ) -> None:
        config = canonical_workflow_instance.load_config()
        config.workflows["build_reference"].canonical = False
        canonical_workflow_instance.save_config(config)
        _write_lock_for_instance(canonical_workflow_instance)

        with pytest.raises(ConfigError, match="must be canonical to use apply_entities"):
            compile_workflow(
                canonical_workflow_instance.load_config(),
                build_lock(canonical_workflow_instance.load_config()),
                "build_reference",
                {},
                config_base_path=canonical_workflow_instance.get_config_path().parent,
            )

    def test_build_lock_rejects_stale_canonical_artifact_hash(
        self, canonical_workflow_instance: CruxibleInstance
    ) -> None:
        config = canonical_workflow_instance.load_config()
        config.artifacts["canonical_bundle"].sha256 = "sha256:bad"
        canonical_workflow_instance.save_config(config)

        with pytest.raises(ConfigError, match="sha256 does not match live contents"):
            build_lock(
                canonical_workflow_instance.load_config(),
                canonical_workflow_instance.get_config_path().parent,
            )

    def test_executor_uses_legacy_lock_path_as_fallback(
        self, workflow_instance: CruxibleInstance
    ) -> None:
        config = workflow_instance.load_config()
        legacy_path = get_legacy_lock_path(workflow_instance)
        write_lock(build_lock(config, workflow_instance.get_config_path().parent), legacy_path)

        result = execute_workflow(
            workflow_instance,
            config,
            "evaluate_promo",
            {
                "sku": "SKU-123",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            },
        )

        assert result.output["decision"] == "approve"


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

    def test_execute_workflow_builds_relationship_proposal_artifact(
        self, proposal_workflow_instance: CruxibleInstance
    ) -> None:
        _write_lock_for_instance(proposal_workflow_instance)

        result = execute_workflow(
            proposal_workflow_instance,
            proposal_workflow_instance.load_config(),
            "propose_campaign_recommendations",
            {"campaign_id": "CMP-1"},
        )

        assert result.output["relationship_type"] == "recommended_for"
        assert len(result.output["members"]) == 2
        assert result.output["integrations_used"] == ["catalog"]
        assert len(result.traces) == 1
        plan_steps = [node for node in result.receipt.nodes if node.node_type == "plan_step"]
        assert any(node.detail.get("relationship_type") == "recommended_for" for node in plan_steps)
        assert any(node.detail.get("integration") == "catalog" for node in plan_steps)
        assert any(node.detail.get("signals_from") == ["catalog_signals"] for node in plan_steps)

    def test_execute_canonical_workflow_runs_in_preview_mode_without_mutating_graph(
        self, canonical_workflow_instance: CruxibleInstance
    ) -> None:
        _write_lock_for_instance(canonical_workflow_instance)

        result = execute_workflow(
            canonical_workflow_instance,
            canonical_workflow_instance.load_config(),
            "build_reference",
            {},
        )

        assert result.mode == "preview"
        assert result.canonical is True
        assert result.apply_digest is not None
        assert result.committed_snapshot_id is None
        assert result.receipt.committed is False
        assert result.output["total_results"] == 1
        assert canonical_workflow_instance.load_graph().list_entities("Vendor") == []

    def test_execute_canonical_workflow_apply_commits_graph_and_snapshot(
        self, canonical_workflow_instance: CruxibleInstance
    ) -> None:
        _write_lock_for_instance(canonical_workflow_instance)
        preview = execute_workflow(
            canonical_workflow_instance,
            canonical_workflow_instance.load_config(),
            "build_reference",
            {},
        )

        applied = execute_workflow(
            canonical_workflow_instance,
            canonical_workflow_instance.load_config(),
            "build_reference",
            {},
            mode="apply",
        )

        assert applied.mode == "apply"
        assert applied.apply_digest == preview.apply_digest
        assert applied.committed_snapshot_id is not None
        assert applied.receipt.committed is True
        assert canonical_workflow_instance.load_graph().has_entity("Vendor", "vendor-acme")
