"""SQLite persistence for candidate groups, members, and resolutions.

Shares feedback.db with FeedbackStore. Tables are created on init.
Write methods do NOT auto-commit — use transaction() for compound writes.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cruxible_core.group.types import (
    CandidateGroup,
    CandidateMember,
    CandidateSignal,
)

# group_resolutions FIRST (referenced by candidate_groups.resolution_id)
_SCHEMA = """\
CREATE TABLE IF NOT EXISTS group_resolutions (
    resolution_id TEXT PRIMARY KEY,
    relationship_type TEXT NOT NULL,
    group_signature TEXT NOT NULL,
    action TEXT NOT NULL,
    rationale TEXT DEFAULT '',
    thesis_text TEXT NOT NULL DEFAULT '',
    thesis_facts TEXT NOT NULL DEFAULT '{}',
    analysis_state TEXT NOT NULL DEFAULT '{}',
    trust_status TEXT NOT NULL DEFAULT 'watch',
    trust_reason TEXT NOT NULL DEFAULT '',
    confirmed INTEGER NOT NULL DEFAULT 0,
    resolved_by TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_group_resolutions_match
    ON group_resolutions(relationship_type, group_signature);

CREATE TABLE IF NOT EXISTS candidate_groups (
    group_id TEXT PRIMARY KEY,
    relationship_type TEXT NOT NULL,
    signature TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    thesis_text TEXT NOT NULL DEFAULT '',
    thesis_facts TEXT NOT NULL DEFAULT '{}',
    analysis_state TEXT NOT NULL DEFAULT '{}',
    integrations_used TEXT NOT NULL DEFAULT '[]',
    proposed_by TEXT NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    review_priority TEXT NOT NULL DEFAULT 'normal',
    suggested_priority TEXT,
    resolution_id TEXT REFERENCES group_resolutions(resolution_id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_groups_signature ON candidate_groups(signature);
CREATE INDEX IF NOT EXISTS idx_candidate_groups_status ON candidate_groups(status);
CREATE INDEX IF NOT EXISTS idx_candidate_groups_rel_type ON candidate_groups(relationship_type);

CREATE TABLE IF NOT EXISTS candidate_members (
    group_id TEXT NOT NULL REFERENCES candidate_groups(group_id),
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    signals TEXT NOT NULL DEFAULT '[]',
    properties TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (group_id, from_type, from_id, to_type, to_id, relationship_type)
);
"""


class GroupStore:
    """Stores and retrieves candidate groups, members, and resolutions."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        # PRAGMA must be set before executescript (separate statement)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

    # -----------------------------------------------------------------
    # Transaction support
    # -----------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Context manager for atomic compound writes."""
        self._conn.execute("BEGIN")
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def commit(self) -> None:
        """Explicit commit for callers managing their own transactions."""
        self._conn.commit()

    # -----------------------------------------------------------------
    # Groups
    # -----------------------------------------------------------------

    def save_group(self, group: CandidateGroup) -> str:
        """Persist a CandidateGroup. Does NOT commit."""
        self._conn.execute(
            "INSERT OR REPLACE INTO candidate_groups "
            "(group_id, relationship_type, signature, status, thesis_text, "
            "thesis_facts, analysis_state, integrations_used, proposed_by, "
            "member_count, review_priority, suggested_priority, resolution_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                group.group_id,
                group.relationship_type,
                group.signature,
                group.status,
                group.thesis_text,
                json.dumps(group.thesis_facts),
                json.dumps(group.analysis_state),
                json.dumps(group.integrations_used),
                group.proposed_by,
                group.member_count,
                group.review_priority,
                group.suggested_priority,
                group.resolution_id,
                group.created_at.isoformat(),
            ),
        )
        return group.group_id

    def get_group(self, group_id: str) -> CandidateGroup | None:
        """Load a CandidateGroup by ID."""
        row = self._conn.execute(
            "SELECT * FROM candidate_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_group(row)

    def list_groups(
        self,
        *,
        relationship_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[CandidateGroup]:
        """List groups with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if relationship_type is not None:
            clauses.append("relationship_type = ?")
            params.append(relationship_type)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM candidate_groups{where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_group(r) for r in rows]

    def count_groups(
        self,
        *,
        relationship_type: str | None = None,
        status: str | None = None,
    ) -> int:
        """Count groups with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if relationship_type is not None:
            clauses.append("relationship_type = ?")
            params.append(relationship_type)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._conn.execute(
            f"SELECT COUNT(*) AS count FROM candidate_groups{where}",
            tuple(params),
        ).fetchone()
        return int(row["count"]) if row else 0

    def update_group_status(
        self,
        group_id: str,
        status: str,
        resolution_id: str | None = None,
    ) -> bool:
        """Update group status, optionally setting resolution_id. Does NOT commit."""
        if resolution_id is not None:
            self._conn.execute(
                "UPDATE candidate_groups SET status = ?, resolution_id = ? WHERE group_id = ?",
                (status, resolution_id, group_id),
            )
        else:
            self._conn.execute(
                "UPDATE candidate_groups SET status = ? WHERE group_id = ?",
                (status, group_id),
            )
        return self._conn.total_changes > 0

    @staticmethod
    def _row_to_group(row: sqlite3.Row) -> CandidateGroup:
        return CandidateGroup(
            group_id=row["group_id"],
            relationship_type=row["relationship_type"],
            signature=row["signature"],
            status=row["status"],
            thesis_text=row["thesis_text"],
            thesis_facts=json.loads(row["thesis_facts"]),
            analysis_state=json.loads(row["analysis_state"]),
            integrations_used=json.loads(row["integrations_used"]),
            proposed_by=row["proposed_by"],
            member_count=row["member_count"],
            review_priority=row["review_priority"],
            suggested_priority=row["suggested_priority"],
            resolution_id=row["resolution_id"],
            created_at=row["created_at"],
        )

    # -----------------------------------------------------------------
    # Members
    # -----------------------------------------------------------------

    def save_members(self, group_id: str, members: list[CandidateMember]) -> None:
        """Batch insert candidate members. Does NOT commit."""
        for m in members:
            signals_json = json.dumps([s.model_dump(mode="json") for s in m.signals])
            self._conn.execute(
                "INSERT INTO candidate_members "
                "(group_id, from_type, from_id, to_type, to_id, relationship_type, "
                "signals, properties) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    group_id,
                    m.from_type,
                    m.from_id,
                    m.to_type,
                    m.to_id,
                    m.relationship_type,
                    signals_json,
                    json.dumps(m.properties),
                ),
            )

    def get_members(self, group_id: str) -> list[CandidateMember]:
        """Load members for a group."""
        rows = self._conn.execute(
            "SELECT * FROM candidate_members WHERE group_id = ?",
            (group_id,),
        ).fetchall()
        return [self._row_to_member(r) for r in rows]

    @staticmethod
    def _row_to_member(row: sqlite3.Row) -> CandidateMember:
        signals_data = json.loads(row["signals"])
        return CandidateMember(
            from_type=row["from_type"],
            from_id=row["from_id"],
            to_type=row["to_type"],
            to_id=row["to_id"],
            relationship_type=row["relationship_type"],
            signals=[CandidateSignal(**s) for s in signals_data],
            properties=json.loads(row["properties"]),
        )

    # -----------------------------------------------------------------
    # Resolutions
    # -----------------------------------------------------------------

    def save_resolution(
        self,
        relationship_type: str,
        signature: str,
        action: str,
        rationale: str,
        thesis_text: str,
        thesis_facts: dict[str, Any],
        analysis_state: dict[str, Any],
        resolved_by: str,
        trust_status: str = "watch",
        confirmed: bool = False,
    ) -> str:
        """Persist a resolution. Does NOT commit. Returns resolution_id."""
        resolution_id = f"RES-{uuid.uuid4().hex[:12]}"
        self._conn.execute(
            "INSERT INTO group_resolutions "
            "(resolution_id, relationship_type, group_signature, action, rationale, "
            "thesis_text, thesis_facts, analysis_state, trust_status, confirmed, "
            "resolved_by, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                resolution_id,
                relationship_type,
                signature,
                action,
                rationale,
                thesis_text,
                json.dumps(thesis_facts),
                json.dumps(analysis_state),
                trust_status,
                1 if confirmed else 0,
                resolved_by,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return resolution_id

    def confirm_resolution(
        self,
        resolution_id: str,
        trust_status: str | None = None,
    ) -> None:
        """Set confirmed=1 on a resolution. Optionally overwrite trust_status. Does NOT commit."""
        if trust_status is not None:
            self._conn.execute(
                "UPDATE group_resolutions SET confirmed = 1, trust_status = ? "
                "WHERE resolution_id = ?",
                (trust_status, resolution_id),
            )
        else:
            self._conn.execute(
                "UPDATE group_resolutions SET confirmed = 1 WHERE resolution_id = ?",
                (resolution_id,),
            )

    def get_resolution(self, resolution_id: str) -> dict[str, Any] | None:
        """Load a resolution by ID."""
        row = self._conn.execute(
            "SELECT * FROM group_resolutions WHERE resolution_id = ?",
            (resolution_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_resolution(row)

    def find_resolution(
        self,
        relationship_type: str,
        signature: str,
        action: str | None = None,
        confirmed: bool | None = None,
    ) -> dict[str, Any] | None:
        """Find the most recent resolution for a signature, with optional filters."""
        clauses = ["relationship_type = ?", "group_signature = ?"]
        params: list[Any] = [relationship_type, signature]
        if action is not None:
            clauses.append("action = ?")
            params.append(action)
        if confirmed is not None:
            clauses.append("confirmed = ?")
            params.append(1 if confirmed else 0)

        where = " AND ".join(clauses)
        row = self._conn.execute(
            f"SELECT * FROM group_resolutions WHERE {where} ORDER BY resolved_at DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_resolution(row)

    def list_resolutions(
        self,
        *,
        relationship_type: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List resolutions with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if relationship_type is not None:
            clauses.append("relationship_type = ?")
            params.append(relationship_type)
        if action is not None:
            clauses.append("action = ?")
            params.append(action)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM group_resolutions{where} ORDER BY resolved_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_resolution(r) for r in rows]

    def update_resolution_trust_status(
        self,
        resolution_id: str,
        trust_status: str,
        trust_reason: str = "",
    ) -> bool:
        """Update trust_status + trust_reason on a resolution. Does NOT commit."""
        cursor = self._conn.execute(
            "UPDATE group_resolutions SET trust_status = ?, trust_reason = ? "
            "WHERE resolution_id = ?",
            (trust_status, trust_reason, resolution_id),
        )
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_resolution(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "resolution_id": row["resolution_id"],
            "relationship_type": row["relationship_type"],
            "group_signature": row["group_signature"],
            "action": row["action"],
            "rationale": row["rationale"],
            "thesis_text": row["thesis_text"],
            "thesis_facts": json.loads(row["thesis_facts"]),
            "analysis_state": json.loads(row["analysis_state"]),
            "trust_status": row["trust_status"],
            "trust_reason": row["trust_reason"],
            "confirmed": bool(row["confirmed"]),
            "resolved_by": row["resolved_by"],
            "resolved_at": row["resolved_at"],
        }

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
