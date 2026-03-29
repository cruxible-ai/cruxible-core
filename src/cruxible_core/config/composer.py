"""Explicit base+overlay config composition for release-backed forks."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cruxible_core.config.loader import load_config, save_config
from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError

_SAFE_LIST_KEYS = {"constraints", "quality_checks", "tests", "decision_policies"}
_KEYED_MAP_KEYS = {
    "entity_types",
    "named_queries",
    "ingestion",
    "integrations",
    "contracts",
    "artifacts",
    "providers",
    "workflows",
    "feedback_profiles",
    "outcome_profiles",
}


def compose_configs(
    base: CoreConfig,
    overlay: CoreConfig,
    *,
    base_config_path: Path | None = None,
    overlay_config_path: Path | None = None,
) -> CoreConfig:
    """Compose a base config and overlay using strict append-only semantics."""
    base_data = base.model_dump(mode="python", by_alias=True, exclude_none=True)
    overlay_data = overlay.model_dump(mode="python", by_alias=True, exclude_none=True)
    if base_config_path is not None:
        base_data = _rebase_artifact_uris(base_data, base_config_path.resolve().parent)
    if overlay_config_path is not None:
        overlay_data = _rebase_artifact_uris(overlay_data, overlay_config_path.resolve().parent)
    composed = _compose_mapping(base_data, overlay_data)
    composed.pop("extends", None)
    return CoreConfig.model_validate(composed)


def write_composed_config(
    *,
    base_path: Path,
    overlay_path: Path,
    output_path: Path,
) -> CoreConfig:
    """Compose base+overlay configs and materialize the merged output on disk."""
    base = load_config(base_path)
    overlay = load_config(overlay_path)
    composed = compose_configs(
        base,
        overlay,
        base_config_path=base_path,
        overlay_config_path=overlay_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_config(composed, output_path)
    return composed


def compose_config_files(
    *,
    base_path: Path,
    overlay_path: Path,
) -> CoreConfig:
    """Compose two config files without writing the merged result to disk."""
    base = load_config(base_path)
    overlay = load_config(overlay_path)
    return compose_configs(
        base,
        overlay,
        base_config_path=base_path,
        overlay_config_path=overlay_path,
    )


def _compose_mapping(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, overlay_value in overlay.items():
        if key == "extends":
            result[key] = overlay_value
            continue
        if key in {"name", "description"}:
            result[key] = overlay_value
            continue
        if key in _SAFE_LIST_KEYS:
            result[key] = list(base.get(key, [])) + list(overlay_value)
            continue
        if key == "relationships":
            result[key] = _compose_relationships(base.get(key, []), overlay_value)
            continue
        if key in _KEYED_MAP_KEYS:
            base_map = dict(base.get(key, {}))
            for child_key, child_value in overlay_value.items():
                if child_key in base_map:
                    raise ConfigError(
                        f"Overlay cannot redefine upstream '{key}' entry '{child_key}'"
                    )
                base_map[child_key] = child_value
            result[key] = base_map
            continue
        if key in result and result[key] != overlay_value:
            raise ConfigError(f"Overlay cannot override upstream field '{key}'")
        result[key] = overlay_value
    return result


def _compose_relationships(
    base_rels: list[dict[str, Any]],
    overlay_rels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = {rel["name"] for rel in base_rels}
    merged = list(base_rels)
    for rel in overlay_rels:
        if rel["name"] in names:
            raise ConfigError(f"Overlay cannot redefine upstream relationship '{rel['name']}'")
        merged.append(rel)
    return merged


def _rebase_artifact_uris(data: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        return data

    rebased_artifacts: dict[str, Any] = {}
    changed = False
    for artifact_name, artifact_value in artifacts.items():
        if not isinstance(artifact_value, dict):
            rebased_artifacts[artifact_name] = artifact_value
            continue
        uri = artifact_value.get("uri")
        if not isinstance(uri, str):
            rebased_artifacts[artifact_name] = artifact_value
            continue
        rebased_uri = _rebase_artifact_uri(uri, config_dir)
        if rebased_uri == uri:
            rebased_artifacts[artifact_name] = artifact_value
            continue
        changed = True
        rebased_artifact = dict(artifact_value)
        rebased_artifact["uri"] = rebased_uri
        rebased_artifacts[artifact_name] = rebased_artifact

    if not changed:
        return data

    rebased = dict(data)
    rebased["artifacts"] = rebased_artifacts
    return rebased


def _rebase_artifact_uri(uri: str, config_dir: Path) -> str:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        return uri

    if parsed.scheme == "file":
        path = Path(parsed.path)
        if path.is_absolute():
            return uri
        return (config_dir / path).resolve().as_uri()

    path = Path(uri)
    if path.is_absolute():
        return uri
    return str((config_dir / path).resolve())
