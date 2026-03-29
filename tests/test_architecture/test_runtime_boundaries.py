"""Architecture boundary tests for the runtime refactor."""

from __future__ import annotations

import tomllib
from pathlib import Path

from cruxible_client import CruxibleClient
from cruxible_client import contracts as client_contracts
from cruxible_core.cli.instance import CruxibleInstance as CliCruxibleInstance
from cruxible_core.client import CruxibleClient as CoreCompatClient
from cruxible_core.mcp import contracts as core_contracts
from cruxible_core.mcp import handlers
from cruxible_core.mcp.handlers import get_manager as handler_get_manager
from cruxible_core.runtime import local_api
from cruxible_core.runtime.instance import CruxibleInstance as RuntimeCruxibleInstance
from cruxible_core.runtime.instance_manager import get_manager as runtime_get_manager


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_mcp_handlers_get_manager_returns_canonical_runtime_singleton():
    assert handler_get_manager() is runtime_get_manager()


def test_cli_instance_re_exports_runtime_class_object():
    assert CliCruxibleInstance is RuntimeCruxibleInstance


def test_mcp_local_wrappers_delegate_to_runtime_local_api(monkeypatch):
    sentinel = client_contracts.EvaluateResult(
        entity_count=1,
        edge_count=2,
        findings=[],
        summary={},
        quality_summary={},
    )

    monkeypatch.setattr(handlers, "_get_client", lambda: None)
    monkeypatch.setattr(local_api, "_handle_evaluate_local", lambda *args, **kwargs: sentinel)

    assert handlers.handle_evaluate("instance-id") is sentinel


def test_server_routes_do_not_import_mcp_handlers():
    routes_dir = _repo_root() / "src/cruxible_core/server/routes"
    for path in routes_dir.glob("*.py"):
        source = path.read_text()
        assert "from cruxible_core.mcp.handlers import" not in source, str(path)


def test_service_modules_do_not_import_cli_instance():
    service_dir = _repo_root() / "src/cruxible_core/service"
    for path in service_dir.glob("*.py"):
        source = path.read_text()
        assert "from cruxible_core.cli.instance import" not in source, str(path)


def test_client_package_does_not_import_core_modules():
    client_dir = _repo_root() / "packages/cruxible-client/src/cruxible_client"
    for path in client_dir.rglob("*.py"):
        source = path.read_text()
        assert "cruxible_core" not in source, str(path)


def test_compatibility_re_exports_point_at_client_package():
    assert CoreCompatClient is CruxibleClient
    assert core_contracts.ValidateResult is client_contracts.ValidateResult


def test_core_and_client_package_versions_are_locked_together():
    root_pyproject = tomllib.loads((_repo_root() / "pyproject.toml").read_text())
    client_pyproject = tomllib.loads(
        (_repo_root() / "packages/cruxible-client/pyproject.toml").read_text()
    )

    core_version = root_pyproject["project"]["version"]
    client_version = client_pyproject["project"]["version"]
    dependencies = root_pyproject["project"]["dependencies"]

    assert core_version == client_version
    assert f"cruxible-client=={client_version}" in dependencies
