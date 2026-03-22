"""CLI server-mode tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from cruxible_core.cli.main import cli
from cruxible_core.mcp import contracts
from tests.test_cli.conftest import CAR_PARTS_YAML


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_fails_when_server_required_without_endpoint(monkeypatch, runner: CliRunner):
    monkeypatch.setenv("CRUXIBLE_REQUIRE_SERVER", "true")
    result = runner.invoke(cli, ["query", "--query", "parts_for_vehicle"])
    assert result.exit_code == 2
    assert "Server mode is required" in result.output


def test_server_mode_init_reads_local_config_and_prints_instance_id(
    monkeypatch,
    runner: CliRunner,
    tmp_path: Path,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CAR_PARTS_YAML)
    captured: dict[str, object] = {}

    class StubClient:
        def init(self, *, root_dir, config_path=None, config_yaml=None, data_dir=None):
            captured["root_dir"] = root_dir
            captured["config_path"] = config_path
            captured["config_yaml"] = config_yaml
            captured["data_dir"] = data_dir
            return contracts.InitResult(instance_id="inst_abc123", status="initialized")

    monkeypatch.setattr("cruxible_core.cli.commands._get_client", lambda: StubClient())
    result = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "init",
            "--root-dir",
            "/srv/project",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert captured["root_dir"] == "/srv/project"
    assert captured["config_path"] is None
    assert isinstance(captured["config_yaml"], str)
    assert "Instance ID: inst_abc123" in result.output


def test_explain_is_rejected_in_server_mode(monkeypatch, runner: CliRunner):
    monkeypatch.setattr("cruxible_core.cli.commands._get_client", lambda: object())
    result = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "explain",
            "--receipt",
            "R1",
        ],
    )
    assert result.exit_code == 2
    assert "not available in server mode" in result.output


def test_workflow_commands_delegate_to_client_in_server_mode(
    monkeypatch,
    runner: CliRunner,
    tmp_path: Path,
):
    input_path = tmp_path / "input.yaml"
    input_path.write_text("sku: SKU-123\n")

    class StubClient:
        def workflow_lock(self, instance_id):
            assert instance_id == "inst_123"
            return contracts.WorkflowLockResult(
                lock_path="/srv/project/cruxible.lock.yaml",
                config_digest="sha256:abc",
                providers_locked=1,
                artifacts_locked=0,
            )

        def workflow_plan(self, instance_id, *, workflow_name, input_payload=None):
            assert instance_id == "inst_123"
            assert workflow_name == "wf"
            assert input_payload == {"sku": "SKU-123"}
            return contracts.WorkflowPlanResult(plan={"workflow": "wf", "steps": []})

        def workflow_run(self, instance_id, *, workflow_name, input_payload=None):
            assert instance_id == "inst_123"
            return contracts.WorkflowRunResult(
                workflow=workflow_name,
                output={"decision": "approve"},
                receipt_id="RCP-1",
                trace_ids=["TRC-1"],
            )

        def workflow_test(self, instance_id, *, name=None):
            assert instance_id == "inst_123"
            assert name == "smoke"
            return contracts.WorkflowTestResult(
                total=1,
                passed=1,
                failed=0,
                cases=[
                    contracts.WorkflowTestCaseResult(
                        name="smoke",
                        workflow="wf",
                        passed=True,
                        receipt_id="RCP-1",
                    )
                ],
            )

    monkeypatch.setattr("cruxible_core.cli.commands._get_client", lambda: StubClient())

    lock = runner.invoke(
        cli, ["--server-url", "http://server", "--instance-id", "inst_123", "lock"]
    )
    assert lock.exit_code == 0
    assert "digest=sha256:abc" in lock.output

    plan = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "plan",
            "--workflow",
            "wf",
            "--input-file",
            str(input_path),
        ],
    )
    assert plan.exit_code == 0
    assert '"workflow": "wf"' in plan.output

    run = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "run",
            "--workflow",
            "wf",
            "--input-file",
            str(input_path),
        ],
    )
    assert run.exit_code == 0
    assert "Receipt ID: RCP-1" in run.output

    test = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "test",
            "--name",
            "smoke",
        ],
    )
    assert test.exit_code == 0
    assert "1 passed, 0 failed, 1 total" in test.output


def test_propose_snapshot_and_fork_delegate_to_client_in_server_mode(
    monkeypatch,
    runner: CliRunner,
    tmp_path: Path,
):
    input_path = tmp_path / "input.yaml"
    input_path.write_text("campaign_id: CMP-1\n")

    class StubClient:
        def propose_workflow(self, instance_id, *, workflow_name, input_payload=None):
            assert instance_id == "inst_123"
            assert workflow_name == "wf"
            assert input_payload == {"campaign_id": "CMP-1"}
            return contracts.WorkflowProposeResult(
                workflow="wf",
                output={"members": []},
                receipt_id="RCP-1",
                group_id="GRP-1",
                group_status="pending_review",
                review_priority="review",
                trace_ids=["TRC-1"],
            )

        def create_snapshot(self, instance_id, *, label=None):
            assert instance_id == "inst_123"
            assert label == "baseline"
            return contracts.SnapshotCreateResult(
                snapshot=contracts.SnapshotMetadata(
                    snapshot_id="snap_1",
                    created_at="2026-03-21T00:00:00Z",
                    label="baseline",
                    config_digest="sha256:abc",
                    lock_digest=None,
                    graph_sha256="sha256:def",
                    parent_snapshot_id=None,
                    origin_snapshot_id=None,
                )
            )

        def list_snapshots(self, instance_id):
            assert instance_id == "inst_123"
            return contracts.SnapshotListResult(
                snapshots=[
                    contracts.SnapshotMetadata(
                        snapshot_id="snap_1",
                        created_at="2026-03-21T00:00:00Z",
                        label="baseline",
                        config_digest="sha256:abc",
                        lock_digest=None,
                        graph_sha256="sha256:def",
                        parent_snapshot_id=None,
                        origin_snapshot_id=None,
                    )
                ]
            )

        def fork_snapshot(self, instance_id, *, snapshot_id, root_dir):
            assert instance_id == "inst_123"
            assert snapshot_id == "snap_1"
            return contracts.ForkSnapshotResult(
                instance_id="inst_fork",
                snapshot=contracts.SnapshotMetadata(
                    snapshot_id="snap_1",
                    created_at="2026-03-21T00:00:00Z",
                    label="baseline",
                    config_digest="sha256:abc",
                    lock_digest=None,
                    graph_sha256="sha256:def",
                    parent_snapshot_id=None,
                    origin_snapshot_id=None,
                ),
            )

    monkeypatch.setattr("cruxible_core.cli.commands._get_client", lambda: StubClient())

    propose = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "propose",
            "--workflow",
            "wf",
            "--input-file",
            str(input_path),
        ],
    )
    assert propose.exit_code == 0
    assert "group GRP-1" in propose.output

    create = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "snapshot",
            "create",
            "--label",
            "baseline",
        ],
    )
    assert create.exit_code == 0
    assert "Created snapshot snap_1" in create.output

    listed = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "snapshot",
            "list",
        ],
    )
    assert listed.exit_code == 0
    assert "snap_1" in listed.output

    fork = runner.invoke(
        cli,
        [
            "--server-url",
            "http://server",
            "--instance-id",
            "inst_123",
            "fork",
            "--snapshot",
            "snap_1",
            "--root-dir",
            str(tmp_path / "forked"),
        ],
    )
    assert fork.exit_code == 0
    assert "instance inst_fork" in fork.output
