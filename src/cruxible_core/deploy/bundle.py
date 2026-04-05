"""Deploy bundle builder for remote bootstrap."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cruxible_client import contracts
from cruxible_core import __version__
from cruxible_core.config.composer import _rebase_artifact_uris, compose_configs
from cruxible_core.config.loader import load_config
from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError, InstanceNotFoundError
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.workflow.compiler import (
    build_lock,
    compute_lock_config_digest,
    compute_path_sha256,
    write_lock,
)


@dataclass(frozen=True)
class BuiltDeployBundle:
    bundle_path: Path
    manifest: contracts.DeployBundleManifest


def build_deploy_bundle(
    *,
    root_dir: str | Path,
    config_path: str | None = None,
) -> BuiltDeployBundle:
    """Build a self-contained deploy bundle zip for a plain instance or release fork."""
    root = Path(root_dir).expanduser().resolve()

    instance: CruxibleInstance | None = None
    try:
        loaded = CruxibleInstance.load(root)
        if loaded.get_root_path().resolve() == root:
            instance = loaded
    except InstanceNotFoundError:
        instance = None

    if instance is not None and instance.get_upstream_metadata() is not None:
        return _build_release_fork_bundle(instance)

    resolved_config = Path(config_path) if config_path is not None else root / "config.yaml"
    if not resolved_config.is_absolute():
        resolved_config = root / resolved_config
    if not resolved_config.exists():
        raise ConfigError(f"Config file not found: {resolved_config}")
    return _build_plain_bundle(root=root, config_path=resolved_config)


def _build_plain_bundle(*, root: Path, config_path: Path) -> BuiltDeployBundle:
    config = load_config(config_path)
    if config.extends is not None:
        base_path = Path(config.extends)
        if not base_path.is_absolute():
            base_path = config_path.resolve().parent / base_path
        if not base_path.exists():
            raise ConfigError(f"Base config for extends not found: {base_path}")
        base = load_config(base_path)
        config = compose_configs(
            base,
            config,
            base_config_path=base_path,
            overlay_config_path=config_path.resolve(),
        )

    temp_root = Path(tempfile.mkdtemp(prefix="cruxible_deploy_bundle_"))
    temp_config_path = temp_root / "config.yaml"
    data = config.model_dump(mode="python", by_alias=True, exclude_none=True)
    data = _rebase_artifact_uris(data, config_path.resolve().parent)
    rewritten = _copy_artifacts_and_rewrite_uris(data, temp_root=temp_root)
    bundled_config = CoreConfig.model_validate(rewritten)
    temp_config_path.write_text(
        yaml.safe_dump(rewritten, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    lock = build_lock(bundled_config, temp_root)
    write_lock(lock, temp_root / "cruxible.lock.yaml")

    manifest = contracts.DeployBundleManifest(
        instance_kind="plain",
        cruxible_core_version=__version__,
        config_name=bundled_config.name,
        config_path="config.yaml",
        lock_path="cruxible.lock.yaml",
        config_digest=compute_lock_config_digest(bundled_config),
        lock_digest=lock.lock_digest or "",
        artifacts=_build_manifest_artifacts(rewritten),
    )
    return BuiltDeployBundle(
        bundle_path=_write_bundle_zip(temp_root, manifest),
        manifest=manifest,
    )


def _build_release_fork_bundle(instance: CruxibleInstance) -> BuiltDeployBundle:
    upstream = instance.get_upstream_metadata()
    assert upstream is not None
    root = instance.get_root_path()
    overlay_path = root / upstream.overlay_config_path
    active_config_path = instance.get_config_path()
    upstream_bundle_dir = root / ".cruxible" / "upstream" / "current"
    if not overlay_path.exists():
        raise ConfigError(f"Overlay config not found: {overlay_path}")
    if not active_config_path.exists():
        raise ConfigError(f"Active config not found: {active_config_path}")
    if not upstream_bundle_dir.exists():
        raise ConfigError(f"Upstream bundle not found: {upstream_bundle_dir}")

    temp_root = Path(tempfile.mkdtemp(prefix="cruxible_deploy_bundle_"))
    active_data = load_config(active_config_path).model_dump(
        mode="python",
        by_alias=True,
        exclude_none=True,
    )
    active_data = _rebase_artifact_uris(active_data, active_config_path.resolve().parent)
    overlay_data = load_config(overlay_path).model_dump(
        mode="python",
        by_alias=True,
        exclude_none=True,
    )
    overlay_data = _rebase_artifact_uris(overlay_data, overlay_path.resolve().parent)
    rewritten_active = _copy_artifacts_and_rewrite_uris(active_data, temp_root=temp_root)
    rewritten_overlay = _copy_artifacts_and_rewrite_uris(
        overlay_data,
        temp_root=temp_root,
        preserve_existing=True,
    )
    active_bundle_path = temp_root / "active-config.yaml"
    overlay_bundle_path = temp_root / "overlay-config.yaml"
    active_bundle_path.write_text(
        yaml.safe_dump(rewritten_active, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    overlay_bundle_path.write_text(
        yaml.safe_dump(rewritten_overlay, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    copied_upstream_dir = temp_root / "upstream" / "current"
    copied_upstream_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(upstream_bundle_dir, copied_upstream_dir, dirs_exist_ok=True)

    bundled_active_config = CoreConfig.model_validate(rewritten_active)
    lock = build_lock(bundled_active_config, temp_root)
    write_lock(lock, temp_root / "cruxible.lock.yaml")
    (temp_root / "upstream-metadata.json").write_text(
        upstream.model_dump_json(indent=2),
        encoding="utf-8",
    )

    manifest = contracts.DeployBundleManifest(
        instance_kind="release_fork",
        cruxible_core_version=__version__,
        config_name=bundled_active_config.name,
        config_path="active-config.yaml",
        lock_path="cruxible.lock.yaml",
        config_digest=compute_lock_config_digest(bundled_active_config),
        lock_digest=lock.lock_digest or "",
        artifacts=_build_manifest_artifacts(rewritten_active),
        upstream_release_id=upstream.release_id,
        upstream_metadata_path="upstream-metadata.json",
        overlay_config_path="overlay-config.yaml",
        active_config_path="active-config.yaml",
        upstream_bundle_path="upstream/current",
    )
    return BuiltDeployBundle(
        bundle_path=_write_bundle_zip(temp_root, manifest),
        manifest=manifest,
    )


def _copy_artifacts_and_rewrite_uris(
    data: dict[str, Any],
    *,
    temp_root: Path,
    preserve_existing: bool = False,
) -> dict[str, Any]:
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        return dict(data)

    result = dict(data)
    rewritten_artifacts: dict[str, Any] = {}
    artifact_dir = temp_root / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for artifact_name, artifact_value in artifacts.items():
        if not isinstance(artifact_value, dict):
            rewritten_artifacts[artifact_name] = artifact_value
            continue
        uri = artifact_value.get("uri")
        if not isinstance(uri, str):
            rewritten_artifacts[artifact_name] = artifact_value
            continue
        source_path = _resolve_local_artifact_source(uri)
        if source_path is None:
            rewritten_artifacts[artifact_name] = artifact_value
            continue
        if not source_path.exists():
            raise ConfigError(f"Artifact path does not exist: {source_path}")
        target_rel = Path("artifacts") / artifact_name
        target_path = temp_root / target_rel
        if target_path.exists():
            if preserve_existing:
                rewritten_artifacts[artifact_name] = {
                    **artifact_value,
                    "uri": target_rel.as_posix(),
                    "sha256": compute_path_sha256(target_path),
                }
                continue
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()
        _copy_path(source_path, target_path)
        rewritten_artifacts[artifact_name] = {
            **artifact_value,
            "uri": target_rel.as_posix(),
            "sha256": compute_path_sha256(target_path),
        }

    result["artifacts"] = rewritten_artifacts
    result.pop("extends", None)
    return result


def _resolve_local_artifact_source(uri: str) -> Path | None:
    if uri.startswith("file://"):
        path = Path(uri[7:])
    else:
        path = Path(uri)
    if path.is_absolute():
        return path
    if ".." in path.parts:
        raise ConfigError(f"Deploy bundle artifacts must not escape the source root: {uri}")
    return path.resolve()


def _copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
        return
    shutil.copy2(source, target)


def _build_manifest_artifacts(data: dict[str, Any]) -> list[contracts.DeployBundleArtifact]:
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        return []
    result: list[contracts.DeployBundleArtifact] = []
    for artifact_name, artifact_value in artifacts.items():
        if not isinstance(artifact_value, dict):
            continue
        uri = artifact_value.get("uri")
        sha256 = artifact_value.get("sha256")
        if not isinstance(uri, str) or not isinstance(sha256, str):
            continue
        result.append(
            contracts.DeployBundleArtifact(
                name=artifact_name,
                uri=uri,
                bundle_path=uri,
                sha256=sha256,
            )
        )
    return result


def _write_bundle_zip(temp_root: Path, manifest: contracts.DeployBundleManifest) -> Path:
    (temp_root / "manifest.json").write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    bundle_path = Path(tempfile.mkstemp(prefix="cruxible_bundle_", suffix=".zip")[1])
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(temp_root.rglob("*")):
            if path.is_dir():
                continue
            zf.write(path, path.relative_to(temp_root).as_posix())
    return bundle_path
