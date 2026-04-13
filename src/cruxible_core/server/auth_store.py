"""Server-owned credential, deploy metadata, and replay persistence."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cruxible_core.server.config import get_server_state_dir

_UNSET = object()


@dataclass(frozen=True)
class RuntimeKeyRecord:
    key_id: str
    instance_scope: str
    role: str
    subject_label: str
    created_by: str
    created_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class DeployUploadRecord:
    upload_id: str
    staging_path: str
    bundle_digest: str
    manifest_summary_json: str
    created_at: str
    consumed_at: str | None


@dataclass(frozen=True)
class DeployOperationRecord:
    operation_id: str
    system_id: str
    upload_id: str
    instance_id: str | None
    status: str
    phase: str | None
    current_workflow: str | None
    current_step_id: str | None
    current_provider: str | None
    progress_message: str | None
    warnings: list[str]
    error_message: str | None
    failure_reason: str | None
    last_progress_at: str
    created_at: str
    updated_at: str
    completed_at: str | None
    admin_key_claimed_at: str | None


@dataclass(frozen=True)
class DeploySessionRecord:
    session_id: str
    operation_id: str
    system_id: str
    principal_id: str
    actions: list[str]
    created_at: str
    expires_at: str | None
    revoked_at: str | None


class RuntimeAuthStore:
    """SQLite-backed auth metadata store."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_keys (
                    key_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    instance_scope TEXT NOT NULL,
                    role TEXT NOT NULL,
                    subject_label TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_bootstrap_jtis (
                    jti TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deploy_uploads (
                    upload_id TEXT PRIMARY KEY,
                    staging_path TEXT NOT NULL,
                    bundle_digest TEXT NOT NULL,
                    manifest_summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deploy_operations (
                    operation_id TEXT PRIMARY KEY,
                    system_id TEXT NOT NULL,
                    upload_id TEXT NOT NULL,
                    instance_id TEXT,
                    status TEXT NOT NULL,
                    phase TEXT,
                    current_workflow TEXT,
                    current_step_id TEXT,
                    current_provider TEXT,
                    progress_message TEXT,
                    warnings_json TEXT NOT NULL,
                    error_message TEXT,
                    failure_reason TEXT,
                    last_progress_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    admin_key_claimed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_deploy_operations_system_status
                ON deploy_operations(system_id, status, created_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deploy_session_tokens (
                    session_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    operation_id TEXT NOT NULL,
                    system_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_deploy_session_operation
                ON deploy_session_tokens(operation_id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deploy_claim_slots (
                    operation_id TEXT PRIMARY KEY,
                    admin_bearer_token TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    claimed_at TEXT
                )
                """
            )
            self._ensure_column(conn, "deploy_session_tokens", "expires_at", "TEXT")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_json_list(raw: str) -> list[str]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, str)]

    def issue_runtime_key(
        self,
        *,
        instance_scope: str,
        role: str,
        subject_label: str,
        created_by: str,
    ) -> tuple[RuntimeKeyRecord, str]:
        key_id = f"key_{uuid.uuid4().hex[:12]}"
        secret = secrets.token_urlsafe(32)
        plaintext = f"crx_{key_id}_{secret}"
        created_at = self._now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_keys(
                    key_id,
                    token_hash,
                    instance_scope,
                    role,
                    subject_label,
                    created_by,
                    created_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    key_id,
                    self._hash_token(plaintext),
                    instance_scope,
                    role,
                    subject_label,
                    created_by,
                    created_at,
                ),
            )
        record = self.get_runtime_key(key_id)
        assert record is not None
        return record, plaintext

    def get_runtime_key(self, key_id: str) -> RuntimeKeyRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT key_id, instance_scope, role, subject_label,
                       created_by, created_at, revoked_at
                FROM runtime_keys
                WHERE key_id = ?
                """,
                (key_id,),
            ).fetchone()
        if row is None:
            return None
        return RuntimeKeyRecord(
            key_id=row["key_id"],
            instance_scope=row["instance_scope"],
            role=row["role"],
            subject_label=row["subject_label"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            revoked_at=row["revoked_at"],
        )

    def get_deploy_operation(self, operation_id: str) -> DeployOperationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT operation_id, system_id, upload_id, instance_id, status, phase,
                       current_workflow, current_step_id, current_provider, progress_message,
                       warnings_json, error_message, failure_reason, last_progress_at,
                       created_at, updated_at, completed_at, admin_key_claimed_at
                FROM deploy_operations
                WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_deploy_operation(row)

    def get_active_deploy_operation(self, *, system_id: str) -> DeployOperationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT operation_id, system_id, upload_id, instance_id, status, phase,
                       current_workflow, current_step_id, current_provider, progress_message,
                       warnings_json, error_message, failure_reason, last_progress_at,
                       created_at, updated_at, completed_at, admin_key_claimed_at
                FROM deploy_operations
                WHERE system_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (system_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_deploy_operation(row)

    def create_deploy_operation(
        self,
        *,
        system_id: str,
        upload_id: str,
        instance_id: str,
    ) -> DeployOperationRecord:
        operation_id = f"op_{uuid.uuid4().hex[:16]}"
        now = self._now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deploy_operations(
                    operation_id,
                    system_id,
                    upload_id,
                    instance_id,
                    status,
                    phase,
                    current_workflow,
                    current_step_id,
                    current_provider,
                    progress_message,
                    warnings_json,
                    error_message,
                    failure_reason,
                    last_progress_at,
                    created_at,
                    updated_at,
                    completed_at,
                    admin_key_claimed_at
                )
                VALUES (
                    ?, ?, ?, ?, ?,
                    NULL, NULL, NULL, NULL, NULL,
                    ?, NULL, NULL, ?, ?, ?,
                    NULL, NULL
                )
                """,
                (
                    operation_id,
                    system_id,
                    upload_id,
                    instance_id,
                    "queued",
                    json.dumps([]),
                    now,
                    now,
                    now,
                ),
            )
        record = self.get_deploy_operation(operation_id)
        assert record is not None
        return record

    def update_deploy_operation(
        self,
        operation_id: str,
        *,
        status: str | object = _UNSET,
        phase: str | None | object = _UNSET,
        current_workflow: str | None | object = _UNSET,
        current_step_id: str | None | object = _UNSET,
        current_provider: str | None | object = _UNSET,
        progress_message: str | None | object = _UNSET,
        warnings: list[str] | object = _UNSET,
        error_message: str | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
        completed_at: str | None | object = _UNSET,
        admin_key_claimed_at: str | None | object = _UNSET,
        bump_progress: bool = False,
    ) -> DeployOperationRecord:
        updates: dict[str, object] = {}
        for key, value in (
            ("status", status),
            ("phase", phase),
            ("current_workflow", current_workflow),
            ("current_step_id", current_step_id),
            ("current_provider", current_provider),
            ("progress_message", progress_message),
            ("warnings_json", json.dumps(warnings) if warnings is not _UNSET else _UNSET),
            ("error_message", error_message),
            ("failure_reason", failure_reason),
            ("completed_at", completed_at),
            ("admin_key_claimed_at", admin_key_claimed_at),
        ):
            if value is not _UNSET:
                updates[key] = value
        now = self._now().isoformat()
        updates["updated_at"] = now
        if bump_progress:
            updates["last_progress_at"] = now

        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values()) + [operation_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE deploy_operations SET {assignments} WHERE operation_id = ?",
                values,
            )
        record = self.get_deploy_operation(operation_id)
        assert record is not None
        return record

    def issue_deploy_session_token(
        self,
        *,
        operation_id: str,
        system_id: str,
        principal_id: str,
        actions: list[str],
        ttl: timedelta = timedelta(hours=24),
    ) -> str:
        session_id = f"dplsess_{uuid.uuid4().hex[:12]}"
        secret = secrets.token_urlsafe(32)
        plaintext = f"crxds_{session_id}_{secret}"
        now = self._now()
        created_at = now.isoformat()
        expires_at = (now + ttl).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deploy_session_tokens(
                    session_id,
                    token_hash,
                    operation_id,
                    system_id,
                    principal_id,
                    actions_json,
                    created_at,
                    expires_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    session_id,
                    self._hash_token(plaintext),
                    operation_id,
                    system_id,
                    principal_id,
                    json.dumps(actions),
                    created_at,
                    expires_at,
                ),
            )
        return plaintext

    def resolve_deploy_session_token(self, token: str) -> DeploySessionRecord | None:
        now_iso = self._now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, operation_id, system_id, principal_id, actions_json,
                       created_at, expires_at, revoked_at
                FROM deploy_session_tokens
                WHERE token_hash = ?
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (self._hash_token(token), now_iso),
            ).fetchone()
        if row is None:
            return None
        return DeploySessionRecord(
            session_id=row["session_id"],
            operation_id=row["operation_id"],
            system_id=row["system_id"],
            principal_id=row["principal_id"],
            actions=self._parse_json_list(row["actions_json"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    def revoke_deploy_sessions_for_operation(self, operation_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE deploy_session_tokens
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE operation_id = ?
                """,
                (self._now().isoformat(), operation_id),
            )

    def complete_deploy_operation_with_claim_slot(
        self,
        *,
        operation_id: str,
        instance_scope: str,
        subject_label: str,
        created_by: str,
        warnings: list[str],
        claim_ttl: timedelta = timedelta(minutes=60),
    ) -> tuple[str, str]:
        key_id = f"key_{uuid.uuid4().hex[:12]}"
        secret = secrets.token_urlsafe(32)
        plaintext = f"crx_{key_id}_{secret}"
        now = self._now()
        now_iso = now.isoformat()
        expires_at = (now + claim_ttl).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO runtime_keys(
                    key_id,
                    token_hash,
                    instance_scope,
                    role,
                    subject_label,
                    created_by,
                    created_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    key_id,
                    self._hash_token(plaintext),
                    instance_scope,
                    "admin",
                    subject_label,
                    created_by,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO deploy_claim_slots(
                    operation_id,
                    created_at,
                    expires_at,
                    claimed_at
                )
                VALUES (?, ?, ?, NULL)
                """,
                (operation_id, now_iso, expires_at),
            )
            conn.execute(
                """
                UPDATE deploy_operations
                SET status = ?,
                    phase = ?,
                    current_workflow = NULL,
                    current_step_id = NULL,
                    current_provider = NULL,
                    progress_message = ?,
                    warnings_json = ?,
                    error_message = NULL,
                    failure_reason = NULL,
                    last_progress_at = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE operation_id = ?
                """,
                (
                    "succeeded",
                    "admin_key_ready",
                    "Bootstrap complete; admin key ready to claim",
                    json.dumps(warnings),
                    now_iso,
                    now_iso,
                    now_iso,
                    operation_id,
                ),
            )
        return plaintext, expires_at

    def consume_deploy_claim_slot(self, operation_id: str) -> bool:
        now_iso = self._now().isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._purge_expired_claim_slots(conn, now_iso)
            slot_exists = conn.execute(
                """
                SELECT 1
                FROM deploy_claim_slots
                WHERE operation_id = ?
                  AND claimed_at IS NULL
                """,
                (operation_id,),
            ).fetchone()
            if slot_exists is None:
                return False
            conn.execute(
                """
                UPDATE deploy_claim_slots
                SET claimed_at = ?
                WHERE operation_id = ? AND claimed_at IS NULL
                """,
                (now_iso, operation_id),
            )
            conn.execute(
                """
                UPDATE deploy_operations
                SET admin_key_claimed_at = ?, updated_at = ?
                WHERE operation_id = ?
                """,
                (now_iso, now_iso, operation_id),
            )
            conn.execute(
                """
                UPDATE deploy_session_tokens
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE operation_id = ?
                """,
                (now_iso, operation_id),
            )
            return True

    def recover_deploy_admin_key(
        self,
        *,
        operation_id: str,
        instance_scope: str,
        subject_label: str,
        created_by: str,
    ) -> str | None:
        key_id = f"key_{uuid.uuid4().hex[:12]}"
        secret = secrets.token_urlsafe(32)
        plaintext = f"crx_{key_id}_{secret}"
        now_iso = self._now().isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._purge_expired_claim_slots(conn, now_iso)
            slot_exists = conn.execute(
                """
                SELECT 1
                FROM deploy_claim_slots
                WHERE operation_id = ?
                  AND claimed_at IS NULL
                """,
                (operation_id,),
            ).fetchone()
            if slot_exists is None:
                return None
            conn.execute(
                """
                INSERT INTO runtime_keys(
                    key_id,
                    token_hash,
                    instance_scope,
                    role,
                    subject_label,
                    created_by,
                    created_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    key_id,
                    self._hash_token(plaintext),
                    instance_scope,
                    "admin",
                    subject_label,
                    created_by,
                    now_iso,
                ),
            )
            conn.execute(
                """
                UPDATE deploy_claim_slots
                SET claimed_at = ?
                WHERE operation_id = ? AND claimed_at IS NULL
                """,
                (now_iso, operation_id),
            )
            conn.execute(
                """
                UPDATE deploy_operations
                SET admin_key_claimed_at = ?, updated_at = ?
                WHERE operation_id = ?
                """,
                (now_iso, now_iso, operation_id),
            )
            conn.execute(
                """
                UPDATE deploy_session_tokens
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE operation_id = ?
                """,
                (now_iso, operation_id),
            )
        return plaintext

    def purge_expired_claim_slots(self) -> None:
        with self._connect() as conn:
            self._purge_expired_claim_slots(conn, self._now().isoformat())

    def purge_expired_deploy_sessions(self) -> None:
        now_iso = self._now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM deploy_session_tokens
                WHERE expires_at IS NOT NULL AND expires_at <= ?
                """,
                (now_iso,),
            )

    def list_stale_deploy_operations(
        self,
        *,
        stale_before: datetime,
    ) -> list[DeployOperationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT operation_id, system_id, upload_id, instance_id, status, phase,
                       current_workflow, current_step_id, current_provider, progress_message,
                       warnings_json, error_message, failure_reason, last_progress_at,
                       created_at, updated_at, completed_at, admin_key_claimed_at
                FROM deploy_operations
                WHERE status IN ('queued', 'running') AND last_progress_at < ?
                ORDER BY created_at ASC
                """,
                (stale_before.isoformat(),),
            ).fetchall()
        return [self._row_to_deploy_operation(row) for row in rows]

    def list_active_deploy_operations(self) -> list[DeployOperationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT operation_id, system_id, upload_id, instance_id, status, phase,
                       current_workflow, current_step_id, current_provider, progress_message,
                       warnings_json, error_message, failure_reason, last_progress_at,
                       created_at, updated_at, completed_at, admin_key_claimed_at
                FROM deploy_operations
                WHERE status IN ('queued', 'running')
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [self._row_to_deploy_operation(row) for row in rows]

    def _row_to_deploy_operation(self, row: sqlite3.Row) -> DeployOperationRecord:
        return DeployOperationRecord(
            operation_id=row["operation_id"],
            system_id=row["system_id"],
            upload_id=row["upload_id"],
            instance_id=row["instance_id"],
            status=row["status"],
            phase=row["phase"],
            current_workflow=row["current_workflow"],
            current_step_id=row["current_step_id"],
            current_provider=row["current_provider"],
            progress_message=row["progress_message"],
            warnings=self._parse_json_list(row["warnings_json"]),
            error_message=row["error_message"],
            failure_reason=row["failure_reason"],
            last_progress_at=row["last_progress_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            admin_key_claimed_at=row["admin_key_claimed_at"],
        )

    def _purge_expired_claim_slots(self, conn: sqlite3.Connection, now_iso: str) -> None:
        conn.execute(
            """
            DELETE FROM deploy_claim_slots
            WHERE expires_at < ? OR claimed_at IS NOT NULL
            """,
            (now_iso,),
        )

    def resolve_runtime_key(self, token: str) -> RuntimeKeyRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT key_id, instance_scope, role, subject_label,
                       created_by, created_at, revoked_at
                FROM runtime_keys
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (self._hash_token(token),),
            ).fetchone()
        if row is None:
            return None
        return RuntimeKeyRecord(
            key_id=row["key_id"],
            instance_scope=row["instance_scope"],
            role=row["role"],
            subject_label=row["subject_label"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            revoked_at=row["revoked_at"],
        )

    def list_runtime_keys(self, *, instance_scope: str) -> list[RuntimeKeyRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key_id, instance_scope, role, subject_label,
                       created_by, created_at, revoked_at
                FROM runtime_keys
                WHERE instance_scope = ?
                ORDER BY created_at ASC
                """,
                (instance_scope,),
            ).fetchall()
        return [
            RuntimeKeyRecord(
                key_id=row["key_id"],
                instance_scope=row["instance_scope"],
                role=row["role"],
                subject_label=row["subject_label"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                revoked_at=row["revoked_at"],
            )
            for row in rows
        ]

    def revoke_runtime_key(self, key_id: str) -> RuntimeKeyRecord | None:
        revoked_at = self._now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE runtime_keys SET revoked_at = COALESCE(revoked_at, ?) WHERE key_id = ?",
                (revoked_at, key_id),
            )
        return self.get_runtime_key(key_id)

    def register_upload(
        self,
        *,
        upload_id: str,
        staging_path: Path,
        bundle_digest: str,
        manifest_summary_json: str,
    ) -> DeployUploadRecord:
        created_at = self._now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deploy_uploads(
                    upload_id,
                    staging_path,
                    bundle_digest,
                    manifest_summary_json,
                    created_at,
                    consumed_at
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (upload_id, str(staging_path), bundle_digest, manifest_summary_json, created_at),
            )
        record = self.get_upload(upload_id)
        assert record is not None
        return record

    def get_upload(self, upload_id: str) -> DeployUploadRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT upload_id, staging_path, bundle_digest,
                       manifest_summary_json, created_at, consumed_at
                FROM deploy_uploads
                WHERE upload_id = ?
                """,
                (upload_id,),
            ).fetchone()
        if row is None:
            return None
        return DeployUploadRecord(
            upload_id=row["upload_id"],
            staging_path=row["staging_path"],
            bundle_digest=row["bundle_digest"],
            manifest_summary_json=row["manifest_summary_json"],
            created_at=row["created_at"],
            consumed_at=row["consumed_at"],
        )

    def mark_upload_consumed(self, upload_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE deploy_uploads
                SET consumed_at = COALESCE(consumed_at, ?)
                WHERE upload_id = ?
                """,
                (self._now().isoformat(), upload_id),
            )

    def consume_bootstrap_jti(self, *, jti: str, expires_at: datetime) -> bool:
        now = self._now()
        self.prune_expired_jtis(now=now)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO consumed_bootstrap_jtis(jti, expires_at)
                    VALUES (?, ?)
                    """,
                    (jti, expires_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def prune_expired_jtis(
        self,
        *,
        now: datetime | None = None,
        skew_seconds: int = 60,
    ) -> None:
        cutoff = (now or self._now()) - timedelta(seconds=skew_seconds)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM consumed_bootstrap_jtis WHERE expires_at < ?",
                (cutoff.isoformat(),),
            )


_auth_store: RuntimeAuthStore | None = None


def get_auth_store() -> RuntimeAuthStore:
    global _auth_store
    if _auth_store is None:
        _auth_store = RuntimeAuthStore(get_server_state_dir() / "auth.db")
    return _auth_store


def reset_auth_store() -> None:
    global _auth_store
    _auth_store = None
