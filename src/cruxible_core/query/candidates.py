"""Deterministic relationship candidate detection.

Finds potential new edges between entities using data-only strategies
(no ML). Claude or another AI agent reviews candidates and approves
them for ingestion.

Two strategies:
- property_match: entities with matching property values across types
- shared_neighbors: entities sharing a high % of neighbors via a relationship
"""

from __future__ import annotations

import heapq
import logging
import math
from collections.abc import Hashable
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, Field

from cruxible_core.errors import DataValidationError, RelationshipNotFoundError
from cruxible_core.graph.types import EntityInstance

if TYPE_CHECKING:
    from cruxible_core.config.schema import CoreConfig
    from cruxible_core.graph.entity_graph import EntityGraph

logger = logging.getLogger(__name__)

_MAX_BRUTE_FORCE = 10_000_000
_MAX_SHARED_NEIGHBORS = 50_000


class MatchRule(BaseModel):
    """A property matching rule for candidate detection."""

    from_property: str
    to_property: str
    operator: Literal["equals", "iequals", "contains"] = "equals"


class CandidateMatch(BaseModel):
    """A suggested relationship between two entities."""

    from_entity: EntityInstance
    to_entity: EntityInstance
    confidence: float
    evidence: dict[str, Any] = Field(default_factory=dict)


def find_candidates(
    config: CoreConfig,
    graph: EntityGraph,
    relationship_type: str,
    strategy: Literal["property_match", "shared_neighbors"],
    *,
    match_rules: list[MatchRule] | None = None,
    via_relationship: str | None = None,
    min_overlap: float = 0.5,
    min_confidence: float = 0.5,
    limit: int = 100,
    min_distinct_neighbors: int = 1,
) -> list[CandidateMatch]:
    """Find candidate relationships using a deterministic strategy.

    Args:
        config: Config with relationship definitions
        graph: Populated graph
        relationship_type: The relationship type to suggest candidates for
        strategy: Detection strategy to use
        match_rules: For property_match — which properties to compare
        via_relationship: For shared_neighbors — relationship to check overlap
        min_overlap: For shared_neighbors — minimum Jaccard similarity
        min_confidence: Minimum confidence to include (default 0.5)
        limit: Maximum candidates to return

    Returns:
        List of CandidateMatch sorted by confidence (descending)
    """
    if min_distinct_neighbors < 1:
        raise ValueError("min_distinct_neighbors must be >= 1")

    if strategy == "property_match":
        if not match_rules:
            msg = "property_match strategy requires match_rules"
            raise ValueError(msg)
        if limit <= 0:
            return []
        return _property_match(
            config,
            graph,
            relationship_type,
            match_rules,
            min_confidence=min_confidence,
            limit=limit,
        )

    if strategy == "shared_neighbors":
        if not via_relationship:
            msg = "shared_neighbors strategy requires via_relationship"
            raise ValueError(msg)
        if limit <= 0:
            return []
        return _shared_neighbors(
            config,
            graph,
            relationship_type,
            via_relationship,
            min_overlap=min_overlap,
            limit=limit,
            min_distinct_neighbors=min_distinct_neighbors,
        )

    msg = f"Unknown strategy: {strategy}"
    raise ValueError(msg)


def _property_match(
    config: CoreConfig,
    graph: EntityGraph,
    relationship_type: str,
    match_rules: list[MatchRule],
    *,
    min_confidence: float = 0.5,
    limit: int = 100,
) -> list[CandidateMatch]:
    """Find candidates by matching property values across entity types."""
    rel_schema = config.get_relationship(relationship_type)
    if rel_schema is None:
        raise RelationshipNotFoundError(relationship_type)

    from_entities = graph.list_entities(rel_schema.from_entity)
    to_entities = graph.list_entities(rel_schema.to_entity)

    # Route to hash-join if all rules are equals/iequals
    uses_contains = any(r.operator == "contains" for r in match_rules)
    if uses_contains:
        return _property_match_brute_force(
            graph,
            relationship_type,
            from_entities,
            to_entities,
            match_rules,
            min_confidence=min_confidence,
            limit=limit,
        )
    else:
        return _property_match_hash_join(
            graph,
            relationship_type,
            from_entities,
            to_entities,
            match_rules,
            min_confidence=min_confidence,
            limit=limit,
        )


def _normalize_key(value: Any, operator: str) -> Hashable | None:
    """Normalize a value for hash-join indexing.

    For equals: return raw value (preserves type semantics so True != "True").
    For iequals: return str(value).lower().
    Returns None for unhashable values (skipped during indexing).
    """
    if value is None:
        return None
    if operator == "iequals":
        return str(value).lower()
    # equals — return raw value to preserve type semantics
    try:
        hash(value)
    except TypeError:
        return None
    return cast(Hashable, value)


def _push_candidate(
    heap: list[tuple[float, int, CandidateMatch]],
    candidate: CandidateMatch,
    counter: int,
    limit: int,
) -> int:
    """Push a candidate into a bounded min-heap. Returns next counter value."""
    entry = (candidate.confidence, counter, candidate)
    if len(heap) < limit:
        heapq.heappush(heap, entry)
    elif candidate.confidence > heap[0][0]:
        heapq.heappushpop(heap, entry)
    return counter + 1


def _heap_to_sorted(heap: list[tuple[float, int, CandidateMatch]]) -> list[CandidateMatch]:
    """Extract candidates from heap, sorted by confidence descending."""
    result = [entry[2] for entry in heap]
    result.sort(key=lambda c: c.confidence, reverse=True)
    return result


def _property_match_hash_join(
    graph: EntityGraph,
    relationship_type: str,
    from_entities: list[EntityInstance],
    to_entities: list[EntityInstance],
    match_rules: list[MatchRule],
    *,
    min_confidence: float = 0.5,
    limit: int = 100,
) -> list[CandidateMatch]:
    """O(n+m) hash-join for equals/iequals rules."""
    # Build index on to_entities for each rule
    # index[rule_idx] = {normalized_value: [to_entity_indices]}
    to_indices: list[dict[Hashable, list[int]]] = []
    for rule in match_rules:
        idx: dict[Hashable, list[int]] = {}
        for i, to_ent in enumerate(to_entities):
            val = to_ent.properties.get(rule.to_property)
            key = _normalize_key(val, rule.operator)
            if key is not None:
                idx.setdefault(key, []).append(i)
        to_indices.append(idx)

    # Process one from_entity at a time to bound intermediate memory to O(m)
    heap: list[tuple[float, int, CandidateMatch]] = []
    counter = 0
    num_rules = len(match_rules)

    for from_ent in from_entities:
        # local_matches: to_idx -> (match_count, evidence_dict)
        local_matches: dict[int, tuple[int, dict[str, Any]]] = {}

        for rule_idx, rule in enumerate(match_rules):
            from_val = from_ent.properties.get(rule.from_property)
            key = _normalize_key(from_val, rule.operator)
            if key is None:
                continue
            matching_to = to_indices[rule_idx].get(key, [])
            for to_idx in matching_to:
                if to_idx not in local_matches:
                    local_matches[to_idx] = (0, {})
                count, evidence = local_matches[to_idx]
                evidence[rule.from_property] = {
                    "matched": True,
                    "value": from_val,
                    "rule": {
                        "from_property": rule.from_property,
                        "to_property": rule.to_property,
                    },
                }
                local_matches[to_idx] = (count + 1, evidence)

        # Build candidates from this from_entity's matches
        for to_idx, (matched, evidence) in local_matches.items():
            confidence = matched / num_rules if num_rules else 0
            if confidence <= 0 or confidence < min_confidence:
                continue

            to_ent = to_entities[to_idx]

            # Skip existing relationships
            if graph.has_relationship(
                from_ent.entity_type,
                from_ent.entity_id,
                to_ent.entity_type,
                to_ent.entity_id,
                relationship_type,
            ):
                continue

            # Add non-matching rule evidence
            for rule in match_rules:
                if rule.from_property not in evidence:
                    evidence[rule.from_property] = {
                        "matched": False,
                        "from_value": from_ent.properties.get(rule.from_property),
                        "to_value": to_ent.properties.get(rule.to_property),
                        "rule": {
                            "from_property": rule.from_property,
                            "to_property": rule.to_property,
                        },
                    }

            candidate = CandidateMatch(
                from_entity=from_ent,
                to_entity=to_ent,
                confidence=confidence,
                evidence=evidence,
            )
            counter = _push_candidate(heap, candidate, counter, limit)

    return _heap_to_sorted(heap)


def _property_match_brute_force(
    graph: EntityGraph,
    relationship_type: str,
    from_entities: list[EntityInstance],
    to_entities: list[EntityInstance],
    match_rules: list[MatchRule],
    *,
    min_confidence: float = 0.5,
    limit: int = 100,
) -> list[CandidateMatch]:
    """Brute-force matching for rules with contains operator."""
    product = len(from_entities) * len(to_entities)
    if product > _MAX_BRUTE_FORCE:
        raise DataValidationError(
            f"Entity set too large for substring matching "
            f"({len(from_entities)} x {len(to_entities)} = {product:,} pairs, "
            f"max {_MAX_BRUTE_FORCE:,}). "
            f"Use equals/iequals operators or filter with a named query first."
        )

    num_rules = len(match_rules)
    if num_rules == 0:
        return []
    required_matches = math.ceil(min_confidence * num_rules)

    # Sort rules by selectivity for early-prune benefit (equals > iequals > contains)
    _OP_RANK = {"equals": 0, "iequals": 1, "contains": 2}
    eval_order = sorted(range(num_rules), key=lambda i: _OP_RANK.get(match_rules[i].operator, 9))

    # Precompute normalized values per rule
    from_normed: list[list[Any]] = []
    to_normed: list[list[Any]] = []
    for rule in match_rules:
        needs_lower = rule.operator in ("iequals", "contains")
        from_normed.append(
            [
                str(v).lower()
                if (v := e.properties.get(rule.from_property)) is not None and needs_lower
                else v
                for e in from_entities
            ]
        )
        to_normed.append(
            [
                str(v).lower()
                if (v := e.properties.get(rule.to_property)) is not None and needs_lower
                else v
                for e in to_entities
            ]
        )

    heap: list[tuple[float, int, CandidateMatch]] = []
    counter = 0

    for fi, from_entity in enumerate(from_entities):
        for ti, to_entity in enumerate(to_entities):
            if graph.has_relationship(
                from_entity.entity_type,
                from_entity.entity_id,
                to_entity.entity_type,
                to_entity.entity_id,
                relationship_type,
            ):
                continue

            matched_indices: set[int] = set()
            pruned = False
            for ei, ri in enumerate(eval_order):
                fv = from_normed[ri][fi]
                tv = to_normed[ri][ti]
                if fv is not None and tv is not None:
                    op = match_rules[ri].operator
                    hit = (
                        (op == "equals" and fv == tv)
                        or (op == "iequals" and fv == tv)
                        or (op == "contains" and tv in fv)
                    )
                    if hit:
                        matched_indices.add(ri)

                # Early-prune: can't reach min_confidence
                remaining = num_rules - ei - 1
                if len(matched_indices) + remaining < required_matches:
                    pruned = True
                    break

            if pruned:
                continue

            confidence = len(matched_indices) / num_rules
            if confidence <= 0 or confidence < min_confidence:
                continue

            # Build evidence in original rule order
            evidence: dict[str, Any] = {}
            for ri, rule in enumerate(match_rules):
                rule_info = {
                    "from_property": rule.from_property,
                    "to_property": rule.to_property,
                }
                if ri in matched_indices:
                    evidence[rule.from_property] = {
                        "matched": True,
                        "value": from_entity.properties.get(rule.from_property),
                        "rule": rule_info,
                    }
                else:
                    evidence[rule.from_property] = {
                        "matched": False,
                        "from_value": from_entity.properties.get(rule.from_property),
                        "to_value": to_entity.properties.get(rule.to_property),
                        "rule": rule_info,
                    }

            candidate = CandidateMatch(
                from_entity=from_entity,
                to_entity=to_entity,
                confidence=confidence,
                evidence=evidence,
            )
            counter = _push_candidate(heap, candidate, counter, limit)

    return _heap_to_sorted(heap)


def _shared_neighbors(
    config: CoreConfig,
    graph: EntityGraph,
    relationship_type: str,
    via_relationship: str,
    *,
    min_overlap: float = 0.5,
    limit: int = 100,
    min_distinct_neighbors: int = 1,
) -> list[CandidateMatch]:
    """Find candidates by shared neighbor overlap (Jaccard similarity)."""
    rel_schema = config.get_relationship(relationship_type)
    if rel_schema is None:
        raise RelationshipNotFoundError(relationship_type)

    entity_type = rel_schema.from_entity
    entities = graph.list_entities(entity_type)

    if len(entities) > _MAX_SHARED_NEIGHBORS:
        logger.warning(
            "shared_neighbors: %d entities of type '%s' — may be slow (threshold: %d)",
            len(entities),
            entity_type,
            _MAX_SHARED_NEIGHBORS,
        )

    # Build neighbor set for each entity via the shared relationship
    neighbor_sets: dict[str, set[str]] = {}
    entity_map: dict[str, EntityInstance] = {}

    for entity in entities:
        neighbors = graph.get_neighbors_with_edge_refs(
            entity.entity_type,
            entity.entity_id,
            relationship_type=via_relationship,
            direction="outgoing",
        )
        neighbor_sets[entity.entity_id] = {n.entity_id for n, _, _ in neighbors}
        entity_map[entity.entity_id] = entity

    # Compare all pairs using bounded heap
    heap: list[tuple[float, int, CandidateMatch]] = []
    counter = 0
    entity_ids = list(neighbor_sets.keys())

    for i in range(len(entity_ids)):
        for j in range(i + 1, len(entity_ids)):
            id_a, id_b = entity_ids[i], entity_ids[j]
            set_a, set_b = neighbor_sets[id_a], neighbor_sets[id_b]

            if not set_a or not set_b:
                continue

            # Skip pairs where BOTH entities have fewer than threshold neighbors
            if len(set_a) < min_distinct_neighbors and len(set_b) < min_distinct_neighbors:
                continue

            intersection = set_a & set_b
            union = set_a | set_b
            overlap = len(intersection) / len(union)

            if overlap < min_overlap:
                continue

            # Skip if already related in either direction
            if graph.has_relationship(
                entity_type, id_a, entity_type, id_b, relationship_type
            ) or graph.has_relationship(entity_type, id_b, entity_type, id_a, relationship_type):
                continue

            candidate = CandidateMatch(
                from_entity=entity_map[id_a],
                to_entity=entity_map[id_b],
                confidence=overlap,
                evidence={
                    "shared_neighbors": sorted(intersection),
                    "total_union": len(union),
                    "overlap_ratio": overlap,
                },
            )
            counter = _push_candidate(heap, candidate, counter, limit)

    return _heap_to_sorted(heap)
