"""Tests for workflow execution service functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.errors import ConfigError
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance
from cruxible_core.service import (
    service_create_snapshot,
    service_fork_snapshot,
    service_list_snapshots,
    service_lock,
    service_plan,
    service_propose_workflow,
    service_resolve_group,
    service_run,
    service_test,
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

    def test_service_propose_workflow_creates_candidate_group_with_lineage(
        self, proposal_workflow_instance: CruxibleInstance
    ) -> None:
        service_lock(proposal_workflow_instance)

        result = service_propose_workflow(
            proposal_workflow_instance,
            "propose_campaign_recommendations",
            {"campaign_id": "CMP-1"},
        )

        assert result.group_id.startswith("GRP-")
        assert result.group_status == "pending_review"
        assert result.receipt_id.startswith("RCP-")
        assert result.trace_ids

        group_store = proposal_workflow_instance.get_group_store()
        try:
            group = group_store.get_group(result.group_id)
            members = group_store.get_members(result.group_id)
        finally:
            group_store.close()

        assert group is not None
        assert group.source_workflow_name == "propose_campaign_recommendations"
        assert group.source_workflow_receipt_id == result.receipt_id
        assert group.source_trace_ids == result.trace_ids
        assert group.source_step_ids == ["recommend"]
        assert len(members) == 2
        assert all(member.relationship_type == "recommended_for" for member in members)

    def test_service_run_does_not_create_group_side_effects(
        self, proposal_workflow_instance: CruxibleInstance
    ) -> None:
        service_lock(proposal_workflow_instance)

        result = service_run(
            proposal_workflow_instance,
            "propose_campaign_recommendations",
            {"campaign_id": "CMP-1"},
        )

        assert result.output["members"]
        group_store = proposal_workflow_instance.get_group_store()
        try:
            assert group_store.count_groups() == 0
        finally:
            group_store.close()

    def test_snapshot_create_list_and_fork(
        self, proposal_workflow_instance: CruxibleInstance, tmp_path: Path
    ) -> None:
        service_lock(proposal_workflow_instance)
        proposed = service_propose_workflow(
            proposal_workflow_instance,
            "propose_campaign_recommendations",
            {"campaign_id": "CMP-1"},
        )
        resolved = service_resolve_group(
            proposal_workflow_instance,
            proposed.group_id,
            "approve",
        )
        assert resolved.edges_created == 2

        created = service_create_snapshot(proposal_workflow_instance, label="baseline")
        listed = service_list_snapshots(proposal_workflow_instance)

        assert created.snapshot.snapshot_id.startswith("snap_")
        assert listed.snapshots[0].snapshot_id == created.snapshot.snapshot_id
        assert listed.snapshots[0].label == "baseline"

        fork_root = tmp_path / "forked"
        fork_result = service_fork_snapshot(
            proposal_workflow_instance,
            created.snapshot.snapshot_id,
            fork_root,
        )

        assert fork_result.snapshot.snapshot_id == created.snapshot.snapshot_id
        assert fork_result.instance.get_root_path() == fork_root
        assert fork_result.instance.metadata["origin_snapshot_id"] == created.snapshot.snapshot_id
        fork_graph = fork_result.instance.load_graph()
        assert fork_graph.edge_count("recommended_for") == 2
