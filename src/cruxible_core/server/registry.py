"""Persistent registry mapping opaque server IDs to backend locations."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cruxible_core.server.config import get_server_state_dir

LOCAL_FILESYSTEM_BACKEND = "local_filesystem"


@dataclass(frozen=True)
class InstanceRecord:
    """Persistent mapping from opaque instance ID to backend metadata."""

    instance_id: str
    backend: str
    location: str
    created_at: str


@dataclass(frozen=True)
class RegisteredInstance:
    """Registry result for get-or-create flows."""

    record: InstanceRecord
    created: bool


class InstanceRegistry:
    """SQLite-backed registry of server-owned instance IDs."""

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
                CREATE TABLE IF NOT EXISTS instances (
                    instance_id TEXT PRIMARY KEY,
                    backend TEXT NOT NULL,
                    location TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(backend, location)
                )
                """
            )

    def get(self, instance_id: str) -> InstanceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT instance_id, backend, location, created_at
                FROM instances
                WHERE instance_id = ?
                """,
                (instance_id,),
            ).fetchone()
        if row is None:
            return None
        return InstanceRecord(
            instance_id=row["instance_id"],
            backend=row["backend"],
            location=row["location"],
            created_at=row["created_at"],
        )

    def get_or_create_local_instance(self, location: str | Path) -> RegisteredInstance:
        resolved_location = str(Path(location).expanduser().resolve())
        existing = self._get_by_backend_location(LOCAL_FILESYSTEM_BACKEND, resolved_location)
        if existing is not None:
            return RegisteredInstance(record=existing, created=False)

        created_at = datetime.now(timezone.utc).isoformat()
        instance_id = f"inst_{uuid.uuid4().hex[:16]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO instances(instance_id, backend, location, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (instance_id, LOCAL_FILESYSTEM_BACKEND, resolved_location, created_at),
            )

        # Another process may have inserted first; re-read canonical row.
        record = self._get_by_backend_location(LOCAL_FILESYSTEM_BACKEND, resolved_location)
        assert record is not None
        return RegisteredInstance(record=record, created=record.instance_id == instance_id)

    def _get_by_backend_location(self, backend: str, location: str) -> InstanceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT instance_id, backend, location, created_at
                FROM instances
                WHERE backend = ? AND location = ?
                """,
                (backend, location),
            ).fetchone()
        if row is None:
            return None
        return InstanceRecord(
            instance_id=row["instance_id"],
            backend=row["backend"],
            location=row["location"],
            created_at=row["created_at"],
        )


_registry: InstanceRegistry | None = None


def get_registry() -> InstanceRegistry:
    """Return the process-global registry instance."""
    global _registry
    if _registry is None:
        state_dir = get_server_state_dir()
        _registry = InstanceRegistry(state_dir / "registry.db")
    return _registry


def reset_registry() -> None:
    """Clear the process-global registry cache. Used by tests."""
    global _registry
    _registry = None
