"""Persistent registry mapping opaque server IDs to backend locations."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from cruxible_core.server.config import get_server_state_dir

LOCAL_FILESYSTEM_BACKEND = "local_filesystem"
GOVERNED_DAEMON_BACKEND = "governed_daemon"


@dataclass(frozen=True)
class InstanceRecord:
    """Persistent mapping from opaque instance ID to backend metadata."""

    instance_id: str
    backend: str
    location: str
    workspace_root: str | None
    system_id: str | None
    instance_slug: str | None
    bootstrap_status: str | None
    created_at: str


@dataclass(frozen=True)
class RegisteredInstance:
    """Registry result for get-or-create flows."""

    record: InstanceRecord
    created: bool


@dataclass(frozen=True)
class DeployBootstrapClaim:
    """Result of atomically claiming a deployed-system bootstrap slot."""

    record: InstanceRecord
    status: Literal["acquired", "initialized", "bootstrapping"]
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
                    workspace_root TEXT,
                    system_id TEXT,
                    instance_slug TEXT,
                    bootstrap_status TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(backend, location)
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(instances)").fetchall()
            }
            if "workspace_root" not in columns:
                try:
                    conn.execute("ALTER TABLE instances ADD COLUMN workspace_root TEXT")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            if "system_id" not in columns:
                try:
                    conn.execute("ALTER TABLE instances ADD COLUMN system_id TEXT")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            if "instance_slug" not in columns:
                try:
                    conn.execute("ALTER TABLE instances ADD COLUMN instance_slug TEXT")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            if "bootstrap_status" not in columns:
                try:
                    conn.execute("ALTER TABLE instances ADD COLUMN bootstrap_status TEXT")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_instances_backend_workspace_root
                ON instances(backend, workspace_root)
                WHERE workspace_root IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_instances_system_id
                ON instances(system_id)
                WHERE system_id IS NOT NULL
                """
            )

    def get(self, instance_id: str) -> InstanceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT instance_id, backend, location, workspace_root, system_id,
                       instance_slug, bootstrap_status, created_at
                FROM instances
                WHERE instance_id = ?
                """,
                (instance_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_system_id(self, system_id: str) -> InstanceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT instance_id, backend, location, workspace_root, system_id,
                       instance_slug, bootstrap_status, created_at
                FROM instances
                WHERE system_id = ?
                """,
                (system_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_or_create_local_instance(self, location: str | Path) -> RegisteredInstance:
        resolved_location = str(Path(location).expanduser().resolve())
        existing = self._get_by_backend_location(LOCAL_FILESYSTEM_BACKEND, resolved_location)
        if existing is not None:
            return RegisteredInstance(record=existing, created=False)

        return self._insert_instance(
            backend=LOCAL_FILESYSTEM_BACKEND,
            location=resolved_location,
            workspace_root=None,
            system_id=None,
            instance_slug=None,
            bootstrap_status=None,
        )

    def get_or_create_governed_instance(
        self,
        workspace_root: str | Path,
    ) -> RegisteredInstance:
        resolved_workspace_root = str(Path(workspace_root).expanduser().resolve())
        existing = self._get_by_backend_workspace_root(
            GOVERNED_DAEMON_BACKEND,
            resolved_workspace_root,
        )
        if existing is not None:
            return RegisteredInstance(record=existing, created=False)
        return self._create_governed_instance(workspace_root=resolved_workspace_root)

    def create_governed_instance(
        self, workspace_root: str | Path | None = None,
    ) -> RegisteredInstance:
        resolved_workspace_root: str | None = None
        if workspace_root is not None:
            resolved_workspace_root = str(Path(workspace_root).expanduser().resolve())
        return self._create_governed_instance(workspace_root=resolved_workspace_root)

    def create_deployed_instance(
        self,
        *,
        system_id: str,
        instance_slug: str | None = None,
        bootstrap_status: str = "bootstrapping",
    ) -> RegisteredInstance:
        existing = self.get_by_system_id(system_id)
        if existing is not None:
            return RegisteredInstance(record=existing, created=False)
        return self._create_governed_instance(
            workspace_root=None,
            system_id=system_id,
            instance_slug=instance_slug,
            bootstrap_status=bootstrap_status,
        )

    def claim_deployed_bootstrap(
        self,
        *,
        system_id: str,
        instance_slug: str | None = None,
    ) -> DeployBootstrapClaim:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT instance_id, backend, location, workspace_root, system_id,
                       instance_slug, bootstrap_status, created_at
                FROM instances
                WHERE system_id = ?
                """,
                (system_id,),
            ).fetchone()
            if row is None:
                instance_id = f"inst_{uuid.uuid4().hex[:16]}"
                location = str((get_server_state_dir() / "instances" / instance_id).resolve())
                conn.execute(
                    """
                    INSERT INTO instances(
                        instance_id,
                        backend,
                        location,
                        workspace_root,
                        system_id,
                        instance_slug,
                        bootstrap_status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        instance_id,
                        GOVERNED_DAEMON_BACKEND,
                        location,
                        None,
                        system_id,
                        instance_slug,
                        "bootstrapping",
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                row = conn.execute(
                    """
                    SELECT instance_id, backend, location, workspace_root, system_id,
                           instance_slug, bootstrap_status, created_at
                    FROM instances
                    WHERE system_id = ?
                    """,
                    (system_id,),
                ).fetchone()
                assert row is not None
                return DeployBootstrapClaim(
                    record=self._row_to_record(row),
                    status="acquired",
                    created=True,
                )

            record = self._row_to_record(row)
            if record.bootstrap_status == "initialized":
                return DeployBootstrapClaim(record=record, status="initialized", created=False)
            if record.bootstrap_status == "bootstrapping":
                return DeployBootstrapClaim(record=record, status="bootstrapping", created=False)

            conn.execute(
                """
                UPDATE instances
                SET bootstrap_status = ?, instance_slug = COALESCE(?, instance_slug)
                WHERE instance_id = ?
                """,
                ("bootstrapping", instance_slug, record.instance_id),
            )
            row = conn.execute(
                """
                SELECT instance_id, backend, location, workspace_root, system_id,
                       instance_slug, bootstrap_status, created_at
                FROM instances
                WHERE instance_id = ?
                """,
                (record.instance_id,),
            ).fetchone()
            assert row is not None
            return DeployBootstrapClaim(
                record=self._row_to_record(row),
                status="acquired",
                created=False,
            )

    def update_bootstrap_status(self, instance_id: str, bootstrap_status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE instances SET bootstrap_status = ? WHERE instance_id = ?",
                (bootstrap_status, instance_id),
            )

    def _create_governed_instance(
        self,
        *,
        workspace_root: str | None,
        system_id: str | None = None,
        instance_slug: str | None = None,
        bootstrap_status: str | None = None,
    ) -> RegisteredInstance:
        instance_id = f"inst_{uuid.uuid4().hex[:16]}"
        location = str((get_server_state_dir() / "instances" / instance_id).resolve())
        return self._insert_instance(
            backend=GOVERNED_DAEMON_BACKEND,
            location=location,
            workspace_root=workspace_root,
            system_id=system_id,
            instance_slug=instance_slug,
            bootstrap_status=bootstrap_status,
            preferred_instance_id=instance_id,
        )

    def _insert_instance(
        self,
        *,
        backend: str,
        location: str,
        workspace_root: str | None,
        system_id: str | None,
        instance_slug: str | None,
        bootstrap_status: str | None,
        preferred_instance_id: str | None = None,
    ) -> RegisteredInstance:
        created_at = datetime.now(timezone.utc).isoformat()
        instance_id = preferred_instance_id or f"inst_{uuid.uuid4().hex[:16]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO instances(
                    instance_id,
                    backend,
                    location,
                    workspace_root,
                    system_id,
                    instance_slug,
                    bootstrap_status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instance_id,
                    backend,
                    location,
                    workspace_root,
                    system_id,
                    instance_slug,
                    bootstrap_status,
                    created_at,
                ),
            )

        if system_id is not None:
            record = self.get_by_system_id(system_id)
        elif workspace_root is not None:
            record = self._get_by_backend_workspace_root(backend, workspace_root)
        else:
            record = self._get_by_backend_location(backend, location)
        assert record is not None
        return RegisteredInstance(record=record, created=record.instance_id == instance_id)

    def _get_by_backend_location(self, backend: str, location: str) -> InstanceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT instance_id, backend, location, workspace_root, system_id,
                       instance_slug, bootstrap_status, created_at
                FROM instances
                WHERE backend = ? AND location = ?
                """,
                (backend, location),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def _get_by_backend_workspace_root(
        self, backend: str, workspace_root: str,
    ) -> InstanceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT instance_id, backend, location, workspace_root, system_id,
                       instance_slug, bootstrap_status, created_at
                FROM instances
                WHERE backend = ? AND workspace_root = ?
                """,
                (backend, workspace_root),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> InstanceRecord:
        return InstanceRecord(
            instance_id=row["instance_id"],
            backend=row["backend"],
            location=row["location"],
            workspace_root=row["workspace_root"],
            system_id=row["system_id"],
            instance_slug=row["instance_slug"],
            bootstrap_status=row["bootstrap_status"],
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
