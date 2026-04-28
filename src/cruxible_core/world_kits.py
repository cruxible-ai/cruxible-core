"""Checked-in fork overlay kit catalog and materialization helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from cruxible_core.errors import ConfigError


@dataclass(frozen=True)
class WorldKitEntry:
    """One checked-in fork overlay kit entry."""

    kit: str
    source_dir: Path
    config_path: str = "config.yaml"
    copy_paths: tuple[str, ...] = ()
    world_id: str | None = None
    description: str | None = None


def get_world_kit_catalog() -> dict[str, WorldKitEntry]:
    """Return the checked-in fork kit catalog."""
    repo_root = Path(__file__).resolve().parents[2]
    kev_dir = repo_root / "kits" / "kev-triage"
    return {
        "kev-triage": WorldKitEntry(
            kit="kev-triage",
            source_dir=kev_dir,
            config_path="config.yaml",
            copy_paths=("providers.py", "data/seed"),
            world_id="kev-reference",
            description="Internal KEV triage overlay kit",
        )
    }


def materialize_world_kit(
    *,
    kit: str,
    root: Path,
    upstream_world_id: str,
    upstream_config_path: str = ".cruxible/upstream/current/config.yaml",
) -> Path:
    """Copy a checked-in kit overlay into a fork workspace."""
    catalog = get_world_kit_catalog()
    try:
        entry = catalog[kit]
    except KeyError as exc:
        known = ", ".join(sorted(catalog))
        raise ConfigError(
            f"Unknown world kit '{kit}'. Known kits: {known or '(none)'}"
        ) from exc

    if entry.world_id is not None and entry.world_id != upstream_world_id:
        raise ConfigError(
            f"Kit '{kit}' targets world '{entry.world_id}', not '{upstream_world_id}'"
        )

    source_dir = entry.source_dir
    if not source_dir.exists():
        raise ConfigError(
            f"Kit '{kit}' source directory is missing: {source_dir}"
        )

    config_source = source_dir / entry.config_path
    if not config_source.exists():
        raise ConfigError(f"Kit '{kit}' is missing config file: {config_source}")

    root.mkdir(parents=True, exist_ok=True)
    config_target = root / "config.yaml"
    _copy_file(config_source, config_target)
    _rewrite_extends(config_target, upstream_config_path)

    for rel_path in entry.copy_paths:
        source = source_dir / rel_path
        target = root / rel_path
        if not source.exists():
            raise ConfigError(
                f"Kit '{kit}' is missing companion path: {source}"
            )
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            _copy_file(source, target)

    return config_target


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _rewrite_extends(config_path: Path, upstream_config_path: str) -> None:
    raw = config_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.lstrip().startswith("extends:"):
            indent = line[: len(line) - len(line.lstrip())]
            updated.append(f"{indent}extends: {upstream_config_path}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        raise ConfigError(
            f"Kit config '{config_path}' must contain an extends: entry"
        )
    config_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
