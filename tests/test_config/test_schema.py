"""Tests for config schema Pydantic models."""

import pytest
from pydantic import ValidationError

from cruxible_core.config.loader import load_config_from_string, save_config
from cruxible_core.config.schema import (
    AssertSpec,
    BoundsQualityCheck,
    CardinalityQualityCheck,
    ConstraintSchema,
    ContractSchema,
    CoreConfig,
    EntityTypeSchema,
    IngestionMapping,
    IntegrationConfig,
    IntegrationSpec,
    JsonContentQualityCheck,
    MatchingConfig,
    NamedQuerySchema,
    PropertyQualityCheck,
    PropertySchema,
    ProviderArtifactSchema,
    ProviderSchema,
    RelationshipSchema,
    TraversalStep,
    UniquenessQualityCheck,
    WorkflowSchema,
    WorkflowStepSchema,
    WorkflowTestExpectSchema,
    WorkflowTestSchema,
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

    def test_json_schema_allowed_for_json_type(self):
        prop = PropertySchema(
            type="json",
            json_schema={"type": "array", "items": {"type": "object"}},
        )
        assert prop.json_schema == {"type": "array", "items": {"type": "object"}}

    def test_json_schema_rejected_for_non_json_type(self):
        with pytest.raises(ValidationError, match="json_schema is only allowed"):
            PropertySchema(type="string", json_schema={"type": "string"})


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


class TestQualityCheckSchema:
    def test_property_check_parses(self):
        check = PropertyQualityCheck(
            name="non_empty_name",
            target="entity",
            entity_type="Vendor",
            property="name",
            rule="non_empty",
        )
        assert check.kind == "property"

    def test_json_content_check_parses(self):
        check = JsonContentQualityCheck(
            name="no_empty_json",
            target="relationship",
            relationship_type="vulnerability_affects_product",
            property="affected_versions",
            rule="no_empty_objects_in_array",
        )
        assert check.kind == "json_content"

    def test_uniqueness_requires_properties(self):
        with pytest.raises(ValidationError, match="at least one property"):
            UniquenessQualityCheck(name="unique", entity_type="Product", properties=[])

    def test_bounds_requires_a_limit(self):
        with pytest.raises(ValidationError, match="min_count, max_count, or both"):
            BoundsQualityCheck(name="bounds", target="entity_count", entity_type="Product")

    def test_cardinality_requires_a_limit(self):
        with pytest.raises(ValidationError, match="min_count, max_count, or both"):
            CardinalityQualityCheck(
                name="cardinality",
                entity_type="Product",
                relationship_type="product_from_vendor",
                direction="outgoing",
            )


class TestWorkflowSchema:
    def test_query_step_requires_alias(self):
        with pytest.raises(ValidationError, match="require 'as'"):
            WorkflowStepSchema(id="context", query="get_context")

    def test_provider_step_forbids_params(self):
        with pytest.raises(ValidationError, match="may not define 'params'"):
            WorkflowStepSchema(
                id="lift",
                provider="predictor",
                params={"sku": "x"},
                input={"sku": "x"},
                **{"as": "lift"},
            )

    def test_assert_step_shape(self):
        step = WorkflowStepSchema(
            id="gate",
            **{
                "assert": AssertSpec(left="$steps.score", op="gte", right=0.5, message="Too low"),
            },
        )
        assert step.assert_spec is not None
        assert step.assert_spec.op == "gte"

    def test_workflow_requires_contract_in(self):
        workflow = WorkflowSchema(
            contract_in="PromoInput",
            steps=[
                WorkflowStepSchema(
                    id="context",
                    query="get_context",
                    params={"sku": "$input.sku"},
                    **{"as": "context"},
                )
            ],
            returns="context",
        )
        assert workflow.contract_in == "PromoInput"

    def test_make_candidates_step_accepts_item_refs(self):
        step = WorkflowStepSchema(
            id="candidates",
            make_candidates={
                "relationship_type": "recommended_for",
                "items": "$steps.rows.items",
                "from_type": "Campaign",
                "from_id": "$input.campaign_id",
                "to_type": "Product",
                "to_id": "$item.product_sku",
                "properties": {"reason": "$item.reason"},
            },
            **{"as": "candidates"},
        )
        assert step.make_candidates is not None
        assert step.make_candidates.relationship_type == "recommended_for"

    def test_list_entities_step_accepts_property_filter_refs(self):
        step = WorkflowStepSchema(
            id="products",
            list_entities={
                "entity_type": "Product",
                "property_filter": {"category": "$input.category"},
                "limit": 5,
            },
            **{"as": "products"},
        )
        assert step.list_entities is not None
        assert step.list_entities.entity_type == "Product"

    def test_list_relationships_step_accepts_property_filter_refs(self):
        step = WorkflowStepSchema(
            id="links",
            list_relationships={
                "relationship_type": "recommended_for",
                "property_filter": {"review_status": "$input.status"},
            },
            **{"as": "links"},
        )
        assert step.list_relationships is not None
        assert step.list_relationships.relationship_type == "recommended_for"

    def test_map_signals_requires_exactly_one_mapping_mode(self):
        with pytest.raises(ValidationError, match="exactly one of 'score' or 'enum'"):
            WorkflowStepSchema(
                id="catalog_signals",
                map_signals={
                    "integration": "catalog",
                    "items": "$steps.rows.items",
                    "from_id": "$input.campaign_id",
                    "to_id": "$item.product_sku",
                },
                **{"as": "signals"},
            )

    def test_propose_relationship_group_step_accepts_signal_aliases(self):
        step = WorkflowStepSchema(
            id="proposal",
            propose_relationship_group={
                "relationship_type": "recommended_for",
                "candidates_from": "candidates",
                "signals_from": ["catalog_signals"],
                "thesis_text": "Recommend products for campaign",
            },
            **{"as": "proposal"},
        )
        assert step.propose_relationship_group is not None
        assert step.propose_relationship_group.signals_from == ["catalog_signals"]

    def test_workflow_rejects_removed_proposal_output(self):
        with pytest.raises(ValidationError, match="proposal_output"):
            WorkflowSchema(
                contract_in="PromoInput",
                steps=[
                    WorkflowStepSchema(
                        id="recommend",
                        provider="recommender",
                        input={"sku": "$input.sku"},
                        **{"as": "recommendations"},
                    )
                ],
                returns="recommendations",
                proposal_output={
                    "kind": "relationship_group",
                    "relationship_type": "recommended_for",
                },
            )


class TestWorkflowTests:
    def test_expectation_normalizes_provider_list(self):
        expect = WorkflowTestExpectSchema(receipt_contains_provider="lift_predictor")
        assert expect.required_providers == ["lift_predictor"]

    def test_workflow_test_schema(self):
        test_case = WorkflowTestSchema(
            name="smoke",
            workflow="evaluate_promo",
            input={"sku": "SKU-1"},
        )
        assert test_case.name == "smoke"
        assert test_case.expect.required_providers == []


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
        assert config.kind == "world_model"
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

    def test_execution_sections_default_empty(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "Thing": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                )
            },
            relationships=[],
        )
        assert config.contracts == {}
        assert config.artifacts == {}
        assert config.providers == {}
        assert config.workflows == {}
        assert config.tests == []

    def test_execution_sections_round_trip(self):
        config = CoreConfig(
            name="test",
            entity_types={
                "Thing": EntityTypeSchema(
                    properties={"id": PropertySchema(type="string", primary_key=True)}
                )
            },
            relationships=[],
            contracts={"ThingInput": ContractSchema(fields={"id": PropertySchema(type="string")})},
            artifacts={
                "artifact": ProviderArtifactSchema(
                    kind="model", uri="file:///tmp/model", sha256="abc"
                )
            },
            providers={
                "loader": ProviderSchema(
                    kind="function",
                    contract_in="ThingInput",
                    contract_out="ThingInput",
                    ref="tests.support.workflow_test_providers.lift_predictor",
                    version="1.0.0",
                )
            },
            workflows={
                "wf": WorkflowSchema(
                    contract_in="ThingInput",
                    steps=[
                        WorkflowStepSchema(
                            id="load",
                            provider="loader",
                            input={"id": "$input.id"},
                            **{"as": "loaded"},
                        )
                    ],
                    returns="loaded",
                )
            },
            tests=[WorkflowTestSchema(name="smoke", workflow="wf", input={"id": "1"})],
        )
        assert "ThingInput" in config.contracts
        assert "artifact" in config.artifacts
        assert "loader" in config.providers
        assert "wf" in config.workflows
        assert config.tests[0].name == "smoke"


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
            matching=MatchingConfig(integrations={"bolt_v1": IntegrationConfig(role="blocking")}),
        )
        validate_config(config)

    def test_nonempty_registry_unresolved_key_error(self):
        config = self._config(
            integrations={"bolt_v1": IntegrationSpec(kind="physical")},
            matching=MatchingConfig(integrations={"unknown": IntegrationConfig(role="blocking")}),
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


class TestQualityCheckValidation:
    def _config(self, *, quality_checks):
        return CoreConfig(
            name="quality_validation",
            entity_types={
                "Vendor": EntityTypeSchema(
                    properties={
                        "vendor_id": PropertySchema(type="string", primary_key=True),
                        "name": PropertySchema(type="string"),
                    }
                ),
                "Product": EntityTypeSchema(
                    properties={
                        "product_id": PropertySchema(type="string", primary_key=True),
                        "vendor_name": PropertySchema(type="string"),
                    }
                ),
            },
            relationships=[
                RelationshipSchema(
                    name="product_from_vendor",
                    from_entity="Product",
                    to_entity="Vendor",
                    properties={
                        "affected_versions": PropertySchema(type="json", optional=True),
                    },
                )
            ],
            quality_checks=quality_checks,
        )

    def test_duplicate_quality_check_names_rejected(self):
        config = self._config(
            quality_checks=[
                PropertyQualityCheck(
                    name="dup",
                    target="entity",
                    entity_type="Vendor",
                    property="name",
                    rule="non_empty",
                ),
                PropertyQualityCheck(
                    name="dup",
                    target="entity",
                    entity_type="Vendor",
                    property="name",
                    rule="required",
                ),
            ]
        )
        with pytest.raises(ConfigError, match="Duplicate quality check name"):
            validate_config(config)

    def test_json_content_requires_json_property(self):
        config = self._config(
            quality_checks=[
                JsonContentQualityCheck(
                    name="bad_json",
                    target="entity",
                    entity_type="Vendor",
                    property="name",
                    rule="no_empty_objects_in_array",
                )
            ]
        )
        with pytest.raises(ConfigError, match="requires property 'name' to have type 'json'"):
            validate_config(config)

    def test_cardinality_requires_compatible_direction(self):
        config = self._config(
            quality_checks=[
                CardinalityQualityCheck(
                    name="bad_cardinality",
                    entity_type="Vendor",
                    relationship_type="product_from_vendor",
                    direction="outgoing",
                    min_count=1,
                )
            ]
        )
        with pytest.raises(ConfigError, match="requires entity_type 'Product'"):
            validate_config(config)
