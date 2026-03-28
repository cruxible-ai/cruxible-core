"""Integration tests for the KEV demo providers and workflows."""

from __future__ import annotations

import csv
from pathlib import Path

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.config.composer import compose_config_files
from cruxible_core.config.loader import save_config
from cruxible_core.demo_providers.kev_triage import (
    load_fork_seed_data,
    load_reference_product_catalog,
    match_software_to_products,
)
from cruxible_core.provider.types import ProviderContext, ResolvedArtifact
from cruxible_core.service import service_apply_workflow, service_lock, service_run

REPO_ROOT = Path(__file__).resolve().parents[2]
KEV_DEMO_DIR = REPO_ROOT / "demos" / "kev-triage"


def _provider_context(artifact_path: Path | None) -> ProviderContext:
    artifact = None
    if artifact_path is not None:
        artifact = ResolvedArtifact(
            name="bundle",
            kind="directory",
            uri=str(artifact_path),
            local_path=str(artifact_path),
            sha256="sha256:test",
        )
    return ProviderContext(
        workflow_name="test",
        step_id="provider",
        provider_name="provider",
        provider_version="1.0.0",
        artifact=artifact,
    )


def _csv_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _composed_kev_config_path(tmp_path: Path) -> Path:
    composed = compose_config_files(
        base_path=KEV_DEMO_DIR / "kev-reference.yaml",
        overlay_path=KEV_DEMO_DIR / "config.yaml",
    )
    config_path = tmp_path / "config.yaml"
    save_config(composed, config_path)
    return config_path


def test_load_fork_seed_data_reads_expected_rows() -> None:
    payload = load_fork_seed_data({}, _provider_context(KEV_DEMO_DIR / "data" / "seed"))
    assert set(payload) == {
        "assets",
        "business_services",
        "owners",
        "compensating_controls",
        "exceptions",
        "patch_windows",
        "service_depends_on_asset",
        "asset_owned_by",
        "asset_has_control",
        "asset_has_exception",
        "asset_patch_window",
    }
    assert payload["assets"][0]["internet_exposed"] is True


def test_load_reference_product_catalog_returns_unique_products() -> None:
    payload = load_reference_product_catalog({}, _provider_context(KEV_DEMO_DIR / "data"))
    product_ids = [item["product_id"] for item in payload["items"]]
    assert payload["items"]
    assert len(product_ids) == len(set(product_ids))
    assert all(item["product_name"] for item in payload["items"])


def test_match_software_to_products_deduplicates_asset_product_pairs() -> None:
    payload = match_software_to_products(
        {
            "inventory_items": [
                {
                    "asset_id": "ASSET-1",
                    "software_name": "Apache HTTP Server",
                    "vendor": "Apache",
                    "version": "2.4.49",
                    "evidence_source": "scanner-a",
                    "last_seen": "2026-03-20",
                },
                {
                    "asset_id": "ASSET-1",
                    "software_name": "Apache HTTP Server",
                    "vendor": "Apache",
                    "version": "2.4.49",
                    "evidence_source": "scanner-b",
                    "last_seen": "2026-03-21",
                },
            ],
            "reference_products": [
                {
                    "product_id": "apache__http_server",
                    "product_name": "Http Server",
                    "vendor_id": "apache",
                    "vendor_name": "Apache",
                    "cpe_vendor": "apache",
                    "cpe_product": "http_server",
                    "cpe_part": "a",
                },
                {
                    "product_id": "nginx__nginx",
                    "product_name": "Nginx",
                    "vendor_id": "nginx",
                    "vendor_name": "Nginx",
                    "cpe_vendor": "nginx",
                    "cpe_product": "nginx",
                    "cpe_part": "a",
                },
            ],
        },
        _provider_context(None),
    )

    assert payload["items"] == [
        {
            "asset_id": "ASSET-1",
            "product_id": "apache__http_server",
            "installed_version": "2.4.49",
            "evidence_source": "scanner-b",
            "match_confidence": payload["items"][0]["match_confidence"],
            "verdict": "support",
        },
    ]


def test_kev_demo_workflows_lock_and_run_from_composed_config(tmp_path: Path) -> None:
    config_path = _composed_kev_config_path(tmp_path)
    instance = CruxibleInstance.init(tmp_path, str(config_path))

    lock_result = service_lock(instance)
    assert lock_result.providers_locked >= 4

    preview = service_run(instance, "build_fork_state", {})
    assert preview.mode == "preview"
    assert preview.apply_digest is not None

    applied = service_apply_workflow(
        instance,
        "build_fork_state",
        {},
        expected_apply_digest=preview.apply_digest or "",
        expected_head_snapshot_id=preview.head_snapshot_id,
    )
    assert applied.committed_snapshot_id is not None

    graph = instance.load_graph()
    assert graph.entity_count("Asset") == _csv_row_count(
        KEV_DEMO_DIR / "data" / "seed" / "assets.csv"
    )
    assert graph.edge_count("asset_owned_by") == _csv_row_count(
        KEV_DEMO_DIR / "data" / "seed" / "asset_owned_by.csv"
    )

    proposal = service_run(instance, "propose_asset_products", {})
    assert proposal.output["relationship_type"] == "asset_runs_product"
    assert proposal.output["members"]
