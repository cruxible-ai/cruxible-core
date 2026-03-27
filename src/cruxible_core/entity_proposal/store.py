"""SQLite persistence for governed entity change proposals."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cruxible_core.entity_proposal.types import EntityChangeMember, EntityChangeProposal

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS entity_proposal_resolutions (
    resolution_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    action TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    resolved_by TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entity_proposal_resolutions_proposal
    ON entity_proposal_resolutions(proposal_id);

CREATE TABLE IF NOT EXISTS entity_proposals (
    proposal_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending_review',
    thesis_text TEXT NOT NULL DEFAULT '',
    thesis_facts TEXT NOT NULL DEFAULT '{}',
    analysis_state TEXT NOT NULL DEFAULT '{}',
    proposed_by TEXT NOT NULL,
    suggested_priority TEXT,
    source_workflow_name TEXT,
    source_workflow_receipt_id TEXT,
    source_trace_ids TEXT NOT NULL DEFAULT '[]',
    source_step_ids TEXT NOT NULL DEFAULT '[]',
    member_count INTEGER NOT NULL DEFAULT 0,
    resolution_id TEXT REFERENCES entity_proposal_resolutions(resolution_id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entity_proposals_status
    ON entity_proposals(status);

CREATE TABLE IF NOT EXISTS entity_proposal_members (
    proposal_id TEXT NOT NULL REFERENCES entity_proposals(proposal_id),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (proposal_id, entity_type, entity_id)
);
"""


class EntityProposalStore:
    """Stores and retrieves governed entity change proposals."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

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

    def save_proposal(self, proposal: EntityChangeProposal) -> str:
        """Persist a proposal. Does not commit."""
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_proposals "
            "(proposal_id, status, thesis_text, thesis_facts, analysis_state, proposed_by, "
            "suggested_priority, source_workflow_name, source_workflow_receipt_id, "
            "source_trace_ids, source_step_ids, member_count, resolution_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal.proposal_id,
                proposal.status,
                proposal.thesis_text,
                json.dumps(proposal.thesis_facts),
                json.dumps(proposal.analysis_state),
                proposal.proposed_by,
                proposal.suggested_priority,
                proposal.source_workflow_name,
                proposal.source_workflow_receipt_id,
                json.dumps(proposal.source_trace_ids),
                json.dumps(proposal.source_step_ids),
                proposal.member_count,
                proposal.resolution_id,
                proposal.created_at.isoformat(),
            ),
        )
        return proposal.proposal_id

    def get_proposal(self, proposal_id: str) -> EntityChangeProposal | None:
        """Load a proposal by ID."""
        row = self._conn.execute(
            "SELECT * FROM entity_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def list_proposals(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[EntityChangeProposal]:
        """List proposals with optional status filter."""
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM entity_proposals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM entity_proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self._row_to_proposal(row) for row in rows]

    def count_proposals(self, *, status: str | None = None) -> int:
        """Count proposals with optional status filter."""
        if status is None:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM entity_proposals").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM entity_proposals WHERE status = ?",
                (status,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        resolution_id: str | None = None,
    ) -> bool:
        """Update proposal status, optionally setting resolution ID. Does not commit."""
        if resolution_id is None:
            cursor = self._conn.execute(
                "UPDATE entity_proposals SET status = ? WHERE proposal_id = ?",
                (status, proposal_id),
            )
        else:
            cursor = self._conn.execute(
                "UPDATE entity_proposals SET status = ?, resolution_id = ? WHERE proposal_id = ?",
                (status, resolution_id, proposal_id),
            )
        return cursor.rowcount > 0

    def save_members(self, proposal_id: str, members: list[EntityChangeMember]) -> None:
        """Persist proposal members. Does not commit."""
        for member in members:
            self._conn.execute(
                "INSERT INTO entity_proposal_members "
                "(proposal_id, entity_type, entity_id, operation, properties) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    proposal_id,
                    member.entity_type,
                    member.entity_id,
                    member.operation,
                    json.dumps(member.properties),
                ),
            )

    def get_members(self, proposal_id: str) -> list[EntityChangeMember]:
        """Load proposal members."""
        rows = self._conn.execute(
            "SELECT * FROM entity_proposal_members WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchall()
        return [
            EntityChangeMember(
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                operation=row["operation"],
                properties=json.loads(row["properties"]),
            )
            for row in rows
        ]

    def save_resolution(
        self,
        proposal_id: str,
        action: str,
        rationale: str,
        resolved_by: str,
    ) -> str:
        """Persist a resolution. Does not commit."""
        resolution_id = f"ERES-{uuid.uuid4().hex[:12]}"
        self._conn.execute(
            "INSERT INTO entity_proposal_resolutions "
            "(resolution_id, proposal_id, action, rationale, resolved_by, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                resolution_id,
                proposal_id,
                action,
                rationale,
                resolved_by,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return resolution_id

    def get_resolution(self, resolution_id: str) -> dict[str, Any] | None:
        """Load a resolution by ID."""
        row = self._conn.execute(
            "SELECT * FROM entity_proposal_resolutions WHERE resolution_id = ?",
            (resolution_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "resolution_id": row["resolution_id"],
            "proposal_id": row["proposal_id"],
            "action": row["action"],
            "rationale": row["rationale"],
            "resolved_by": row["resolved_by"],
            "resolved_at": row["resolved_at"],
        }

    @staticmethod
    def _row_to_proposal(row: sqlite3.Row) -> EntityChangeProposal:
        return EntityChangeProposal(
            proposal_id=row["proposal_id"],
            status=row["status"],
            thesis_text=row["thesis_text"],
            thesis_facts=json.loads(row["thesis_facts"]),
            analysis_state=json.loads(row["analysis_state"]),
            proposed_by=row["proposed_by"],
            suggested_priority=row["suggested_priority"],
            source_workflow_name=row["source_workflow_name"],
            source_workflow_receipt_id=row["source_workflow_receipt_id"],
            source_trace_ids=json.loads(row["source_trace_ids"]),
            source_step_ids=json.loads(row["source_step_ids"]),
            member_count=row["member_count"],
            resolution_id=row["resolution_id"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
