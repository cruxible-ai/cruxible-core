"""Receipt serialization: JSON, Markdown, and Mermaid output."""

from __future__ import annotations

from cruxible_core.receipt.types import Receipt, ReceiptNode


def to_json(receipt: Receipt) -> str:
    """Serialize a receipt to JSON."""
    return receipt.model_dump_json(indent=2)


def to_markdown(receipt: Receipt) -> str:
    """Render a receipt as a human-readable Markdown summary."""
    lines: list[str] = []
    lines.append(f"# Receipt {receipt.receipt_id}")
    lines.append("")
    lines.append(f"**Query:** {receipt.query_name}")
    lines.append(f"**Parameters:** {receipt.parameters}")
    lines.append(f"**Duration:** {receipt.duration_ms}ms")
    lines.append(f"**Results:** {len(receipt.results)}")
    lines.append("")

    lookups = [n for n in receipt.nodes if n.node_type == "entity_lookup"]
    traversals = [n for n in receipt.nodes if n.node_type == "edge_traversal"]
    filters = [n for n in receipt.nodes if n.node_type == "filter_applied"]
    constraints = [n for n in receipt.nodes if n.node_type == "constraint_check"]

    if lookups:
        lines.append("## Entry Points")
        for n in lookups:
            lines.append(f"- {n.entity_type}:{n.entity_id}")
        lines.append("")

    if traversals:
        lines.append("## Traversals")
        for n in traversals:
            from_type = n.detail.get("from_entity_type", "?")
            from_id = n.detail.get("from_entity_id", "?")
            lines.append(
                f"- {from_type}:{from_id} --[{n.relationship}]--> {n.entity_type}:{n.entity_id}"
            )
        lines.append("")

    if filters:
        lines.append("## Filters")
        for n in filters:
            status = "PASS" if n.detail.get("passed") else "FAIL"
            spec = n.detail.get("filter", {})
            lines.append(f"- [{status}] {spec}")
        lines.append("")

    if constraints:
        lines.append("## Constraints")
        for n in constraints:
            status = "PASS" if n.detail.get("passed") else "FAIL"
            expr = n.detail.get("constraint", "")
            lines.append(f"- [{status}] {expr} on {n.entity_type}:{n.entity_id}")
        lines.append("")

    return "\n".join(lines)


def to_mermaid(receipt: Receipt) -> str:
    """Render the receipt DAG as a Mermaid flowchart."""
    lines: list[str] = ["graph TD"]

    for node in receipt.nodes:
        label = _node_label(node)
        lines.append(f'    {node.node_id}["{label}"]')

    for edge in receipt.edges:
        lines.append(f"    {edge.from_node} -->|{edge.edge_type}| {edge.to_node}")

    return "\n".join(lines)


def _node_label(node: ReceiptNode) -> str:
    """Generate a concise label for a Mermaid node."""
    if node.node_type == "query":
        return f"Query: {node.detail.get('query_name', 'query')}"

    if node.node_type == "entity_lookup":
        return f"Lookup: {node.entity_type}:{node.entity_id}"

    if node.node_type == "edge_traversal":
        from_id = node.detail.get("from_entity_id", "?")
        return f"{from_id} --{node.relationship}--> {node.entity_id}"

    if node.node_type == "filter_applied":
        status = "PASS" if node.detail.get("passed") else "FAIL"
        return f"Filter: {status}"

    if node.node_type == "constraint_check":
        status = "PASS" if node.detail.get("passed") else "FAIL"
        return f"Constraint: {status}"

    if node.node_type == "result":
        return f"Results: {node.detail.get('count', 0)}"

    return node.node_type
