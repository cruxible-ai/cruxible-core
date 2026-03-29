"""Lifecycle service functions."""

from __future__ import annotations

from pathlib import Path

from cruxible_core.config.composer import compose_configs, write_composed_config
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
    """Validate a config file or inline YAML string.

    If the config uses ``extends``, the base config is resolved and
    composed in memory before validation.  For file-based configs the
    base path is resolved relative to the config file's directory.  For
    inline ``config_yaml``, ``extends`` must be an absolute path or a
    ``ConfigError`` is raised.
    """
    sources = sum(value is not None for value in (config_path, config_yaml))
    if sources == 0:
        raise ConfigError("Provide exactly one of config_path or config_yaml")
    if sources > 1:
        raise ConfigError("Provide exactly one of config_path or config_yaml")

    if config_yaml is not None:
        config = load_config_from_string(config_yaml)
        config_dir: Path | None = None
    else:
        assert config_path is not None
        config = load_config(config_path)
        config_dir = Path(config_path).resolve().parent

    if config.extends is not None:
        base_path = Path(config.extends)
        if not base_path.is_absolute():
            if config_dir is None:
                raise ConfigError(
                    "Inline config_yaml with a relative extends path cannot be "
                    "composed — use an absolute path or validate from a file"
                )
            base_path = config_dir / base_path
        if not base_path.exists():
            raise ConfigError(f"Base config for extends not found: {base_path}")
        base = load_config(base_path)
        config = compose_configs(
            base,
            config,
            base_config_path=base_path,
            overlay_config_path=Path(config_path).resolve() if config_path is not None else None,
        )

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
    upstream = instance.get_upstream_metadata()
    if upstream is not None:
        root = instance.get_root_path()
        overlay_path = root / (config_path or upstream.overlay_config_path)
        if not overlay_path.is_absolute():
            overlay_path = root / overlay_path
        if not overlay_path.exists():
            raise ConfigError(f"Overlay config not found: {overlay_path}")

        composed = write_composed_config(
            base_path=root / upstream.config_path,
            overlay_path=overlay_path,
            output_path=root / upstream.active_config_path,
        )
        warnings = validate_config(composed)
        if config_path is not None:
            try:
                overlay_config_path = str(overlay_path.relative_to(root))
            except ValueError:
                overlay_config_path = str(overlay_path)
            updated = upstream.model_copy(
                update={"overlay_config_path": overlay_config_path}
            )
            instance.set_upstream_metadata(updated)
        instance.set_config_path(upstream.active_config_path)
        return ReloadConfigResult(
            config_path=str(instance.get_config_path()),
            updated=True,
            warnings=warnings,
        )

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
