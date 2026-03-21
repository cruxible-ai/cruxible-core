"""CLI tests for workflow lock/plan/run/test commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.cli.main import cli
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _chdir_run(runner: CliRunner, directory: Path, args: list[str]) -> object:
    original = os.getcwd()
    try:
        os.chdir(directory)
        return runner.invoke(cli, args)
    finally:
        os.chdir(original)


@pytest.fixture
def workflow_project(tmp_path: Path, workflow_config_yaml: str) -> CruxibleInstance:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(workflow_config_yaml)
    instance = CruxibleInstance.init(tmp_path, "config.yaml")
    graph = EntityGraph()
    graph.add_entity(
        EntityInstance(
            entity_type="Product",
            entity_id="SKU-123",
            properties={"sku": "SKU-123", "category": "soda"},
        )
    )
    instance.save_graph(graph)
    return instance


@pytest.fixture
def workflow_input_file(workflow_project: CruxibleInstance) -> Path:
    path = workflow_project.root / "input.yaml"
    path.write_text("sku: SKU-123\nstart_date: '2026-03-01'\nend_date: '2026-03-07'\n")
    return path


class TestWorkflowCli:
    def test_lock_writes_lock_file(
        self, runner: CliRunner, workflow_project: CruxibleInstance
    ) -> None:
        result = _chdir_run(runner, workflow_project.root, ["lock"])
        assert result.exit_code == 0
        assert (workflow_project.root / "cruxible.lock.yaml").exists()
        assert "digest=" in result.output

    def test_plan_prints_compiled_plan(
        self,
        runner: CliRunner,
        workflow_project: CruxibleInstance,
        workflow_input_file: Path,
    ) -> None:
        _chdir_run(runner, workflow_project.root, ["lock"])
        result = _chdir_run(
            runner,
            workflow_project.root,
            ["plan", "--workflow", "evaluate_promo", "--input-file", str(workflow_input_file)],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["workflow"] == "evaluate_promo"
        assert payload["steps"][1]["provider_version"] == "1.2.0"
        assert payload["steps"][1]["artifact_sha256"] == "abc123"

    def test_run_executes_workflow(
        self,
        runner: CliRunner,
        workflow_project: CruxibleInstance,
        workflow_input_file: Path,
    ) -> None:
        _chdir_run(runner, workflow_project.root, ["lock"])
        result = _chdir_run(
            runner,
            workflow_project.root,
            ["run", "--workflow", "evaluate_promo", "--input-file", str(workflow_input_file)],
        )
        assert result.exit_code == 0
        assert "Receipt ID:" in result.output
        assert "Trace IDs:" in result.output
        assert '"decision": "approve"' in result.output

    def test_test_executes_config_defined_tests(
        self,
        runner: CliRunner,
        workflow_project: CruxibleInstance,
    ) -> None:
        _chdir_run(runner, workflow_project.root, ["lock"])
        result = _chdir_run(runner, workflow_project.root, ["test"])
        assert result.exit_code == 0
        assert "1 passed, 0 failed, 1 total" in result.output
        assert "[PASS] promo_margin_smoke" in result.output
