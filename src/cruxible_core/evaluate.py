"""Graph quality assessment.

Deterministic checks for orphans, coverage gaps, constraint violations,
candidate opportunities, and low-confidence edges.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.schema import CoreConfig
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import make_node_id, split_node_id

FindingCategory = Literal[
    "orphan_entity",
    "coverage_gap",
    "constraint_violation",
    "candidate_opportunity",
    "low_confidence_edge",
    "unreviewed_co_member",
]


class EvaluationFinding(BaseModel):
    """A single finding from graph evaluation."""

    category: FindingCategory
    severity: Literal["info", "warning", "error"]
    message: str
    detail: dict[str, Any] = {}


class EvaluationReport(BaseModel):
    """Results of a graph evaluation."""

    entity_count: int
    edge_count: int
    findings: list[EvaluationFinding]
    summary: dict[str, int]  # category -> count


def evaluate_graph(
    config: CoreConfig,
    graph: EntityGraph,
    *,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> EvaluationReport:
    """Evaluate graph quality with deterministic checks.

    Runs six checks:
    1. Orphan entities — nodes with no edges
    2. Coverage gaps — entity/relationship types in config but absent from graph
    3. Constraint violations — rule-based checks on edge properties
    4. Candidate opportunities — entity pairs sharing neighbors but lacking a direct edge
    5. Low-confidence edges — edges below the confidence threshold or pending review
    6. Unreviewed co-members — entities sharing an intermediary with a cross-referenced
       entity but lacking a cross-reference edge themselves
    """
    findings: list[EvaluationFinding] = []

    _check_orphans(graph, findings, exclude_types=exclude_orphan_types)
    _check_coverage_gaps(config, graph, findings)
    _check_constraint_violations(config, graph, findings)
    _check_candidate_opportunities(config, graph, findings)
    _check_low_confidence_edges(graph, findings, confidence_threshold)
    _check_unreviewed_co_members(config, graph, findings)

    # Truncate to max_findings
    truncated = findings[:max_findings]

    # Build summary from all findings (before truncation) for accurate counts
    summary: dict[str, int] = {}
    for f in findings:
        summary[f.category] = summary.get(f.category, 0) + 1

    return EvaluationReport(
        entity_count=graph.entity_count(),
        edge_count=graph.edge_count(),
        findings=truncated,
        summary=summary,
    )


def _check_orphans(
    graph: EntityGraph,
    findings: list[EvaluationFinding],
    exclude_types: list[str] | None = None,
) -> None:
    """Find entities with no edges."""
    _exclude = set(exclude_types) if exclude_types else set()
    for entity in graph.iter_all_entities():
        if entity.entity_type in _exclude:
            continue
        if graph.is_isolated(entity.entity_type, entity.entity_id):
            findings.append(
                EvaluationFinding(
                    category="orphan_entity",
                    severity="warning",
                    message=f"Orphan entity: {entity.entity_type}:{entity.entity_id}",
                    detail={
                        "entity_type": entity.entity_type,
                        "entity_id": entity.entity_id,
                    },
                )
            )


def _check_coverage_gaps(
    config: CoreConfig, graph: EntityGraph, findings: list[EvaluationFinding]
) -> None:
    """Find entity/relationship types in config but not in graph."""
    graph_entity_types = set(graph.list_entity_types())
    for entity_type in config.entity_types:
        if entity_type not in graph_entity_types:
            findings.append(
                EvaluationFinding(
                    category="coverage_gap",
                    severity="info",
                    message=f"Entity type '{entity_type}' defined in config but absent from graph",
                    detail={"type": "entity_type", "name": entity_type},
                )
            )

    graph_rel_types = set(graph.list_relationship_types())
    for rel in config.relationships:
        if rel.name not in graph_rel_types:
            findings.append(
                EvaluationFinding(
                    category="coverage_gap",
                    severity="info",
                    message=f"Relationship '{rel.name}' defined in config but absent from graph",
                    detail={"type": "relationship_type", "name": rel.name},
                )
            )


def _check_constraint_violations(
    config: CoreConfig, graph: EntityGraph, findings: list[EvaluationFinding]
) -> None:
    """Check constraint rules against graph edges."""
    for constraint in config.constraints:
        parsed = parse_constraint_rule(constraint.rule)
        if not parsed:
            # Skip unparseable rules (matches validator.py pattern)
            continue

        rel_name, from_prop, to_prop = parsed

        for from_type, from_id, to_type, to_id, _props in graph.iter_edge_data(rel_name):
            from_entity = graph.get_entity(from_type, from_id)
            to_entity = graph.get_entity(to_type, to_id)

            from_props = from_entity.properties if from_entity else {}
            to_props = to_entity.properties if to_entity else {}

            from_val = from_props.get(from_prop)
            to_val = to_props.get(to_prop)

            if from_val is not None and to_val is not None and from_val != to_val:
                findings.append(
                    EvaluationFinding(
                        category="constraint_violation",
                        severity=constraint.severity,
                        message=(
                            f"Constraint '{constraint.name}' violated: "
                            f"{from_type}:{from_id}.{from_prop} ({from_val!r}) "
                            f"!= {to_type}:{to_id}.{to_prop} ({to_val!r})"
                        ),
                        detail={
                            "constraint": constraint.name,
                            "rule": constraint.rule,
                            "from_entity": f"{from_type}:{from_id}",
                            "to_entity": f"{to_type}:{to_id}",
                            "from_value": from_val,
                            "to_value": to_val,
                        },
                    )
                )


_MAX_ENTITIES_FOR_CANDIDATES = 500


def _check_candidate_opportunities(
    config: CoreConfig, graph: EntityGraph, findings: list[EvaluationFinding]
) -> None:
    """Find entity pairs sharing neighbors but lacking a target edge.

    Only checks self-referential relationships (from == to entity type).
    Skips if > 500 entities of the relevant type (performance guard).
    """
    for rel in config.relationships:
        if rel.from_entity != rel.to_entity:
            continue

        entity_type = rel.from_entity
        entities = graph.list_entities(entity_type)
        if len(entities) > _MAX_ENTITIES_FOR_CANDIDATES:
            continue

        # Build neighbor sets: for each entity, collect its neighbors via any relationship
        neighbor_sets: dict[str, set[str]] = {}
        for entity in entities:
            node_id = make_node_id(entity.entity_type, entity.entity_id)
            neighbor_sets[node_id] = graph.neighbor_ids(entity.entity_type, entity.entity_id)

        # Check pairs for shared neighbors without a direct edge
        entity_list = list(neighbor_sets.keys())
        for i, node_a in enumerate(entity_list):
            for node_b in entity_list[i + 1 :]:
                if not neighbor_sets[node_a] or not neighbor_sets[node_b]:
                    continue

                shared = neighbor_sets[node_a] & neighbor_sets[node_b]
                if not shared:
                    continue

                # Check if direct edge already exists (both directions)
                type_a, id_a = split_node_id(node_a)
                type_b, id_b = split_node_id(node_b)
                has_edge = graph.has_relationship(type_a, id_a, type_b, id_b, rel.name)
                has_reverse = graph.has_relationship(type_b, id_b, type_a, id_a, rel.name)

                if has_edge or has_reverse:
                    continue

                entity_a = graph.get_entity(type_a, id_a)
                entity_b = graph.get_entity(type_b, id_b)
                if not entity_a or not entity_b:
                    continue
                findings.append(
                    EvaluationFinding(
                        category="candidate_opportunity",
                        severity="info",
                        message=(
                            f"Candidate: {entity_a.entity_type}:{entity_a.entity_id} "
                            f"and {entity_b.entity_type}:{entity_b.entity_id} "
                            f"share {len(shared)} neighbor(s) but lack '{rel.name}' edge"
                        ),
                        detail={
                            "relationship_type": rel.name,
                            "entity_a": f"{entity_a.entity_type}:{entity_a.entity_id}",
                            "entity_b": f"{entity_b.entity_type}:{entity_b.entity_id}",
                            "shared_neighbors": len(shared),
                        },
                    )
                )


def _check_low_confidence_edges(
    graph: EntityGraph,
    findings: list[EvaluationFinding],
    threshold: float,
) -> None:
    """Find edges with low confidence or pending review status."""
    for from_type, from_id, to_type, to_id, props in graph.iter_edge_data():
        confidence = props.get("confidence")
        review_status = props.get("review_status")

        if review_status == "pending_review":
            findings.append(
                EvaluationFinding(
                    category="low_confidence_edge",
                    severity="warning",
                    message=(
                        f"Pending review: {from_type}:{from_id} "
                        f"—[{props.get('relationship_type', '?')}]→ "
                        f"{to_type}:{to_id}"
                    ),
                    detail={
                        "from_entity": f"{from_type}:{from_id}",
                        "to_entity": f"{to_type}:{to_id}",
                        "relationship_type": props.get("relationship_type", ""),
                        "review_status": "pending_review",
                    },
                )
            )
        elif confidence is not None:
            try:
                conf_val = float(confidence)
            except (ValueError, TypeError):
                findings.append(
                    EvaluationFinding(
                        category="low_confidence_edge",
                        severity="warning",
                        message=(
                            f"Non-numeric confidence '{confidence}': {from_type}:{from_id} "
                            f"—[{props.get('relationship_type', '?')}]→ "
                            f"{to_type}:{to_id}"
                        ),
                        detail={
                            "from_entity": f"{from_type}:{from_id}",
                            "to_entity": f"{to_type}:{to_id}",
                            "relationship_type": props.get("relationship_type", ""),
                            "confidence": confidence,
                        },
                    )
                )
                continue
            if conf_val < threshold:
                findings.append(
                    EvaluationFinding(
                        category="low_confidence_edge",
                        severity="warning",
                        message=(
                            f"Low confidence ({conf_val:.2f}): {from_type}:{from_id} "
                            f"—[{props.get('relationship_type', '?')}]→ "
                            f"{to_type}:{to_id}"
                        ),
                        detail={
                            "from_entity": f"{from_type}:{from_id}",
                            "to_entity": f"{to_type}:{to_id}",
                            "relationship_type": props.get("relationship_type", ""),
                            "confidence": confidence,
                        },
                    )
                )


_MAX_MATCHED_FOR_CO_MEMBERS = 1000
_MAX_INTERMEDIARY_DEGREE = 200
_REJECTED_STATUSES = {"human_rejected", "ai_rejected"}


def _check_unreviewed_co_members(
    config: CoreConfig,
    graph: EntityGraph,
    findings: list[EvaluationFinding],
) -> None:
    """Find entities sharing an intermediary with a cross-referenced
    entity but lacking a cross-reference edge.

    For each relationship R, find co-membership relationships S where
    R.to_entity == S.from_entity. Entities reachable from matched
    targets through shared intermediaries that lack their own R edge
    are flagged as unreviewed co-members.
    """
    for r_rel in config.relationships:
        # Find co-membership relationships S where R.to_entity == S.from_entity
        s_rels = [
            s
            for s in config.relationships
            if s.from_entity == r_rel.to_entity and s.name != r_rel.name
        ]
        if not s_rels:
            continue

        # Build matched_set: non-rejected R targets
        matched_set: set[str] = set()
        for _, _, to_type, to_id, props in graph.iter_edge_data(r_rel.name):
            if to_type != r_rel.to_entity:
                continue
            if props.get("review_status") in _REJECTED_STATUSES:
                continue
            matched_set.add(make_node_id(to_type, to_id))

        if not matched_set or len(matched_set) > _MAX_MATCHED_FOR_CO_MEMBERS:
            continue

        for s_rel in s_rels:
            seen: set[tuple[str, str, str, str]] = set()
            intermediary_cache: dict[str, list[tuple[Any, dict[str, Any], int]] | None] = {}

            for matched_node_id in matched_set:
                matched_type, matched_id = split_node_id(matched_node_id)

                # Follow S outgoing from matched entity to intermediaries
                outgoing = graph.get_neighbors_with_edge_refs(
                    matched_type, matched_id, s_rel.name, "outgoing"
                )

                for intermediary, out_edge_props, _ in outgoing:
                    # Skip rejected outgoing S edges
                    if out_edge_props.get("review_status") in _REJECTED_STATUSES:
                        continue

                    intermediary_node_id = make_node_id(
                        intermediary.entity_type, intermediary.entity_id
                    )

                    # Check/populate cache for this intermediary
                    if intermediary_node_id not in intermediary_cache:
                        degree = graph.count_edges(
                            intermediary.entity_type,
                            intermediary.entity_id,
                            s_rel.name,
                            "incoming",
                        )
                        if degree > _MAX_INTERMEDIARY_DEGREE:
                            intermediary_cache[intermediary_node_id] = None
                        else:
                            intermediary_cache[intermediary_node_id] = (
                                graph.get_neighbors_with_edge_refs(
                                    intermediary.entity_type,
                                    intermediary.entity_id,
                                    s_rel.name,
                                    "incoming",
                                )
                            )

                    cached = intermediary_cache[intermediary_node_id]
                    if cached is None:
                        continue

                    for co_member, in_edge_props, _ in cached:
                        # Skip rejected incoming S edges
                        if in_edge_props.get("review_status") in _REJECTED_STATUSES:
                            continue

                        # Defensive: skip malformed edges
                        if co_member.entity_type != r_rel.to_entity:
                            continue

                        co_member_node_id = make_node_id(co_member.entity_type, co_member.entity_id)

                        # Skip self
                        if co_member_node_id == matched_node_id:
                            continue

                        # Skip if already matched
                        if co_member_node_id in matched_set:
                            continue

                        # Dedup
                        dedup_key = (
                            co_member.entity_type,
                            co_member.entity_id,
                            r_rel.name,
                            s_rel.name,
                        )
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)

                        findings.append(
                            EvaluationFinding(
                                category="unreviewed_co_member",
                                severity="info",
                                message=(
                                    f"Unreviewed co-member: "
                                    f"{r_rel.to_entity}:{co_member.entity_id}"
                                    f" shares {intermediary.entity_type}"
                                    f":{intermediary.entity_id}"
                                    f" (via '{s_rel.name}') with "
                                    f"{r_rel.to_entity}:{matched_id}"
                                    f" (cross-referenced via"
                                    f" '{r_rel.name}') but has no"
                                    f" '{r_rel.name}' edge"
                                ),
                                detail={
                                    "entity_type": co_member.entity_type,
                                    "entity_id": co_member.entity_id,
                                    "matched_sibling": (f"{r_rel.to_entity}:{matched_id}"),
                                    "shared_via": s_rel.name,
                                    "shared_entity": (
                                        f"{intermediary.entity_type}:{intermediary.entity_id}"
                                    ),
                                    "missing_relationship": r_rel.name,
                                },
                            )
                        )
