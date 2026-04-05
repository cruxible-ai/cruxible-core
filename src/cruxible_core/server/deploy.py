"""Deploy bundle staging, bootstrap, and runtime credential management."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from pydantic import ValidationError

from cruxible_client import contracts
from cruxible_core import __version__
from cruxible_core.config.loader import load_config
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import AuthenticationError, ConfigError
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.runtime.instance_manager import get_manager
from cruxible_core.server.auth import (
    require_admin_runtime_auth,
    require_bootstrap_or_admin_auth,
)
from cruxible_core.server.auth_store import get_auth_store
from cruxible_core.server.config import get_server_state_dir
from cruxible_core.server.registry import get_registry
from cruxible_core.service.execution import service_apply_workflow, service_lock, service_run
from cruxible_core.service.lifecycle import service_init
from cruxible_core.service.snapshots import service_create_snapshot
from cruxible_core.service.world import _load_graph_from_bundle, _materialize_upstream_bundle
from cruxible_core.snapshot.types import UpstreamMetadata
from cruxible_core.workflow.compiler import (
    build_lock,
    compute_lock_config_digest,
    compute_path_sha256,
)

DeployStatusLiteral = Literal["bootstrapping", "initialized", "failed", "not_found"]


def stage_deploy_upload(bundle_path: Path) -> contracts.DeployUploadResult:
    """Stage an uploaded deploy bundle under server-owned storage."""
    manifest = _read_bundle_manifest(bundle_path)
    upload_id = f"upload_{uuid.uuid4().hex[:12]}"
    uploads_dir = get_server_state_dir() / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    staged_path = uploads_dir / f"{upload_id}.zip"
    shutil.copy2(bundle_path, staged_path)
    bundle_digest = f"sha256:{hashlib.sha256(staged_path.read_bytes()).hexdigest()}"
    get_auth_store().register_upload(
        upload_id=upload_id,
        staging_path=staged_path,
        bundle_digest=bundle_digest,
        manifest_summary_json=manifest.model_dump_json(),
    )
    return contracts.DeployUploadResult(
        upload_id=upload_id,
        bundle_digest=bundle_digest,
        manifest_summary=manifest,
    )


def get_deploy_status(*, system_id: str, server_url: str | None) -> contracts.DeployStatusResult:
    """Return the bootstrap status for a deployed system."""
    record = get_registry().get_by_system_id(system_id)
    if record is None:
        return contracts.DeployStatusResult(system_id=system_id, status="not_found")
    return contracts.DeployStatusResult(
        system_id=system_id,
        status=cast(DeployStatusLiteral, record.bootstrap_status or "initialized"),
        instance_id=record.instance_id,
        instance_slug=record.instance_slug,
        server_url=server_url,
    )


def bootstrap_deploy(
    *,
    system_id: str,
    upload_id: str,
    instance_slug: str | None,
    server_url: str | None,
) -> contracts.DeployBootstrapResult:
    """Create or re-bootstrap the primary governed instance for a system."""
    auth_context = require_bootstrap_or_admin_auth(system_id=system_id)
    upload = get_auth_store().get_upload(upload_id)
    if upload is None:
        raise ConfigError(f"Deploy upload '{upload_id}' not found")
    if upload.consumed_at is not None:
        raise ConfigError(f"Deploy upload '{upload_id}' has already been used")

    claim = get_registry().claim_deployed_bootstrap(
        system_id=system_id,
        instance_slug=instance_slug,
    )
    if claim.status == "initialized":
        record = claim.record
        return contracts.DeployBootstrapResult(
            status="already_initialized",
            system_id=system_id,
            instance_id=record.instance_id,
            server_url=server_url,
        )
    if claim.status == "bootstrapping":
        raise ConfigError("Deploy bootstrap is already in progress for this system")
    record = claim.record
    root = Path(record.location)
    extract_dir: Path | None = None

    try:
        if auth_context.credential_type == "bootstrap_jwt":
            if auth_context.bootstrap_jti is None or auth_context.bootstrap_expires_at is None:
                raise AuthenticationError("Bootstrap token is missing replay-protection claims")
            if not get_auth_store().consume_bootstrap_jti(
                jti=auth_context.bootstrap_jti,
                expires_at=auth_context.bootstrap_expires_at,
            ):
                raise AuthenticationError("Bootstrap token has already been consumed")

        shutil.rmtree(root, ignore_errors=True)
        root.parent.mkdir(parents=True, exist_ok=True)
        extract_dir = _extract_upload_bundle(Path(upload.staging_path))
        manifest = contracts.DeployBundleManifest.model_validate_json(upload.manifest_summary_json)
        _validate_bundle(extract_dir, manifest)

        warnings: list[str] = []
        if manifest.instance_kind == "plain":
            instance = _bootstrap_plain_instance(
                root=root,
                bundle_root=extract_dir,
                manifest=manifest,
            )
        else:
            instance = _bootstrap_release_fork(
                root=root,
                bundle_root=extract_dir,
                manifest=manifest,
            )

        warnings.extend(_run_canonical_bootstrap_workflows(instance))
        service_create_snapshot(instance, label="bootstrap-initial")
        created_by = auth_context.created_by or f"bootstrap:{system_id}"
        key_record, plaintext = get_auth_store().issue_runtime_key(
            instance_scope=record.instance_id,
            role="admin",
            subject_label=f"{system_id}-admin",
            created_by=created_by,
        )
        get_registry().update_bootstrap_status(record.instance_id, "initialized")
        get_auth_store().mark_upload_consumed(upload_id)
        get_manager().register(record.instance_id, instance)
        return contracts.DeployBootstrapResult(
            status="bootstrapped",
            system_id=system_id,
            instance_id=record.instance_id,
            server_url=server_url,
            warnings=warnings,
            admin_bearer_token=plaintext,
        )
    except Exception:
        get_registry().update_bootstrap_status(record.instance_id, "failed")
        raise
    finally:
        if extract_dir is not None:
            shutil.rmtree(extract_dir, ignore_errors=True)


def create_runtime_key(
    *,
    role: contracts.RuntimeCredentialRole,
    subject_label: str,
) -> contracts.RuntimeCredentialCreateResult:
    auth_context = require_admin_runtime_auth()
    instance_scope = _require_admin_instance_scope(auth_context)
    created_by = auth_context.principal_id
    record, plaintext = get_auth_store().issue_runtime_key(
        instance_scope=instance_scope,
        role=role,
        subject_label=subject_label,
        created_by=created_by,
    )
    return contracts.RuntimeCredentialCreateResult(
        credential=_runtime_credential_metadata(record),
        bearer_token=plaintext,
    )


def list_runtime_keys() -> contracts.RuntimeCredentialListResult:
    auth_context = require_admin_runtime_auth()
    instance_scope = _require_admin_instance_scope(auth_context)
    return contracts.RuntimeCredentialListResult(
        credentials=[
            _runtime_credential_metadata(record)
            for record in get_auth_store().list_runtime_keys(instance_scope=instance_scope)
        ]
    )


def revoke_runtime_key(key_id: str) -> contracts.RuntimeCredentialRevokeResult:
    auth_context = require_admin_runtime_auth()
    instance_scope = _require_admin_instance_scope(auth_context)
    record = get_auth_store().get_runtime_key(key_id)
    if record is None or record.instance_scope != instance_scope:
        raise ConfigError(f"Runtime credential '{key_id}' not found for this instance")
    revoked = get_auth_store().revoke_runtime_key(key_id)
    assert revoked is not None
    return contracts.RuntimeCredentialRevokeResult(
        key_id=revoked.key_id,
        revoked=revoked.revoked_at is not None,
        revoked_at=revoked.revoked_at,
    )


def _runtime_credential_metadata(
    record: object,
) -> contracts.RuntimeCredentialMetadata:
    from cruxible_core.server.auth_store import RuntimeKeyRecord

    assert isinstance(record, RuntimeKeyRecord)
    return contracts.RuntimeCredentialMetadata(
        key_id=record.key_id,
        instance_scope=record.instance_scope,
        role=record.role,  # type: ignore[arg-type]
        subject_label=record.subject_label,
        created_by=record.created_by,
        created_at=record.created_at,
        revoked_at=record.revoked_at,
    )


def _require_admin_instance_scope(auth_context: object) -> str:
    from cruxible_core.server.auth import ResolvedAuthContext

    assert isinstance(auth_context, ResolvedAuthContext)
    if auth_context.instance_scope is None:
        raise AuthenticationError("Admin route requires an instance-scoped runtime credential")
    return auth_context.instance_scope


def _extract_upload_bundle(staged_zip: Path) -> Path:
    extract_dir = Path(tempfile.mkdtemp(prefix="cruxible_deploy_extract_"))
    try:
        with zipfile.ZipFile(staged_zip) as zf:
            for member in zf.infolist():
                _extract_zip_member(zf, member, extract_dir)
        return extract_dir
    except Exception:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise


def _extract_zip_member(zf: zipfile.ZipFile, member: zipfile.ZipInfo, extract_dir: Path) -> None:
    member_path = PurePosixPath(member.filename)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ConfigError(f"Deploy bundle contains invalid archive path: {member.filename}")
    if not member.filename:
        return

    target = extract_dir.joinpath(*member_path.parts)
    resolved_target = target.resolve()
    resolved_root = extract_dir.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ConfigError(f"Deploy bundle contains invalid archive path: {member.filename}")

    if member.is_dir():
        resolved_target.mkdir(parents=True, exist_ok=True)
        return

    resolved_target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as source, resolved_target.open("wb") as handle:
        shutil.copyfileobj(source, handle)


def _read_bundle_manifest(bundle_path: Path) -> contracts.DeployBundleManifest:
    try:
        with zipfile.ZipFile(bundle_path) as zf:
            with zf.open("manifest.json") as handle:
                raw = handle.read().decode("utf-8")
    except KeyError as exc:
        raise ConfigError("Deploy bundle is missing manifest.json") from exc
    except zipfile.BadZipFile as exc:
        raise ConfigError("Deploy bundle must be a valid zip archive") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError("Deploy bundle manifest must be valid UTF-8 JSON") from exc
    try:
        return contracts.DeployBundleManifest.model_validate_json(raw)
    except ValidationError as exc:
        raise ConfigError("Deploy bundle manifest is invalid") from exc


def _validate_bundle(bundle_root: Path, manifest: contracts.DeployBundleManifest) -> None:
    if manifest.cruxible_core_version != __version__:
        raise ConfigError(
            "Deploy bundle cruxible-core version does not match host runtime version"
        )

    config_path = bundle_root / manifest.config_path
    if not config_path.exists():
        raise ConfigError(f"Deploy bundle config path not found: {manifest.config_path}")

    config = load_config(config_path)
    if compute_lock_config_digest(config) != manifest.config_digest:
        raise ConfigError("Deploy bundle config digest mismatch")

    built_lock = build_lock(config, config_path.parent)
    if (built_lock.lock_digest or "") != manifest.lock_digest:
        raise ConfigError("Deploy bundle lock digest mismatch")

    for artifact in manifest.artifacts:
        artifact_path = bundle_root / artifact.bundle_path
        if not artifact_path.exists():
            raise ConfigError(f"Deploy bundle artifact missing: {artifact.bundle_path}")
        if compute_path_sha256(artifact_path) != artifact.sha256:
            raise ConfigError(f"Deploy bundle artifact digest mismatch: {artifact.name}")

    if manifest.instance_kind == "release_fork":
        required = [
            manifest.upstream_metadata_path,
            manifest.overlay_config_path,
            manifest.active_config_path,
            manifest.upstream_bundle_path,
        ]
        if any(value is None for value in required):
            raise ConfigError("Release-fork bundles must include upstream metadata and paths")


def _bootstrap_plain_instance(
    *,
    root: Path,
    bundle_root: Path,
    manifest: contracts.DeployBundleManifest,
) -> CruxibleInstance:
    config_yaml = (bundle_root / manifest.config_path).read_text(encoding="utf-8")
    result = service_init(
        root,
        config_yaml=config_yaml,
        instance_mode=CruxibleInstance.GOVERNED_MODE,
    )
    instance = result.instance
    if not isinstance(instance, CruxibleInstance):
        raise ConfigError("Bootstrap init returned unsupported instance implementation")
    _copy_bundle_artifacts(bundle_root=bundle_root, root=root, manifest=manifest)
    service_lock(instance)
    return instance


def _bootstrap_release_fork(
    *,
    root: Path,
    bundle_root: Path,
    manifest: contracts.DeployBundleManifest,
) -> CruxibleInstance:
    if (
        manifest.upstream_metadata_path is None
        or manifest.overlay_config_path is None
        or manifest.active_config_path is None
        or manifest.upstream_bundle_path is None
    ):
        raise ConfigError("Release-fork bundle is missing upstream metadata or path declarations")

    upstream = UpstreamMetadata.model_validate_json(
        (bundle_root / manifest.upstream_metadata_path).read_text(encoding="utf-8")
    )
    overlay_source = bundle_root / manifest.overlay_config_path
    active_source = bundle_root / manifest.active_config_path
    upstream_bundle_source = bundle_root / manifest.upstream_bundle_path
    overlay_dest = root / upstream.overlay_config_path
    active_dest = root / upstream.active_config_path
    overlay_dest.parent.mkdir(parents=True, exist_ok=True)
    active_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(overlay_source, overlay_dest)
    shutil.copy2(active_source, active_dest)
    validate_config(load_config(active_dest))

    instance = CruxibleInstance.init(
        root,
        upstream.active_config_path,
        instance_mode=CruxibleInstance.GOVERNED_MODE,
    )
    upstream_dir = _materialize_upstream_bundle(root, upstream_bundle_source, upstream.release_id)
    instance.save_graph(_load_graph_from_bundle(upstream_dir))
    instance.set_upstream_metadata(upstream)
    _copy_bundle_artifacts(bundle_root=bundle_root, root=root, manifest=manifest)
    service_lock(instance)
    return instance


def _copy_bundle_artifacts(
    *,
    bundle_root: Path,
    root: Path,
    manifest: contracts.DeployBundleManifest,
) -> None:
    for artifact in manifest.artifacts:
        source = bundle_root / artifact.bundle_path
        target = root / artifact.bundle_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def _run_canonical_bootstrap_workflows(instance: CruxibleInstance) -> list[str]:
    config = instance.load_config()
    warnings: list[str] = []
    for workflow_name, workflow in config.workflows.items():
        if not workflow.canonical:
            continue
        preview = service_run(instance, workflow_name, {})
        if preview.apply_digest is None:
            warnings.append(f"Canonical workflow '{workflow_name}' did not produce an apply digest")
            continue
        service_apply_workflow(
            instance,
            workflow_name,
            {},
            expected_apply_digest=preview.apply_digest,
            expected_head_snapshot_id=preview.head_snapshot_id,
        )
    return warnings
