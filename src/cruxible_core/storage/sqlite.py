"""SQLite backend for receipt persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from cruxible_core.receipt.types import Receipt

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id TEXT PRIMARY KEY,
    query_name TEXT NOT NULL,
    parameters TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    duration_ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receipts_query_name ON receipts(query_name);
CREATE INDEX IF NOT EXISTS idx_receipts_created_at ON receipts(created_at);

CREATE TABLE IF NOT EXISTS receipt_entities (
    receipt_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (receipt_id, entity_type, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_receipt_entities_lookup
ON receipt_entities(entity_type, entity_id);
"""


class SQLiteStore:
    """Stores and retrieves receipts from a SQLite database."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def save_receipt(self, receipt: Receipt) -> str:
        """Persist a receipt. Returns the receipt_id."""
        self._conn.execute(
            "INSERT OR REPLACE INTO receipts "
            "(receipt_id, query_name, parameters, receipt_json, created_at, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                receipt.receipt_id,
                receipt.query_name,
                json.dumps(receipt.parameters),
                receipt.model_dump_json(),
                receipt.created_at.isoformat(),
                receipt.duration_ms,
            ),
        )
        self._conn.execute(
            "DELETE FROM receipt_entities WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        indexed = set()
        for node in receipt.nodes:
            if not node.entity_type or not node.entity_id:
                continue
            key = (receipt.receipt_id, node.entity_type, node.entity_id)
            if key in indexed:
                continue
            indexed.add(key)
            self._conn.execute(
                "INSERT OR REPLACE INTO receipt_entities (receipt_id, entity_type, entity_id) "
                "VALUES (?, ?, ?)",
                key,
            )
        self._conn.commit()
        return receipt.receipt_id

    def get_receipt(self, receipt_id: str) -> Receipt | None:
        """Load a receipt by ID. Returns None if not found."""
        row = self._conn.execute(
            "SELECT receipt_json FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return Receipt.model_validate_json(row["receipt_json"])

    def list_receipts(
        self,
        query_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List receipt summaries, optionally filtered by query name."""
        if query_name is not None:
            rows = self._conn.execute(
                "SELECT receipt_id, query_name, parameters, created_at, duration_ms "
                "FROM receipts WHERE query_name = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (query_name, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT receipt_id, query_name, parameters, created_at, duration_ms "
                "FROM receipts ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        return [
            {
                "receipt_id": r["receipt_id"],
                "query_name": r["query_name"],
                "parameters": json.loads(r["parameters"]),
                "created_at": r["created_at"],
                "duration_ms": r["duration_ms"],
            }
            for r in rows
        ]

    def count_receipts(self, query_name: str | None = None) -> int:
        """Count receipt records with optional query_name filter."""
        if query_name is None:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM receipts").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM receipts WHERE query_name = ?",
                (query_name,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def get_receipts_for_entity(self, entity_type: str, entity_id: str) -> list[str]:
        """List receipt IDs where the entity appears in receipt nodes."""
        rows = self._conn.execute(
            "SELECT re.receipt_id FROM receipt_entities re "
            "JOIN receipts r ON r.receipt_id = re.receipt_id "
            "WHERE re.entity_type = ? AND re.entity_id = ? "
            "ORDER BY r.created_at DESC",
            (entity_type, entity_id),
        ).fetchall()
        return [str(r["receipt_id"]) for r in rows]

    def delete_receipt(self, receipt_id: str) -> bool:
        """Delete a receipt. Returns True if it existed."""
        cursor = self._conn.execute(
            "DELETE FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
