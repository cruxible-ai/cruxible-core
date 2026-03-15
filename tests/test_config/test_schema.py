"""Tests for config schema Pydantic models."""

import pytest
from pydantic import ValidationError

from cruxible_core.config.loader import load_config_from_string, save_config
from cruxible_core.config.schema import (
    ConstraintSchema,
    CoreConfig,
    EntityTypeSchema,
    IntegrationConfig,
    IngestionMapping,
    IntegrationSpec,
    MatchingConfig,
    NamedQuerySchema,
    PropertySchema,
    RelationshipSchema,
    TraversalStep,
)
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import ConfigError


class TestPropertySchema:
    def test_minimal(self):
        prop = PropertySchema(type="string")
        assert prop.type == "string"
        assert prop.primary_key is False
        assert prop.optional is False
        assert prop.enum is None

    def test_full(self):
        prop = PropertySchema(
            type="string",
            primary_key=True,
            indexed=True,
            enum=["a", "b"],
            description="test",
        )
        assert prop.primary_key is True
        assert prop.indexed is True
        assert prop.enum == ["a", "b"]


class TestEntityTypeSchema:
    def test_get_primary_key(self):
        entity = EntityTypeSchema(
            properties={
                "id": PropertySchema(type="string", primary_key=True),
                "name": PropertySchema(type="string"),
            }
        )
        assert entity.get_primary_key() == "id"

    def test_no_primary_key(self):
        entity = EntityTypeSchema(properties={"name": PropertySchema(type="string")})
        assert entity.get_primary_key() is None


class TestRelationshipSchema:
    def test_from_alias(self):
        """Relationship uses 'from'/'to' in YAML but from_entity/to_entity in Python."""
        rel = RelationshipSchema(
            name="fits",
            **{"from": "Part", "to": "Vehicle"},
        )
        assert rel.from_entity == "Part"
        assert rel.to_entity == "Vehicle"

    def test_populate_by_name(self):
        rel = RelationshipSchema(
            name="fits",
            from_entity="Part",
            to_entity="Vehicle",
        )
        assert rel.from_entity == "Part"

    def test_defaults(self):
        rel = RelationshipSchema(name="r", from_entity="A", to_entity="B")
        assert rel.cardinality == "many_to_many"
        assert rel.properties == {}
        assert rel.inverse is None
        assert rel.is_hierarchy is False


class TestTraversalStep:
    def test_defaults(self):
        step = TraversalStep(relationship="fits")
        assert step.direction == "outgoing"
        assert step.filter is None
        assert step.constraint is None
        assert step.max_depth == 1

    def test_full(self):
        step = TraversalStep(
            relationship="fits",
            direction="incoming",
            filter={"verified": True},
            constraint="target.year >= 2020",
            max_depth=2,
        )
        assert step.direction == "incoming"
        assert step.filter == {"verified": True}


class TestNamedQuerySchema:
    def test_minimal(self):
        query = NamedQuerySchema(
            entry_point="Vehicle",
            traversal=[TraversalStep(relationship="fits", direction="incoming")],
            returns="list[Part]",
        )
        assert query.entry_point == "Vehicle"
        assert len(query.traversal) == 1

    def test_multi_step(self):
        query = NamedQuerySchema(
            entry_point="Part",
            traversal=[
                TraversalStep(relationship="replaces", direction="outgoing"),
                TraversalStep(relationship="fits", direction="outgoing"),
            ],
            returns="list[Part]",
        )
        assert len(query.traversal) == 2


class TestConstraintSchema:
    def test_defaults(self):
        c = ConstraintSchema(name="test", rule="a == b")
        assert c.severity == "warning"

    def test_error_severity(self):
        c = ConstraintSchema(name="test", rule="a == b", severity="error")
        assert c.severity == "error"


class TestIngestionMapping:
    def test_entity_mapping(self):
        m = IngestionMapping(entity_type="Part", id_column="part_number")
        assert m.is_entity is True
        assert m.is_relationship is False

    def test_relationship_mapping(self):
        m = IngestionMapping(
            relationship_type="fits",
            from_column="part_number",
            to_column="vehicle_id",
        )
        assert m.is_entity is False
        assert m.is_relationship is True

    def test_neither_set_fails(self):
        with pytest.raises(ValidationError, match="Exactly one"):
            IngestionMapping()

    def test_both_set_fails(self):
        with pytest.raises(ValidationError, match="Exactly one"):
            IngestionMapping(
                entity_type="Part",
                relationship_type="fits",
                id_column="id",
                from_column="a",
                to_column="b",
            )

    def test_entity_without_id_column_fails(self):
        with pytest.raises(ValidationError, match="id_column"):
            IngestionMapping(entity_type="Part")

    def test_relationship_without_columns_fails(self):
        with pytest.raises(ValidationError, match="from_column"):
            IngestionMapping(relationship_type="fits")

    def test_column_map(self):
        m = IngestionMapping(
            entity_type="Part",
            id_column="pn",
            column_map={"part_name": "name", "cat": "category"},
        )
        assert m.column_map["part_name"] == "name"

    def test_description(self):
        m = IngestionMapping(
            description="CSV of SDN entities with sdn_id, name, country columns",
            entity_type="SDNEntity",
            id_column="sdn_id",
        )
        assert m.description == "CSV of SDN entities with sdn_id, name, country columns"
        dumped = m.model_dump(exclude_none=True)
        assert dumped["description"] == m.description


class TestCoreConfig:
    def test_minimal_config(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "Thing": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                )
            },
            relationships=[],
        )
        assert config.name == "test"
        assert config.version == "1.0"
        assert config.named_queries == {}
        assert config.constraints == []
        assert config.ingestion == {}

    def test_get_relationship(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "A": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
                "B": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
            },
            relationships=[
                RelationshipSchema(name="links", from_entity="A", to_entity="B"),
            ],
        )
        assert config.get_relationship("links") is not None
        assert config.get_relationship("missing") is None

    def test_get_entity_type(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "Thing": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                )
            },
            relationships=[],
        )
        assert config.get_entity_type("Thing") is not None
        assert config.get_entity_type("Missing") is None

    def test_get_hierarchy_relationships(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "A": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
                "B": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
            },
            relationships=[
                RelationshipSchema(
                    name="parent_of", from_entity="A", to_entity="A", is_hierarchy=True
                ),
                RelationshipSchema(name="links", from_entity="A", to_entity="B"),
            ],
        )
        hierarchy = config.get_hierarchy_relationships()
        assert len(hierarchy) == 1
        assert hierarchy[0].name == "parent_of"

    def test_get_hierarchy_relationships_empty(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "A": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
            },
            relationships=[
                RelationshipSchema(name="links", from_entity="A", to_entity="A"),
            ],
        )
        assert config.get_hierarchy_relationships() == []

    def test_integrations_default_empty(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "A": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
            },
            relationships=[],
        )
        assert config.integrations == {}


# ---------------------------------------------------------------------------
# IntegrationSpec + IntegrationConfig + MatchingConfig
# ---------------------------------------------------------------------------


class TestIntegrationSpec:
    def test_basic(self):
        spec = IntegrationSpec(
            kind="vector_similarity",
            contract={"model_ref": "text-embed-3-large", "metric": "cosine"},
            notes="semantic similarity",
        )
        assert spec.kind == "vector_similarity"
        assert spec.contract["metric"] == "cosine"

    def test_defaults(self):
        spec = IntegrationSpec(kind="test")
        assert spec.contract == {}
        assert spec.notes == ""

    def test_non_serializable_contract_fails(self):
        with pytest.raises(ValidationError, match="JSON-serializable"):
            IntegrationSpec(kind="test", contract={"bad": object()})


class TestIntegrationConfig:
    def test_defaults(self):
        cfg = IntegrationConfig()
        assert cfg.role == "required"
        assert cfg.always_review_on_unsure is False
        assert cfg.note == ""

    def test_all_roles(self):
        for role in ("blocking", "required", "advisory"):
            cfg = IntegrationConfig(role=role)
            assert cfg.role == role


class TestMatchingConfig:
    def test_defaults(self):
        cfg = MatchingConfig()
        assert cfg.integrations == {}
        assert cfg.auto_resolve_when == "all_support"
        assert cfg.auto_resolve_requires_prior_trust == "trusted_only"
        assert cfg.max_group_size == 1000

    def test_full(self):
        cfg = MatchingConfig(
            integrations={
                "bolt_check": IntegrationConfig(role="blocking"),
                "style_v1": IntegrationConfig(role="advisory"),
            },
            auto_resolve_when="no_contradict",
            auto_resolve_requires_prior_trust="trusted_or_watch",
            max_group_size=200,
        )
        assert len(cfg.integrations) == 2
        assert cfg.integrations["bolt_check"].role == "blocking"


class TestRelationshipSchemaMatching:
    def test_matching_default_none(self):
        rel = RelationshipSchema(name="r", from_entity="A", to_entity="B")
        assert rel.matching is None

    def test_matching_section(self):
        rel = RelationshipSchema(
            name="fits",
            from_entity="Part",
            to_entity="Vehicle",
            matching=MatchingConfig(
                integrations={"bolt": IntegrationConfig(role="blocking")},
                max_group_size=100,
            ),
        )
        assert rel.matching is not None
        assert rel.matching.max_group_size == 100


class TestStrictMixedMode:
    """Non-empty global registry requires all matching.integrations keys to resolve."""

    def _config(self, *, integrations=None, matching=None):
        return CoreConfig(
            name="test",
            entity_types={
                "A": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
                "B": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                ),
            },
            relationships=[
                RelationshipSchema(
                    name="links",
                    from_entity="A",
                    to_entity="B",
                    matching=matching,
                ),
            ],
            integrations=integrations or {},
        )

    def test_empty_registry_bare_labels_ok(self):
        """Empty global registry = open mode, bare labels allowed."""
        config = self._config(
            matching=MatchingConfig(
                integrations={"some_label": IntegrationConfig(role="blocking")}
            ),
        )
        # Should not raise
        validate_config(config)

    def test_nonempty_registry_all_resolved_ok(self):
        config = self._config(
            integrations={"bolt_v1": IntegrationSpec(kind="physical")},
            matching=MatchingConfig(
                integrations={"bolt_v1": IntegrationConfig(role="blocking")}
            ),
        )
        validate_config(config)

    def test_nonempty_registry_unresolved_key_error(self):
        config = self._config(
            integrations={"bolt_v1": IntegrationSpec(kind="physical")},
            matching=MatchingConfig(
                integrations={"unknown": IntegrationConfig(role="blocking")}
            ),
        )
        with pytest.raises(ConfigError, match="not found in global integrations"):
            validate_config(config)

    def test_no_matching_section_ok(self):
        """Matching=None is always fine."""
        config = self._config(
            integrations={"bolt_v1": IntegrationSpec(kind="physical")},
            matching=None,
        )
        validate_config(config)


class TestMatchingConfigRoundTrip:
    """Load -> save -> load preserves integrations + matching."""

    def test_round_trip(self, tmp_path):
        yaml_str = """\
version: "1.0"
name: test_matching
entity_types:
  Shoe:
    properties:
      id:
        type: string
        primary_key: true
  Outfit:
    properties:
      id:
        type: string
        primary_key: true
integrations:
  cosine_v1:
    kind: vector_similarity
    contract:
      model_ref: text-embed-3-large
    notes: semantic similarity
relationships:
  - name: fits
    from: Shoe
    to: Outfit
    matching:
      integrations:
        cosine_v1:
          role: blocking
          always_review_on_unsure: true
          note: authoritative
      auto_resolve_when: no_contradict
      max_group_size: 200
"""
        config = load_config_from_string(yaml_str)
        assert config.integrations["cosine_v1"].kind == "vector_similarity"
        rel = config.get_relationship("fits")
        assert rel is not None
        assert rel.matching is not None
        assert rel.matching.integrations["cosine_v1"].role == "blocking"
        assert rel.matching.auto_resolve_when == "no_contradict"
        assert rel.matching.max_group_size == 200

        # Save and reload
        path = tmp_path / "config.yaml"
        save_config(config, path)
        config2 = load_config_from_string(path.read_text())
        rel2 = config2.get_relationship("fits")
        assert rel2 is not None
        assert rel2.matching is not None
        assert rel2.matching.integrations["cosine_v1"].role == "blocking"
        assert rel2.matching.integrations["cosine_v1"].always_review_on_unsure is True
        assert config2.integrations["cosine_v1"].contract["model_ref"] == "text-embed-3-large"
