"""Tests for published model release, fork, and pull flows."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cruxible_core.config.loader import load_config
from cruxible_core.errors import OwnershipError
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.service import (
    EntityUpsertInput,
    RelationshipUpsertInput,
    service_add_entities,
    service_add_relationships,
    service_fork_model,
    service_model_status,
    service_publish_model,
    service_pull_model_apply,
    service_pull_model_preview,
    service_reload_config,
)
from cruxible_core.snapshot.types import UpstreamMetadata
from cruxible_core.workflow.executor import _apply_entity_set, _apply_relationship_set

WORLD_MODEL_YAML = """\
version: "1.0"
name: case_reference
kind: world_model

entity_types:
  Case:
    properties:
      case_id:
        type: string
        primary_key: true
      title:
        type: string

relationships:
  - name: cites
    from: Case
    to: Case
"""


@pytest.fixture
def published_release_fixture(tmp_path: Path) -> tuple[CruxibleInstance, Path]:
    root = tmp_path / "root-model"
    root.mkdir()
    (root / "config.yaml").write_text(WORLD_MODEL_YAML)
    instance = CruxibleInstance.init(root, "config.yaml")
    service_add_entities(
        instance,
        [
            _case("CASE-A", "Alpha"),
            _case("CASE-B", "Beta"),
        ],
    )

    release_dir = tmp_path / "releases" / "current"
    service_publish_model(
        instance,
        transport_ref=f"file://{release_dir}",
        model_id="case-law",
        release_id="v1.0.0",
        compatibility="data_only",
    )
    return instance, release_dir


def test_publish_fork_and_pull_apply_preserves_fork_overlay(
    published_release_fixture: tuple[CruxibleInstance, Path],
    tmp_path: Path,
) -> None:
    root_instance, release_dir = published_release_fixture
    fork_root = tmp_path / "forked-model"

    fork_result = service_fork_model(
        transport_ref=f"file://{release_dir}",
        root_dir=fork_root,
    )
    fork_instance = fork_result.instance
    _write_overlay_config(fork_root)
    service_reload_config(fork_instance)

    add_result = service_add_relationships(
        fork_instance,
        [
            RelationshipUpsertInput(
                from_type="Case",
                from_id="CASE-A",
                relationship="follow_up",
                to_type="Case",
                to_id="CASE-B",
                properties={"reason": "watch"},
            )
        ],
        source="test",
        source_ref="model-test",
    )
    assert add_result.added == 1

    root_graph = root_instance.load_graph()
    root_graph.add_entity(
        EntityInstance(
            entity_type="Case",
            entity_id="CASE-C",
            properties={"case_id": "CASE-C", "title": "Gamma"},
        )
    )
    root_instance.save_graph(root_graph)

    successor_dir = tmp_path / "releases" / "successor"
    service_publish_model(
        root_instance,
        transport_ref=f"file://{successor_dir}",
        model_id="case-law",
        release_id="v1.1.0",
        compatibility="data_only",
    )
    _replace_release_dir(successor_dir, release_dir)

    preview = service_pull_model_preview(fork_instance)
    assert preview.target_release_id == "v1.1.0"
    assert preview.conflicts == []
    assert preview.upstream_entity_delta == 1

    applied = service_pull_model_apply(
        fork_instance,
        expected_apply_digest=preview.apply_digest,
    )
    assert applied.release_id == "v1.1.0"
    assert applied.pre_pull_snapshot_id.startswith("snap_")

    merged_graph = fork_instance.load_graph()
    assert merged_graph.has_entity("Case", "CASE-C")
    assert merged_graph.has_relationship("Case", "CASE-A", "Case", "CASE-B", "follow_up")
    status = service_model_status(fork_instance)
    assert status.upstream is not None
    assert status.upstream.release_id == "v1.1.0"


def test_pull_preview_surfaces_dangling_fork_relationships(
    published_release_fixture: tuple[CruxibleInstance, Path],
    tmp_path: Path,
) -> None:
    root_instance, release_dir = published_release_fixture
    fork_root = tmp_path / "forked-model"
    fork_instance = service_fork_model(
        transport_ref=f"file://{release_dir}",
        root_dir=fork_root,
    ).instance
    _write_overlay_config(fork_root)
    service_reload_config(fork_instance)
    service_add_relationships(
        fork_instance,
        [
            RelationshipUpsertInput(
                from_type="Case",
                from_id="CASE-A",
                relationship="follow_up",
                to_type="Case",
                to_id="CASE-B",
                properties={"reason": "watch"},
            )
        ],
        source="test",
        source_ref="model-test",
    )

    root_graph = root_instance.load_graph()
    root_graph.remove_entity("Case", "CASE-B")
    root_instance.save_graph(root_graph)

    successor_dir = tmp_path / "releases" / "successor"
    service_publish_model(
        root_instance,
        transport_ref=f"file://{successor_dir}",
        model_id="case-law",
        release_id="v2.0.0",
        compatibility="breaking",
    )
    _replace_release_dir(successor_dir, release_dir)

    preview = service_pull_model_preview(fork_instance)
    assert preview.target_release_id == "v2.0.0"
    assert any("missing upstream entity Case:CASE-B" in conflict for conflict in preview.conflicts)


def test_load_config_with_extends_remains_single_file(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(WORLD_MODEL_YAML)
    overlay.write_text(
        "\n".join(
            [
                'version: "1.0"',
                "name: case_reference_fork",
                f"extends: {base}",
                "entity_types: {}",
                "relationships: []",
            ]
        )
        + "\n"
    )

    config = load_config(overlay)
    assert config.extends == str(base)
    assert config.entity_types == {}
    assert config.relationships == []


def test_canonical_apply_respects_upstream_ownership(tmp_path: Path) -> None:
    root = tmp_path / "owned-case-model"
    root.mkdir()
    (root / "config.yaml").write_text(WORLD_MODEL_YAML)
    instance = CruxibleInstance.init(root, "config.yaml")
    instance.set_upstream_metadata(
        UpstreamMetadata(
            transport_ref="file:///tmp/release",
            model_id="case-law",
            release_id="v1.0.0",
            snapshot_id="snap_1",
            compatibility="data_only",
            owned_entity_types=["Case"],
            owned_relationship_types=["cites"],
        )
    )

    graph = EntityGraph()
    graph.add_entity(
        EntityInstance(
            entity_type="Case",
            entity_id="CASE-A",
            properties={"case_id": "CASE-A", "title": "Alpha"},
        )
    )
    graph.add_entity(
        EntityInstance(
            entity_type="Case",
            entity_id="CASE-B",
            properties={"case_id": "CASE-B", "title": "Beta"},
        )
    )
    receipt_builder = ReceiptBuilder(query_name="wf", parameters={}, operation_type="workflow")

    with pytest.raises(OwnershipError, match="upstream-owned entity types"):
        _apply_entity_set(
            instance,
            graph,
            "step_entities",
            {
                "entity_type": "Case",
                "entities": [{"entity_id": "CASE-C", "properties": {"case_id": "CASE-C"}}],
            },
            receipt_builder,
            persist_writes=False,
            parent_id=None,
        )

    preview = _apply_relationship_set(
        instance,
        graph,
        "wf",
        "step_edges",
        {
            "relationship_type": "follow_up",
            "relationships": [
                {
                    "from_type": "Case",
                    "from_id": "CASE-A",
                    "to_type": "Case",
                    "to_id": "CASE-B",
                    "properties": {"reason": "watch"},
                }
            ],
        },
        receipt_builder,
        persist_writes=False,
        parent_id=None,
    )
    assert preview.create_count == 1
    assert graph.has_relationship("Case", "CASE-A", "Case", "CASE-B", "follow_up")


def _case(case_id: str, title: str) -> EntityUpsertInput:
    return EntityUpsertInput(
        entity_type="Case",
        entity_id=case_id,
        properties={"case_id": case_id, "title": title},
    )


def _write_overlay_config(root: Path) -> None:
    (root / "config.yaml").write_text(
        "\n".join(
            [
                'version: "1.0"',
                "name: case-law-fork",
                "extends: .cruxible/upstream/current/config.yaml",
                "entity_types: {}",
                "relationships:",
                "  - name: follow_up",
                "    from: Case",
                "    to: Case",
            ]
        )
        + "\n"
    )


def _replace_release_dir(source: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
