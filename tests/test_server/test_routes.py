"""Tests for FastAPI server routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cruxible_core.errors import ConstraintViolationError, InstanceNotFoundError
from cruxible_core.mcp.handlers import get_manager, reset_client_cache
from cruxible_core.mcp.permissions import reset_permissions
from cruxible_core.server.app import create_app
from cruxible_core.server.registry import reset_registry
from cruxible_core.server.routes import resolve_server_instance_id
from tests.test_cli.conftest import CAR_PARTS_YAML


@pytest.fixture
def server_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "config.yaml").write_text(CAR_PARTS_YAML)
    return root


@pytest.fixture
def vehicles_csv(server_project: Path) -> Path:
    csv_path = server_project / "vehicles.csv"
    csv_path.write_text(
        "vehicle_id,year,make,model\n"
        "V-2024-CIVIC-EX,2024,Honda,Civic\n"
        "V-2024-ACCORD-SPORT,2024,Honda,Accord\n"
    )
    return csv_path


@pytest.fixture
def parts_csv(server_project: Path) -> Path:
    csv_path = server_project / "parts.csv"
    csv_path.write_text(
        "part_number,name,category,price\n"
        "BP-1001,Ceramic Brake Pads,brakes,49.99\n"
        "BP-1002,Performance Brake Pads,brakes,89.99\n"
    )
    return csv_path


@pytest.fixture
def fitments_csv(server_project: Path) -> Path:
    csv_path = server_project / "fitments.csv"
    csv_path.write_text(
        "part_number,vehicle_id,verified,source\n"
        "BP-1001,V-2024-CIVIC-EX,true,catalog\n"
        "BP-1001,V-2024-ACCORD-SPORT,true,catalog\n"
        "BP-1002,V-2024-CIVIC-EX,true,user_report\n"
    )
    return csv_path


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CRUXIBLE_SERVER_STATE_DIR", str(tmp_path / "server-state"))
    reset_permissions()
    reset_registry()
    reset_client_cache()
    get_manager().clear()
    app = create_app()
    return TestClient(app)


def _init_instance(client: TestClient, root: Path) -> str:
    response = client.post(
        "/api/v1/instances",
        json={"root_dir": str(root), "config_path": "config.yaml"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["instance_id"] != str(root)
    return payload["instance_id"]


def test_health_endpoint_returns_ok(app_client: TestClient):
    response = app_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_init_then_ingest_then_query_round_trip(
    app_client: TestClient,
    server_project: Path,
    vehicles_csv: Path,
    parts_csv: Path,
    fitments_csv: Path,
):
    instance_id = _init_instance(app_client, server_project)

    for mapping, csv_path in [
        ("vehicles", vehicles_csv),
        ("parts", parts_csv),
        ("fitments", fitments_csv),
    ]:
        with csv_path.open("rb") as handle:
            response = app_client.post(
                f"/api/v1/{instance_id}/ingest",
                data={"mapping_name": mapping},
                files={"file": (csv_path.name, handle, "text/csv")},
            )
        assert response.status_code == 200

    response = app_client.post(
        f"/api/v1/{instance_id}/query",
        json={
            "query_name": "parts_for_vehicle",
            "params": {"vehicle_id": "V-2024-CIVIC-EX"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_results"] == 2
    assert payload["receipt_id"]


def test_repeated_init_returns_same_opaque_id(app_client: TestClient, server_project: Path):
    first = _init_instance(app_client, server_project)
    second = app_client.post("/api/v1/instances", json={"root_dir": str(server_project)}).json()
    assert second["instance_id"] == first
    assert second["status"] == "loaded"


def test_add_entity_returns_contract_shape(app_client: TestClient, server_project: Path):
    instance_id = _init_instance(app_client, server_project)
    response = app_client.post(
        f"/api/v1/{instance_id}/entities",
        json={
            "entities": [
                {
                    "entity_type": "Vehicle",
                    "entity_id": "V-1",
                    "properties": {
                        "vehicle_id": "V-1",
                        "year": 2024,
                        "make": "Honda",
                        "model": "Civic",
                    },
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["entities_added"] == 1


def test_permission_denied_returns_structured_403(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    server_project: Path,
):
    monkeypatch.setenv("CRUXIBLE_SERVER_STATE_DIR", str(tmp_path / "server-state"))
    reset_permissions()
    reset_registry()
    reset_client_cache()
    get_manager().clear()
    admin_client = TestClient(create_app())
    instance_id = _init_instance(admin_client, server_project)

    monkeypatch.setenv("CRUXIBLE_MODE", "read_only")
    reset_permissions()
    reset_client_cache()
    get_manager().clear()
    client = TestClient(create_app())
    response = client.post(
        f"/api/v1/{instance_id}/entities",
        json={"entities": [{"entity_type": "Vehicle", "entity_id": "V-1", "properties": {}}]},
    )
    assert response.status_code == 403
    assert response.json()["error_type"] == "PermissionDeniedError"


def test_data_validation_error_returns_400_with_errors(
    app_client: TestClient,
    server_project: Path,
):
    instance_id = _init_instance(app_client, server_project)
    response = app_client.post(
        f"/api/v1/{instance_id}/entities",
        json={
            "entities": [
                {
                    "entity_type": "UnknownEntity",
                    "entity_id": "V-1",
                    "properties": {"vehicle_id": "V-1"},
                }
            ]
        },
    )
    assert response.status_code == 400
    assert response.json()["error_type"] == "DataValidationError"
    assert response.json()["errors"]


def test_constraint_violation_returns_422_with_context(
    app_client: TestClient,
    server_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    instance_id = _init_instance(app_client, server_project)

    def raise_constraint(*_args, **_kwargs):
        raise ConstraintViolationError("constraint failed", violations=["mismatch"])

    monkeypatch.setattr(
        "cruxible_core.server.routes.queries._handle_evaluate_local",
        raise_constraint,
    )
    response = app_client.post(f"/api/v1/{instance_id}/evaluate", json={})
    assert response.status_code == 422
    assert response.json()["context"]["violations"] == ["mismatch"]


def test_server_restart_can_reload_existing_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    server_project: Path,
    vehicles_csv: Path,
):
    monkeypatch.setenv("CRUXIBLE_SERVER_STATE_DIR", str(tmp_path / "server-state"))
    reset_permissions()
    reset_registry()
    reset_client_cache()
    get_manager().clear()
    client1 = TestClient(create_app())
    instance_id = _init_instance(client1, server_project)
    with vehicles_csv.open("rb") as handle:
        response = client1.post(
            f"/api/v1/{instance_id}/ingest",
            data={"mapping_name": "vehicles"},
            files={"file": (vehicles_csv.name, handle, "text/csv")},
        )
    assert response.status_code == 200

    get_manager().clear()
    reset_registry()
    client2 = TestClient(create_app())
    response = client2.get(f"/api/v1/{instance_id}/sample/Vehicle", params={"limit": 5})
    assert response.status_code == 200
    assert response.json()["count"] == 2


def test_add_relationship_stamps_http_api_provenance(
    app_client: TestClient,
    server_project: Path,
):
    instance_id = _init_instance(app_client, server_project)
    for entity in [
        {
            "entity_type": "Part",
            "entity_id": "BP-1",
            "properties": {
                "part_number": "BP-1",
                "name": "Brake Pad",
                "category": "brakes",
                "price": 49.99,
            },
        },
        {
            "entity_type": "Vehicle",
            "entity_id": "V-1",
            "properties": {
                "vehicle_id": "V-1",
                "year": 2024,
                "make": "Honda",
                "model": "Civic",
            },
        },
    ]:
        response = app_client.post(f"/api/v1/{instance_id}/entities", json={"entities": [entity]})
        assert response.status_code == 200

    response = app_client.post(
        f"/api/v1/{instance_id}/relationships",
        json={
            "relationships": [
                {
                    "from_type": "Part",
                    "from_id": "BP-1",
                    "relationship": "fits",
                    "to_type": "Vehicle",
                    "to_id": "V-1",
                    "properties": {"verified": True},
                }
            ]
        },
    )
    assert response.status_code == 200

    lookup = app_client.get(
        f"/api/v1/{instance_id}/relationships/lookup",
        params={
            "from_type": "Part",
            "from_id": "BP-1",
            "relationship_type": "fits",
            "to_type": "Vehicle",
            "to_id": "V-1",
        },
    )
    assert lookup.status_code == 200
    props = lookup.json()["properties"]
    assert props["_provenance"]["source"] == "http_api"
    assert props["_provenance"]["source_ref"] == "cruxible_add_relationship"


def test_server_routes_reject_unknown_instance_ids(
    app_client: TestClient,
    server_project: Path,
):
    _init_instance(app_client, server_project)

    response = app_client.post(
        "/api/v1/inst_missing/query",
        json={"query_name": "parts_for_vehicle", "params": {"vehicle_id": "V-1"}},
    )

    assert response.status_code == 404
    assert response.json()["error_type"] == "InstanceNotFoundError"


def test_resolve_server_instance_id_rejects_raw_filesystem_paths(
    app_client: TestClient,
    server_project: Path,
):
    _init_instance(app_client, server_project)

    with pytest.raises(InstanceNotFoundError):
        resolve_server_instance_id(str(server_project))
