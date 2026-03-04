"""Rich table formatters for CLI output."""

from __future__ import annotations

from typing import Any

from rich.table import Table

from cruxible_core.config.schema import CoreConfig
from cruxible_core.feedback.types import FeedbackRecord, OutcomeRecord
from cruxible_core.graph.types import EntityInstance, RelationshipInstance
from cruxible_core.query.candidates import CandidateMatch


def entities_table(entities: list[EntityInstance], entity_type: str) -> Table:
    """Build a Rich table for a list of entities."""
    table = Table(title=f"{entity_type} entities")
    table.add_column("ID", style="cyan")
    table.add_column("Properties")

    for e in entities:
        props = ", ".join(f"{k}={v}" for k, v in e.properties.items())
        table.add_row(e.entity_id, props)

    return table


def receipts_table(receipts: list[dict[str, Any]]) -> Table:
    """Build a Rich table for receipt summaries."""
    table = Table(title="Receipts")
    table.add_column("ID", style="cyan")
    table.add_column("Query")
    table.add_column("Created At")
    table.add_column("Duration (ms)", justify="right")

    for r in receipts:
        table.add_row(
            r["receipt_id"],
            r["query_name"],
            r["created_at"],
            f"{r['duration_ms']:.1f}",
        )

    return table


def candidates_table(candidates: list[CandidateMatch]) -> Table:
    """Build a Rich table for candidate matches."""
    table = Table(title="Candidate Matches")
    table.add_column("From", style="cyan")
    table.add_column("To", style="cyan")
    table.add_column("Confidence", justify="right")
    table.add_column("Evidence")

    for c in candidates:
        from_label = f"{c.from_entity.entity_type}:{c.from_entity.entity_id}"
        to_label = f"{c.to_entity.entity_type}:{c.to_entity.entity_id}"
        evidence_str = ", ".join(
            f"{k}={v}" for k, v in c.evidence.items() if isinstance(v, str | int | float)
        )
        table.add_row(from_label, to_label, f"{c.confidence:.2f}", evidence_str)

    return table


def feedback_table(records: list[FeedbackRecord]) -> Table:
    """Build a Rich table for feedback records."""
    table = Table(title="Feedback")
    table.add_column("ID", style="cyan")
    table.add_column("Receipt")
    table.add_column("Action")
    table.add_column("Target")
    table.add_column("Reason")

    for r in records:
        t = r.target
        target_str = f"{t.from_type}:{t.from_id}:{t.relationship}:{t.to_type}:{t.to_id}"
        if t.edge_key is not None:
            target_str = f"{target_str}:{t.edge_key}"
        table.add_row(
            r.feedback_id,
            r.receipt_id,
            r.action,
            target_str,
            r.reason,
        )

    return table


def outcomes_table(records: list[OutcomeRecord]) -> Table:
    """Build a Rich table for outcome records."""
    table = Table(title="Outcomes")
    table.add_column("ID", style="cyan")
    table.add_column("Receipt")
    table.add_column("Outcome")
    table.add_column("Created At")

    for r in records:
        table.add_row(
            r.outcome_id,
            r.receipt_id,
            r.outcome,
            str(r.created_at),
        )

    return table


def relationship_table(rel: RelationshipInstance) -> Table:
    """Build a Rich table for a single relationship."""
    table = Table(title=f"{rel.relationship_type} relationship")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("From", f"{rel.from_entity_type}:{rel.from_entity_id}")
    table.add_row("To", f"{rel.to_entity_type}:{rel.to_entity_id}")
    table.add_row("Type", rel.relationship_type)
    if rel.edge_key is not None:
        table.add_row("Edge Key", str(rel.edge_key))
    for k, v in rel.properties.items():
        table.add_row(f"  {k}", str(v))

    return table


def edges_table(edges: list[dict[str, Any]]) -> Table:
    """Build a Rich table for a list of edges."""
    table = Table(title="Edges")
    table.add_column("From", style="cyan")
    table.add_column("To", style="cyan")
    table.add_column("Relationship")
    table.add_column("Edge Key", justify="right")
    table.add_column("Properties")

    for e in edges:
        from_label = f"{e['from_type']}:{e['from_id']}"
        to_label = f"{e['to_type']}:{e['to_id']}"
        props = e.get("properties", {})
        props_str = ", ".join(
            f"{k}={v}" for k, v in props.items() if k != "_provenance"
        )
        table.add_row(
            from_label,
            to_label,
            e.get("relationship_type", ""),
            str(e.get("edge_key", "")),
            props_str,
        )

    return table


def schema_table(config: CoreConfig) -> Table:
    """Build a Rich table showing the config schema."""
    table = Table(title=f"Schema: {config.name}")
    table.add_column("Section", style="cyan")
    table.add_column("Name")
    table.add_column("Details")

    for name, et in config.entity_types.items():
        pk = et.get_primary_key() or "-"
        props = ", ".join(et.properties.keys())
        table.add_row("Entity", name, f"pk={pk}  props=[{props}]")

    for rel in config.relationships:
        table.add_row(
            "Relationship",
            rel.name,
            f"{rel.from_entity} -> {rel.to_entity}  ({rel.cardinality})",
        )

    for name, q in config.named_queries.items():
        steps = len(q.traversal)
        table.add_row("Query", name, f"entry={q.entry_point}  steps={steps}")

    for name, m in config.ingestion.items():
        if m.is_entity:
            table.add_row("Ingestion", name, f"entity={m.entity_type}")
        else:
            table.add_row("Ingestion", name, f"relationship={m.relationship_type}")

    return table
