"""Deploy bundle staging, async bootstrap, and runtime credential management."""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import threading
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
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
    get_current_auth_context,
    require_admin_runtime_auth,
    require_bootstrap_or_admin_auth,
    require_deploy_session,
)
from cruxible_core.server.auth_store import (
    DeployOperationRecord,
    get_auth_store,
)
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

_LOG = logging.getLogger(__name__)
_DEPLOY_EXECUTOR: ThreadPoolExecutor | None = None
_DEPLOY_FUTURES: dict[str, Future[None]] = {}
_DEPLOY_EXECUTOR_LOCK = threading.Lock()
_DEPLOY_FUTURES_LOCK = threading.Lock()
_DEPLOY_RUNTIME_LOCK = threading.Lock()
_DEPLOY_RUNTIME_INITIALIZED = False
_DEPLOY_START_LOCK = threading.Lock()
_PENDING_ADMIN_CLAIMS: dict[str, tuple[str, str]] = {}
_PENDING_ADMIN_CLAIMS_LOCK = threading.Lock()


def initialize_deploy_runtime() -> None:
    """Initialize async deploy runtime and recover stale operations."""
    global _DEPLOY_RUNTIME_INITIALIZED
    with _DEPLOY_RUNTIME_LOCK:
        if _DEPLOY_RUNTIME_INITIALIZED:
            return
        _ensure_deploy_executor()
        _recover_abandoned_operations()
        get_auth_store().purge_expired_claim_slots()
        get_auth_store().purge_expired_deploy_sessions()
        _purge_expired_pending_admin_claims()
        _DEPLOY_RUNTIME_INITIALIZED = True


def reset_deploy_runtime() -> None:
    """Reset background deploy runtime. Intended for tests."""
    global _DEPLOY_EXECUTOR, _DEPLOY_RUNTIME_INITIALIZED
    with _DEPLOY_FUTURES_LOCK:
        futures = list(_DEPLOY_FUTURES.values())
        _DEPLOY_FUTURES.clear()
    with _PENDING_ADMIN_CLAIMS_LOCK:
        _PENDING_ADMIN_CLAIMS.clear()
    for future in futures:
        future.cancel()
    if _DEPLOY_EXECUTOR is not None:
        _DEPLOY_EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _DEPLOY_EXECUTOR = None
    _DEPLOY_RUNTIME_INITIALIZED = False


def _ensure_deploy_executor() -> ThreadPoolExecutor:
    global _DEPLOY_EXECUTOR
    with _DEPLOY_EXECUTOR_LOCK:
        if _DEPLOY_EXECUTOR is None:
            _DEPLOY_EXECUTOR = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="cruxible-deploy",
            )
    return _DEPLOY_EXECUTOR


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


def start_deploy_bootstrap(
    *,
    system_id: str,
    upload_id: str,
    instance_slug: str | None,
    server_url: str | None,
) -> contracts.DeployBootstrapStartResult:
    """Start or resume an async remote bootstrap operation."""
    auth_context = require_bootstrap_or_admin_auth(system_id=system_id)
    with _DEPLOY_START_LOCK:
        upload = get_auth_store().get_upload(upload_id)
        if upload is None:
            raise ConfigError(f"Deploy upload '{upload_id}' not found")
        if upload.consumed_at is not None:
            raise ConfigError(f"Deploy upload '{upload_id}' has already been used")

        claim = _claim_bootstrap_slot_with_recovery(
            system_id=system_id,
            instance_slug=instance_slug,
        )
        if claim.status == "initialized":
            record = claim.record
            return contracts.DeployBootstrapStartResult(
                status="already_initialized",
                system_id=system_id,
                instance_id=record.instance_id,
                server_url=server_url,
            )

        if claim.status == "bootstrapping":
            existing = get_auth_store().get_active_deploy_operation(system_id=system_id)
            if existing is None:
                raise ConfigError("Deploy bootstrap is already in progress for this system")
            if existing.upload_id != upload_id:
                raise ConfigError(
                    "Deploy bootstrap is already in progress for this system "
                    "with a different upload"
                )
            return _start_result_from_operation(
                existing,
                server_url=server_url,
                status="in_progress",
                deploy_session_token=None,
            )

        record = claim.record
        try:
            if auth_context.credential_type == "bootstrap_jwt":
                if auth_context.bootstrap_jti is None or auth_context.bootstrap_expires_at is None:
                    raise AuthenticationError("Bootstrap token is missing replay-protection claims")
                if not get_auth_store().consume_bootstrap_jti(
                    jti=auth_context.bootstrap_jti,
                    expires_at=auth_context.bootstrap_expires_at,
                ):
                    get_registry().update_bootstrap_status(record.instance_id, "failed")
                    raise AuthenticationError("Bootstrap token has already been consumed")

            operation = get_auth_store().create_deploy_operation(
                system_id=system_id,
                upload_id=upload_id,
                instance_id=record.instance_id,
            )
            session_token = get_auth_store().issue_deploy_session_token(
                operation_id=operation.operation_id,
                system_id=system_id,
                principal_id=auth_context.principal_id,
                actions=["status", "claim_admin_key"],
            )
            _submit_deploy_operation(
                operation_id=operation.operation_id,
                created_by=auth_context.created_by or f"bootstrap:{system_id}",
            )
        except Exception:
            get_registry().update_bootstrap_status(record.instance_id, "failed")
            raise

    return _start_result_from_operation(
        operation,
        server_url=server_url,
        status="started",
        deploy_session_token=session_token,
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


def get_deploy_operation_status(
    *,
    operation_id: str,
    server_url: str | None,
) -> contracts.DeployOperationStatus:
    """Return detailed async deploy operation status."""
    operation = get_auth_store().get_deploy_operation(operation_id)
    if operation is None:
        raise ConfigError(f"Deploy operation '{operation_id}' not found")
    _require_operation_auth(operation, action="status")
    return _operation_status_from_record(operation, server_url=server_url)


def claim_deploy_admin_key(
    *,
    operation_id: str,
    server_url: str | None,
) -> contracts.ClaimAdminKeyResult:
    """Claim the one-time initial admin bearer token for a finished deploy."""
    operation = get_auth_store().get_deploy_operation(operation_id)
    if operation is None:
        raise ConfigError(f"Deploy operation '{operation_id}' not found")
    _require_operation_auth(operation, action="claim_admin_key")
    if operation.status != "succeeded":
        raise ConfigError("Deploy operation is not ready to claim an admin key")
    token = _peek_pending_admin_claim(operation_id)
    if token is None:
        raise ConfigError("Initial admin key is no longer available for this deploy operation")
    if not get_auth_store().consume_deploy_claim_slot(operation_id):
        _discard_pending_admin_claim(operation_id)
        raise ConfigError("Initial admin key is no longer available for this deploy operation")
    _discard_pending_admin_claim(operation_id)
    refreshed = get_auth_store().get_deploy_operation(operation_id)
    assert refreshed is not None
    if refreshed.instance_id is None:
        raise ConfigError("Deploy operation is missing an instance ID")
    return contracts.ClaimAdminKeyResult(
        operation_id=operation_id,
        system_id=refreshed.system_id,
        instance_id=refreshed.instance_id,
        server_url=server_url,
        admin_bearer_token=token,
    )


def recover_deploy_admin_key(
    *,
    operation_id: str,
    server_url: str | None,
) -> contracts.ClaimAdminKeyResult:
    """Recover the initial admin credential when the in-memory claim token is gone."""
    operation = get_auth_store().get_deploy_operation(operation_id)
    if operation is None:
        raise ConfigError(f"Deploy operation '{operation_id}' not found")
    auth_context = require_bootstrap_or_admin_auth(system_id=operation.system_id)
    if operation.status != "succeeded":
        raise ConfigError("Deploy operation is not ready to recover an admin key")
    if operation.instance_id is None:
        raise ConfigError("Deploy operation is missing an instance ID")

    token = _peek_pending_admin_claim(operation_id)
    if token is not None:
        if not get_auth_store().consume_deploy_claim_slot(operation_id):
            _discard_pending_admin_claim(operation_id)
            raise ConfigError(
                "Initial admin key is no longer recoverable for this deploy operation"
            )
        _discard_pending_admin_claim(operation_id)
    else:
        token = get_auth_store().recover_deploy_admin_key(
            operation_id=operation_id,
            instance_scope=operation.instance_id,
            subject_label=f"{operation.system_id}-admin-recovered",
            created_by=auth_context.created_by or auth_context.principal_id,
        )
        if token is None:
            raise ConfigError(
                "Initial admin key is no longer recoverable for this deploy operation"
            )

    refreshed = get_auth_store().get_deploy_operation(operation_id)
    assert refreshed is not None
    return contracts.ClaimAdminKeyResult(
        operation_id=operation_id,
        system_id=refreshed.system_id,
        instance_id=operation.instance_id,
        server_url=server_url,
        admin_bearer_token=token,
    )


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


def _submit_deploy_operation(*, operation_id: str, created_by: str) -> None:
    executor = _ensure_deploy_executor()
    future = executor.submit(_run_deploy_operation, operation_id, created_by)
    with _DEPLOY_FUTURES_LOCK:
        _DEPLOY_FUTURES[operation_id] = future

    def _cleanup(done: Future[None]) -> None:
        with _DEPLOY_FUTURES_LOCK:
            _DEPLOY_FUTURES.pop(operation_id, None)
        exc = done.exception()
        if exc is None:
            return
        operation = get_auth_store().get_deploy_operation(operation_id)
        if operation is not None and operation.status in {"queued", "running"}:
            _mark_operation_failed(
                operation,
                error_message=_public_operation_error(exc),
                failure_reason="worker_exception",
            )
        _LOG.exception(
            "Deploy operation %s failed in background worker",
            operation_id,
            exc_info=exc,
        )

    future.add_done_callback(_cleanup)


def _run_deploy_operation(operation_id: str, created_by: str) -> None:
    operation = get_auth_store().get_deploy_operation(operation_id)
    if operation is None:
        raise ConfigError(f"Deploy operation '{operation_id}' not found")
    registry_record = get_registry().get_by_system_id(operation.system_id)
    if registry_record is None:
        raise ConfigError(f"Deploy system '{operation.system_id}' is missing from the registry")
    upload = get_auth_store().get_upload(operation.upload_id)
    if upload is None:
        raise ConfigError(f"Deploy upload '{operation.upload_id}' not found")
    root = Path(registry_record.location)
    extract_dir: Path | None = None
    warnings: list[str] = []

    try:
        _update_operation_progress(
            operation_id,
            phase="validation",
            progress_message="Validating deploy bundle",
        )
        extract_dir = _extract_upload_bundle(Path(upload.staging_path))
        manifest = contracts.DeployBundleManifest.model_validate_json(upload.manifest_summary_json)
        _validate_bundle(extract_dir, manifest)

        _update_operation_progress(
            operation_id,
            phase="init",
            progress_message="Initializing governed instance",
            current_workflow=None,
            current_step_id=None,
            current_provider=None,
        )
        shutil.rmtree(root, ignore_errors=True)
        root.parent.mkdir(parents=True, exist_ok=True)

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

        warnings.extend(_run_canonical_bootstrap_workflows(instance, operation_id=operation_id))
        _update_operation_progress(
            operation_id,
            phase="snapshot",
            progress_message="Creating bootstrap snapshot",
            current_workflow=None,
            current_step_id=None,
            current_provider=None,
        )
        service_create_snapshot(instance, label="bootstrap-initial")
        get_manager().register(registry_record.instance_id, instance)
        plaintext, expires_at = get_auth_store().complete_deploy_operation_with_claim_slot(
            operation_id=operation_id,
            instance_scope=registry_record.instance_id,
            subject_label=f"{operation.system_id}-admin",
            created_by=created_by,
            warnings=warnings,
        )
        _store_pending_admin_claim(operation_id, plaintext, expires_at)
        get_registry().update_bootstrap_status(registry_record.instance_id, "initialized")
        get_auth_store().mark_upload_consumed(operation.upload_id)
        Path(upload.staging_path).unlink(missing_ok=True)
    except Exception as exc:
        _mark_operation_failed(
            operation,
            error_message=_public_operation_error(exc),
            failure_reason="worker_exception",
        )
        _LOG.exception("Deploy operation %s failed", operation_id, exc_info=exc)
        raise
    finally:
        if extract_dir is not None:
            shutil.rmtree(extract_dir, ignore_errors=True)


def _recover_abandoned_operations() -> None:
    for operation in get_auth_store().list_active_deploy_operations():
        _mark_operation_failed(
            operation,
            error_message="Bootstrap marked failed after server restart or worker crash",
            failure_reason="server_restart_or_worker_crash",
        )
        _LOG.warning(
            "Marked deploy operation failed during startup recovery: operation_id=%s system_id=%s "
            "status=%s phase=%s workflow=%s step=%s provider=%s last_progress_at=%s "
            "failure_reason=%s",
            operation.operation_id,
            operation.system_id,
            operation.status,
            operation.phase,
            operation.current_workflow,
            operation.current_step_id,
            operation.current_provider,
            operation.last_progress_at,
            "server_restart_or_worker_crash",
        )


def _require_operation_auth(
    operation: DeployOperationRecord,
    *,
    action: str,
) -> None:
    context = get_current_auth_context()
    if context is None:
        raise AuthenticationError("Deploy operation authentication required")
    if context.credential_type == "deploy_session":
        require_deploy_session(operation.operation_id, action)
        return
    require_bootstrap_or_admin_auth(system_id=operation.system_id)


def _start_result_from_operation(
    operation: DeployOperationRecord,
    *,
    server_url: str | None,
    status: contracts.DeployBootstrapStartStatus,
    deploy_session_token: str | None,
) -> contracts.DeployBootstrapStartResult:
    return contracts.DeployBootstrapStartResult(
        status=status,
        system_id=operation.system_id,
        operation_id=operation.operation_id,
        instance_id=operation.instance_id,
        server_url=server_url,
        phase=cast(contracts.DeployOperationPhase | None, operation.phase),
        current_workflow=operation.current_workflow,
        current_step_id=operation.current_step_id,
        current_provider=operation.current_provider,
        progress_message=operation.progress_message,
        deploy_session_token=deploy_session_token,
    )


def _operation_status_from_record(
    operation: DeployOperationRecord,
    *,
    server_url: str | None,
) -> contracts.DeployOperationStatus:
    return contracts.DeployOperationStatus(
        operation_id=operation.operation_id,
        system_id=operation.system_id,
        status=cast(contracts.DeployOperationStatusLiteral, operation.status),
        phase=cast(contracts.DeployOperationPhase | None, operation.phase),
        instance_id=operation.instance_id,
        server_url=server_url,
        current_workflow=operation.current_workflow,
        current_step_id=operation.current_step_id,
        current_provider=operation.current_provider,
        progress_message=operation.progress_message,
        warnings=operation.warnings,
        error_message=operation.error_message,
        failure_reason=cast(contracts.DeployFailureReason | None, operation.failure_reason),
        last_progress_at=operation.last_progress_at,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        completed_at=operation.completed_at,
        admin_key_claimed_at=operation.admin_key_claimed_at,
    )


def _claim_bootstrap_slot_with_recovery(
    *,
    system_id: str,
    instance_slug: str | None,
):
    claim = get_registry().claim_deployed_bootstrap(
        system_id=system_id,
        instance_slug=instance_slug,
    )
    if claim.status != "bootstrapping":
        return claim

    existing = get_auth_store().get_active_deploy_operation(system_id=system_id)
    if existing is not None:
        return claim

    _LOG.warning(
        "Resetting orphaned bootstrapping registry state: system_id=%s instance_id=%s",
        system_id,
        claim.record.instance_id,
    )
    get_registry().update_bootstrap_status(claim.record.instance_id, "failed")
    healed = get_registry().claim_deployed_bootstrap(
        system_id=system_id,
        instance_slug=instance_slug,
    )
    if healed.status == "bootstrapping":
        raise ConfigError("Deploy bootstrap is in an inconsistent state; retry the request")
    return healed


def _public_operation_error(exc: Exception) -> str:
    if isinstance(exc, (AuthenticationError, ConfigError)):
        return str(exc)
    return "Bootstrap failed; see server logs for server-side details"


def _mark_operation_failed(
    operation: DeployOperationRecord,
    *,
    error_message: str,
    failure_reason: contracts.DeployFailureReason,
) -> None:
    _discard_pending_admin_claim(operation.operation_id)
    now_iso = datetime.now(UTC).isoformat()
    get_auth_store().update_deploy_operation(
        operation.operation_id,
        status="failed",
        error_message=error_message,
        failure_reason=failure_reason,
        completed_at=now_iso,
        bump_progress=True,
    )
    if operation.instance_id is not None:
        get_registry().update_bootstrap_status(operation.instance_id, "failed")


def _store_pending_admin_claim(operation_id: str, token: str, expires_at: str) -> None:
    with _PENDING_ADMIN_CLAIMS_LOCK:
        _PENDING_ADMIN_CLAIMS[operation_id] = (token, expires_at)


def _peek_pending_admin_claim(operation_id: str) -> str | None:
    now_iso = datetime.now(UTC).isoformat()
    with _PENDING_ADMIN_CLAIMS_LOCK:
        entry = _PENDING_ADMIN_CLAIMS.get(operation_id)
        if entry is None:
            return None
        token, expires_at = entry
        if expires_at <= now_iso:
            _PENDING_ADMIN_CLAIMS.pop(operation_id, None)
            return None
        return token


def _discard_pending_admin_claim(operation_id: str) -> None:
    with _PENDING_ADMIN_CLAIMS_LOCK:
        _PENDING_ADMIN_CLAIMS.pop(operation_id, None)


def _purge_expired_pending_admin_claims() -> None:
    now_iso = datetime.now(UTC).isoformat()
    with _PENDING_ADMIN_CLAIMS_LOCK:
        expired = [
            operation_id
            for operation_id, (_token, expires_at) in _PENDING_ADMIN_CLAIMS.items()
            if expires_at <= now_iso
        ]
        for operation_id in expired:
            _PENDING_ADMIN_CLAIMS.pop(operation_id, None)


def _update_operation_progress(
    operation_id: str,
    *,
    phase: contracts.DeployOperationPhase,
    progress_message: str,
    current_workflow: str | None = None,
    current_step_id: str | None = None,
    current_provider: str | None = None,
) -> None:
    get_auth_store().update_deploy_operation(
        operation_id,
        status="running",
        phase=phase,
        current_workflow=current_workflow,
        current_step_id=current_step_id,
        current_provider=current_provider,
        progress_message=progress_message,
        bump_progress=True,
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


def _run_canonical_bootstrap_workflows(
    instance: CruxibleInstance,
    *,
    operation_id: str,
) -> list[str]:
    config = instance.load_config()
    warnings: list[str] = []

    def _progress_callback(step_id: str, provider_name: str | None, kind: str) -> None:
        progress_message = f"Running {kind} step '{step_id}'"
        if provider_name:
            progress_message = f"Running provider '{provider_name}' in step '{step_id}'"
        _update_operation_progress(
            operation_id,
            phase="bootstrap_workflows",
            current_workflow=current_workflow,
            current_step_id=step_id,
            current_provider=provider_name,
            progress_message=progress_message,
        )

    for workflow_name, workflow in config.workflows.items():
        if not workflow.canonical:
            continue
        current_workflow = workflow_name
        _update_operation_progress(
            operation_id,
            phase="bootstrap_workflows",
            current_workflow=workflow_name,
            current_step_id=None,
            current_provider=None,
            progress_message=f"Previewing canonical workflow '{workflow_name}'",
        )
        preview = service_run(
            instance,
            workflow_name,
            {},
            progress_callback=_progress_callback,
        )
        if preview.apply_digest is None:
            warning = f"Canonical workflow '{workflow_name}' did not produce an apply digest"
            warnings.append(warning)
            get_auth_store().update_deploy_operation(
                operation_id,
                warnings=warnings,
                bump_progress=True,
            )
            continue
        _update_operation_progress(
            operation_id,
            phase="bootstrap_workflows",
            current_workflow=workflow_name,
            current_step_id=None,
            current_provider=None,
            progress_message=f"Applying canonical workflow '{workflow_name}'",
        )
        service_apply_workflow(
            instance,
            workflow_name,
            {},
            expected_apply_digest=preview.apply_digest,
            expected_head_snapshot_id=preview.head_snapshot_id,
            progress_callback=_progress_callback,
        )
    return warnings
