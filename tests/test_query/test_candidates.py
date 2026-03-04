"""Tests for candidate detection."""

import pytest

from cruxible_core.config.schema import (
    CoreConfig,
    EntityTypeSchema,
    PropertySchema,
    RelationshipSchema,
)
from cruxible_core.errors import RelationshipNotFoundError
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance, RelationshipInstance
from cruxible_core.query.candidates import (
    MatchRule,
    _property_match_brute_force,
    find_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> CoreConfig:
    return CoreConfig(
        name="test",
        entity_types={
            "Part": EntityTypeSchema(
                properties={
                    "part_number": PropertySchema(type="string", primary_key=True),
                    "category": PropertySchema(type="string"),
                    "diameter": PropertySchema(type="float", optional=True),
                    "brand": PropertySchema(type="string", optional=True),
                }
            ),
            "Vehicle": EntityTypeSchema(
                properties={
                    "vehicle_id": PropertySchema(type="string", primary_key=True),
                    "rotor_spec": PropertySchema(type="float", optional=True),
                }
            ),
        },
        relationships=[
            RelationshipSchema(
                name="fits",
                from_entity="Part",
                to_entity="Vehicle",
            ),
            RelationshipSchema(
                name="replaces",
                from_entity="Part",
                to_entity="Part",
            ),
        ],
    )


@pytest.fixture
def graph() -> EntityGraph:
    g = EntityGraph()

    # Parts with diameter specs
    g.add_entity(
        EntityInstance(
            entity_type="Part",
            entity_id="P-1",
            properties={"category": "brakes", "diameter": 300.0, "brand": "StopTech"},
        )
    )
    g.add_entity(
        EntityInstance(
            entity_type="Part",
            entity_id="P-2",
            properties={"category": "brakes", "diameter": 300.0, "brand": "Brembo"},
        )
    )
    g.add_entity(
        EntityInstance(
            entity_type="Part",
            entity_id="P-3",
            properties={"category": "suspension", "diameter": 250.0, "brand": "StopTech"},
        )
    )

    # Vehicles with rotor specs
    g.add_entity(
        EntityInstance(
            entity_type="Vehicle",
            entity_id="V-1",
            properties={"rotor_spec": 300.0},
        )
    )
    g.add_entity(
        EntityInstance(
            entity_type="Vehicle",
            entity_id="V-2",
            properties={"rotor_spec": 250.0},
        )
    )

    return g


@pytest.fixture
def graph_with_edges(graph: EntityGraph) -> EntityGraph:
    """Graph with fitment edges for shared_neighbors tests."""
    # P-1 fits V-1 and V-2
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="fits",
            from_entity_type="Part",
            from_entity_id="P-1",
            to_entity_type="Vehicle",
            to_entity_id="V-1",
            properties={},
        )
    )
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="fits",
            from_entity_type="Part",
            from_entity_id="P-1",
            to_entity_type="Vehicle",
            to_entity_id="V-2",
            properties={},
        )
    )

    # P-2 fits V-1 and V-2 (same vehicles as P-1)
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="fits",
            from_entity_type="Part",
            from_entity_id="P-2",
            to_entity_type="Vehicle",
            to_entity_id="V-1",
            properties={},
        )
    )
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="fits",
            from_entity_type="Part",
            from_entity_id="P-2",
            to_entity_type="Vehicle",
            to_entity_id="V-2",
            properties={},
        )
    )

    # P-3 fits only V-2 (partial overlap with P-1/P-2)
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="fits",
            from_entity_type="Part",
            from_entity_id="P-3",
            to_entity_type="Vehicle",
            to_entity_id="V-2",
            properties={},
        )
    )

    return graph


# ---------------------------------------------------------------------------
# property_match
# ---------------------------------------------------------------------------


class TestPropertyMatch:
    def test_basic_match(self, config: CoreConfig, graph: EntityGraph):
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
            ],
            min_confidence=0.5,
        )
        # P-1 (300) matches V-1 (300), P-2 (300) matches V-1 (300)
        # P-3 (250) matches V-2 (250)
        assert len(candidates) >= 3
        for c in candidates:
            assert c.confidence == 1.0

    def test_partial_match(self, config: CoreConfig, graph: EntityGraph):
        """Two rules, only one matches."""
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
                MatchRule(from_property="brand", to_property="rotor_spec"),
            ],
            min_confidence=0.0,
        )
        # brand never matches rotor_spec, so confidence is 0.5 at best
        for c in candidates:
            assert c.confidence <= 0.5

    def test_min_confidence_filters(self, config: CoreConfig, graph: EntityGraph):
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
                MatchRule(from_property="brand", to_property="rotor_spec"),
            ],
            min_confidence=0.8,
        )
        assert len(candidates) == 0

    def test_skips_existing_relationships(self, config: CoreConfig, graph_with_edges: EntityGraph):
        candidates = find_candidates(
            config,
            graph_with_edges,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
            ],
            min_confidence=0.5,
        )
        # P-1 fits V-1 and V-2 already exist, P-2 fits V-1 and V-2 already exist
        # Only P-3 → V-2 (250 match) should appear
        pair_ids = {(c.from_entity.entity_id, c.to_entity.entity_id) for c in candidates}
        assert ("P-1", "V-1") not in pair_ids
        assert ("P-2", "V-1") not in pair_ids

    def test_limit(self, config: CoreConfig, graph: EntityGraph):
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
            ],
            min_confidence=0.0,
            limit=2,
        )
        assert len(candidates) <= 2

    def test_sorted_by_confidence(self, config: CoreConfig, graph: EntityGraph):
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
            ],
            min_confidence=0.0,
        )
        confidences = [c.confidence for c in candidates]
        assert confidences == sorted(confidences, reverse=True)

    def test_evidence_populated(self, config: CoreConfig, graph: EntityGraph):
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
            ],
            min_confidence=0.5,
        )
        assert len(candidates) > 0
        evidence = candidates[0].evidence
        assert "diameter" in evidence
        assert evidence["diameter"]["matched"] is True
        assert evidence["diameter"]["rule"] == {
            "from_property": "diameter",
            "to_property": "rotor_spec",
        }

    def test_missing_rules_raises(self, config: CoreConfig, graph: EntityGraph):
        with pytest.raises(ValueError, match="match_rules"):
            find_candidates(config, graph, "fits", "property_match")

    def test_bad_relationship_raises(self, config: CoreConfig, graph: EntityGraph):
        with pytest.raises(RelationshipNotFoundError):
            find_candidates(
                config,
                graph,
                "nonexistent",
                "property_match",
                match_rules=[MatchRule(from_property="a", to_property="b")],
            )


# ---------------------------------------------------------------------------
# shared_neighbors
# ---------------------------------------------------------------------------


class TestSharedNeighbors:
    def test_full_overlap(self, config: CoreConfig, graph_with_edges: EntityGraph):
        """P-1 and P-2 fit exactly the same vehicles — Jaccard = 1.0."""
        candidates = find_candidates(
            config,
            graph_with_edges,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.5,
        )
        pair_ids = {(c.from_entity.entity_id, c.to_entity.entity_id) for c in candidates}
        # P-1 and P-2 share 100% overlap
        assert ("P-1", "P-2") in pair_ids or ("P-2", "P-1") in pair_ids

    def test_partial_overlap(self, config: CoreConfig, graph_with_edges: EntityGraph):
        """P-1 and P-3 share V-2 but not V-1 — Jaccard = 1/2 = 0.5."""
        candidates = find_candidates(
            config,
            graph_with_edges,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.5,
        )
        all_pairs = {
            tuple(sorted([c.from_entity.entity_id, c.to_entity.entity_id])) for c in candidates
        }
        assert ("P-1", "P-3") in all_pairs or ("P-3", "P-1") in all_pairs

    def test_min_overlap_filters(self, config: CoreConfig, graph_with_edges: EntityGraph):
        candidates = find_candidates(
            config,
            graph_with_edges,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.9,
        )
        # Only P-1/P-2 with 1.0 overlap should pass
        assert len(candidates) == 1

    def test_skips_existing_relationships(self, config: CoreConfig, graph_with_edges: EntityGraph):
        # Add a replaces edge between P-1 and P-2
        graph_with_edges.add_relationship(
            RelationshipInstance(
                relationship_type="replaces",
                from_entity_type="Part",
                from_entity_id="P-1",
                to_entity_type="Part",
                to_entity_id="P-2",
                properties={"direction": "equivalent", "confidence": 0.9},
            )
        )

        candidates = find_candidates(
            config,
            graph_with_edges,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.9,
        )
        pair_ids = {(c.from_entity.entity_id, c.to_entity.entity_id) for c in candidates}
        assert ("P-1", "P-2") not in pair_ids

    def test_evidence_populated(self, config: CoreConfig, graph_with_edges: EntityGraph):
        candidates = find_candidates(
            config,
            graph_with_edges,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.9,
        )
        assert len(candidates) > 0
        evidence = candidates[0].evidence
        assert "shared_neighbors" in evidence
        assert "overlap_ratio" in evidence

    def test_empty_graph(self, config: CoreConfig):
        g = EntityGraph()
        candidates = find_candidates(
            config,
            g,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.5,
        )
        assert candidates == []

    def test_no_neighbors(self, config: CoreConfig, graph: EntityGraph):
        """Entities exist but have no edges."""
        candidates = find_candidates(
            config,
            graph,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.5,
        )
        assert candidates == []

    def test_single_shared_neighbor_filtered(self, config: CoreConfig):
        """Entities with only 1 neighbor each are filtered by default min_distinct_neighbors=2."""
        g = EntityGraph()
        g.add_entity(EntityInstance(entity_type="Part", entity_id="P-A", properties={}))
        g.add_entity(EntityInstance(entity_type="Part", entity_id="P-B", properties={}))
        g.add_entity(EntityInstance(entity_type="Vehicle", entity_id="V-1", properties={}))
        g.add_relationship(
            RelationshipInstance(
                relationship_type="fits",
                from_entity_type="Part",
                from_entity_id="P-A",
                to_entity_type="Vehicle",
                to_entity_id="V-1",
                properties={},
            )
        )
        g.add_relationship(
            RelationshipInstance(
                relationship_type="fits",
                from_entity_type="Part",
                from_entity_id="P-B",
                to_entity_type="Vehicle",
                to_entity_id="V-1",
                properties={},
            )
        )
        candidates = find_candidates(
            config,
            g,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.5,
            min_distinct_neighbors=2,
        )
        assert len(candidates) == 0

    def test_min_distinct_neighbors_one_disables(self, config: CoreConfig):
        """min_distinct_neighbors=1 evaluates all pairs (backward compatible)."""
        g = EntityGraph()
        g.add_entity(EntityInstance(entity_type="Part", entity_id="P-A", properties={}))
        g.add_entity(EntityInstance(entity_type="Part", entity_id="P-B", properties={}))
        g.add_entity(EntityInstance(entity_type="Vehicle", entity_id="V-1", properties={}))
        g.add_relationship(
            RelationshipInstance(
                relationship_type="fits",
                from_entity_type="Part",
                from_entity_id="P-A",
                to_entity_type="Vehicle",
                to_entity_id="V-1",
                properties={},
            )
        )
        g.add_relationship(
            RelationshipInstance(
                relationship_type="fits",
                from_entity_type="Part",
                from_entity_id="P-B",
                to_entity_type="Vehicle",
                to_entity_id="V-1",
                properties={},
            )
        )
        candidates = find_candidates(
            config,
            g,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.5,
            min_distinct_neighbors=1,
        )
        assert len(candidates) == 1

    def test_degenerate_case_large(self, config: CoreConfig):
        """100 entities each with 1 shared neighbor → zero candidates at threshold 2."""
        g = EntityGraph()
        g.add_entity(EntityInstance(entity_type="Vehicle", entity_id="V-SHARED", properties={}))
        for i in range(100):
            g.add_entity(EntityInstance(entity_type="Part", entity_id=f"P-{i}", properties={}))
            g.add_relationship(
                RelationshipInstance(
                    relationship_type="fits",
                    from_entity_type="Part",
                    from_entity_id=f"P-{i}",
                    to_entity_type="Vehicle",
                    to_entity_id="V-SHARED",
                    properties={},
                )
            )
        candidates = find_candidates(
            config,
            g,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.5,
            min_distinct_neighbors=2,
        )
        assert len(candidates) == 0

    def test_min_distinct_neighbors_zero_rejected_core(
        self, config: CoreConfig, graph: EntityGraph
    ):
        """find_candidates directly raises ValueError for min_distinct_neighbors < 1."""
        with pytest.raises(ValueError, match="min_distinct_neighbors must be >= 1"):
            find_candidates(
                config,
                graph,
                "replaces",
                "shared_neighbors",
                via_relationship="fits",
                min_distinct_neighbors=0,
            )

    def test_missing_via_relationship_raises(self, config: CoreConfig, graph: EntityGraph):
        with pytest.raises(ValueError, match="via_relationship"):
            find_candidates(
                config,
                graph,
                "replaces",
                "shared_neighbors",
            )

    def test_bad_relationship_raises(self, config: CoreConfig, graph: EntityGraph):
        with pytest.raises(RelationshipNotFoundError):
            find_candidates(
                config,
                graph,
                "nonexistent",
                "shared_neighbors",
                via_relationship="fits",
            )

    def test_limit(self, config: CoreConfig, graph_with_edges: EntityGraph):
        candidates = find_candidates(
            config,
            graph_with_edges,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            min_overlap=0.0,
            limit=1,
        )
        assert len(candidates) <= 1


# ---------------------------------------------------------------------------
# find_candidates: dispatcher
# ---------------------------------------------------------------------------


class TestFindCandidatesDispatcher:
    def test_unknown_strategy(self, config: CoreConfig, graph: EntityGraph):
        with pytest.raises(ValueError, match="Unknown strategy"):
            find_candidates(config, graph, "fits", "unknown_strategy")

    def test_limit_zero_property_match(self, config: CoreConfig, graph: EntityGraph):
        """limit=0 returns empty list, no crash."""
        result = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[MatchRule(from_property="diameter", to_property="rotor_spec")],
            limit=0,
        )
        assert result == []

    def test_limit_zero_shared_neighbors(self, config: CoreConfig, graph_with_edges: EntityGraph):
        """limit=0 returns empty list, no crash."""
        result = find_candidates(
            config,
            graph_with_edges,
            "replaces",
            "shared_neighbors",
            via_relationship="fits",
            limit=0,
        )
        assert result == []

    def test_limit_zero_still_validates_strategy(self, config: CoreConfig, graph: EntityGraph):
        """Unknown strategy raises even with limit=0."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            find_candidates(config, graph, "fits", "unknown_strategy", limit=0)

    def test_limit_zero_still_validates_rules(self, config: CoreConfig, graph: EntityGraph):
        """property_match without match_rules raises even with limit=0."""
        with pytest.raises(ValueError, match="match_rules"):
            find_candidates(config, graph, "fits", "property_match", limit=0)


# ---------------------------------------------------------------------------
# New operators: iequals, contains
# ---------------------------------------------------------------------------


class TestOperators:
    def test_iequals_operator(self, config: CoreConfig) -> None:
        """iequals matches mixed-case values."""
        g = EntityGraph()
        g.add_entity(
            EntityInstance(
                entity_type="Part",
                entity_id="P-1",
                properties={"brand": "StopTech"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Vehicle",
                entity_id="V-1",
                properties={"rotor_spec": "stoptech"},
            )
        )
        candidates = find_candidates(
            config,
            g,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(
                    from_property="brand",
                    to_property="rotor_spec",
                    operator="iequals",
                ),
            ],
            min_confidence=0.5,
        )
        assert len(candidates) == 1
        assert candidates[0].confidence == 1.0

    def test_contains_operator(self, config: CoreConfig) -> None:
        """contains matches substrings."""
        g = EntityGraph()
        g.add_entity(
            EntityInstance(
                entity_type="Part",
                entity_id="P-1",
                properties={"brand": "StopTech Ceramic Brake Pads"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Vehicle",
                entity_id="V-1",
                properties={"rotor_spec": "ceramic"},
            )
        )
        candidates = find_candidates(
            config,
            g,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(
                    from_property="brand",
                    to_property="rotor_spec",
                    operator="contains",
                ),
            ],
            min_confidence=0.5,
        )
        assert len(candidates) == 1

    def test_equals_type_coercion(self, config: CoreConfig) -> None:
        """equals preserves types: True != 'True', but int 300 == float 300.0."""
        g = EntityGraph()
        g.add_entity(
            EntityInstance(
                entity_type="Part",
                entity_id="P-bool",
                properties={"category": True},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Vehicle",
                entity_id="V-str",
                properties={"rotor_spec": "True"},
            )
        )
        # True should NOT match "True" under equals
        candidates = find_candidates(
            config,
            g,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="category", to_property="rotor_spec", operator="equals"),
            ],
            min_confidence=0.0,
        )
        assert len(candidates) == 0

        # int 300 SHOULD match float 300.0 under equals (Python ==)
        g2 = EntityGraph()
        g2.add_entity(
            EntityInstance(
                entity_type="Part",
                entity_id="P-int",
                properties={"diameter": 300},
            )
        )
        g2.add_entity(
            EntityInstance(
                entity_type="Vehicle",
                entity_id="V-float",
                properties={"rotor_spec": 300.0},
            )
        )
        candidates2 = find_candidates(
            config,
            g2,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec", operator="equals"),
            ],
            min_confidence=0.0,
        )
        assert len(candidates2) == 1
        assert candidates2[0].confidence == 1.0

    def test_contains_no_match(self, config: CoreConfig) -> None:
        """contains does not false-positive when substring is absent."""
        g = EntityGraph()
        g.add_entity(
            EntityInstance(
                entity_type="Part",
                entity_id="P-1",
                properties={"brand": "Brembo"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Vehicle",
                entity_id="V-1",
                properties={"rotor_spec": "ceramic"},
            )
        )
        candidates = find_candidates(
            config,
            g,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(
                    from_property="brand",
                    to_property="rotor_spec",
                    operator="contains",
                ),
            ],
            min_confidence=0.5,
        )
        assert len(candidates) == 0


# ---------------------------------------------------------------------------
# Bounded accumulation and memory safety
# ---------------------------------------------------------------------------


class TestBoundedAccumulation:
    def test_zero_confidence_excluded(self, config: CoreConfig, graph: EntityGraph) -> None:
        """Pairs with no matching rules are never returned."""
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="brand", to_property="rotor_spec"),
            ],
            min_confidence=0.0,
        )
        # brand never equals rotor_spec, so all pairs have 0 confidence
        assert len(candidates) == 0

    def test_min_confidence_filters_new(self, config: CoreConfig, graph: EntityGraph) -> None:
        """Only pairs above threshold are returned."""
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[
                MatchRule(from_property="diameter", to_property="rotor_spec"),
            ],
            min_confidence=1.0,
        )
        for c in candidates:
            assert c.confidence >= 1.0

    def test_bounded_accumulation(self, config: CoreConfig) -> None:
        """With many matches, output is bounded by limit."""
        g = EntityGraph()
        # Create enough entities to generate many pairs
        for i in range(20):
            g.add_entity(
                EntityInstance(
                    entity_type="Part",
                    entity_id=f"P-{i}",
                    properties={"category": "brakes", "diameter": 300.0},
                )
            )
            g.add_entity(
                EntityInstance(
                    entity_type="Vehicle",
                    entity_id=f"V-{i}",
                    properties={"rotor_spec": 300.0},
                )
            )
        candidates = find_candidates(
            config,
            g,
            "fits",
            "property_match",
            match_rules=[MatchRule(from_property="diameter", to_property="rotor_spec")],
            min_confidence=0.5,
            limit=5,
        )
        assert len(candidates) <= 5

    def test_hash_join_equivalence(self, config: CoreConfig, graph: EntityGraph) -> None:
        """equals via hash-join produces same results as would brute-force."""
        candidates = find_candidates(
            config,
            graph,
            "fits",
            "property_match",
            match_rules=[MatchRule(from_property="diameter", to_property="rotor_spec")],
            min_confidence=0.5,
        )
        # P-1 (300) → V-1 (300), P-2 (300) → V-1 (300), P-3 (250) → V-2 (250)
        assert len(candidates) >= 3
        for c in candidates:
            assert c.confidence == 1.0

    def test_contains_large_set_errors(self, config: CoreConfig) -> None:
        """Entity product > threshold raises error for contains."""
        import cruxible_core.query.candidates as cmod
        from cruxible_core.errors import DataValidationError

        g = EntityGraph()
        old_max = cmod._MAX_BRUTE_FORCE
        try:
            cmod._MAX_BRUTE_FORCE = 2  # Very low threshold
            g.add_entity(
                EntityInstance(
                    entity_type="Part",
                    entity_id="P-1",
                    properties={"brand": "A"},
                )
            )
            g.add_entity(
                EntityInstance(
                    entity_type="Part",
                    entity_id="P-2",
                    properties={"brand": "B"},
                )
            )
            g.add_entity(
                EntityInstance(
                    entity_type="Vehicle",
                    entity_id="V-1",
                    properties={"rotor_spec": "a"},
                )
            )
            g.add_entity(
                EntityInstance(
                    entity_type="Vehicle",
                    entity_id="V-2",
                    properties={"rotor_spec": "b"},
                )
            )

            with pytest.raises(DataValidationError, match="too large"):
                find_candidates(
                    config,
                    g,
                    "fits",
                    "property_match",
                    match_rules=[
                        MatchRule(
                            from_property="brand",
                            to_property="rotor_spec",
                            operator="contains",
                        ),
                    ],
                    min_confidence=0.5,
                )
        finally:
            cmod._MAX_BRUTE_FORCE = old_max


# ---------------------------------------------------------------------------
# Brute-force optimizations
# ---------------------------------------------------------------------------


class TestBruteForceOptimizations:
    """Tests for precomputed normalization, early-prune, and rule ordering."""

    @pytest.fixture
    def bf_config(self) -> CoreConfig:
        return CoreConfig(
            name="bf_test",
            entity_types={
                "Product": EntityTypeSchema(
                    properties={
                        "pid": PropertySchema(type="string", primary_key=True),
                        "name": PropertySchema(type="string"),
                        "desc": PropertySchema(type="string", optional=True),
                        "sku": PropertySchema(type="string", optional=True),
                        "color": PropertySchema(type="string", optional=True),
                    }
                ),
                "Listing": EntityTypeSchema(
                    properties={
                        "lid": PropertySchema(type="string", primary_key=True),
                        "title": PropertySchema(type="string"),
                        "body": PropertySchema(type="string", optional=True),
                        "code": PropertySchema(type="string", optional=True),
                        "shade": PropertySchema(type="string", optional=True),
                    }
                ),
            },
            relationships=[
                RelationshipSchema(
                    name="matches",
                    from_entity="Product",
                    to_entity="Listing",
                ),
            ],
        )

    def test_brute_force_precomputed_matches_original(self, bf_config: CoreConfig) -> None:
        """Optimized brute force produces identical results to original semantics."""
        g = EntityGraph()
        g.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id="P-1",
                properties={"name": "StopTech Ceramic Brake Pads", "desc": "High performance"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id="P-2",
                properties={"name": "Brembo Sport Rotors", "desc": "Drilled rotors"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Listing",
                entity_id="L-1",
                properties={"title": "ceramic", "body": "performance"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Listing",
                entity_id="L-2",
                properties={"title": "sport", "body": "drilled"},
            )
        )

        candidates = find_candidates(
            bf_config,
            g,
            "matches",
            "property_match",
            match_rules=[
                MatchRule(from_property="name", to_property="title", operator="contains"),
                MatchRule(from_property="desc", to_property="body", operator="contains"),
            ],
            min_confidence=0.5,
        )

        pairs = {(c.from_entity.entity_id, c.to_entity.entity_id): c for c in candidates}
        # P-1 matches L-1 on both rules (ceramic in name, performance in desc)
        assert ("P-1", "L-1") in pairs
        assert pairs[("P-1", "L-1")].confidence == 1.0
        ev = pairs[("P-1", "L-1")].evidence
        assert ev["name"]["matched"] is True
        assert ev["desc"]["matched"] is True

        # P-2 matches L-2 on both rules (sport in name, drilled in desc)
        assert ("P-2", "L-2") in pairs
        assert pairs[("P-2", "L-2")].confidence == 1.0

    def test_rule_ordering_does_not_affect_results(self, bf_config: CoreConfig) -> None:
        """Shuffling rule input order produces same candidates and evidence."""
        g = EntityGraph()
        g.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id="P-1",
                properties={"name": "Exact Match", "desc": "Has Ceramic Inside", "sku": "ABC"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Listing",
                entity_id="L-1",
                properties={"title": "exact match", "body": "ceramic", "code": "ABC"},
            )
        )

        rules_order_a = [
            MatchRule(from_property="name", to_property="title", operator="contains"),
            MatchRule(from_property="sku", to_property="code", operator="equals"),
            MatchRule(from_property="desc", to_property="body", operator="contains"),
        ]
        rules_order_b = [
            MatchRule(from_property="sku", to_property="code", operator="equals"),
            MatchRule(from_property="desc", to_property="body", operator="contains"),
            MatchRule(from_property="name", to_property="title", operator="contains"),
        ]

        candidates_a = find_candidates(
            bf_config,
            g,
            "matches",
            "property_match",
            match_rules=rules_order_a,
            min_confidence=0.5,
        )
        candidates_b = find_candidates(
            bf_config,
            g,
            "matches",
            "property_match",
            match_rules=rules_order_b,
            min_confidence=0.5,
        )

        assert len(candidates_a) == len(candidates_b) == 1
        assert candidates_a[0].confidence == candidates_b[0].confidence

        # Evidence keys should be the same (each rule has unique from_property)
        assert set(candidates_a[0].evidence.keys()) == set(candidates_b[0].evidence.keys())
        for key in candidates_a[0].evidence:
            ev_a = candidates_a[0].evidence[key]["matched"]
            ev_b = candidates_b[0].evidence[key]["matched"]
            assert ev_a == ev_b

    def test_duplicate_from_property_evidence_stability(self, bf_config: CoreConfig) -> None:
        """Two rules sharing from_property: last in original order wins."""
        g = EntityGraph()
        g.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id="P-1",
                properties={"name": "StopTech Ceramic"},
            )
        )
        g.add_entity(
            EntityInstance(
                entity_type="Listing",
                entity_id="L-1",
                properties={"title": "ceramic", "body": "stoptech"},
            )
        )

        # Both rules use from_property="name" — last rule in input order wins
        rules = [
            MatchRule(from_property="name", to_property="title", operator="contains"),
            MatchRule(from_property="name", to_property="body", operator="contains"),
        ]

        candidates = find_candidates(
            bf_config,
            g,
            "matches",
            "property_match",
            match_rules=rules,
            min_confidence=0.5,
        )

        assert len(candidates) == 1
        ev = candidates[0].evidence["name"]
        # Last rule (name→body) should overwrite first rule (name→title)
        assert ev["matched"] is True
        assert ev["rule"]["to_property"] == "body"

    def test_brute_force_early_prune_reduces_work(self) -> None:
        """Early-prune correctly filters pairs that can't reach min_confidence."""
        g = EntityGraph()

        # P-below: matches 2/4 rules (below 0.75 threshold)
        g.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id="P-below",
                properties={
                    "name": "alpha widget",
                    "desc": "beta gadget",
                    "sku": "no-match-sku",
                    "color": "no-match-color",
                },
            )
        )
        # P-above: matches 3/4 rules (at 0.75 threshold)
        g.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id="P-above",
                properties={
                    "name": "alpha widget",
                    "desc": "beta gadget",
                    "sku": "gamma-thing",
                    "color": "no-match-color",
                },
            )
        )
        # P-zero: matches 0 rules
        g.add_entity(
            EntityInstance(
                entity_type="Product",
                entity_id="P-zero",
                properties={
                    "name": "xxx",
                    "desc": "yyy",
                    "sku": "zzz",
                    "color": "www",
                },
            )
        )

        g.add_entity(
            EntityInstance(
                entity_type="Listing",
                entity_id="L-1",
                properties={
                    "title": "alpha",
                    "body": "beta",
                    "code": "gamma",
                    "shade": "delta",
                },
            )
        )

        rules = [
            MatchRule(from_property="name", to_property="title", operator="contains"),
            MatchRule(from_property="desc", to_property="body", operator="contains"),
            MatchRule(from_property="sku", to_property="code", operator="contains"),
            MatchRule(from_property="color", to_property="shade", operator="contains"),
        ]

        from_entities = g.list_entities("Product")
        to_entities = g.list_entities("Listing")

        candidates = _property_match_brute_force(
            g,
            "matches",
            from_entities,
            to_entities,
            rules,
            min_confidence=0.75,
            limit=100,
        )

        pair_ids = {c.from_entity.entity_id for c in candidates}
        # P-above (3/4 = 0.75) should be returned
        assert "P-above" in pair_ids
        # P-below (2/4 = 0.5) pruned — can't reach 0.75
        assert "P-below" not in pair_ids
        # P-zero (0/4) pruned immediately
        assert "P-zero" not in pair_ids

        # Verify the surviving candidate has correct confidence and evidence
        above = [c for c in candidates if c.from_entity.entity_id == "P-above"][0]
        assert above.confidence == 0.75
        assert above.evidence["name"]["matched"] is True
        assert above.evidence["desc"]["matched"] is True
        assert above.evidence["sku"]["matched"] is True
        assert above.evidence["color"]["matched"] is False
