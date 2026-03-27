"""Lifecycle service functions."""

from __future__ import annotations

from pathlib import Path

from cruxible_core.config.loader import load_config, load_config_from_string
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import ConfigError
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.service.types import InitResult, ReloadConfigResult, ValidateServiceResult


def service_validate(
    config_path: str | None = None,
    config_yaml: str | None = None,
) -> ValidateServiceResult:
    """Validate a config file or inline YAML string."""
    sources = sum(value is not None for value in (config_path, config_yaml))
    if sources == 0:
        raise ConfigError("Provide exactly one of config_path or config_yaml")
    if sources > 1:
        raise ConfigError("Provide exactly one of config_path or config_yaml")

    if config_yaml is not None:
        config = load_config_from_string(config_yaml)
    else:
        assert config_path is not None
        config = load_config(config_path)

    warnings = validate_config(config)
    return ValidateServiceResult(config=config, warnings=warnings)


def service_init(
    root_dir: str | Path,
    config_path: str | None = None,
    config_yaml: str | None = None,
    data_dir: str | None = None,
) -> InitResult:
    """Initialize a new cruxible instance (create-only)."""
    if config_path is not None and config_yaml is not None:
        raise ConfigError("Provide exactly one of config_path or config_yaml, not both")
    if config_path is None and config_yaml is None:
        raise ConfigError("config_path or config_yaml is required when initializing a new instance")

    root = Path(root_dir)

    if config_yaml is not None:
        load_config_from_string(config_yaml)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"Failed to create directory {root}: {exc}") from exc
        disk_config = root / "config.yaml"
        if disk_config.exists():
            raise ConfigError(
                f"config.yaml already exists at {root}. "
                "Use config_path to reference the existing file, or remove it first."
            )
        try:
            disk_config.write_text(config_yaml)
        except OSError as exc:
            raise ConfigError(f"Failed to write config.yaml: {exc}") from exc
        config_path = "config.yaml"

    assert config_path is not None
    resolved = Path(config_path)
    if not resolved.is_absolute():
        resolved = root / resolved

    try:
        instance = CruxibleInstance.init(root, config_path, data_dir)
    except Exception:
        if config_yaml is not None:
            try:
                disk_config = root / "config.yaml"
                disk_config.unlink(missing_ok=True)
            except Exception:
                pass
        raise

    config = instance.load_config()
    warnings = validate_config(config)

    return InitResult(instance=instance, warnings=warnings)


def service_reload_config(
    instance: InstanceProtocol,
    config_path: str | None = None,
) -> ReloadConfigResult:
    """Validate the active config or repoint the instance to a new config path."""
    if config_path is not None:
        resolved = Path(config_path)
        if not resolved.is_absolute():
            resolved = instance.get_root_path() / resolved
        config = load_config(resolved)
        warnings = validate_config(config)
        instance.set_config_path(config_path)
        return ReloadConfigResult(
            config_path=str(instance.get_config_path()),
            updated=True,
            warnings=warnings,
        )

    config = instance.load_config()
    warnings = validate_config(config)
    return ReloadConfigResult(
        config_path=str(instance.get_config_path()),
        updated=False,
        warnings=warnings,
    )
