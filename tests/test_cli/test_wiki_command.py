"""Tests for wiki rendering CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.feedback.types import FeedbackRecord, OutcomeRecord
from cruxible_core.graph.types import RelationshipInstance
from cruxible_core.graph.entity_graph import EntityGraph
from cruxible_core.graph.types import EntityInstance, RelationshipInstance
from cruxible_core.group.signature import compute_group_signature
from cruxible_core.group.types import CandidateGroup, CandidateMember
from cruxible_core.provider.types import ExecutionTrace
from cruxible_core.receipt.builder import ReceiptBuilder
from cruxible_core.wiki import WikiOptions, render_wiki
from cruxible_core.wiki.generator import SubjectRef, _humanize

WIKI_TEST_CONFIG = """\
version: "1.0"
name: kev_subject_wiki
description: Deterministic wiki test world
kind: world_model

contracts:
  exposure_input:
    fields:
      vulnerability_id:
        type: string
  asset_records:
    fields:
      items:
        type: json
  exposure_output:
    fields:
      assessments:
        type: json

entity_types:
  Asset:
    description: Internal asset tracked for remediation.
    properties:
      asset_id:
        type: string
        primary_key: true
      name:
        type: string
      environment:
        type: string
      internet_exposed:
        type: bool
      criticality:
        type: string
  Vulnerability:
    description: Public vulnerability tracked for triage.
    properties:
      vulnerability_id:
        type: string
        primary_key: true
      cve_id:
        type: string
      title:
        type: string
  BusinessService:
    description: Business service supported by internal assets.
    properties:
      service_id:
        type: string
        primary_key: true
      name:
        type: string
  Owner:
    description: Team responsible for remediation.
    properties:
      owner_id:
        type: string
        primary_key: true
      name:
        type: string

relationships:
  - name: asset_affected_by_vulnerability
    from: Asset
    to: Vulnerability
    description: Asset currently associated with the vulnerability.
    matching: {}
  - name: asset_requires_action_for_vulnerability
    from: Asset
    to: Vulnerability
    description: Asset currently requires remediation action.
    matching: {}
  - name: service_impacted_by_vulnerability
    from: BusinessService
    to: Vulnerability
    description: Service currently considered exposed through affected infrastructure.
    matching: {}
  - name: asset_supports_service
    from: Asset
    to: BusinessService
    description: Asset supports the business service.
  - name: asset_owned_by
    from: Asset
    to: Owner
    description: Asset is owned by the responsible team.

named_queries:
  assets_for_vulnerability:
    description: Find assets currently associated with a vulnerability.
    entry_point: Vulnerability
    traversal:
      - relationship: asset_affected_by_vulnerability
        direction: incoming
      - relationship: asset_supports_service
        direction: outgoing
    returns: list[Asset]

providers:
  load_software_inventory:
    kind: function
    description: Load software inventory facts for the asset.
    contract_in: exposure_input
    contract_out: asset_records
    ref: tests.providers:load_software_inventory
    version: "1.0.0"
    deterministic: true
    runtime: python
  assess_asset_exposure:
    kind: function
    description: Assess whether an asset currently requires action.
    contract_in: exposure_input
    contract_out: exposure_output
    ref: tests.providers:assess_asset_exposure
    version: "2.1.0"
    deterministic: true
    runtime: python

workflows:
  propose_asset_exposure:
    description: Build remediation conclusions for affected assets.
    canonical: false
    contract_in: exposure_input
    returns: exposure_output
    steps:
      - id: load_inventory
        provider: load_software_inventory
        input:
          vulnerability_id: $input.vulnerability_id
        as: inventory
      - id: assess_exposure
        provider: assess_asset_exposure
        input:
          vulnerability_id: $input.vulnerability_id
          inventory: $steps.inventory
        as: exposure
"""

def _build_test_graph() -> EntityGraph:
    graph = EntityGraph()
    graph.add_entity(
        EntityInstance(
            entity_type="Asset",
            entity_id="prod-web-01",
            properties={
                "asset_id": "prod-web-01",
                "name": "prod-web-01",
                "environment": "production",
                "internet_exposed": True,
                "criticality": "critical",
            },
        )
    )
    graph.add_entity(
        EntityInstance(
            entity_type="Vulnerability",
            entity_id="CVE-2021-41773",
            properties={
                "vulnerability_id": "CVE-2021-41773",
                "cve_id": "CVE-2021-41773",
                "title": "Apache HTTP Server 2.4.49 path traversal",
            },
        )
    )
    graph.add_entity(
        EntityInstance(
            entity_type="BusinessService",
            entity_id="svc-billing",
            properties={"service_id": "svc-billing", "name": "Billing"},
        )
    )
    graph.add_entity(
        EntityInstance(
            entity_type="Owner",
            entity_id="owner-seceng",
            properties={"owner_id": "owner-seceng", "name": "Security Engineering"},
        )
    )
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="asset_affected_by_vulnerability",
            from_entity_type="Asset",
            from_entity_id="prod-web-01",
            to_entity_type="Vulnerability",
            to_entity_id="CVE-2021-41773",
            properties={"review_status": "accepted", "basis": "inventory_match"},
        )
    )
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="asset_requires_action_for_vulnerability",
            from_entity_type="Asset",
            from_entity_id="prod-web-01",
            to_entity_type="Vulnerability",
            to_entity_id="CVE-2021-41773",
            properties={"review_status": "accepted", "priority": "urgent"},
        )
    )
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="service_impacted_by_vulnerability",
            from_entity_type="BusinessService",
            from_entity_id="svc-billing",
            to_entity_type="Vulnerability",
            to_entity_id="CVE-2021-41773",
            properties={"review_status": "accepted", "basis": "dependency_chain"},
        )
    )
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="asset_supports_service",
            from_entity_type="Asset",
            from_entity_id="prod-web-01",
            to_entity_type="BusinessService",
            to_entity_id="svc-billing",
            properties={"source": "cmdb"},
        )
    )
    graph.add_relationship(
        RelationshipInstance(
            relationship_type="asset_owned_by",
            from_entity_type="Asset",
            from_entity_id="prod-web-01",
            to_entity_type="Owner",
            to_entity_id="owner-seceng",
            properties={"source": "fork_seed"},
        )
    )
    return graph


def _seed_receipts_and_traces(instance: CruxibleInstance) -> tuple[str, str, str]:
    query_builder = ReceiptBuilder(
        query_name="assets_for_vulnerability",
        parameters={"vulnerability_id": "CVE-2021-41773"},
    )
    vulnerability_lookup = query_builder.record_entity_lookup("Vulnerability", "CVE-2021-41773")
    asset_step = query_builder.record_traversal(
        "Vulnerability",
        "CVE-2021-41773",
        "Asset",
        "prod-web-01",
        "asset_affected_by_vulnerability",
        {"review_status": "accepted"},
        parent_id=vulnerability_lookup,
    )
    query_builder.record_filter({"environment": "production"}, True, asset_step)
    service_step = query_builder.record_traversal(
        "Asset",
        "prod-web-01",
        "BusinessService",
        "svc-billing",
        "asset_supports_service",
        {"source": "cmdb"},
        parent_id=asset_step,
    )
    query_builder.record_results(
        [
            {"entity_type": "Asset", "entity_id": "prod-web-01"},
            {"entity_type": "BusinessService", "entity_id": "svc-billing"},
        ],
        parent_ids=[asset_step, service_step],
    )
    query_receipt = query_builder.build(
        results=[
            {"entity_type": "Asset", "entity_id": "prod-web-01"},
            {"entity_type": "BusinessService", "entity_id": "svc-billing"},
        ]
    )

    workflow_builder = ReceiptBuilder(
        query_name="propose_asset_exposure",
        parameters={"vulnerability_id": "CVE-2021-41773"},
        operation_type="workflow",
    )
    load_step = workflow_builder.record_plan_step(
        "load_inventory",
        "provider",
        detail={
            "provider_name": "load_software_inventory",
            "provider_version": "1.0.0",
            "trace_id": "TRC-load-001",
        },
    )
    assess_step = workflow_builder.record_plan_step(
        "assess_exposure",
        "provider",
        detail={
            "provider_name": "assess_asset_exposure",
            "provider_version": "2.1.0",
            "trace_id": "TRC-exposure-001",
        },
        parent_id=load_step,
    )
    workflow_builder.record_entity_lookup("Asset", "prod-web-01", parent_id=assess_step)
    workflow_builder.record_entity_lookup("Vulnerability", "CVE-2021-41773", parent_id=assess_step)
    workflow_builder.record_relationship_write(
        "Asset",
        "prod-web-01",
        "Vulnerability",
        "CVE-2021-41773",
        "asset_requires_action_for_vulnerability",
        is_update=False,
        parent_id=assess_step,
    )
    workflow_builder.record_relationship_write(
        "BusinessService",
        "svc-billing",
        "Vulnerability",
        "CVE-2021-41773",
        "service_impacted_by_vulnerability",
        is_update=False,
        parent_id=assess_step,
    )
    workflow_builder.record_results(
        [{"entity_type": "Asset", "entity_id": "prod-web-01"}],
        parent_ids=[assess_step],
    )
    workflow_receipt = workflow_builder.build(
        results=[{"entity_type": "Asset", "entity_id": "prod-web-01"}]
    )

    receipt_store = instance.get_receipt_store()
    try:
        receipt_store.save_receipt(query_receipt)
        receipt_store.save_receipt(workflow_receipt)
        receipt_store.save_trace(
            ExecutionTrace(
                trace_id="TRC-load-001",
                workflow_name="propose_asset_exposure",
                step_id="load_inventory",
                provider_name="load_software_inventory",
                provider_version="1.0.0",
                provider_ref="tests.providers:load_software_inventory",
                runtime="python",
                deterministic=True,
                side_effects=False,
                artifact_name="inventory-snapshot.json",
                artifact_sha256="abc123",
                input_payload={"vulnerability_id": "CVE-2021-41773"},
                output_payload={"items": [{"asset_id": "prod-web-01"}]},
                status="success",
            )
        )
        receipt_store.save_trace(
            ExecutionTrace(
                trace_id="TRC-exposure-001",
                workflow_name="propose_asset_exposure",
                step_id="assess_exposure",
                provider_name="assess_asset_exposure",
                provider_version="2.1.0",
                provider_ref="tests.providers:assess_asset_exposure",
                runtime="python",
                deterministic=True,
                side_effects=False,
                input_payload={
                    "vulnerability_id": "CVE-2021-41773",
                    "inventory": {"asset_id": "prod-web-01"},
                },
                output_payload={"requires_action": True, "asset_id": "prod-web-01"},
                status="success",
            )
        )
    finally:
        receipt_store.close()

    return query_receipt.receipt_id, workflow_receipt.receipt_id, "TRC-exposure-001"


def _seed_review_history(
    instance: CruxibleInstance,
    workflow_receipt_id: str,
    trace_id: str,
) -> str:
    signature = compute_group_signature(
        "asset_requires_action_for_vulnerability",
        {"asset_id": "prod-web-01", "vulnerability_id": "CVE-2021-41773"},
    )
    created_at = datetime.now(timezone.utc)
    group_store = instance.get_group_store()
    try:
        with group_store.transaction():
            resolution_id = group_store.save_resolution(
                "asset_requires_action_for_vulnerability",
                signature,
                "approve",
                "Confirmed during patch planning",
                "prod-web-01 requires action for CVE-2021-41773",
                {"asset_id": "prod-web-01", "vulnerability_id": "CVE-2021-41773"},
                {"priority": "urgent"},
                "human",
                trust_status="trusted",
                confirmed=True,
            )
            group_store.save_group(
                CandidateGroup(
                    group_id="GRP-asset-exposure-001",
                    relationship_type="asset_requires_action_for_vulnerability",
                    signature=signature,
                    status="resolved",
                    thesis_text="prod-web-01 requires action for CVE-2021-41773",
                    thesis_facts={
                        "asset_id": "prod-web-01",
                        "vulnerability_id": "CVE-2021-41773",
                    },
                    analysis_state={"priority": "urgent"},
                    integrations_used=["inventory"],
                    proposed_by="ai_review",
                    member_count=1,
                    review_priority="review",
                    source_workflow_name="propose_asset_exposure",
                    source_workflow_receipt_id=workflow_receipt_id,
                    source_trace_ids=[trace_id],
                    source_step_ids=["assess_exposure"],
                    resolution_id=resolution_id,
                    created_at=created_at,
                )
            )
            group_store.save_members(
                "GRP-asset-exposure-001",
                [
                    CandidateMember(
                        from_type="Asset",
                        from_id="prod-web-01",
                        to_type="Vulnerability",
                        to_id="CVE-2021-41773",
                        relationship_type="asset_requires_action_for_vulnerability",
                        properties={"priority": "urgent"},
                    )
                ],
            )
            group_store.save_group(
                CandidateGroup(
                    group_id="GRP-service-review-001",
                    relationship_type="service_impacted_by_vulnerability",
                    signature=compute_group_signature(
                        "service_impacted_by_vulnerability",
                        {"service_id": "svc-billing", "vulnerability_id": "CVE-2021-41773"},
                    ),
                    status="pending_review",
                    thesis_text="Billing is impacted through prod-web-01",
                    thesis_facts={
                        "service_id": "svc-billing",
                        "vulnerability_id": "CVE-2021-41773",
                    },
                    analysis_state={"priority": "review"},
                    integrations_used=["inventory"],
                    proposed_by="ai_review",
                    member_count=1,
                    review_priority="review",
                    source_workflow_name="propose_asset_exposure",
                    source_workflow_receipt_id=workflow_receipt_id,
                    source_trace_ids=[trace_id],
                    source_step_ids=["assess_exposure"],
                    created_at=created_at,
                )
            )
            group_store.save_members(
                "GRP-service-review-001",
                [
                    CandidateMember(
                        from_type="BusinessService",
                        from_id="svc-billing",
                        to_type="Vulnerability",
                        to_id="CVE-2021-41773",
                        relationship_type="service_impacted_by_vulnerability",
                    )
                ],
            )
    finally:
        group_store.close()

    feedback_store = instance.get_feedback_store()
    try:
        feedback_store.save_feedback(
            FeedbackRecord(
                receipt_id=workflow_receipt_id,
                action="approve",
                target=RelationshipInstance(
                    from_type="Asset",
                    from_id="prod-web-01",
                    relationship_type="asset_requires_action_for_vulnerability",
                    to_type="Vulnerability",
                    to_id="CVE-2021-41773",
                ),
                reason="Validated during patch planning",
                reason_code="confirmed_by_review",
                decision_context={
                    "surface_type": "workflow",
                    "surface_name": "propose_asset_exposure",
                },
            )
        )
    finally:
        feedback_store.close()

    return resolution_id


def _seed_outcomes(
    instance: CruxibleInstance,
    query_receipt_id: str,
    workflow_receipt_id: str,
    resolution_id: str,
    trace_id: str,
) -> None:
    feedback_store = instance.get_feedback_store()
    try:
        feedback_store.save_outcome(
            OutcomeRecord(
                receipt_id=query_receipt_id,
                anchor_type="receipt",
                outcome="correct",
                outcome_code="validated_in_triage",
                decision_context={
                    "surface_type": "query",
                    "surface_name": "assets_for_vulnerability",
                    "operation_type": "query",
                },
                lineage_snapshot={
                    "receipt": {"receipt_id": query_receipt_id, "operation_type": "query"},
                    "surface": {"type": "query", "name": "assets_for_vulnerability"},
                    "trace_set": {"trace_ids": [], "provider_names": [], "trace_count": 0},
                },
                detail={"note": "asset association held up during review"},
            )
        )
        feedback_store.save_outcome(
            OutcomeRecord(
                receipt_id=workflow_receipt_id,
                anchor_type="resolution",
                anchor_id=resolution_id,
                outcome="partial",
                outcome_code="scope_narrowed",
                decision_context={
                    "surface_type": "workflow",
                    "surface_name": "propose_asset_exposure",
                    "operation_type": "workflow",
                },
                lineage_snapshot={
                    "receipt": {
                        "receipt_id": workflow_receipt_id,
                        "operation_type": "workflow",
                    },
                    "surface": {"type": "workflow", "name": "propose_asset_exposure"},
                    "trace_set": {
                        "trace_ids": [trace_id],
                        "provider_names": ["assess_asset_exposure"],
                        "trace_count": 1,
                    },
                },
                relationship_type="asset_requires_action_for_vulnerability",
                detail={"note": "service impact expanded after later review"},
            )
        )
    finally:
        feedback_store.close()


def test_render_wiki_builds_subject_and_evidence_pages(tmp_path: Path) -> None:
    project = tmp_path / "wiki-project"
    project.mkdir()
    (project / "config.yaml").write_text(WIKI_TEST_CONFIG)
    instance = CruxibleInstance.init(project, "config.yaml")
    instance.save_graph(_build_test_graph())

    query_receipt_id, workflow_receipt_id, trace_id = _seed_receipts_and_traces(instance)
    resolution_id = _seed_review_history(instance, workflow_receipt_id, trace_id)
    _seed_outcomes(instance, query_receipt_id, workflow_receipt_id, resolution_id, trace_id)

    # Avoid relying on CLI cwd resolution; render directly against the seeded instance.
    written = render_wiki(
        instance,
        WikiOptions(
            output_dir=project / "wiki",
            focus=(SubjectRef("Asset", "prod-web-01"),),
        ),
    )

    assert written

    subject_page = project / "wiki" / "subjects" / "asset" / "prod-web-01.md"
    receipt_page = project / "wiki" / "evidence" / "receipts" / f"{query_receipt_id.lower()}.md"
    trace_dir = project / "wiki" / "evidence" / "traces"
    workflow_reference = project / "wiki" / "reference" / "workflows" / "propose-asset-exposure.md"
    provider_reference = project / "wiki" / "reference" / "providers" / "assess-asset-exposure.md"

    assert subject_page.exists()
    assert receipt_page.exists()
    assert not trace_dir.exists(), "Trace pages should no longer be generated"
    assert workflow_reference.exists()
    assert provider_reference.exists()

    subject_text = subject_page.read_text()
    receipt_text = receipt_page.read_text()

    assert "## How This Was Produced" in subject_text
    assert "load_software_inventory" in subject_text
    assert "assess_asset_exposure" in subject_text
    assert "## Outcome History" in subject_text
    assert "validated_in_triage" in subject_text
    assert "scope_narrowed" in subject_text
    assert "## Full Evidence" in subject_text
    assert "../../evidence/receipts/" in subject_text

    assert "## Scope" in receipt_text
    assert "## Workflow Steps" not in receipt_text
    assert "Traversals" not in receipt_text


def test_humanize_splits_camel_case_entity_names() -> None:
    assert _humanize("BusinessService") == "Business Service"
    assert _humanize("CompensatingControl") == "Compensating Control"
    assert _humanize("already_snake") == "Already Snake"
    assert _humanize("kebab-case") == "Kebab Case"
    assert _humanize("") == ""


def test_render_wiki_pending_review_filters_members_for_current_subject(tmp_path: Path) -> None:
    project = tmp_path / "wiki-project"
    project.mkdir()
    (project / "config.yaml").write_text(WIKI_TEST_CONFIG)
    instance = CruxibleInstance.init(project, "config.yaml")
    graph = _build_test_graph()
    graph.add_entity(
        EntityInstance(
            entity_type="Asset",
            entity_id="corp-laptop-01",
            properties={
                "asset_id": "corp-laptop-01",
                "name": "corp-laptop-01",
                "environment": "corporate",
                "internet_exposed": False,
                "criticality": "low",
            },
        )
    )
    instance.save_graph(graph)

    _, workflow_receipt_id, trace_id = _seed_receipts_and_traces(instance)
    _seed_review_history(instance, workflow_receipt_id, trace_id)

    group_store = instance.get_group_store()
    try:
        created_at = datetime.now(timezone.utc)
        with group_store.transaction():
            group_store.save_group(
                CandidateGroup(
                    group_id="GRP-mixed-asset-review-001",
                    relationship_type="asset_requires_action_for_vulnerability",
                    signature=compute_group_signature(
                        "asset_requires_action_for_vulnerability",
                        {"vulnerability_id": "CVE-2021-41773", "subject": "mixed-assets"},
                    ),
                    status="pending_review",
                    thesis_text=(
                        "Mixed review group should only render relevant members per subject"
                    ),
                    thesis_facts={"vulnerability_id": "CVE-2021-41773"},
                    analysis_state={"priority": "review"},
                    integrations_used=["inventory"],
                    proposed_by="ai_review",
                    member_count=2,
                    review_priority="review",
                    source_workflow_name="propose_asset_exposure",
                    source_workflow_receipt_id=workflow_receipt_id,
                    source_trace_ids=[trace_id],
                    source_step_ids=["assess_exposure"],
                    created_at=created_at,
                )
            )
            group_store.save_members(
                "GRP-mixed-asset-review-001",
                [
                    CandidateMember(
                        from_type="Asset",
                        from_id="prod-web-01",
                        to_type="Vulnerability",
                        to_id="CVE-2021-41773",
                        relationship_type="asset_requires_action_for_vulnerability",
                    ),
                    CandidateMember(
                        from_type="Asset",
                        from_id="corp-laptop-01",
                        to_type="Vulnerability",
                        to_id="CVE-2021-41773",
                        relationship_type="asset_requires_action_for_vulnerability",
                    ),
                ],
            )
    finally:
        group_store.close()

    written = render_wiki(
        instance,
        WikiOptions(
            output_dir=project / "wiki",
            focus=(SubjectRef("Asset", "prod-web-01"),),
        ),
    )

    assert written
    subject_text = (project / "wiki" / "subjects" / "asset" / "prod-web-01.md").read_text()
    assert "prod-web-01" in subject_text
    assert "Mixed review group should only render relevant members per subject" in subject_text
    assert "corp-laptop-01" not in subject_text
