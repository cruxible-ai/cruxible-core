"""Shared fixtures for MCP tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cruxible_core.mcp.handlers import reset_client_cache
from cruxible_core.mcp.permissions import reset_permissions
from cruxible_core.runtime.instance_manager import get_manager
from cruxible_core.server.registry import reset_registry
from tests.test_cli.conftest import CAR_PARTS_YAML


@pytest.fixture(autouse=True)
def clear_instances():
    """Clear the instance manager between tests."""
    get_manager().clear()
    reset_client_cache()
    reset_registry()
    yield
    get_manager().clear()
    reset_client_cache()
    reset_registry()


@pytest.fixture(autouse=True)
def reset_permission_mode(monkeypatch):
    """Reset permission mode cache between tests."""
    monkeypatch.delenv("CRUXIBLE_MODE", raising=False)
    monkeypatch.delenv("CRUXIBLE_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("CRUXIBLE_REQUIRE_SERVER", raising=False)
    monkeypatch.delenv("CRUXIBLE_SERVER_URL", raising=False)
    monkeypatch.delenv("CRUXIBLE_SERVER_SOCKET", raising=False)
    monkeypatch.delenv("CRUXIBLE_SERVER_TOKEN", raising=False)
    monkeypatch.delenv("CRUXIBLE_SERVER_AUTH", raising=False)
    monkeypatch.delenv("CRUXIBLE_SERVER_STATE_DIR", raising=False)
    reset_permissions()
    yield
    reset_permissions()


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with a config file."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CAR_PARTS_YAML)
    return tmp_path


@pytest.fixture
def vehicles_csv(tmp_project: Path) -> Path:
    """Create a vehicles CSV file."""
    csv_path = tmp_project / "vehicles.csv"
    csv_path.write_text(
        "vehicle_id,year,make,model\n"
        "V-2024-CIVIC-EX,2024,Honda,Civic\n"
        "V-2024-ACCORD-SPORT,2024,Honda,Accord\n"
    )
    return csv_path


@pytest.fixture
def parts_csv(tmp_project: Path) -> Path:
    """Create a parts CSV file."""
    csv_path = tmp_project / "parts.csv"
    csv_path.write_text(
        "part_number,name,category,price\n"
        "BP-1001,Ceramic Brake Pads,brakes,49.99\n"
        "BP-1002,Performance Brake Pads,brakes,89.99\n"
    )
    return csv_path


@pytest.fixture
def fitments_csv(tmp_project: Path) -> Path:
    """Create a fitments CSV file."""
    csv_path = tmp_project / "fitments.csv"
    csv_path.write_text(
        "part_number,vehicle_id,verified,source\n"
        "BP-1001,V-2024-CIVIC-EX,true,catalog\n"
        "BP-1001,V-2024-ACCORD-SPORT,true,catalog\n"
        "BP-1002,V-2024-CIVIC-EX,true,user_report\n"
    )
    return csv_path
