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


@pytest.fixture
def proposal_workflow_project(
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


@pytest.fixture
def proposal_input_file(proposal_workflow_project: CruxibleInstance) -> Path:
    path = proposal_workflow_project.root / "input.yaml"
    path.write_text("campaign_id: CMP-1\n")
    return path


@pytest.fixture
def canonical_input_file(canonical_workflow_instance: CruxibleInstance) -> Path:
    path = canonical_workflow_instance.root / "input.yaml"
    path.write_text("{}\n")
    return path


class TestWorkflowCli:
    def test_lock_writes_lock_file(
        self, runner: CliRunner, workflow_project: CruxibleInstance
    ) -> None:
        result = _chdir_run(runner, workflow_project.root, ["lock"])
        assert result.exit_code == 0
        assert (workflow_project.root / ".cruxible" / "cruxible.lock.yaml").exists()
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

    def test_run_supports_inline_input(
        self,
        runner: CliRunner,
        workflow_project: CruxibleInstance,
    ) -> None:
        _chdir_run(runner, workflow_project.root, ["lock"])
        result = _chdir_run(
            runner,
            workflow_project.root,
            [
                "run",
                "--workflow",
                "evaluate_promo",
                "--input",
                '{"sku":"SKU-123","start_date":"2026-03-01","end_date":"2026-03-07"}',
            ],
        )
        assert result.exit_code == 0
        assert '"decision": "approve"' in result.output

    def test_run_uses_empty_input_by_default_for_empty_contract(
        self,
        runner: CliRunner,
        canonical_workflow_instance: CruxibleInstance,
    ) -> None:
        _chdir_run(runner, canonical_workflow_instance.root, ["lock"])
        result = _chdir_run(
            runner,
            canonical_workflow_instance.root,
            ["run", "--workflow", "build_reference"],
        )
        assert result.exit_code == 0
        assert "Apply digest:" in result.output

    def test_run_reports_clear_error_for_missing_required_input(
        self,
        runner: CliRunner,
        workflow_project: CruxibleInstance,
    ) -> None:
        _chdir_run(runner, workflow_project.root, ["lock"])
        result = _chdir_run(
            runner,
            workflow_project.root,
            ["run", "--workflow", "evaluate_promo"],
        )
        assert result.exit_code == 1
        assert "empty input payload provided" in result.output
        assert "--input or --input-file" in result.output

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

    def test_propose_bridges_workflow_into_candidate_group(
        self,
        runner: CliRunner,
        proposal_workflow_project: CruxibleInstance,
        proposal_input_file: Path,
    ) -> None:
        _chdir_run(runner, proposal_workflow_project.root, ["lock"])
        result = _chdir_run(
            runner,
            proposal_workflow_project.root,
            [
                "propose",
                "--workflow",
                "propose_campaign_recommendations",
                "--input-file",
                str(proposal_input_file),
            ],
        )
        assert result.exit_code == 0
        assert "proposed group GRP-" in result.output
        assert "Group status: pending_review" in result.output

    def test_snapshot_create_list_and_fork(
        self,
        runner: CliRunner,
        proposal_workflow_project: CruxibleInstance,
        tmp_path: Path,
    ) -> None:
        create = _chdir_run(
            runner,
            proposal_workflow_project.root,
            ["snapshot", "create", "--label", "baseline"],
        )
        assert create.exit_code == 0
        assert "Created snapshot snap_" in create.output
        snapshot_id = next(
            line.split()[2]
            for line in create.output.splitlines()
            if line.startswith("Created snapshot ")
        )

        listed = _chdir_run(runner, proposal_workflow_project.root, ["snapshot", "list"])
        assert listed.exit_code == 0
        assert snapshot_id in listed.output

        fork_root = tmp_path / "forked-cli"
        forked = _chdir_run(
            runner,
            proposal_workflow_project.root,
            ["fork", "--snapshot", snapshot_id, "--root-dir", str(fork_root)],
        )
        assert forked.exit_code == 0
        assert str(fork_root) in forked.output

    def test_apply_commits_canonical_workflow(
        self,
        runner: CliRunner,
        canonical_workflow_instance: CruxibleInstance,
        canonical_input_file: Path,
    ) -> None:
        _chdir_run(runner, canonical_workflow_instance.root, ["lock"])
        preview = _chdir_run(
            runner,
            canonical_workflow_instance.root,
            ["run", "--workflow", "build_reference", "--input-file", str(canonical_input_file)],
        )
        assert preview.exit_code == 0
        digest = next(
            line.split("Apply digest: ", 1)[1]
            for line in preview.output.splitlines()
            if line.startswith("Apply digest: ")
        )

        applied = _chdir_run(
            runner,
            canonical_workflow_instance.root,
            [
                "apply",
                "--workflow",
                "build_reference",
                "--input-file",
                str(canonical_input_file),
                "--apply-digest",
                digest,
            ],
        )
        assert applied.exit_code == 0
        assert "Committed snapshot: snap_" in applied.output

    def test_run_save_preview_writes_file(
        self,
        runner: CliRunner,
        canonical_workflow_instance: CruxibleInstance,
    ) -> None:
        _chdir_run(runner, canonical_workflow_instance.root, ["lock"])
        preview_file = canonical_workflow_instance.root / "preview.json"

        result = _chdir_run(
            runner,
            canonical_workflow_instance.root,
            [
                "run",
                "--workflow",
                "build_reference",
                "--save-preview",
                str(preview_file),
            ],
        )

        assert result.exit_code == 0
        assert preview_file.exists()
        payload = json.loads(preview_file.read_text())
        assert payload["kind"] == "workflow_preview"
        assert payload["version"] == 1
        assert payload["workflow"] == "build_reference"
        assert payload["input"] == {}
        assert payload["apply_digest"].startswith("sha256:")
        assert "head_snapshot_id" in payload
        assert "apply_previews" in payload

    def test_run_save_preview_non_canonical_errors(
        self,
        runner: CliRunner,
        proposal_workflow_project: CruxibleInstance,
        proposal_input_file: Path,
    ) -> None:
        _chdir_run(runner, proposal_workflow_project.root, ["lock"])
        preview_file = proposal_workflow_project.root / "preview.json"

        result = _chdir_run(
            runner,
            proposal_workflow_project.root,
            [
                "run",
                "--workflow",
                "propose_campaign_recommendations",
                "--input-file",
                str(proposal_input_file),
                "--save-preview",
                str(preview_file),
            ],
        )

        assert result.exit_code != 0
        assert "did not produce preview state" in result.output
        assert not preview_file.exists()

    def test_apply_from_preview_file(
        self,
        runner: CliRunner,
        canonical_workflow_instance: CruxibleInstance,
    ) -> None:
        _chdir_run(runner, canonical_workflow_instance.root, ["lock"])
        preview_file = canonical_workflow_instance.root / "preview.json"

        preview = _chdir_run(
            runner,
            canonical_workflow_instance.root,
            [
                "run",
                "--workflow",
                "build_reference",
                "--save-preview",
                str(preview_file),
            ],
        )
        assert preview.exit_code == 0

        applied = _chdir_run(
            runner,
            canonical_workflow_instance.root,
            ["apply", "--preview-file", str(preview_file)],
        )
        assert applied.exit_code == 0
        assert "Committed snapshot: snap_" in applied.output

        canonical_workflow_instance.invalidate_graph_cache()
        graph = canonical_workflow_instance.load_graph()
        assert graph.entity_count("Vendor") == 1
        assert graph.entity_count("Product") == 2
        assert graph.entity_count("Vulnerability") == 2

    @pytest.mark.parametrize(
        ("extra_args", "label"),
        [
            (["--workflow", "build_reference"], "workflow"),
            (["--input", "{}"], "input"),
            (["--input-file", "INPUT_FILE"], "input-file"),
            (["--apply-digest", "sha256:manual"], "apply-digest"),
            (["--head-snapshot", "snap_manual"], "head-snapshot"),
        ],
    )
    def test_apply_preview_file_rejects_mixed_flags(
        self,
        runner: CliRunner,
        canonical_workflow_instance: CruxibleInstance,
        canonical_input_file: Path,
        extra_args: list[str],
        label: str,
    ) -> None:
        preview_file = canonical_workflow_instance.root / f"mixed-{label}.json"
        preview_file.write_text(
            json.dumps(
                {
                    "kind": "workflow_preview",
                    "version": 1,
                    "workflow": "build_reference",
                    "input": {},
                    "apply_digest": "sha256:test",
                    "head_snapshot_id": "snap_test",
                }
            )
        )

        args = ["apply", "--preview-file", str(preview_file)]
        if extra_args == ["--input-file", "INPUT_FILE"]:
            args.extend(["--input-file", str(canonical_input_file)])
        else:
            args.extend(extra_args)

        result = _chdir_run(runner, canonical_workflow_instance.root, args)

        assert result.exit_code != 0
        assert "--preview-file cannot be combined" in result.output

    @pytest.mark.parametrize(
        ("contents", "message"),
        [
            ("{not-json", "is not valid JSON"),
            (json.dumps({"kind": "not_preview", "version": 1}), "unsupported kind"),
            (json.dumps({"kind": "workflow_preview", "version": 2}), "unsupported version"),
        ],
    )
    def test_apply_preview_file_rejects_malformed(
        self,
        runner: CliRunner,
        canonical_workflow_instance: CruxibleInstance,
        contents: str,
        message: str,
    ) -> None:
        preview_file = canonical_workflow_instance.root / "bad-preview.json"
        preview_file.write_text(contents)

        result = _chdir_run(
            runner,
            canonical_workflow_instance.root,
            ["apply", "--preview-file", str(preview_file)],
        )

        assert result.exit_code != 0
        assert message in result.output
