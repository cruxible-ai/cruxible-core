"""Tests for service layer mutation functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.errors import ConfigError, DataValidationError
from cruxible_core.graph.types import EntityInstance, RelationshipInstance
from cruxible_core.service import (
    service_add_entities,
    service_add_relationships,
    service_ingest,
)


def _vehicle(
    vid: str, year: int = 2024, make: str = "Honda", model: str = "Civic"
) -> EntityInstance:
    return EntityInstance(
        entity_type="Vehicle",
        entity_id=vid,
        properties={"vehicle_id": vid, "year": year, "make": make, "model": model},
    )


def _part(pid: str, name: str = "Pads", category: str = "brakes") -> EntityInstance:
    return EntityInstance(
        entity_type="Part",
        entity_id=pid,
        properties={"part_number": pid, "name": name, "category": category},
    )


# ---------------------------------------------------------------------------
# service_add_entities
# ---------------------------------------------------------------------------


class TestAddEntities:
    def test_single(self, initialized_instance: CruxibleInstance) -> None:
        result = service_add_entities(initialized_instance, [_vehicle("V-1")])
        assert result.added == 1
        assert result.updated == 0

        graph = initialized_instance.load_graph()
        entity = graph.get_entity("Vehicle", "V-1")
        assert entity is not None
        assert entity.properties["make"] == "Honda"

    def test_batch(self, initialized_instance: CruxibleInstance) -> None:
        entities = [
            _vehicle("V-1"),
            _vehicle("V-2", make="Toyota", model="Camry"),
            _part("BP-1"),
        ]
        result = service_add_entities(initialized_instance, entities)
        assert result.added == 3
        assert result.updated == 0

    def test_dedup_error(self, initialized_instance: CruxibleInstance) -> None:
        entities = [_vehicle("V-1"), _vehicle("V-1", year=2025)]
        with pytest.raises(DataValidationError, match="duplicate in batch"):
            service_add_entities(initialized_instance, entities)

    def test_bad_type(self, initialized_instance: CruxibleInstance) -> None:
        with pytest.raises(DataValidationError, match="not found in config"):
            service_add_entities(
                initialized_instance,
                [EntityInstance(entity_type="Spaceship", entity_id="X-1")],
            )

    def test_update(self, populated_instance: CruxibleInstance) -> None:
        result = service_add_entities(
            populated_instance,
            [_vehicle("V-2024-CIVIC-EX", year=2025)],
        )
        assert result.added == 0
        assert result.updated == 1

        graph = populated_instance.load_graph()
        entity = graph.get_entity("Vehicle", "V-2024-CIVIC-EX")
        assert entity is not None
        assert entity.properties["year"] == 2025


# ---------------------------------------------------------------------------
# service_add_relationships
# ---------------------------------------------------------------------------


class TestAddRelationships:
    def test_single(self, populated_instance: CruxibleInstance) -> None:
        result = service_add_relationships(
            populated_instance,
            [
                RelationshipInstance(
                    from_type="Part",
                    from_id="BP-1002",
                    relationship="fits",
                    to_type="Vehicle",
                    to_id="V-2024-ACCORD-SPORT",
                    properties={"verified": True},
                )
            ],
            source="test",
            source_ref="test_single",
        )
        assert result.added == 1
        assert result.updated == 0

        graph = populated_instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1002", "Vehicle", "V-2024-ACCORD-SPORT", "fits")
        assert rel is not None
        assert rel.properties.get("_provenance") is not None

    def test_batch(self, populated_instance: CruxibleInstance) -> None:
        result = service_add_relationships(
            populated_instance,
            [
                RelationshipInstance(
                    from_type="Part",
                    from_id="BP-1002",
                    relationship="fits",
                    to_type="Vehicle",
                    to_id="V-2024-ACCORD-SPORT",
                    properties={"verified": True},
                ),
                RelationshipInstance(
                    from_type="Part",
                    from_id="BP-1001",
                    relationship="replaces",
                    to_type="Part",
                    to_id="BP-1002",
                    properties={"direction": "downgrade", "confidence": 0.8},
                ),
            ],
            source="test",
            source_ref="test_batch",
        )
        assert result.added == 2
        assert result.updated == 0

    def test_dedup_error(self, populated_instance: CruxibleInstance) -> None:
        edges = [
            RelationshipInstance(
                from_type="Part",
                from_id="BP-1002",
                relationship="fits",
                to_type="Vehicle",
                to_id="V-2024-ACCORD-SPORT",
            ),
            RelationshipInstance(
                from_type="Part",
                from_id="BP-1002",
                relationship="fits",
                to_type="Vehicle",
                to_id="V-2024-ACCORD-SPORT",
            ),
        ]
        with pytest.raises(DataValidationError, match="duplicate in batch"):
            service_add_relationships(populated_instance, edges, source="test", source_ref="test")

    def test_source_provenance(self, populated_instance: CruxibleInstance) -> None:
        service_add_relationships(
            populated_instance,
            [
                RelationshipInstance(
                    from_type="Part",
                    from_id="BP-1002",
                    relationship="fits",
                    to_type="Vehicle",
                    to_id="V-2024-ACCORD-SPORT",
                )
            ],
            source="agent_review",
            source_ref="review-123",
        )
        graph = populated_instance.load_graph()
        rel = graph.get_relationship("Part", "BP-1002", "Vehicle", "V-2024-ACCORD-SPORT", "fits")
        assert rel is not None
        prov = rel.properties["_provenance"]
        assert prov["source"] == "agent_review"
        assert prov["source_ref"] == "review-123"


# ---------------------------------------------------------------------------
# service_ingest
# ---------------------------------------------------------------------------


class TestIngest:
    def test_file(self, initialized_instance: CruxibleInstance, tmp_project: Path) -> None:
        csv_path = tmp_project / "vehicles.csv"
        csv_path.write_text(
            "vehicle_id,year,make,model\n"
            "V-2024-CIVIC-EX,2024,Honda,Civic\n"
            "V-2024-ACCORD-SPORT,2024,Honda,Accord\n"
        )
        result = service_ingest(initialized_instance, "vehicles", file_path=str(csv_path))
        assert result.records_ingested == 2
        assert result.mapping == "vehicles"
        assert result.entity_type == "Vehicle"

    def test_csv_string(self, initialized_instance: CruxibleInstance) -> None:
        csv_data = "vehicle_id,year,make,model\nV-2024-CIVIC-EX,2024,Honda,Civic\n"
        result = service_ingest(initialized_instance, "vehicles", data_csv=csv_data)
        assert result.records_ingested == 1
        assert result.entity_type == "Vehicle"

    def test_no_source_error(self, initialized_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="Provide exactly one"):
            service_ingest(initialized_instance, "vehicles")

    def test_multi_source_error(self, initialized_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="Provide exactly one"):
            service_ingest(
                initialized_instance,
                "vehicles",
                file_path="/some/file.csv",
                data_csv="a,b\n1,2",
            )

    def test_upload_id_rejected(self, initialized_instance: CruxibleInstance) -> None:
        with pytest.raises(ConfigError, match="upload_id is not supported"):
            service_ingest(initialized_instance, "vehicles", upload_id="upload-123")

    def test_json_rows_list(self, initialized_instance: CruxibleInstance) -> None:
        """Pre-parsed list[dict] (MCP pass-through) ingests correctly."""
        rows = [
            {
                "vehicle_id": "V-2024-CIVIC-EX",
                "year": 2024,
                "make": "Honda",
                "model": "Civic",
            },
            {
                "vehicle_id": "V-2024-ACCORD-SPORT",
                "year": 2024,
                "make": "Honda",
                "model": "Accord",
            },
        ]
        result = service_ingest(initialized_instance, "vehicles", data_json=rows)
        assert result.records_ingested == 2
        assert result.entity_type == "Vehicle"

        graph = initialized_instance.load_graph()
        assert graph.get_entity("Vehicle", "V-2024-CIVIC-EX") is not None
        assert graph.get_entity("Vehicle", "V-2024-ACCORD-SPORT") is not None
