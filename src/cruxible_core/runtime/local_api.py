"""Local execution helpers shared by HTTP routes and MCP handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml

from cruxible_client import contracts
from cruxible_core.config.composer import _rebase_artifact_uris, compose_configs
from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.loader import load_config, load_config_from_string
from cruxible_core.config.schema import ConstraintSchema, DecisionPolicySchema
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import ConfigError
from cruxible_core.feedback.types import EdgeTarget, FeedbackBatchItem
from cruxible_core.group.types import CandidateMember, CandidateSignal
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.mcp.permissions import (
    PermissionMode,
    check_permission,
    validate_root_dir,
)
from cruxible_core.predicate import CONSTRAINT_RULE_SYNTAX
from cruxible_core.query.candidates import MatchRule
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.runtime.instance_manager import get_manager
from cruxible_core.server.registry import GOVERNED_DAEMON_BACKEND, get_registry
from cruxible_core.service import (
    EntityUpsertInput,
    RelationshipUpsertInput,
    service_add_entities,
    service_add_relationships,
    service_analyze_feedback,
    service_analyze_outcomes,
    service_apply_workflow,
    service_create_snapshot,
    service_evaluate,
    service_feedback,
    service_feedback_batch,
    service_find_candidates,
    service_fork_snapshot,
    service_fork_world,
    service_get_entity,
    service_get_group,
    service_get_outcome_profile,
    service_get_receipt,
    service_get_relationship,
    service_ingest,
    service_init,
    service_inspect_entity,
    service_list,
    service_list_groups,
    service_list_resolutions,
    service_list_snapshots,
    service_lock,
    service_outcome,
    service_plan,
    service_propose_group,
    service_propose_workflow,
    service_publish_world,
    service_pull_world_apply,
    service_pull_world_preview,
    service_query,
    service_reload_config,
    service_resolve_group,
    service_run,
    service_sample,
    service_schema,
    service_stats,
    service_test,
    service_update_trust_status,
    service_validate,
    service_world_status,
)

WorkflowExecutionContractT = TypeVar(
    "WorkflowExecutionContractT",
    contracts.WorkflowRunResult,
    contracts.WorkflowApplyResult,
)


def _check_config_compatibility(instance: InstanceProtocol) -> list[str]:
    """Check if graph contents are compatible with the current config."""
    warnings: list[str] = []
    config = instance.load_config()
    graph = instance.load_graph()

    config_entity_types = set(config.entity_types.keys())
    for graph_type in graph.list_entity_types():
        if graph_type not in config_entity_types:
            count = graph.entity_count(graph_type)
            warnings.append(
                f"Entity type '{graph_type}' exists in graph ({count} entities) "
                "but is missing from config"
            )

    config_rel_types = {relationship.name for relationship in config.relationships}
    for graph_rel in graph.list_relationship_types():
        if graph_rel not in config_rel_types:
            count = graph.edge_count(graph_rel)
            warnings.append(
                f"Relationship type '{graph_rel}' exists in graph ({count} edges) "
                "but is missing from config"
            )

    return warnings


def _build_workflow_execution_contract(
    result: Any,
    result_type: type[WorkflowExecutionContractT],
) -> WorkflowExecutionContractT:
    """Normalize workflow run/apply service results into MCP contracts."""
    return result_type(
        workflow=result.workflow,
        output=result.output,
        receipt_id=result.receipt_id,
        mode=result.mode,
        canonical=result.canonical,
        apply_digest=result.apply_digest,
        head_snapshot_id=result.head_snapshot_id,
        committed_snapshot_id=result.committed_snapshot_id,
        apply_previews=result.apply_previews,
        query_receipt_ids=result.query_receipt_ids,
        trace_ids=result.trace_ids,
        receipt=result.receipt.model_dump(mode="json") if result.receipt else None,
        traces=[trace.model_dump(mode="json") for trace in result.traces],
    )


def _normalize_governed_config_yaml(config_yaml: str, *, workspace_root: Path) -> str:
    """Normalize uploaded config content for daemon-owned execution.

    Relative extends and artifact URIs are resolved against the caller workspace root so
    the daemon-owned active config can still execute correctly after being materialized
    under server-owned storage.

    V1 assumption: the local daemon can still read files in the caller workspace when
    resolving relative extends paths. A fully isolated daemon will need callers to upload
    fully resolved config content instead of relying on workspace filesystem access here.
    """
    overlay_path = workspace_root / "config.yaml"
    config = load_config_from_string(config_yaml)
    if config.extends is not None:
        base_path = Path(config.extends)
        if not base_path.is_absolute():
            base_path = overlay_path.parent / base_path
        if not base_path.exists():
            raise ConfigError(f"Base config for extends not found: {base_path}")
        base = load_config(base_path)
        config = compose_configs(
            base,
            config,
            base_config_path=base_path,
            overlay_config_path=overlay_path,
        )
    data = config.model_dump(mode="python", by_alias=True, exclude_none=True)
    data = _rebase_artifact_uris(data, overlay_path.parent)
    return yaml.safe_dump(data, default_flow_style=False, sort_keys=False)


def _handle_init_local(
    root_dir: str,
    config_path: str | None = None,
    config_yaml: str | None = None,
    data_dir: str | None = None,
) -> contracts.InitResult:
    """Initialize a new cruxible instance, or reload an existing one."""
    check_permission("cruxible_init")

    has_config = config_path is not None or config_yaml is not None

    if has_config:
        check_permission(
            "cruxible_init",
            instance_id=root_dir,
            required_mode=PermissionMode.ADMIN,
        )

    validate_root_dir(root_dir)
    root = Path(root_dir)
    instance_json = root / CruxibleInstance.INSTANCE_DIR / "instance.json"

    if instance_json.exists():
        if has_config:
            raise ConfigError(
                f"Instance already exists at {root}. "
                "To update the config, edit the YAML file on disk, then call "
                "cruxible_init(root_dir=...) without config_path/config_yaml to reload. "
                "The updated config takes effect immediately."
            )
        instance = CruxibleInstance.load(root)
        instance_id = str(root)
        get_manager().register(instance_id, instance)
        warnings = _check_config_compatibility(instance)
        return contracts.InitResult(instance_id=instance_id, status="loaded", warnings=warnings)

    result = service_init(
        root_dir,
        config_path=config_path,
        config_yaml=config_yaml,
        data_dir=data_dir,
    )
    instance_id = str(root)
    get_manager().register(instance_id, result.instance)
    return contracts.InitResult(instance_id=instance_id, status="initialized")


def _handle_init_governed(
    root_dir: str,
    config_path: str | None = None,
    config_yaml: str | None = None,
    data_dir: str | None = None,
) -> contracts.InitResult:
    """Initialize or reload a daemon-owned governed instance."""
    check_permission("cruxible_init")

    has_config = config_path is not None or config_yaml is not None
    if has_config:
        check_permission(
            "cruxible_init",
            instance_id=root_dir,
            required_mode=PermissionMode.ADMIN,
        )

    validate_root_dir(root_dir)
    registered = get_registry().get_or_create_governed_instance(root_dir)
    governed_root = Path(registered.record.location)
    instance_json = governed_root / CruxibleInstance.INSTANCE_DIR / "instance.json"

    if instance_json.exists():
        if has_config:
            raise ConfigError(
                "Governed instance already exists for this workspace root. "
                "Edit the config locally, then use reload-config in server mode to sync it."
            )
        instance = CruxibleInstance.load(governed_root)
        get_manager().register(registered.record.instance_id, instance)
        warnings = _check_config_compatibility(instance)
        return contracts.InitResult(
            instance_id=registered.record.instance_id,
            status="loaded",
            warnings=warnings,
        )

    if config_path is not None and config_yaml is None:
        raise ConfigError(
            "Direct server init requires uploaded config content. "
            "CLI and MCP callers should read the config locally and send config_yaml "
            "instead of passing config_path."
        )
    if config_yaml is not None:
        config_yaml = _normalize_governed_config_yaml(config_yaml, workspace_root=Path(root_dir))

    result = service_init(
        governed_root,
        config_path=None,
        config_yaml=config_yaml,
        data_dir=data_dir,
        instance_mode=CruxibleInstance.GOVERNED_MODE,
    )
    get_manager().register(registered.record.instance_id, result.instance)
    return contracts.InitResult(
        instance_id=registered.record.instance_id,
        status="initialized",
        warnings=result.warnings,
    )


def _handle_validate_local(
    config_path: str | None = None,
    config_yaml: str | None = None,
) -> contracts.ValidateResult:
    """Validate a config file or inline YAML string."""
    check_permission("cruxible_validate")

    result = service_validate(config_path=config_path, config_yaml=config_yaml)
    config = result.config
    return contracts.ValidateResult(
        valid=True,
        name=config.name,
        entity_types=list(config.entity_types.keys()),
        relationships=[relationship.name for relationship in config.relationships],
        named_queries=list(config.named_queries.keys()),
        warnings=result.warnings,
    )


def _handle_workflow_lock_local(instance_id: str) -> contracts.WorkflowLockResult:
    """Generate a workflow lock through the governed service layer."""
    check_permission(
        "workflow_lock",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    instance = get_manager().get(instance_id)
    result = service_lock(instance)
    return contracts.WorkflowLockResult(
        lock_path=result.lock_path,
        config_digest=result.config_digest,
        providers_locked=result.providers_locked,
        artifacts_locked=result.artifacts_locked,
    )


def _handle_workflow_plan_local(
    instance_id: str,
    workflow_name: str,
    input_payload: dict[str, Any] | None = None,
) -> contracts.WorkflowPlanResult:
    """Compile a workflow plan through the governed service layer."""
    check_permission(
        "workflow_plan",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_plan(instance, workflow_name, input_payload or {})
    return contracts.WorkflowPlanResult(plan=result.plan.model_dump(mode="json"))


def _handle_workflow_run_local(
    instance_id: str,
    workflow_name: str,
    input_payload: dict[str, Any] | None = None,
) -> contracts.WorkflowRunResult:
    """Execute a workflow through the governed service layer."""
    check_permission(
        "workflow_run",
        instance_id=instance_id,
        required_mode=PermissionMode.GOVERNED_WRITE,
    )
    instance = get_manager().get(instance_id)
    result = service_run(instance, workflow_name, input_payload or {})
    return _build_workflow_execution_contract(result, contracts.WorkflowRunResult)


def _handle_workflow_apply_local(
    instance_id: str,
    workflow_name: str,
    expected_apply_digest: str,
    expected_head_snapshot_id: str | None,
    input_payload: dict[str, Any] | None = None,
) -> contracts.WorkflowApplyResult:
    """Apply a canonical workflow through the governed service layer."""
    check_permission(
        "workflow_apply",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    instance = get_manager().get(instance_id)
    result = service_apply_workflow(
        instance,
        workflow_name,
        input_payload or {},
        expected_apply_digest=expected_apply_digest,
        expected_head_snapshot_id=expected_head_snapshot_id,
    )
    return _build_workflow_execution_contract(result, contracts.WorkflowApplyResult)


def _handle_workflow_test_local(
    instance_id: str,
    name: str | None = None,
) -> contracts.WorkflowTestResult:
    """Execute config-defined workflow tests through the governed service layer."""
    check_permission(
        "workflow_test",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_test(instance, test_name=name)
    return contracts.WorkflowTestResult(
        total=result.total,
        passed=result.passed,
        failed=result.failed,
        cases=[
            contracts.WorkflowTestCaseResult(
                name=case.name,
                workflow=case.workflow,
                passed=case.passed,
                output=case.output,
                receipt_id=case.receipt_id,
                error=case.error,
            )
            for case in result.cases
        ],
    )


def _handle_propose_workflow_local(
    instance_id: str,
    workflow_name: str,
    input_payload: dict[str, Any] | None = None,
) -> contracts.WorkflowProposeResult:
    """Execute a workflow and bridge its output into a governed relationship proposal."""
    check_permission(
        "cruxible_propose_workflow",
        instance_id=instance_id,
    )
    instance = get_manager().get(instance_id)
    result = service_propose_workflow(instance, workflow_name, input_payload or {})
    return contracts.WorkflowProposeResult(
        workflow=result.workflow,
        output=result.output,
        receipt_id=result.receipt_id,
        group_id=result.group_id,
        group_status=result.group_status,
        review_priority=result.review_priority,
        suppressed=result.suppressed,
        query_receipt_ids=result.query_receipt_ids,
        trace_ids=result.trace_ids,
        prior_resolution=result.prior_resolution,
        policy_summary=result.policy_summary,
        receipt=result.receipt.model_dump(mode="json") if result.receipt else None,
        traces=[trace.model_dump(mode="json") for trace in result.traces],
    )


def _handle_create_snapshot_local(
    instance_id: str,
    label: str | None = None,
) -> contracts.SnapshotCreateResult:
    """Create an immutable full snapshot for an instance."""
    check_permission(
        "snapshot_create",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    instance = get_manager().get(instance_id)
    result = service_create_snapshot(instance, label=label)
    return contracts.SnapshotCreateResult(
        snapshot=contracts.SnapshotMetadata.model_validate(result.snapshot.model_dump(mode="json"))
    )


def _handle_list_snapshots_local(instance_id: str) -> contracts.SnapshotListResult:
    """List immutable snapshots for an instance."""
    check_permission(
        "snapshot_list",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_list_snapshots(instance)
    return contracts.SnapshotListResult(
        snapshots=[
            contracts.SnapshotMetadata.model_validate(snapshot.model_dump(mode="json"))
            for snapshot in result.snapshots
        ]
    )


def _handle_fork_snapshot_local(
    instance_id: str,
    snapshot_id: str,
    root_dir: str,
) -> contracts.ForkSnapshotResult:
    """Create a new local instance from a selected snapshot."""
    check_permission(
        "snapshot_fork",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    validate_root_dir(root_dir)
    instance = get_manager().get(instance_id)
    result = service_fork_snapshot(instance, snapshot_id, root_dir)
    registered = get_registry().get_or_create_local_instance(Path(root_dir))
    get_manager().register(registered.record.instance_id, result.instance)
    return contracts.ForkSnapshotResult(
        instance_id=registered.record.instance_id,
        snapshot=contracts.SnapshotMetadata.model_validate(result.snapshot.model_dump(mode="json")),
    )


def _handle_fork_snapshot_governed(
    instance_id: str,
    snapshot_id: str,
    root_dir: str,
) -> contracts.ForkSnapshotResult:
    """Create a new daemon-owned governed instance from a selected snapshot."""
    check_permission(
        "snapshot_fork",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    validate_root_dir(root_dir)
    instance = get_manager().get(instance_id)
    registered = get_registry().create_governed_instance(workspace_root=root_dir)
    result = service_fork_snapshot(
        instance,
        snapshot_id,
        registered.record.location,
        instance_mode=CruxibleInstance.GOVERNED_MODE,
    )
    get_manager().register(registered.record.instance_id, result.instance)
    return contracts.ForkSnapshotResult(
        instance_id=registered.record.instance_id,
        snapshot=contracts.SnapshotMetadata.model_validate(result.snapshot.model_dump(mode="json")),
    )


def _handle_ingest_local(
    instance_id: str,
    mapping_name: str,
    file_path: str | None = None,
    data_csv: str | None = None,
    data_json: str | list[dict[str, Any]] | None = None,
    data_ndjson: str | None = None,
    upload_id: str | None = None,
) -> contracts.IngestResult:
    """Ingest a data file or inline data into the graph."""
    check_permission("cruxible_ingest", instance_id=instance_id)
    instance = get_manager().get(instance_id)

    result = service_ingest(
        instance,
        mapping_name,
        file_path=file_path,
        data_csv=data_csv,
        data_json=data_json,
        data_ndjson=data_ndjson,
        upload_id=upload_id,
    )
    return contracts.IngestResult(
        records_ingested=result.records_ingested,
        records_updated=result.records_updated,
        mapping=result.mapping,
        entity_type=result.entity_type,
        relationship_type=result.relationship_type,
        receipt_id=result.receipt_id,
    )


def _handle_query_local(
    instance_id: str,
    query_name: str,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
) -> contracts.QueryToolResult:
    """Execute a named query."""
    check_permission("cruxible_query")
    if limit is not None and limit < 1:
        raise ConfigError("limit must be a positive integer")

    instance = get_manager().get(instance_id)
    result = service_query(instance, query_name, params or {})

    total = result.total_results
    truncated = limit is not None and total > limit
    visible = result.results[:limit] if truncated else result.results
    include_receipt = limit is None

    return contracts.QueryToolResult(
        results=[entity.model_dump(mode="json") for entity in visible],
        receipt_id=result.receipt_id,
        receipt=(
            result.receipt.model_dump(mode="json") if result.receipt and include_receipt else None
        ),
        total_results=total,
        truncated=truncated,
        steps_executed=result.steps_executed,
        policy_summary=result.policy_summary,
        param_hints=(
            contracts.QueryParamHints(
                entry_point=result.param_hints.entry_point,
                required_params=result.param_hints.required_params,
                primary_key=result.param_hints.primary_key,
                example_ids=result.param_hints.example_ids,
            )
            if result.param_hints is not None
            else None
        ),
    )


def _handle_receipt_local(instance_id: str, receipt_id: str) -> dict[str, Any]:
    """Retrieve a stored receipt by ID."""
    check_permission("cruxible_receipt")
    instance = get_manager().get(instance_id)
    receipt = service_get_receipt(instance, receipt_id)
    return receipt.model_dump(mode="json")


def _handle_feedback_local(
    instance_id: str,
    receipt_id: str,
    action: contracts.FeedbackAction,
    source: contracts.FeedbackSource,
    from_type: str,
    from_id: str,
    relationship: str,
    to_type: str,
    to_id: str,
    edge_key: int | None = None,
    reason: str = "",
    reason_code: str | None = None,
    scope_hints: dict[str, Any] | None = None,
    corrections: dict[str, Any] | None = None,
    group_override: bool = False,
) -> contracts.FeedbackResult:
    """Record feedback on an edge."""
    check_permission("cruxible_feedback", instance_id=instance_id)
    instance = get_manager().get(instance_id)

    target = EdgeTarget(
        from_type=from_type,
        from_id=from_id,
        relationship=relationship,
        to_type=to_type,
        to_id=to_id,
        edge_key=edge_key,
    )
    result = service_feedback(
        instance,
        receipt_id=receipt_id,
        action=action,
        source=source,
        target=target,
        reason=reason,
        reason_code=reason_code,
        scope_hints=scope_hints,
        corrections=corrections,
        group_override=group_override,
    )
    return contracts.FeedbackResult(
        feedback_id=result.feedback_id,
        applied=result.applied,
        receipt_id=result.receipt_id,
    )


def _handle_feedback_batch_local(
    instance_id: str,
    items: list[contracts.FeedbackBatchItemInput],
    *,
    source: contracts.FeedbackSource,
) -> contracts.FeedbackBatchResult:
    """Record batch edge feedback tied to prior receipts."""
    check_permission("cruxible_feedback_batch", instance_id=instance_id)
    instance = get_manager().get(instance_id)
    result = service_feedback_batch(
        instance,
        [
            FeedbackBatchItem(
                receipt_id=item.receipt_id,
                action=item.action,
                target=EdgeTarget(
                    from_type=item.target.from_type,
                    from_id=item.target.from_id,
                    relationship=item.target.relationship,
                    to_type=item.target.to_type,
                    to_id=item.target.to_id,
                    edge_key=item.target.edge_key,
                ),
                reason=item.reason,
                reason_code=item.reason_code,
                scope_hints=item.scope_hints,
                corrections=item.corrections or {},
                group_override=item.group_override,
            )
            for item in items
        ],
        source=source,
    )
    return contracts.FeedbackBatchResult(
        feedback_ids=result.feedback_ids,
        applied_count=result.applied_count,
        total=result.total,
        receipt_id=result.receipt_id,
    )


def _handle_outcome_local(
    instance_id: str,
    receipt_id: str | None,
    outcome: contracts.OutcomeValue,
    anchor_type: contracts.OutcomeAnchorType = "receipt",
    anchor_id: str | None = None,
    source: contracts.FeedbackSource = "human",
    outcome_code: str | None = None,
    scope_hints: dict[str, Any] | None = None,
    outcome_profile_key: str | None = None,
    detail: dict[str, Any] | None = None,
) -> contracts.OutcomeResult:
    """Record a structured outcome for a prior receipt or proposal resolution."""
    check_permission("cruxible_outcome", instance_id=instance_id)
    instance = get_manager().get(instance_id)
    result = service_outcome(
        instance,
        receipt_id=receipt_id,
        outcome=outcome,
        anchor_type=anchor_type,
        anchor_id=anchor_id,
        source=source,
        outcome_code=outcome_code,
        scope_hints=scope_hints,
        outcome_profile_key=outcome_profile_key,
        detail=detail,
    )
    return contracts.OutcomeResult(outcome_id=result.outcome_id)


def _handle_list_local(
    instance_id: str,
    resource_type: contracts.ResourceType,
    entity_type: str | None = None,
    relationship_type: str | None = None,
    query_name: str | None = None,
    receipt_id: str | None = None,
    limit: int = 50,
    property_filter: dict[str, Any] | None = None,
    operation_type: str | None = None,
) -> contracts.ListResult:
    """List entities, edges, receipts, feedback, or outcomes."""
    check_permission("cruxible_list")
    instance = get_manager().get(instance_id)

    result = service_list(
        instance,
        resource_type,
        entity_type=entity_type,
        relationship_type=relationship_type,
        query_name=query_name,
        receipt_id=receipt_id,
        property_filter=property_filter,
        operation_type=operation_type,
        limit=limit,
    )

    if resource_type in ("entities", "feedback", "outcomes"):
        items = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in result.items
        ]
    else:
        items = result.items

    return contracts.ListResult(items=items, total=result.total)


def _handle_find_candidates_local(
    instance_id: str,
    relationship_type: str,
    strategy: contracts.CandidateStrategy,
    match_rules: list[dict[str, str]] | None = None,
    via_relationship: str | None = None,
    min_overlap: float = 0.5,
    min_confidence: float = 0.5,
    limit: int = 20,
    min_distinct_neighbors: int = 2,
) -> contracts.CandidatesResult:
    """Find candidate relationships."""
    check_permission("cruxible_find_candidates")
    instance = get_manager().get(instance_id)

    rules = [MatchRule.model_validate(rule) for rule in match_rules] if match_rules else None
    candidates = service_find_candidates(
        instance,
        relationship_type,
        strategy,
        match_rules=rules,
        via_relationship=via_relationship,
        min_overlap=min_overlap,
        min_confidence=min_confidence,
        limit=limit,
        min_distinct_neighbors=min_distinct_neighbors,
    )

    return contracts.CandidatesResult(
        candidates=[candidate.model_dump(mode="json") for candidate in candidates],
        total=len(candidates),
    )


def _handle_evaluate_local(
    instance_id: str,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> contracts.EvaluateResult:
    """Evaluate graph quality."""
    check_permission("cruxible_evaluate")
    instance = get_manager().get(instance_id)
    report = service_evaluate(
        instance,
        confidence_threshold=confidence_threshold,
        max_findings=max_findings,
        exclude_orphan_types=exclude_orphan_types,
    )
    return contracts.EvaluateResult(
        entity_count=report.entity_count,
        edge_count=report.edge_count,
        findings=[finding.model_dump(mode="json") for finding in report.findings],
        summary=report.summary,
        constraint_summary=report.constraint_summary,
        quality_summary=report.quality_summary,
    )


def _handle_schema_local(instance_id: str) -> dict[str, Any]:
    """Get config schema details."""
    check_permission("cruxible_schema")
    instance = get_manager().get(instance_id)
    config = service_schema(instance)
    return config.model_dump(mode="json")


def _handle_get_feedback_profile_local(
    instance_id: str,
    relationship_type: str,
) -> contracts.FeedbackProfileResult:
    """Return one configured feedback profile, if present."""
    check_permission(
        "cruxible_get_feedback_profile",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    profile = instance.load_config().get_feedback_profile(relationship_type)
    if profile is None:
        return contracts.FeedbackProfileResult(
            found=False,
            relationship_type=relationship_type,
        )
    return contracts.FeedbackProfileResult(
        found=True,
        relationship_type=relationship_type,
        profile=profile.model_dump(mode="json"),
    )


def _handle_get_outcome_profile_local(
    instance_id: str,
    *,
    anchor_type: contracts.OutcomeAnchorType,
    relationship_type: str | None = None,
    workflow_name: str | None = None,
    surface_type: str | None = None,
    surface_name: str | None = None,
) -> contracts.OutcomeProfileResult:
    """Return one configured outcome profile for an anchor context, if present."""
    check_permission(
        "cruxible_get_outcome_profile",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    profile_key, profile = service_get_outcome_profile(
        instance,
        anchor_type=anchor_type,
        relationship_type=relationship_type,
        workflow_name=workflow_name,
        surface_type=surface_type,
        surface_name=surface_name,
    )
    if profile is None:
        return contracts.OutcomeProfileResult(
            found=False,
            profile_key=None,
            anchor_type=anchor_type,
        )
    return contracts.OutcomeProfileResult(
        found=True,
        profile_key=profile_key,
        anchor_type=anchor_type,
        profile=profile.model_dump(mode="json"),
    )


def _handle_analyze_feedback_local(
    instance_id: str,
    relationship_type: str,
    *,
    limit: int = 200,
    min_support: int = 5,
    decision_surface_type: str | None = None,
    decision_surface_name: str | None = None,
    property_pairs: list[contracts.PropertyPairInput] | None = None,
) -> contracts.AnalyzeFeedbackResult:
    """Analyze structured feedback into deterministic remediation suggestions."""
    check_permission(
        "cruxible_analyze_feedback",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_analyze_feedback(
        instance,
        relationship_type,
        limit=limit,
        min_support=min_support,
        decision_surface_type=decision_surface_type,
        decision_surface_name=decision_surface_name,
        property_pairs=(
            [(pair.from_property, pair.to_property) for pair in property_pairs]
            if property_pairs
            else None
        ),
    )
    return contracts.AnalyzeFeedbackResult(
        relationship_type=result.relationship_type,
        feedback_count=result.feedback_count,
        action_counts=result.action_counts,
        source_counts=result.source_counts,
        reason_code_counts=result.reason_code_counts,
        coded_groups=[
            contracts.FeedbackGroupSummary(
                relationship_type=group.relationship_type,
                reason_code=group.reason_code,
                remediation_hint=group.remediation_hint,
                decision_context=group.decision_context,
                scope_hints=group.scope_hints,
                feedback_count=group.feedback_count,
                feedback_ids=group.feedback_ids,
                sample_reasons=group.sample_reasons,
            )
            for group in result.coded_groups
        ],
        uncoded_feedback_count=result.uncoded_feedback_count,
        uncoded_examples=[
            contracts.UncodedFeedbackExample(
                feedback_id=example.feedback_id,
                relationship_type=example.relationship_type,
                reason=example.reason,
                decision_context=example.decision_context,
                scope_hints=example.scope_hints,
                target=example.target,
            )
            for example in result.uncoded_examples
        ],
        constraint_suggestions=[
            contracts.ConstraintSuggestion(
                name=suggestion.name,
                description=suggestion.description,
                relationship_type=suggestion.relationship_type,
                rule=suggestion.rule,
                severity=suggestion.severity,  # type: ignore[arg-type]
                support_count=suggestion.support_count,
                feedback_ids=suggestion.feedback_ids,
                sample_value_pairs=suggestion.sample_value_pairs,
            )
            for suggestion in result.constraint_suggestions
        ],
        decision_policy_suggestions=[
            contracts.DecisionPolicySuggestion(
                name=suggestion.name,
                description=suggestion.description,
                relationship_type=suggestion.relationship_type,
                applies_to=suggestion.applies_to,  # type: ignore[arg-type]
                effect=suggestion.effect,  # type: ignore[arg-type]
                rationale=suggestion.rationale,
                match=suggestion.match,
                query_name=suggestion.query_name,
                workflow_name=suggestion.workflow_name,
                support_count=suggestion.support_count,
                feedback_ids=suggestion.feedback_ids,
            )
            for suggestion in result.decision_policy_suggestions
        ],
        quality_check_candidates=[
            contracts.QualityCheckCandidate(
                relationship_type=candidate.relationship_type,
                reason_code=candidate.reason_code,
                support_count=candidate.support_count,
                description=candidate.description,
                feedback_ids=candidate.feedback_ids,
            )
            for candidate in result.quality_check_candidates
        ],
        provider_fix_candidates=[
            contracts.ProviderFixCandidate(
                relationship_type=candidate.relationship_type,
                reason_code=candidate.reason_code,
                support_count=candidate.support_count,
                description=candidate.description,
                feedback_ids=candidate.feedback_ids,
            )
            for candidate in result.provider_fix_candidates
        ],
        warnings=result.warnings,
    )


def _handle_analyze_outcomes_local(
    instance_id: str,
    *,
    anchor_type: contracts.OutcomeAnchorType,
    relationship_type: str | None = None,
    workflow_name: str | None = None,
    query_name: str | None = None,
    surface_type: str | None = None,
    surface_name: str | None = None,
    limit: int = 200,
    min_support: int = 5,
) -> contracts.AnalyzeOutcomesResult:
    """Analyze structured outcomes into trust and debugging suggestions."""
    check_permission(
        "cruxible_analyze_outcomes",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_analyze_outcomes(
        instance,
        anchor_type=anchor_type,
        relationship_type=relationship_type,
        workflow_name=workflow_name,
        query_name=query_name,
        surface_type=surface_type,
        surface_name=surface_name,
        limit=limit,
        min_support=min_support,
    )
    return contracts.AnalyzeOutcomesResult(
        anchor_type=result.anchor_type,  # type: ignore[arg-type]
        outcome_count=result.outcome_count,
        outcome_counts=result.outcome_counts,
        outcome_code_counts=result.outcome_code_counts,
        coded_groups=[
            contracts.OutcomeGroupSummary(
                anchor_type=group.anchor_type,  # type: ignore[arg-type]
                outcome_code=group.outcome_code,
                remediation_hint=group.remediation_hint,
                decision_context=group.decision_context,
                scope_hints=group.scope_hints,
                outcome_count=group.outcome_count,
                outcome_counts=group.outcome_counts,
                outcome_ids=group.outcome_ids,
            )
            for group in result.coded_groups
        ],
        uncoded_outcome_count=result.uncoded_outcome_count,
        uncoded_examples=[
            contracts.UncodedOutcomeExample(
                outcome_id=example.outcome_id,
                anchor_type=example.anchor_type,  # type: ignore[arg-type]
                anchor_id=example.anchor_id,
                outcome=example.outcome,  # type: ignore[arg-type]
                detail=example.detail,
                decision_context=example.decision_context,
                scope_hints=example.scope_hints,
            )
            for example in result.uncoded_examples
        ],
        trust_adjustment_suggestions=[
            contracts.TrustAdjustmentSuggestion(
                resolution_id=suggestion.resolution_id,
                relationship_type=suggestion.relationship_type,
                group_signature=suggestion.group_signature,
                current_trust_status=suggestion.current_trust_status,  # type: ignore[arg-type]
                suggested_trust_status=suggestion.suggested_trust_status,  # type: ignore[arg-type]
                support_count=suggestion.support_count,
                rationale=suggestion.rationale,
                outcome_ids=suggestion.outcome_ids,
            )
            for suggestion in result.trust_adjustment_suggestions
        ],
        workflow_review_policy_suggestions=[
            contracts.OutcomeDecisionPolicySuggestion(
                name=suggestion.name,
                description=suggestion.description,
                relationship_type=suggestion.relationship_type,
                applies_to=suggestion.applies_to,  # type: ignore[arg-type]
                effect=suggestion.effect,  # type: ignore[arg-type]
                rationale=suggestion.rationale,
                match=suggestion.match,
                query_name=suggestion.query_name,
                workflow_name=suggestion.workflow_name,
                support_count=suggestion.support_count,
                outcome_ids=suggestion.outcome_ids,
            )
            for suggestion in result.workflow_review_policy_suggestions
        ],
        query_policy_suggestions=[
            contracts.QueryPolicySuggestion(
                surface_name=suggestion.surface_name,
                outcome_code=suggestion.outcome_code,
                support_count=suggestion.support_count,
                description=suggestion.description,
                outcome_ids=suggestion.outcome_ids,
            )
            for suggestion in result.query_policy_suggestions
        ],
        provider_fix_candidates=[
            contracts.OutcomeProviderFixCandidate(
                surface_type=candidate.surface_type,
                surface_name=candidate.surface_name,
                outcome_code=candidate.outcome_code,
                support_count=candidate.support_count,
                description=candidate.description,
                outcome_ids=candidate.outcome_ids,
            )
            for candidate in result.provider_fix_candidates
        ],
        debug_packages=[
            contracts.DebugPackage(
                anchor_id=package.anchor_id,
                outcome_count=package.outcome_count,
                outcome_breakdown=package.outcome_breakdown,
                outcome_code_breakdown=package.outcome_code_breakdown,
                sample_outcome_ids=package.sample_outcome_ids,
                lineage_summary=package.lineage_summary,
                common_providers=package.common_providers,
                common_trace_patterns=package.common_trace_patterns,
            )
            for package in result.debug_packages
        ],
        workflow_debug_packages=[
            contracts.DebugPackage(
                anchor_id=package.anchor_id,
                outcome_count=package.outcome_count,
                outcome_breakdown=package.outcome_breakdown,
                outcome_code_breakdown=package.outcome_code_breakdown,
                sample_outcome_ids=package.sample_outcome_ids,
                lineage_summary=package.lineage_summary,
                common_providers=package.common_providers,
                common_trace_patterns=package.common_trace_patterns,
            )
            for package in result.workflow_debug_packages
        ],
        warnings=result.warnings,
    )


def _handle_stats_local(instance_id: str) -> contracts.StatsResult:
    """Return grouped entity and relationship counts."""
    check_permission(
        "cruxible_stats",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_stats(instance)
    return contracts.StatsResult(
        entity_count=result.entity_count,
        edge_count=result.edge_count,
        entity_counts=result.entity_counts,
        relationship_counts=result.relationship_counts,
        head_snapshot_id=result.head_snapshot_id,
    )


def _handle_inspect_entity_local(
    instance_id: str,
    entity_type: str,
    entity_id: str,
    *,
    direction: str = "both",
    relationship_type: str | None = None,
    limit: int | None = None,
) -> contracts.InspectEntityResult:
    """Inspect an entity and its immediate neighbors."""
    check_permission(
        "cruxible_inspect_entity",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_inspect_entity(
        instance,
        entity_type,
        entity_id,
        direction=direction,  # type: ignore[arg-type]
        relationship_type=relationship_type,
        limit=limit,
    )
    return contracts.InspectEntityResult(
        found=result.found,
        entity_type=result.entity_type,
        entity_id=result.entity_id,
        properties=result.properties,
        neighbors=[
            contracts.InspectNeighborResult(
                direction=neighbor.direction,  # type: ignore[arg-type]
                relationship_type=neighbor.relationship_type,
                edge_key=neighbor.edge_key,
                properties=neighbor.properties,
                entity=neighbor.entity.model_dump(mode="json") if neighbor.entity else {},
            )
            for neighbor in result.neighbors
        ],
        total_neighbors=result.total_neighbors,
    )


def _handle_reload_config_local(
    instance_id: str,
    config_path: str | None = None,
    config_yaml: str | None = None,
) -> contracts.ReloadConfigResult:
    """Validate the current config or repoint the instance to a new config path."""
    check_permission(
        "cruxible_reload_config",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    if config_yaml is not None:
        record = get_registry().get(instance_id)
        if (
            record is not None
            and record.backend == GOVERNED_DAEMON_BACKEND
            and record.workspace_root is not None
        ):
            config_yaml = _normalize_governed_config_yaml(
                config_yaml,
                workspace_root=Path(record.workspace_root),
            )
    instance = get_manager().get(instance_id)
    result = service_reload_config(instance, config_path=config_path, config_yaml=config_yaml)
    return contracts.ReloadConfigResult(
        config_path=result.config_path,
        updated=result.updated,
        warnings=result.warnings,
    )


def _handle_sample_local(
    instance_id: str,
    entity_type: str,
    limit: int = 5,
) -> contracts.SampleResult:
    """Sample entities of a given type."""
    check_permission("cruxible_sample")
    instance = get_manager().get(instance_id)
    sampled = service_sample(instance, entity_type, limit=limit)
    return contracts.SampleResult(
        entities=[entity.model_dump(mode="json") for entity in sampled],
        entity_type=entity_type,
        count=len(sampled),
    )


def _handle_add_relationship_impl(
    instance_id: str,
    relationships: list[contracts.RelationshipInput],
    *,
    provenance_source: str,
    provenance_source_ref: str,
) -> contracts.AddRelationshipResult:
    """Add or update one or more relationships in the graph (upsert)."""
    check_permission("cruxible_add_relationship", instance_id=instance_id)
    instance = get_manager().get(instance_id)

    inputs = [
        RelationshipUpsertInput(
            from_type=edge.from_type,
            from_id=edge.from_id,
            relationship=edge.relationship,
            to_type=edge.to_type,
            to_id=edge.to_id,
            properties=edge.properties,
        )
        for edge in relationships
    ]
    result = service_add_relationships(
        instance,
        inputs,
        source=provenance_source,
        source_ref=provenance_source_ref,
    )
    return contracts.AddRelationshipResult(
        added=result.added,
        updated=result.updated,
        receipt_id=result.receipt_id,
    )


def _handle_add_relationship_local(
    instance_id: str,
    relationships: list[contracts.RelationshipInput],
) -> contracts.AddRelationshipResult:
    """Add or update one or more relationships in the graph (upsert)."""
    return _handle_add_relationship_impl(
        instance_id,
        relationships,
        provenance_source="mcp_add",
        provenance_source_ref="cruxible_add_relationship",
    )


def _handle_add_entity_local(
    instance_id: str,
    entities: list[contracts.EntityInput],
) -> contracts.AddEntityResult:
    """Add or update one or more entities in the graph (upsert)."""
    check_permission("cruxible_add_entity", instance_id=instance_id)
    instance = get_manager().get(instance_id)

    inputs = [
        EntityUpsertInput(
            entity_type=entity.entity_type,
            entity_id=entity.entity_id,
            properties=entity.properties,
        )
        for entity in entities
    ]
    result = service_add_entities(instance, inputs)
    return contracts.AddEntityResult(
        entities_added=result.added,
        entities_updated=result.updated,
        receipt_id=result.receipt_id,
    )


def _handle_add_constraint_local(
    instance_id: str,
    name: str,
    rule: str,
    severity: contracts.ConstraintSeverity = "warning",
    description: str | None = None,
) -> contracts.AddConstraintResult:
    """Add a constraint rule to the config and write back to YAML."""
    check_permission("cruxible_add_constraint", instance_id=instance_id)
    instance = get_manager().get(instance_id)
    config = instance.load_config()

    for existing in config.constraints:
        if existing.name == name:
            raise ConfigError(f"Constraint '{name}' already exists in config")

    parsed = parse_constraint_rule(rule)
    if parsed is None:
        raise ConfigError(
            f"Rule syntax not supported: {rule!r}. "
            f"Expected: {CONSTRAINT_RULE_SYNTAX}"
        )

    constraint = ConstraintSchema(
        name=name,
        rule=rule,
        severity=severity,
        description=description,
    )
    config.constraints.append(constraint)

    warnings = validate_config(config)
    instance.save_config(config)

    return contracts.AddConstraintResult(
        name=name,
        added=True,
        config_updated=True,
        warnings=warnings,
    )


def _handle_add_decision_policy_local(
    instance_id: str,
    *,
    name: str,
    applies_to: contracts.DecisionPolicyAppliesTo,
    relationship_type: str,
    effect: contracts.DecisionPolicyEffect,
    match: contracts.DecisionPolicyMatchInput | None = None,
    description: str | None = None,
    rationale: str = "",
    query_name: str | None = None,
    workflow_name: str | None = None,
    expires_at: str | None = None,
) -> contracts.AddDecisionPolicyResult:
    """Add a decision policy to the config and write back to YAML."""
    check_permission("cruxible_add_decision_policy", instance_id=instance_id)
    instance = get_manager().get(instance_id)
    config = instance.load_config()

    for existing in config.decision_policies:
        if existing.name == name:
            raise ConfigError(f"Decision policy '{name}' already exists in config")

    policy = DecisionPolicySchema(
        name=name,
        description=description,
        rationale=rationale,
        applies_to=applies_to,
        query_name=query_name,
        workflow_name=workflow_name,
        relationship_type=relationship_type,
        effect=effect,
        match=match.model_dump(mode="json", by_alias=True) if match is not None else {},
        expires_at=expires_at,
    )
    config.decision_policies.append(policy)
    warnings = validate_config(config)
    instance.save_config(config)
    return contracts.AddDecisionPolicyResult(
        name=name,
        added=True,
        config_updated=True,
        warnings=warnings,
    )


def _handle_get_entity_local(
    instance_id: str,
    entity_type: str,
    entity_id: str,
) -> contracts.GetEntityResult:
    """Look up a specific entity by type and ID."""
    check_permission("cruxible_get_entity")
    instance = get_manager().get(instance_id)
    entity = service_get_entity(instance, entity_type, entity_id)
    if entity is None:
        return contracts.GetEntityResult(found=False, entity_type=entity_type, entity_id=entity_id)
    return contracts.GetEntityResult(
        found=True,
        entity_type=entity.entity_type,
        entity_id=entity.entity_id,
        properties=entity.properties,
    )


def _handle_get_relationship_local(
    instance_id: str,
    from_type: str,
    from_id: str,
    relationship_type: str,
    to_type: str,
    to_id: str,
    edge_key: int | None = None,
) -> contracts.GetRelationshipResult:
    """Look up a specific relationship by its endpoints and type."""
    check_permission("cruxible_get_relationship")
    instance = get_manager().get(instance_id)
    relationship = service_get_relationship(
        instance,
        from_type,
        from_id,
        relationship_type,
        to_type,
        to_id,
        edge_key=edge_key,
    )
    if relationship is None:
        return contracts.GetRelationshipResult(
            found=False,
            from_type=from_type,
            from_id=from_id,
            relationship_type=relationship_type,
            to_type=to_type,
            to_id=to_id,
        )
    return contracts.GetRelationshipResult(
        found=True,
        from_type=relationship.from_entity_type,
        from_id=relationship.from_entity_id,
        relationship_type=relationship.relationship_type,
        to_type=relationship.to_entity_type,
        to_id=relationship.to_entity_id,
        edge_key=relationship.edge_key,
        properties=relationship.properties,
    )


def _handle_propose_group_local(
    instance_id: str,
    relationship_type: str,
    members: list[contracts.MemberInput],
    thesis_text: str = "",
    thesis_facts: dict[str, Any] | None = None,
    analysis_state: dict[str, Any] | None = None,
    integrations_used: list[str] | None = None,
    proposed_by: contracts.GroupProposedBy = "ai_review",
    suggested_priority: str | None = None,
) -> contracts.ProposeGroupToolResult:
    """Propose a candidate group for batch edge review."""
    check_permission("cruxible_propose_group", instance_id=instance_id)
    instance = get_manager().get(instance_id)

    domain_members = [
        CandidateMember(
            from_type=member.from_type,
            from_id=member.from_id,
            to_type=member.to_type,
            to_id=member.to_id,
            relationship_type=member.relationship_type,
            signals=[
                CandidateSignal(
                    integration=signal.integration,
                    signal=signal.signal,
                    evidence=signal.evidence,
                )
                for signal in member.signals
            ],
            properties=member.properties,
        )
        for member in members
    ]

    result = service_propose_group(
        instance,
        relationship_type,
        domain_members,
        thesis_text=thesis_text,
        thesis_facts=thesis_facts,
        analysis_state=analysis_state,
        integrations_used=integrations_used,
        proposed_by=proposed_by,
        suggested_priority=suggested_priority,
    )
    return contracts.ProposeGroupToolResult(
        group_id=result.group_id,
        signature=result.signature,
        status=result.status,
        review_priority=result.review_priority,
        member_count=result.member_count,
        prior_resolution=result.prior_resolution,
        suppressed=result.suppressed,
        policy_summary=result.policy_summary,
    )


def _handle_resolve_group_local(
    instance_id: str,
    group_id: str,
    action: contracts.GroupAction,
    rationale: str = "",
    resolved_by: contracts.GroupResolvedBy = "human",
) -> contracts.ResolveGroupToolResult:
    """Resolve a candidate group (approve or reject)."""
    check_permission("cruxible_resolve_group", instance_id=instance_id)
    instance = get_manager().get(instance_id)

    result = service_resolve_group(
        instance,
        group_id,
        action,
        rationale=rationale,
        resolved_by=resolved_by,
    )
    return contracts.ResolveGroupToolResult(
        group_id=result.group_id,
        action=result.action,
        edges_created=result.edges_created,
        edges_skipped=result.edges_skipped,
        resolution_id=result.resolution_id,
        receipt_id=result.receipt_id,
    )


def _handle_update_trust_status_local(
    instance_id: str,
    resolution_id: str,
    trust_status: contracts.GroupTrustStatus,
    reason: str = "",
) -> contracts.UpdateTrustStatusToolResult:
    """Update trust status on a resolution."""
    check_permission("cruxible_update_trust_status", instance_id=instance_id)
    instance = get_manager().get(instance_id)

    service_update_trust_status(instance, resolution_id, trust_status, reason=reason)
    return contracts.UpdateTrustStatusToolResult(
        resolution_id=resolution_id,
        trust_status=trust_status,
    )


def _handle_get_group_local(
    instance_id: str,
    group_id: str,
) -> contracts.GetGroupToolResult:
    """Get a candidate group with its members."""
    check_permission("cruxible_get_group")
    instance = get_manager().get(instance_id)

    result = service_get_group(instance, group_id)
    return contracts.GetGroupToolResult(
        group=result.group.model_dump(mode="json"),
        members=[member.model_dump(mode="json") for member in result.members],
    )


def _handle_list_groups_local(
    instance_id: str,
    relationship_type: str | None = None,
    status: contracts.GroupStatus | None = None,
    limit: int = 50,
) -> contracts.ListGroupsToolResult:
    """List candidate groups with optional filters."""
    check_permission("cruxible_list_groups")
    instance = get_manager().get(instance_id)

    result = service_list_groups(
        instance,
        relationship_type=relationship_type,
        status=status,
        limit=limit,
    )
    return contracts.ListGroupsToolResult(
        groups=[group.model_dump(mode="json") for group in result.groups],
        total=result.total,
    )


def _handle_list_resolutions_local(
    instance_id: str,
    relationship_type: str | None = None,
    action: contracts.GroupAction | None = None,
    limit: int = 50,
) -> contracts.ListResolutionsToolResult:
    """List group resolutions with optional filters."""
    check_permission("cruxible_list_resolutions")
    instance = get_manager().get(instance_id)

    result = service_list_resolutions(
        instance,
        relationship_type=relationship_type,
        action=action,
        limit=limit,
    )
    return contracts.ListResolutionsToolResult(
        resolutions=result.resolutions,
        total=result.total,
    )


def _handle_world_publish_local(
    instance_id: str,
    transport_ref: str,
    world_id: str,
    release_id: str,
    compatibility: contracts.WorldCompatibility,
) -> contracts.WorldPublishResult:
    """Publish a root world-model instance as an immutable release bundle."""
    check_permission(
        "cruxible_world_publish",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    instance = get_manager().get(instance_id)
    result = service_publish_world(
        instance,
        transport_ref=transport_ref,
        world_id=world_id,
        release_id=release_id,
        compatibility=compatibility,
    )
    return contracts.WorldPublishResult(
        manifest=contracts.PublishedWorldManifest.model_validate(
            result.manifest.model_dump(mode="json")
        )
    )


def _handle_world_fork_local(
    transport_ref: str,
    root_dir: str,
) -> contracts.WorldForkResult:
    """Create a new local fork from a published world release."""
    check_permission(
        "cruxible_world_fork",
        instance_id=root_dir,
        required_mode=PermissionMode.ADMIN,
    )
    validate_root_dir(root_dir)
    result = service_fork_world(transport_ref=transport_ref, root_dir=root_dir)
    registered = get_registry().get_or_create_local_instance(Path(root_dir))
    get_manager().register(registered.record.instance_id, result.instance)
    return contracts.WorldForkResult(
        instance_id=registered.record.instance_id,
        manifest=contracts.PublishedWorldManifest.model_validate(
            result.manifest.model_dump(mode="json")
        ),
    )


def _handle_world_fork_governed(
    transport_ref: str,
    root_dir: str,
) -> contracts.WorldForkResult:
    """Create a daemon-owned governed fork from a published world release."""
    check_permission(
        "cruxible_world_fork",
        instance_id=root_dir,
        required_mode=PermissionMode.ADMIN,
    )
    validate_root_dir(root_dir)
    registered = get_registry().create_governed_instance(workspace_root=root_dir)
    result = service_fork_world(
        transport_ref=transport_ref,
        root_dir=registered.record.location,
        instance_mode=CruxibleInstance.GOVERNED_MODE,
    )
    get_manager().register(registered.record.instance_id, result.instance)
    return contracts.WorldForkResult(
        instance_id=registered.record.instance_id,
        manifest=contracts.PublishedWorldManifest.model_validate(
            result.manifest.model_dump(mode="json")
        ),
    )


def _handle_world_status_local(instance_id: str) -> contracts.WorldStatusResult:
    """Return upstream tracking metadata for a release-backed fork."""
    check_permission(
        "cruxible_world_status",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_world_status(instance)
    upstream = (
        contracts.UpstreamMetadataResult.model_validate(result.upstream.model_dump(mode="json"))
        if result.upstream is not None
        else None
    )
    return contracts.WorldStatusResult(upstream=upstream)


def _handle_world_pull_preview_local(instance_id: str) -> contracts.WorldPullPreviewResult:
    """Preview pulling a newer upstream release into a fork."""
    check_permission(
        "cruxible_world_pull_preview",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = get_manager().get(instance_id)
    result = service_pull_world_preview(instance)
    return contracts.WorldPullPreviewResult(
        current_release_id=result.current_release_id,
        target_release_id=result.target_release_id,
        compatibility=result.compatibility,
        apply_digest=result.apply_digest,
        warnings=result.warnings,
        conflicts=result.conflicts,
        lock_changed=result.lock_changed,
        upstream_entity_delta=result.upstream_entity_delta,
        upstream_edge_delta=result.upstream_edge_delta,
    )


def _handle_world_pull_apply_local(
    instance_id: str,
    expected_apply_digest: str,
) -> contracts.WorldPullApplyResult:
    """Apply a previewed upstream pull to a tracked fork."""
    check_permission(
        "cruxible_world_pull_apply",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    instance = get_manager().get(instance_id)
    result = service_pull_world_apply(instance, expected_apply_digest=expected_apply_digest)
    return contracts.WorldPullApplyResult(
        release_id=result.release_id,
        apply_digest=result.apply_digest,
        pre_pull_snapshot_id=result.pre_pull_snapshot_id,
    )
