"""SQLite persistence for feedback and outcome records."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cruxible_core.feedback.types import EdgeTarget, FeedbackRecord, OutcomeRecord

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_json TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'human',
    model_id TEXT,
    corrections TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_receipt ON feedback(receipt_id);

CREATE TABLE IF NOT EXISTS feedback_entities (
    feedback_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (feedback_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_entities_entity_id ON feedback_entities(entity_id);

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcomes_receipt ON outcomes(receipt_id);
"""


class FeedbackStore:
    """Stores and retrieves feedback and outcome records."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    # -----------------------------------------------------------------
    # Feedback
    # -----------------------------------------------------------------

    def save_feedback(self, record: FeedbackRecord) -> str:
        """Persist a feedback record. Returns the feedback_id."""
        self._conn.execute(
            "INSERT OR REPLACE INTO feedback "
            "(feedback_id, receipt_id, action, target_json, reason, source, "
            "model_id, corrections, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.feedback_id,
                record.receipt_id,
                record.action,
                record.target.model_dump_json(),
                record.reason,
                record.source,
                record.model_id,
                json.dumps(record.corrections),
                record.created_at.isoformat(),
            ),
        )
        self._index_feedback_entities(record)
        self._conn.commit()
        return record.feedback_id

    def get_feedback(self, feedback_id: str) -> FeedbackRecord | None:
        """Load a feedback record by ID."""
        row = self._conn.execute(
            "SELECT * FROM feedback WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_feedback(row)

    def list_feedback(
        self,
        receipt_id: str | None = None,
        limit: int = 100,
    ) -> list[FeedbackRecord]:
        """List feedback records with optional filter."""
        if receipt_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM feedback WHERE receipt_id = ? ORDER BY created_at DESC LIMIT ?",
                (receipt_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [self._row_to_feedback(r) for r in rows]

    def list_feedback_by_entity_ids(
        self,
        entity_ids: list[str],
        limit: int = 100,
    ) -> list[FeedbackRecord]:
        """List feedback records that mention any provided entity IDs."""
        if not entity_ids:
            return []

        placeholders = ",".join("?" for _ in entity_ids)
        rows = self._conn.execute(
            "SELECT DISTINCT f.* FROM feedback f "
            "JOIN feedback_entities fe ON fe.feedback_id = f.feedback_id "
            f"WHERE fe.entity_id IN ({placeholders}) "
            "ORDER BY f.created_at DESC LIMIT ?",
            (*entity_ids, limit),
        ).fetchall()
        return [self._row_to_feedback(r) for r in rows]

    def count_feedback(self, receipt_id: str | None = None) -> int:
        """Count feedback records with optional receipt filter."""
        if receipt_id is None:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM feedback").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM feedback WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _row_to_feedback(row: sqlite3.Row) -> FeedbackRecord:
        return FeedbackRecord(
            feedback_id=row["feedback_id"],
            receipt_id=row["receipt_id"],
            action=row["action"],
            target=EdgeTarget.model_validate_json(row["target_json"]),
            reason=row["reason"],
            source=row["source"],
            model_id=row["model_id"],
            corrections=json.loads(row["corrections"]),
            created_at=row["created_at"],
        )

    # -----------------------------------------------------------------
    # Outcomes
    # -----------------------------------------------------------------

    def save_outcome(self, record: OutcomeRecord) -> str:
        """Persist an outcome record. Returns the outcome_id."""
        self._conn.execute(
            "INSERT OR REPLACE INTO outcomes "
            "(outcome_id, receipt_id, outcome, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.outcome_id,
                record.receipt_id,
                record.outcome,
                json.dumps(record.detail),
                record.created_at.isoformat(),
            ),
        )
        self._conn.commit()
        return record.outcome_id

    def get_outcome(self, outcome_id: str) -> OutcomeRecord | None:
        """Load an outcome record by ID."""
        row = self._conn.execute(
            "SELECT * FROM outcomes WHERE outcome_id = ?",
            (outcome_id,),
        ).fetchone()
        if row is None:
            return None
        return OutcomeRecord(
            outcome_id=row["outcome_id"],
            receipt_id=row["receipt_id"],
            outcome=row["outcome"],
            detail=json.loads(row["detail"]),
            created_at=row["created_at"],
        )

    def list_outcomes(
        self,
        receipt_id: str | None = None,
        limit: int = 100,
    ) -> list[OutcomeRecord]:
        """List outcome records with optional filter."""
        if receipt_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM outcomes WHERE receipt_id = ? ORDER BY created_at DESC LIMIT ?",
                (receipt_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM outcomes ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [
            OutcomeRecord(
                outcome_id=r["outcome_id"],
                receipt_id=r["receipt_id"],
                outcome=r["outcome"],
                detail=json.loads(r["detail"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def count_outcomes(self, receipt_id: str | None = None) -> int:
        """Count outcome records with optional receipt filter."""
        if receipt_id is None:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM outcomes").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM outcomes WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def _index_feedback_entities(self, record: FeedbackRecord) -> None:
        """Index entity identifiers touched by a feedback record."""
        self._conn.execute(
            "DELETE FROM feedback_entities WHERE feedback_id = ?",
            (record.feedback_id,),
        )
        t = record.target
        entity_ids = {
            f"{t.from_type}:{t.from_id}",
            f"{t.to_type}:{t.to_id}",
        }
        for entity_id in entity_ids:
            self._conn.execute(
                "INSERT OR REPLACE INTO feedback_entities (feedback_id, entity_id) VALUES (?, ?)",
                (record.feedback_id, entity_id),
            )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
