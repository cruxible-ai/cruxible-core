"""Tests for config schema Pydantic models."""

import pytest
from pydantic import ValidationError

from cruxible_core.config.schema import (
    ConstraintSchema,
    CoreConfig,
    EntityTypeSchema,
    IngestionMapping,
    NamedQuerySchema,
    PropertySchema,
    RelationshipSchema,
    TraversalStep,
)


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
