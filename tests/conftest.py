"""Shared test fixtures for cruxible-core."""

from pathlib import Path

import pytest


@pytest.fixture
def configs_dir() -> Path:
    """Path to the configs directory."""
    return Path(__file__).parent.parent / "configs"


@pytest.fixture
def car_parts_config(configs_dir: Path) -> str:
    """Raw YAML string for car parts config."""
    return (configs_dir / "car_parts.yaml").read_text()
