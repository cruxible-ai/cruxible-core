"""Tests for config cross-reference validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cruxible_core.config.loader import load_config
from cruxible_core.config.schema import (
    ContractSchema,
    CoreConfig,
    EntityTypeSchema,
    IngestionMapping,
    NamedQuerySchema,
    PropertySchema,
    ProviderArtifactSchema,
    ProviderSchema,
    RelationshipSchema,
    TraversalStep,
    WorkflowSchema,
    WorkflowStepSchema,
    WorkflowTestSchema,
)
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import ConfigError


def _minimal_config(**overrides) -> CoreConfig:
    """Create a minimal valid config with optional overrides."""
    defaults = dict(
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
    defaults.update(overrides)
    return CoreConfig(**defaults)


class TestValidateRelationships:
    def test_valid_relationships(self):
        config = _minimal_config()
        warnings = validate_config(config)
        assert not warnings or all("primary_key" not in w for w in warnings)

    def test_invalid_from_entity(self):
        config = _minimal_config(
            relationships=[
                RelationshipSchema(name="bad", from_entity="Missing", to_entity="B"),
            ]
        )
        with pytest.raises(ConfigError, match="cross-reference"):
            validate_config(config)

    def test_invalid_to_entity(self):
        config = _minimal_config(
            relationships=[
                RelationshipSchema(name="bad", from_entity="A", to_entity="Missing"),
            ]
        )
        with pytest.raises(ConfigError, match="cross-reference"):
            validate_config(config)

    def test_duplicate_relationship_names(self):
        config = _minimal_config(
            relationships=[
                RelationshipSchema(name="links", from_entity="A", to_entity="B"),
                RelationshipSchema(name="links", from_entity="B", to_entity="A"),
            ]
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("Duplicate" in e for e in exc_info.value.errors)


class TestValidateNamedQueries:
    def test_valid_query(self):
        config = _minimal_config(
            named_queries={
                "find_b": NamedQuerySchema(
                    entry_point="A",
                    traversal=[TraversalStep(relationship="links")],
                    returns="list[B]",
                )
            }
        )
        validate_config(config)

    def test_invalid_entry_point(self):
        config = _minimal_config(
            named_queries={
                "bad": NamedQuerySchema(
                    entry_point="Missing",
                    traversal=[TraversalStep(relationship="links")],
                    returns="list[B]",
                )
            }
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("entry_point" in e for e in exc_info.value.errors)

    def test_invalid_traversal_relationship(self):
        config = _minimal_config(
            named_queries={
                "bad": NamedQuerySchema(
                    entry_point="A",
                    traversal=[TraversalStep(relationship="nonexistent")],
                    returns="list[B]",
                )
            }
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("nonexistent" in e for e in exc_info.value.errors)


class TestValidateMultiRelationshipStep:
    def test_multi_relationship_all_valid(self):
        config = _minimal_config(
            named_queries={
                "q": NamedQuerySchema(
                    entry_point="A",
                    traversal=[TraversalStep(relationship=["links"], direction="outgoing")],
                    returns="list[B]",
                )
            }
        )
        validate_config(config)  # should not raise

    def test_multi_relationship_invalid_name(self):
        config = _minimal_config(
            named_queries={
                "q": NamedQuerySchema(
                    entry_point="A",
                    traversal=[
                        TraversalStep(relationship=["links", "bogus"], direction="outgoing")
                    ],
                    returns="list[B]",
                )
            }
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("bogus" in e for e in exc_info.value.errors)

    def test_empty_list_rejected_at_schema(self):
        with pytest.raises(ValidationError):
            TraversalStep(relationship=[], direction="outgoing")


class TestValidateIngestion:
    def test_valid_entity_mapping(self):
        config = _minimal_config(
            ingestion={
                "items": IngestionMapping(entity_type="A", id_column="id"),
            }
        )
        validate_config(config)

    def test_valid_relationship_mapping(self):
        config = _minimal_config(
            ingestion={
                "edges": IngestionMapping(
                    relationship_type="links",
                    from_column="a_id",
                    to_column="b_id",
                ),
            }
        )
        validate_config(config)

    def test_invalid_entity_type(self):
        config = _minimal_config(
            ingestion={
                "bad": IngestionMapping(entity_type="Missing", id_column="id"),
            }
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("Missing" in e for e in exc_info.value.errors)

    def test_invalid_relationship_type(self):
        config = _minimal_config(
            ingestion={
                "bad": IngestionMapping(
                    relationship_type="missing",
                    from_column="a",
                    to_column="b",
                ),
            }
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("missing" in e for e in exc_info.value.errors)


class TestValidatePrimaryKeys:
    def test_errors_on_missing_primary_key(self):
        config = _minimal_config(
            entity_types={
                "NoPK": EntityTypeSchema(properties={"name": PropertySchema(type="string")}),
            },
            relationships=[],
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("primary_key" in e for e in exc_info.value.errors)


class TestValidateWorkflowExecution:
    def _workflow_config(self, **overrides) -> CoreConfig:
        defaults = dict(
            contracts={
                "WorkflowInput": ContractSchema(fields={"id": PropertySchema(type="string")}),
            },
            artifacts={
                "artifact": ProviderArtifactSchema(
                    kind="model", uri="file:///tmp/model", sha256="abc"
                )
            },
            providers={
                "provider": ProviderSchema(
                    kind="function",
                    contract_in="WorkflowInput",
                    contract_out="WorkflowInput",
                    ref="tests.support.workflow_test_providers.lift_predictor",
                    version="1.0.0",
                    artifact="artifact",
                )
            },
            workflows={
                "wf": WorkflowSchema(
                    contract_in="WorkflowInput",
                    steps=[
                        WorkflowStepSchema(
                            id="provider_step",
                            provider="provider",
                            input={"id": "$input.id"},
                            **{"as": "loaded"},
                        )
                    ],
                    returns="loaded",
                )
            },
            tests=[WorkflowTestSchema(name="smoke", workflow="wf", input={"id": "1"})],
        )
        defaults.update(overrides)
        return _minimal_config(**defaults)

    def test_missing_provider_contract(self):
        config = self._workflow_config(contracts={})
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("contract_in" in error for error in exc_info.value.errors)

    def test_missing_provider_artifact(self):
        config = self._workflow_config(
            artifacts={},
            providers={
                "provider": ProviderSchema(
                    kind="function",
                    contract_in="WorkflowInput",
                    contract_out="WorkflowInput",
                    ref="tests.support.workflow_test_providers.lift_predictor",
                    version="1.0.0",
                    artifact="artifact",
                )
            },
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("artifact 'artifact'" in error for error in exc_info.value.errors)

    def test_invalid_workflow_returns_alias(self):
        config = self._workflow_config(
            workflows={
                "wf": WorkflowSchema(
                    contract_in="WorkflowInput",
                    steps=[
                        WorkflowStepSchema(
                            id="provider_step",
                            provider="provider",
                            input={"id": "$input.id"},
                            **{"as": "loaded"},
                        )
                    ],
                    returns="missing",
                )
            }
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("returns alias" in error for error in exc_info.value.errors)

    def test_invalid_workflow_reference_future_alias(self):
        config = self._workflow_config(
            workflows={
                "wf": WorkflowSchema(
                    contract_in="WorkflowInput",
                    steps=[
                        WorkflowStepSchema(
                            id="provider_step",
                            provider="provider",
                            input={"id": "$steps.missing.id"},
                            **{"as": "loaded"},
                        )
                    ],
                    returns="loaded",
                )
            }
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("unknown or future step alias" in error for error in exc_info.value.errors)

    def test_missing_test_workflow(self):
        config = self._workflow_config(tests=[WorkflowTestSchema(name="smoke", workflow="nope")])
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        assert any("workflow 'nope'" in error for error in exc_info.value.errors)


class TestConfigErrorStr:
    def test_str_includes_individual_errors(self):
        config = _minimal_config(
            relationships=[
                RelationshipSchema(name="bad", from_entity="Ghost", to_entity="B"),
            ]
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        text = str(exc_info.value)
        assert "Ghost" in text

    def test_str_includes_all_errors(self):
        config = _minimal_config(
            relationships=[
                RelationshipSchema(name="bad", from_entity="X", to_entity="Y"),
            ]
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_config(config)
        text = str(exc_info.value)
        assert "X" in text
        assert "Y" in text


class TestCarPartsConfig:
    def test_car_parts_validates(self, configs_dir: Path):
        config = load_config(configs_dir / "car_parts.yaml")
        validate_config(config)  # should not raise
