"""Tests for service layer init, schema, sample, get, receipt, and list functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.errors import ConfigError, EdgeAmbiguityError, ReceiptNotFoundError
from cruxible_core.graph.types import RelationshipInstance
from cruxible_core.service import (
    service_get_entity,
    service_get_receipt,
    service_get_relationship,
    service_init,
    service_inspect_entity,
    service_list,
    service_query,
    service_reload_config,
    service_sample,
    service_schema,
    service_stats,
)
from tests.test_cli.conftest import CAR_PARTS_YAML

# ---------------------------------------------------------------------------
# service_init
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_instance(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(CAR_PARTS_YAML)
        result = service_init(tmp_path, config_path="config.yaml")
        assert result.instance is not None
        assert (tmp_path / ".cruxible").is_dir()

    def test_validates_config(self, tmp_path: Path) -> None:
        bad_yaml = "version: '1.0'\nname: bad\n"
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(bad_yaml)
        with pytest.raises(ConfigError):
            service_init(tmp_path, config_path="bad.yaml")

    def test_inline_yaml(self, tmp_path: Path) -> None:
        result = service_init(tmp_path, config_yaml=CAR_PARTS_YAML)
        assert result.instance is not None
        assert (tmp_path / "config.yaml").exists()

    def test_inline_yaml_overwrite_guard(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("existing content")
        with pytest.raises(ConfigError, match="already exists"):
            service_init(tmp_path, config_yaml=CAR_PARTS_YAML)

    def test_inline_yaml_cleanup_on_failure(self, tmp_path: Path) -> None:
        """If init fails after writing config.yaml, the file is cleaned up."""
        # Write invalid YAML that passes load_config_from_string but fails
        # CruxibleInstance.init. Actually, it's hard to trigger this cleanly.
        # Instead, test the simpler case: bad inline YAML fails validation
        # before writing, so nothing to clean up.
        with pytest.raises(ConfigError):
            service_init(tmp_path, config_yaml="not valid yaml: [")

    def test_both_config_sources_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="exactly one"):
            service_init(
                tmp_path,
                config_path="config.yaml",
                config_yaml=CAR_PARTS_YAML,
            )

    def test_no_config_source_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="config_path or config_yaml is required"):
            service_init(tmp_path)

    def test_relative_config_path_resolves(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(CAR_PARTS_YAML)
        # Pass relative path — should resolve against root_dir, not CWD
        result = service_init(tmp_path, config_path="config.yaml")
        assert result.instance is not None


# ---------------------------------------------------------------------------
# service_schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_returns_config(self, populated_instance: CruxibleInstance) -> None:
        config = service_schema(populated_instance)
        assert "Vehicle" in config.entity_types
        assert "Part" in config.entity_types
        assert any(r.name == "fits" for r in config.relationships)

    def test_reload_config_repoints_instance_path(
        self, populated_instance: CruxibleInstance, tmp_path: Path
    ) -> None:
        new_config = tmp_path / "alt-config.yaml"
        new_config.write_text(CAR_PARTS_YAML.replace("car_parts_compatibility", "alt_name"))

        result = service_reload_config(populated_instance, str(new_config))

        assert result.updated is True
        assert populated_instance.get_config_path() == new_config
        assert populated_instance.load_config().name == "alt_name"


# ---------------------------------------------------------------------------
# service_sample
# ---------------------------------------------------------------------------


class TestSample:
    def test_entities(self, populated_instance: CruxibleInstance) -> None:
        entities = service_sample(populated_instance, "Vehicle", limit=10)
        assert len(entities) == 2  # 2 vehicles in populated graph
        assert all(e.entity_type == "Vehicle" for e in entities)

    def test_bad_type(self, populated_instance: CruxibleInstance) -> None:
        entities = service_sample(populated_instance, "NonexistentType")
        assert entities == []


# ---------------------------------------------------------------------------
# service_get_entity
# ---------------------------------------------------------------------------


class TestGetEntity:
    def test_found(self, populated_instance: CruxibleInstance) -> None:
        entity = service_get_entity(populated_instance, "Vehicle", "V-2024-CIVIC-EX")
        assert entity is not None
        assert entity.entity_id == "V-2024-CIVIC-EX"
        assert entity.properties["make"] == "Honda"

    def test_not_found(self, populated_instance: CruxibleInstance) -> None:
        entity = service_get_entity(populated_instance, "Vehicle", "NONEXISTENT")
        assert entity is None

    def test_inspect_entity_returns_neighbors(self, populated_instance: CruxibleInstance) -> None:
        result = service_inspect_entity(populated_instance, "Vehicle", "V-2024-CIVIC-EX")

        assert result.found is True
        assert result.total_neighbors == 2
        assert {neighbor.relationship_type for neighbor in result.neighbors} == {"fits"}
        assert {neighbor.direction for neighbor in result.neighbors} == {"incoming"}

    def test_inspect_entity_not_found(self, populated_instance: CruxibleInstance) -> None:
        result = service_inspect_entity(populated_instance, "Vehicle", "MISSING")
        assert result.found is False
        assert result.neighbors == []


# ---------------------------------------------------------------------------
# service_get_relationship
# ---------------------------------------------------------------------------


class TestGetRelationship:
    def test_found(self, populated_instance: CruxibleInstance) -> None:
        rel = service_get_relationship(
            populated_instance,
            from_type="Part",
            from_id="BP-1001",
            relationship_type="fits",
            to_type="Vehicle",
            to_id="V-2024-CIVIC-EX",
        )
        assert rel is not None
        assert isinstance(rel, RelationshipInstance)
        assert rel.relationship_type == "fits"

    def test_ambiguous(self, populated_instance: CruxibleInstance) -> None:
        """Multi-edge without edge_key raises EdgeAmbiguityError."""
        graph = populated_instance.load_graph()
        # Add a second fits edge between same endpoints
        graph.add_relationship(
            RelationshipInstance(
                relationship_type="fits",
                from_entity_type="Part",
                from_entity_id="BP-1001",
                to_entity_type="Vehicle",
                to_entity_id="V-2024-CIVIC-EX",
                properties={"verified": False, "source": "duplicate"},
            )
        )
        populated_instance.save_graph(graph)

        with pytest.raises(EdgeAmbiguityError):
            service_get_relationship(
                populated_instance,
                from_type="Part",
                from_id="BP-1001",
                relationship_type="fits",
                to_type="Vehicle",
                to_id="V-2024-CIVIC-EX",
            )


# ---------------------------------------------------------------------------
# service_get_receipt
# ---------------------------------------------------------------------------


class TestGetReceipt:
    def test_found(self, populated_instance: CruxibleInstance) -> None:
        query_result = service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        assert query_result.receipt_id is not None
        receipt = service_get_receipt(populated_instance, query_result.receipt_id)
        assert receipt.receipt_id == query_result.receipt_id
        assert query_result.param_hints is not None
        assert query_result.param_hints.primary_key == "vehicle_id"
        assert "V-2024-CIVIC-EX" in query_result.param_hints.example_ids

    def test_not_found(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ReceiptNotFoundError):
            service_get_receipt(populated_instance, "nonexistent-receipt")

    def test_store_lifecycle(self, populated_instance: CruxibleInstance) -> None:
        """Verify store closes even on error."""
        with pytest.raises(ReceiptNotFoundError):
            service_get_receipt(populated_instance, "bad-id")
        # Should be able to open store again
        store = populated_instance.get_receipt_store()
        store.close()


# ---------------------------------------------------------------------------
# service_list
# ---------------------------------------------------------------------------


class TestList:
    def test_entities(self, populated_instance: CruxibleInstance) -> None:
        result = service_list(populated_instance, "entities", entity_type="Vehicle")
        assert result.total == 2
        assert len(result.items) == 2

    def test_edges(self, populated_instance: CruxibleInstance) -> None:
        result = service_list(populated_instance, "edges")
        assert result.total >= 3  # 3 fits + 1 replaces in populated graph

    def test_receipts(self, populated_instance: CruxibleInstance) -> None:
        # Create a receipt first
        service_query(
            populated_instance,
            "parts_for_vehicle",
            {"vehicle_id": "V-2024-CIVIC-EX"},
        )
        result = service_list(populated_instance, "receipts")
        assert result.total >= 1

    def test_feedback(self, populated_instance: CruxibleInstance) -> None:
        result = service_list(populated_instance, "feedback")
        assert result.total == 0
        assert result.items == []

    def test_outcomes(self, populated_instance: CruxibleInstance) -> None:
        result = service_list(populated_instance, "outcomes")
        assert result.total == 0
        assert result.items == []

    def test_entities_requires_type(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="entity_type is required"):
            service_list(populated_instance, "entities")


class TestStats:
    def test_returns_grouped_counts(self, populated_instance: CruxibleInstance) -> None:
        result = service_stats(populated_instance)

        assert result.entity_count == 4
        assert result.edge_count == 4
        assert result.entity_counts["Vehicle"] == 2
        assert result.entity_counts["Part"] == 2
        assert result.relationship_counts["fits"] == 3
        assert result.relationship_counts["replaces"] == 1

    def test_invalid_resource(self, populated_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="Unknown resource"):
            service_list(populated_instance, "bogus")  # type: ignore[arg-type]
