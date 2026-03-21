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


@pytest.mark.parametrize(
    ("args"),
    [
        ["lock"],
        ["plan", "--workflow", "wf", "--input-file", "/tmp/input.yaml"],
        ["run", "--workflow", "wf", "--input-file", "/tmp/input.yaml"],
        ["test"],
    ],
)
def test_workflow_commands_are_rejected_in_server_mode(
    monkeypatch,
    runner: CliRunner,
    tmp_path: Path,
    args: list[str],
):
    input_path = tmp_path / "input.yaml"
    input_path.write_text("sku: SKU-123\n")
    resolved_args = [str(input_path) if arg == "/tmp/input.yaml" else arg for arg in args]
    monkeypatch.setattr("cruxible_core.cli.commands._get_client", lambda: object())
    result = runner.invoke(cli, ["--server-url", "http://server", *resolved_args])
    assert result.exit_code == 2
    assert "not available in server mode" in result.output
