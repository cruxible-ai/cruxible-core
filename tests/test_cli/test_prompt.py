"""Tests for CLI prompt subcommands."""

from __future__ import annotations

from click.testing import CliRunner

from cruxible_core.cli.main import cli


def test_prompt_list() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["prompt", "list"])
    assert result.exit_code == 0
    for name in [
        "analyze_feedback",
        "common_workflows",
        "onboard_domain",
        "prepare_data",
        "review_graph",
        "user_review",
    ]:
        assert name in result.output


def test_prompt_read_no_args() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["prompt", "read", "--name", "common_workflows"])
    assert result.exit_code == 0
    assert "Debugging a Query" in result.output


def test_prompt_read_with_args() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["prompt", "read", "--name", "onboard_domain", "--arg", "domain=drugs"]
    )
    assert result.exit_code == 0
    assert "drugs" in result.output


def test_prompt_read_unknown_prompt() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["prompt", "read", "--name", "bogus"])
    assert result.exit_code == 1
    assert "Unknown prompt 'bogus'" in result.output


def test_prompt_read_missing_required_arg() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["prompt", "read", "--name", "onboard_domain"])
    assert result.exit_code == 1
    assert "requires: domain" in result.output


def test_prompt_read_extra_arg() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["prompt", "read", "--name", "common_workflows", "--arg", "foo=bar"]
    )
    assert result.exit_code == 1
    assert "Unknown args" in result.output


def test_prompt_read_malformed_arg() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["prompt", "read", "--name", "onboard_domain", "--arg", "domain"]
    )
    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output
