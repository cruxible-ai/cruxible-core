"""Server-owned credential, replay, and upload metadata persistence."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cruxible_core.server.config import get_server_state_dir


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

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

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
