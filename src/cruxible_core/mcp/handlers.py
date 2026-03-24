"""Handler implementations for MCP tools.

Each public handler keeps the existing MCP signature but can delegate to a
governed server when server mode is configured. Local helpers contain the
current library-mode logic so FastAPI routes can call them directly without
recursing back through the HTTP client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cruxible_core.cli.instance import CruxibleInstance
from cruxible_core.client import CruxibleClient
from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.schema import ConstraintSchema
from cruxible_core.config.validator import validate_config
from cruxible_core.entity_proposal.types import EntityChangeMember
from cruxible_core.errors import ConfigError, InstanceNotFoundError
from cruxible_core.feedback.types import EdgeTarget, FeedbackBatchItem
from cruxible_core.group.types import CandidateMember, CandidateSignal
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.mcp import contracts
from cruxible_core.mcp.permissions import (
    PermissionMode,
    check_permission,
    validate_root_dir,
)
from cruxible_core.query.candidates import MatchRule
from cruxible_core.server.config import get_server_token, resolve_server_settings
from cruxible_core.server.registry import LOCAL_FILESYSTEM_BACKEND, get_registry
from cruxible_core.service import (
    EntityUpsertInput,
    RelationshipUpsertInput,
    service_add_entities,
    service_add_relationships,
    service_apply_workflow,
    service_create_snapshot,
    service_evaluate,
    service_feedback,
    service_feedback_batch,
    service_find_candidates,
    service_fork_snapshot,
    service_get_entity,
    service_get_entity_proposal,
    service_get_group,
    service_get_receipt,
    service_get_relationship,
    service_ingest,
    service_init,
    service_inspect_entity,
    service_list,
    service_list_entity_proposals,
    service_list_groups,
    service_list_resolutions,
    service_list_snapshots,
    service_lock,
    service_outcome,
    service_plan,
    service_propose_entity_changes,
    service_propose_group,
    service_propose_workflow,
    service_query,
    service_reload_config,
    service_resolve_entity_proposal,
    service_resolve_group,
    service_run,
    service_sample,
    service_schema,
    service_stats,
    service_test,
    service_update_trust_status,
    service_validate,
)


class InstanceManager:
    """Registry of live instance objects keyed by instance_id."""

    def __init__(self) -> None:
        self._instances: dict[str, InstanceProtocol] = {}

    def register(self, instance_id: str, instance: InstanceProtocol) -> None:
        self._instances[instance_id] = instance

    def get(self, instance_id: str) -> InstanceProtocol:
        instance = self._instances.get(instance_id)
        if instance is not None:
            return instance

        record = get_registry().get(instance_id)
        if record is not None and record.backend == LOCAL_FILESYSTEM_BACKEND:
            loaded = CruxibleInstance.load(Path(record.location))
            self.register(instance_id, loaded)
            return loaded

        try:
            loaded = CruxibleInstance.load(Path(instance_id))
        except InstanceNotFoundError as exc:
            raise InstanceNotFoundError(instance_id) from exc
        self.register(instance_id, loaded)
        return loaded

    def list_ids(self) -> list[str]:
        return list(self._instances.keys())

    def clear(self) -> None:
        self._instances.clear()


_manager = InstanceManager()
_client_cache: CruxibleClient | None = None
_client_cache_key: tuple[str | None, str | None, str | None] | None = None


def get_manager() -> InstanceManager:
    """Return the process-global instance manager."""
    return _manager


def reset_client_cache() -> None:
    """Clear cached client state. Used by tests."""
    global _client_cache, _client_cache_key
    if _client_cache is not None:
        _client_cache.close()
    _client_cache = None
    _client_cache_key = None


def _get_client() -> CruxibleClient | None:
    """Return a configured HTTP client in server mode."""
    global _client_cache, _client_cache_key

    settings = resolve_server_settings()
    if not settings.enabled:
        reset_client_cache()
        return None

    token = get_server_token()
    cache_key = (settings.server_url, settings.server_socket, token)
    if _client_cache is None or _client_cache_key != cache_key:
        reset_client_cache()
        _client_cache = CruxibleClient(
            base_url=settings.server_url,
            socket_path=settings.server_socket,
            token=token,
        )
        _client_cache_key = cache_key
    return _client_cache


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

    config_rel_types = {r.name for r in config.relationships}
    for graph_rel in graph.list_relationship_types():
        if graph_rel not in config_rel_types:
            count = graph.edge_count(graph_rel)
            warnings.append(
                f"Relationship type '{graph_rel}' exists in graph ({count} edges) "
                "but is missing from config"
            )

    return warnings


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
        _manager.register(instance_id, instance)
        warnings = _check_config_compatibility(instance)
        return contracts.InitResult(instance_id=instance_id, status="loaded", warnings=warnings)

    result = service_init(
        root_dir, config_path=config_path, config_yaml=config_yaml, data_dir=data_dir
    )
    instance_id = str(root)
    _manager.register(instance_id, result.instance)
    return contracts.InitResult(instance_id=instance_id, status="initialized")


def handle_init(
    root_dir: str,
    config_path: str | None = None,
    config_yaml: str | None = None,
    data_dir: str | None = None,
) -> contracts.InitResult:
    """Initialize a new cruxible instance, or reload an existing one."""
    client = _get_client()
    if client is not None:
        return client.init(
            root_dir=root_dir,
            config_path=config_path,
            config_yaml=config_yaml,
            data_dir=data_dir,
        )
    return _handle_init_local(root_dir, config_path, config_yaml, data_dir)


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
        relationships=[r.name for r in config.relationships],
        named_queries=list(config.named_queries.keys()),
        warnings=result.warnings,
    )


def handle_validate(
    config_path: str | None = None,
    config_yaml: str | None = None,
) -> contracts.ValidateResult:
    """Validate a config file or inline YAML string."""
    client = _get_client()
    if client is not None:
        return client.validate(config_path=config_path, config_yaml=config_yaml)
    return _handle_validate_local(config_path, config_yaml)


def _handle_workflow_lock_local(instance_id: str) -> contracts.WorkflowLockResult:
    """Generate a workflow lock through the governed service layer."""
    check_permission(
        "workflow_lock",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    instance = _manager.get(instance_id)
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
    instance = _manager.get(instance_id)
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
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = _manager.get(instance_id)
    result = service_run(instance, workflow_name, input_payload or {})
    return contracts.WorkflowRunResult(
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
    instance = _manager.get(instance_id)
    result = service_apply_workflow(
        instance,
        workflow_name,
        input_payload or {},
        expected_apply_digest=expected_apply_digest,
        expected_head_snapshot_id=expected_head_snapshot_id,
    )
    return contracts.WorkflowApplyResult(
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
    instance = _manager.get(instance_id)
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
    instance = _manager.get(instance_id)
    result = service_propose_workflow(instance, workflow_name, input_payload or {})
    return contracts.WorkflowProposeResult(
        workflow=result.workflow,
        output=result.output,
        receipt_id=result.receipt_id,
        group_id=result.group_id,
        group_status=result.group_status,
        review_priority=result.review_priority,
        query_receipt_ids=result.query_receipt_ids,
        trace_ids=result.trace_ids,
        prior_resolution=result.prior_resolution,
        receipt=result.receipt.model_dump(mode="json") if result.receipt else None,
        traces=[trace.model_dump(mode="json") for trace in result.traces],
    )


def handle_propose_workflow(
    instance_id: str,
    workflow_name: str,
    input_payload: dict[str, Any] | None = None,
) -> contracts.WorkflowProposeResult:
    """Execute a workflow and create a governed relationship proposal."""
    client = _get_client()
    if client is not None:
        return client.propose_workflow(
            instance_id,
            workflow_name=workflow_name,
            input_payload=input_payload or {},
        )
    return _handle_propose_workflow_local(instance_id, workflow_name, input_payload)


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
    instance = _manager.get(instance_id)
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
    instance = _manager.get(instance_id)
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
    instance = _manager.get(instance_id)
    result = service_fork_snapshot(instance, snapshot_id, root_dir)
    registered = get_registry().get_or_create_local_instance(Path(root_dir))
    _manager.register(registered.record.instance_id, result.instance)
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
    instance = _manager.get(instance_id)

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


def handle_ingest(
    instance_id: str,
    mapping_name: str,
    file_path: str | None = None,
    data_csv: str | None = None,
    data_json: str | list[dict[str, Any]] | None = None,
    data_ndjson: str | None = None,
    upload_id: str | None = None,
) -> contracts.IngestResult:
    """Ingest a data file or inline data into the graph."""
    client = _get_client()
    if client is not None:
        return client.ingest(
            instance_id,
            mapping_name,
            file_path=file_path,
            data_csv=data_csv,
            data_json=data_json,
            data_ndjson=data_ndjson,
            upload_id=upload_id,
        )
    return _handle_ingest_local(
        instance_id,
        mapping_name,
        file_path=file_path,
        data_csv=data_csv,
        data_json=data_json,
        data_ndjson=data_ndjson,
        upload_id=upload_id,
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

    instance = _manager.get(instance_id)
    result = service_query(instance, query_name, params or {})

    total = result.total_results
    truncated = limit is not None and total > limit
    visible = result.results[:limit] if truncated else result.results
    include_receipt = limit is None

    return contracts.QueryToolResult(
        results=[e.model_dump(mode="json") for e in visible],
        receipt_id=result.receipt_id,
        receipt=(
            result.receipt.model_dump(mode="json") if result.receipt and include_receipt else None
        ),
        total_results=total,
        truncated=truncated,
        steps_executed=result.steps_executed,
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


def handle_query(
    instance_id: str,
    query_name: str,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
) -> contracts.QueryToolResult:
    """Execute a named query."""
    client = _get_client()
    if client is not None:
        return client.query(instance_id, query_name, params, limit=limit)
    return _handle_query_local(instance_id, query_name, params, limit=limit)


def _handle_receipt_local(instance_id: str, receipt_id: str) -> dict[str, Any]:
    """Retrieve a stored receipt by ID."""
    check_permission("cruxible_receipt")
    instance = _manager.get(instance_id)
    receipt = service_get_receipt(instance, receipt_id)
    return receipt.model_dump(mode="json")


def handle_receipt(instance_id: str, receipt_id: str) -> dict[str, Any]:
    """Retrieve a stored receipt by ID."""
    client = _get_client()
    if client is not None:
        return client.receipt(instance_id, receipt_id)
    return _handle_receipt_local(instance_id, receipt_id)


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
    corrections: dict[str, Any] | None = None,
    group_override: bool = False,
) -> contracts.FeedbackResult:
    """Record feedback on an edge."""
    check_permission("cruxible_feedback", instance_id=instance_id)
    instance = _manager.get(instance_id)

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
        corrections=corrections,
        group_override=group_override,
    )
    return contracts.FeedbackResult(
        feedback_id=result.feedback_id, applied=result.applied, receipt_id=result.receipt_id
    )


def handle_feedback(
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
    corrections: dict[str, Any] | None = None,
    group_override: bool = False,
) -> contracts.FeedbackResult:
    """Record feedback on an edge."""
    client = _get_client()
    if client is not None:
        return client.feedback(
            instance_id,
            receipt_id=receipt_id,
            action=action,
            source=source,
            from_type=from_type,
            from_id=from_id,
            relationship=relationship,
            to_type=to_type,
            to_id=to_id,
            edge_key=edge_key,
            reason=reason,
            corrections=corrections,
            group_override=group_override,
        )
    return _handle_feedback_local(
        instance_id,
        receipt_id,
        action,
        source,
        from_type,
        from_id,
        relationship,
        to_type,
        to_id,
        edge_key=edge_key,
        reason=reason,
        corrections=corrections,
        group_override=group_override,
    )


def _handle_feedback_batch_local(
    instance_id: str,
    items: list[contracts.FeedbackBatchItemInput],
    *,
    source: contracts.FeedbackSource,
) -> contracts.FeedbackBatchResult:
    """Record batch edge feedback tied to prior receipts."""
    check_permission("cruxible_feedback_batch", instance_id=instance_id)
    instance = _manager.get(instance_id)
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


def handle_feedback_batch(
    instance_id: str,
    items: list[contracts.FeedbackBatchItemInput],
    *,
    source: contracts.FeedbackSource,
) -> contracts.FeedbackBatchResult:
    """Record batch edge feedback tied to prior receipts."""
    client = _get_client()
    if client is not None:
        return client.feedback_batch(instance_id, items=items, source=source)
    return _handle_feedback_batch_local(instance_id, items, source=source)


def _handle_outcome_local(
    instance_id: str,
    receipt_id: str,
    outcome: contracts.OutcomeValue,
    detail: dict[str, Any] | None = None,
) -> contracts.OutcomeResult:
    """Record an outcome for a query."""
    check_permission("cruxible_outcome", instance_id=instance_id)
    instance = _manager.get(instance_id)
    result = service_outcome(instance, receipt_id=receipt_id, outcome=outcome, detail=detail)
    return contracts.OutcomeResult(outcome_id=result.outcome_id)


def handle_outcome(
    instance_id: str,
    receipt_id: str,
    outcome: contracts.OutcomeValue,
    detail: dict[str, Any] | None = None,
) -> contracts.OutcomeResult:
    """Record an outcome for a query."""
    client = _get_client()
    if client is not None:
        return client.outcome(instance_id, receipt_id=receipt_id, outcome=outcome, detail=detail)
    return _handle_outcome_local(instance_id, receipt_id, outcome, detail)


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
    instance = _manager.get(instance_id)

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


def handle_list(
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
    client = _get_client()
    if client is not None:
        return client.list(
            instance_id,
            resource_type=resource_type,
            entity_type=entity_type,
            relationship_type=relationship_type,
            query_name=query_name,
            receipt_id=receipt_id,
            limit=limit,
            property_filter=property_filter,
            operation_type=operation_type,
        )
    return _handle_list_local(
        instance_id,
        resource_type,
        entity_type=entity_type,
        relationship_type=relationship_type,
        query_name=query_name,
        receipt_id=receipt_id,
        limit=limit,
        property_filter=property_filter,
        operation_type=operation_type,
    )


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
    instance = _manager.get(instance_id)

    rules = [MatchRule.model_validate(r) for r in match_rules] if match_rules else None
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
        candidates=[c.model_dump(mode="json") for c in candidates],
        total=len(candidates),
    )


def handle_find_candidates(
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
    client = _get_client()
    if client is not None:
        return client.find_candidates(
            instance_id,
            relationship_type=relationship_type,
            strategy=strategy,
            match_rules=match_rules,
            via_relationship=via_relationship,
            min_overlap=min_overlap,
            min_confidence=min_confidence,
            limit=limit,
            min_distinct_neighbors=min_distinct_neighbors,
        )
    return _handle_find_candidates_local(
        instance_id,
        relationship_type,
        strategy,
        match_rules=match_rules,
        via_relationship=via_relationship,
        min_overlap=min_overlap,
        min_confidence=min_confidence,
        limit=limit,
        min_distinct_neighbors=min_distinct_neighbors,
    )


def _handle_evaluate_local(
    instance_id: str,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> contracts.EvaluateResult:
    """Evaluate graph quality."""
    check_permission("cruxible_evaluate")
    instance = _manager.get(instance_id)
    report = service_evaluate(
        instance,
        confidence_threshold=confidence_threshold,
        max_findings=max_findings,
        exclude_orphan_types=exclude_orphan_types,
    )
    return contracts.EvaluateResult(
        entity_count=report.entity_count,
        edge_count=report.edge_count,
        findings=[f.model_dump(mode="json") for f in report.findings],
        summary=report.summary,
    )


def handle_evaluate(
    instance_id: str,
    confidence_threshold: float = 0.5,
    max_findings: int = 100,
    exclude_orphan_types: list[str] | None = None,
) -> contracts.EvaluateResult:
    """Evaluate graph quality."""
    client = _get_client()
    if client is not None:
        return client.evaluate(
            instance_id,
            confidence_threshold=confidence_threshold,
            max_findings=max_findings,
            exclude_orphan_types=exclude_orphan_types,
        )
    return _handle_evaluate_local(
        instance_id,
        confidence_threshold=confidence_threshold,
        max_findings=max_findings,
        exclude_orphan_types=exclude_orphan_types,
    )


def _handle_schema_local(instance_id: str) -> dict[str, Any]:
    """Get config schema details."""
    check_permission("cruxible_schema")
    instance = _manager.get(instance_id)
    config = service_schema(instance)
    return config.model_dump(mode="json")


def _handle_stats_local(instance_id: str) -> contracts.StatsResult:
    """Return grouped entity and relationship counts."""
    check_permission(
        "cruxible_stats",
        instance_id=instance_id,
        required_mode=PermissionMode.READ_ONLY,
    )
    instance = _manager.get(instance_id)
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
    instance = _manager.get(instance_id)
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
) -> contracts.ReloadConfigResult:
    """Validate the current config or repoint the instance to a new config path."""
    check_permission(
        "cruxible_reload_config",
        instance_id=instance_id,
        required_mode=PermissionMode.ADMIN,
    )
    instance = _manager.get(instance_id)
    result = service_reload_config(instance, config_path=config_path)
    return contracts.ReloadConfigResult(
        config_path=result.config_path,
        updated=result.updated,
        warnings=result.warnings,
    )


def handle_schema(instance_id: str) -> dict[str, Any]:
    """Get config schema details."""
    client = _get_client()
    if client is not None:
        return client.schema(instance_id)
    return _handle_schema_local(instance_id)


def _handle_sample_local(
    instance_id: str,
    entity_type: str,
    limit: int = 5,
) -> contracts.SampleResult:
    """Sample entities of a given type."""
    check_permission("cruxible_sample")
    instance = _manager.get(instance_id)
    sampled = service_sample(instance, entity_type, limit=limit)
    return contracts.SampleResult(
        entities=[e.model_dump(mode="json") for e in sampled],
        entity_type=entity_type,
        count=len(sampled),
    )


def handle_sample(
    instance_id: str,
    entity_type: str,
    limit: int = 5,
) -> contracts.SampleResult:
    """Sample entities of a given type."""
    client = _get_client()
    if client is not None:
        return client.sample(instance_id, entity_type, limit=limit)
    return _handle_sample_local(instance_id, entity_type, limit=limit)


def _handle_add_relationship_impl(
    instance_id: str,
    relationships: list[contracts.RelationshipInput],
    *,
    provenance_source: str,
    provenance_source_ref: str,
) -> contracts.AddRelationshipResult:
    """Add or update one or more relationships in the graph (upsert)."""
    check_permission("cruxible_add_relationship", instance_id=instance_id)
    instance = _manager.get(instance_id)

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


def handle_add_relationship(
    instance_id: str,
    relationships: list[contracts.RelationshipInput],
) -> contracts.AddRelationshipResult:
    """Add or update one or more relationships in the graph (upsert)."""
    client = _get_client()
    if client is not None:
        return client.add_relationships(instance_id, relationships)
    return _handle_add_relationship_local(instance_id, relationships)


def _handle_add_entity_local(
    instance_id: str,
    entities: list[contracts.EntityInput],
) -> contracts.AddEntityResult:
    """Add or update one or more entities in the graph (upsert)."""
    check_permission("cruxible_add_entity", instance_id=instance_id)
    instance = _manager.get(instance_id)

    inputs = [
        EntityUpsertInput(
            entity_type=ent.entity_type,
            entity_id=ent.entity_id,
            properties=ent.properties,
        )
        for ent in entities
    ]
    result = service_add_entities(instance, inputs)
    return contracts.AddEntityResult(
        entities_added=result.added,
        entities_updated=result.updated,
        receipt_id=result.receipt_id,
    )


def handle_add_entity(
    instance_id: str,
    entities: list[contracts.EntityInput],
) -> contracts.AddEntityResult:
    """Add or update one or more entities in the graph (upsert)."""
    client = _get_client()
    if client is not None:
        return client.add_entities(instance_id, entities)
    return _handle_add_entity_local(instance_id, entities)


def _handle_add_constraint_local(
    instance_id: str,
    name: str,
    rule: str,
    severity: contracts.ConstraintSeverity = "warning",
    description: str | None = None,
) -> contracts.AddConstraintResult:
    """Add a constraint rule to the config and write back to YAML."""
    check_permission("cruxible_add_constraint", instance_id=instance_id)
    instance = _manager.get(instance_id)
    config = instance.load_config()

    for existing in config.constraints:
        if existing.name == name:
            raise ConfigError(f"Constraint '{name}' already exists in config")

    parsed = parse_constraint_rule(rule)
    if parsed is None:
        raise ConfigError(
            f"Rule syntax not supported: {rule!r}. "
            "Expected: RELATIONSHIP.FROM.property == RELATIONSHIP.TO.property"
        )

    warnings: list[str] = []
    rel_name, from_prop, to_prop = parsed
    rel_schema = config.get_relationship(rel_name)
    if rel_schema is None:
        warnings.append(f"Relationship '{rel_name}' not found in config schema")
    else:
        from_entity_schema = config.get_entity_type(rel_schema.from_entity)
        to_entity_schema = config.get_entity_type(rel_schema.to_entity)
        if from_entity_schema and from_prop not in from_entity_schema.properties:
            warnings.append(
                f"Property '{from_prop}' not found on entity type '{rel_schema.from_entity}'"
            )
        if to_entity_schema and to_prop not in to_entity_schema.properties:
            warnings.append(
                f"Property '{to_prop}' not found on entity type '{rel_schema.to_entity}'"
            )

    constraint = ConstraintSchema(
        name=name,
        rule=rule,
        severity=severity,
        description=description,
    )
    config.constraints.append(constraint)

    warnings.extend(validate_config(config))
    instance.save_config(config)

    return contracts.AddConstraintResult(
        name=name,
        added=True,
        config_updated=True,
        warnings=warnings,
    )


def handle_add_constraint(
    instance_id: str,
    name: str,
    rule: str,
    severity: contracts.ConstraintSeverity = "warning",
    description: str | None = None,
) -> contracts.AddConstraintResult:
    """Add a constraint rule to the config and write back to YAML."""
    client = _get_client()
    if client is not None:
        return client.add_constraint(
            instance_id,
            name=name,
            rule=rule,
            severity=severity,
            description=description,
        )
    return _handle_add_constraint_local(instance_id, name, rule, severity, description)


def _handle_get_entity_local(
    instance_id: str,
    entity_type: str,
    entity_id: str,
) -> contracts.GetEntityResult:
    """Look up a specific entity by type and ID."""
    check_permission("cruxible_get_entity")
    instance = _manager.get(instance_id)
    entity = service_get_entity(instance, entity_type, entity_id)
    if entity is None:
        return contracts.GetEntityResult(found=False, entity_type=entity_type, entity_id=entity_id)
    return contracts.GetEntityResult(
        found=True,
        entity_type=entity.entity_type,
        entity_id=entity.entity_id,
        properties=entity.properties,
    )


def handle_get_entity(
    instance_id: str,
    entity_type: str,
    entity_id: str,
) -> contracts.GetEntityResult:
    """Look up a specific entity by type and ID."""
    client = _get_client()
    if client is not None:
        return client.get_entity(instance_id, entity_type, entity_id)
    return _handle_get_entity_local(instance_id, entity_type, entity_id)


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
    instance = _manager.get(instance_id)
    rel = service_get_relationship(
        instance, from_type, from_id, relationship_type, to_type, to_id, edge_key=edge_key
    )
    if rel is None:
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
        from_type=rel.from_entity_type,
        from_id=rel.from_entity_id,
        relationship_type=rel.relationship_type,
        to_type=rel.to_entity_type,
        to_id=rel.to_entity_id,
        edge_key=rel.edge_key,
        properties=rel.properties,
    )


def handle_get_relationship(
    instance_id: str,
    from_type: str,
    from_id: str,
    relationship_type: str,
    to_type: str,
    to_id: str,
    edge_key: int | None = None,
) -> contracts.GetRelationshipResult:
    """Look up a specific relationship by its endpoints and type."""
    client = _get_client()
    if client is not None:
        return client.get_relationship(
            instance_id,
            from_type=from_type,
            from_id=from_id,
            relationship_type=relationship_type,
            to_type=to_type,
            to_id=to_id,
            edge_key=edge_key,
        )
    return _handle_get_relationship_local(
        instance_id,
        from_type,
        from_id,
        relationship_type,
        to_type,
        to_id,
        edge_key=edge_key,
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
    instance = _manager.get(instance_id)

    domain_members = [
        CandidateMember(
            from_type=m.from_type,
            from_id=m.from_id,
            to_type=m.to_type,
            to_id=m.to_id,
            relationship_type=m.relationship_type,
            signals=[
                CandidateSignal(
                    integration=s.integration,
                    signal=s.signal,
                    evidence=s.evidence,
                )
                for s in m.signals
            ],
            properties=m.properties,
        )
        for m in members
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
    )


def handle_propose_group(
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
    client = _get_client()
    if client is not None:
        return client.propose_group(
            instance_id,
            relationship_type=relationship_type,
            members=members,
            thesis_text=thesis_text,
            thesis_facts=thesis_facts,
            analysis_state=analysis_state,
            integrations_used=integrations_used,
            proposed_by=proposed_by,
            suggested_priority=suggested_priority,
        )
    return _handle_propose_group_local(
        instance_id,
        relationship_type,
        members,
        thesis_text=thesis_text,
        thesis_facts=thesis_facts,
        analysis_state=analysis_state,
        integrations_used=integrations_used,
        proposed_by=proposed_by,
        suggested_priority=suggested_priority,
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
    instance = _manager.get(instance_id)

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


def handle_resolve_group(
    instance_id: str,
    group_id: str,
    action: contracts.GroupAction,
    rationale: str = "",
    resolved_by: contracts.GroupResolvedBy = "human",
) -> contracts.ResolveGroupToolResult:
    """Resolve a candidate group (approve or reject)."""
    client = _get_client()
    if client is not None:
        return client.resolve_group(
            instance_id,
            group_id,
            action=action,
            rationale=rationale,
            resolved_by=resolved_by,
        )
    return _handle_resolve_group_local(
        instance_id,
        group_id,
        action,
        rationale=rationale,
        resolved_by=resolved_by,
    )


def _handle_update_trust_status_local(
    instance_id: str,
    resolution_id: str,
    trust_status: contracts.GroupTrustStatus,
    reason: str = "",
) -> contracts.UpdateTrustStatusToolResult:
    """Update trust status on a resolution."""
    check_permission("cruxible_update_trust_status", instance_id=instance_id)
    instance = _manager.get(instance_id)

    service_update_trust_status(instance, resolution_id, trust_status, reason=reason)
    return contracts.UpdateTrustStatusToolResult(
        resolution_id=resolution_id,
        trust_status=trust_status,
    )


def handle_update_trust_status(
    instance_id: str,
    resolution_id: str,
    trust_status: contracts.GroupTrustStatus,
    reason: str = "",
) -> contracts.UpdateTrustStatusToolResult:
    """Update trust status on a resolution."""
    client = _get_client()
    if client is not None:
        return client.update_trust_status(
            instance_id,
            resolution_id,
            trust_status=trust_status,
            reason=reason,
        )
    return _handle_update_trust_status_local(instance_id, resolution_id, trust_status, reason)


def _handle_get_group_local(
    instance_id: str,
    group_id: str,
) -> contracts.GetGroupToolResult:
    """Get a candidate group with its members."""
    check_permission("cruxible_get_group")
    instance = _manager.get(instance_id)

    result = service_get_group(instance, group_id)
    return contracts.GetGroupToolResult(
        group=result.group.model_dump(mode="json"),
        members=[m.model_dump(mode="json") for m in result.members],
    )


def handle_get_group(
    instance_id: str,
    group_id: str,
) -> contracts.GetGroupToolResult:
    """Get a candidate group with its members."""
    client = _get_client()
    if client is not None:
        return client.get_group(instance_id, group_id)
    return _handle_get_group_local(instance_id, group_id)


def _handle_list_groups_local(
    instance_id: str,
    relationship_type: str | None = None,
    status: contracts.GroupStatus | None = None,
    limit: int = 50,
) -> contracts.ListGroupsToolResult:
    """List candidate groups with optional filters."""
    check_permission("cruxible_list_groups")
    instance = _manager.get(instance_id)

    result = service_list_groups(
        instance,
        relationship_type=relationship_type,
        status=status,
        limit=limit,
    )
    return contracts.ListGroupsToolResult(
        groups=[g.model_dump(mode="json") for g in result.groups],
        total=result.total,
    )


def handle_list_groups(
    instance_id: str,
    relationship_type: str | None = None,
    status: contracts.GroupStatus | None = None,
    limit: int = 50,
) -> contracts.ListGroupsToolResult:
    """List candidate groups with optional filters."""
    client = _get_client()
    if client is not None:
        return client.list_groups(
            instance_id,
            relationship_type=relationship_type,
            status=status,
            limit=limit,
        )
    return _handle_list_groups_local(instance_id, relationship_type, status, limit)


def _handle_list_resolutions_local(
    instance_id: str,
    relationship_type: str | None = None,
    action: contracts.GroupAction | None = None,
    limit: int = 50,
) -> contracts.ListResolutionsToolResult:
    """List group resolutions with optional filters."""
    check_permission("cruxible_list_resolutions")
    instance = _manager.get(instance_id)

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


def handle_list_resolutions(
    instance_id: str,
    relationship_type: str | None = None,
    action: contracts.GroupAction | None = None,
    limit: int = 50,
) -> contracts.ListResolutionsToolResult:
    """List group resolutions with optional filters."""
    client = _get_client()
    if client is not None:
        return client.list_resolutions(
            instance_id,
            relationship_type=relationship_type,
            action=action,
            limit=limit,
        )
    return _handle_list_resolutions_local(instance_id, relationship_type, action, limit)


def _handle_propose_entity_changes_local(
    instance_id: str,
    members: list[contracts.EntityChangeInput],
    *,
    thesis_text: str = "",
    thesis_facts: dict[str, Any] | None = None,
    analysis_state: dict[str, Any] | None = None,
    proposed_by: contracts.GroupProposedBy = "ai_review",
    suggested_priority: str | None = None,
    source_workflow_name: str | None = None,
    source_workflow_receipt_id: str | None = None,
    source_trace_ids: list[str] | None = None,
    source_step_ids: list[str] | None = None,
) -> contracts.ProposeEntityChangesToolResult:
    """Propose a governed batch of entity creates or patches."""
    check_permission("cruxible_propose_entity_changes", instance_id=instance_id)
    instance = _manager.get(instance_id)
    result = service_propose_entity_changes(
        instance,
        [
            EntityChangeMember(
                entity_type=member.entity_type,
                entity_id=member.entity_id,
                operation=member.operation,
                properties=member.properties,
            )
            for member in members
        ],
        thesis_text=thesis_text,
        thesis_facts=thesis_facts,
        analysis_state=analysis_state,
        proposed_by=proposed_by,
        suggested_priority=suggested_priority,
        source_workflow_name=source_workflow_name,
        source_workflow_receipt_id=source_workflow_receipt_id,
        source_trace_ids=source_trace_ids,
        source_step_ids=source_step_ids,
    )
    return contracts.ProposeEntityChangesToolResult(
        proposal_id=result.proposal_id,
        status=result.status,
        member_count=result.member_count,
    )


def handle_propose_entity_changes(
    instance_id: str,
    members: list[contracts.EntityChangeInput],
    *,
    thesis_text: str = "",
    thesis_facts: dict[str, Any] | None = None,
    analysis_state: dict[str, Any] | None = None,
    proposed_by: contracts.GroupProposedBy = "ai_review",
    suggested_priority: str | None = None,
    source_workflow_name: str | None = None,
    source_workflow_receipt_id: str | None = None,
    source_trace_ids: list[str] | None = None,
    source_step_ids: list[str] | None = None,
) -> contracts.ProposeEntityChangesToolResult:
    """Propose a governed batch of entity creates or patches."""
    client = _get_client()
    if client is not None:
        return client.propose_entity_changes(
            instance_id,
            members=members,
            thesis_text=thesis_text,
            thesis_facts=thesis_facts,
            analysis_state=analysis_state,
            proposed_by=proposed_by,
            suggested_priority=suggested_priority,
            source_workflow_name=source_workflow_name,
            source_workflow_receipt_id=source_workflow_receipt_id,
            source_trace_ids=source_trace_ids,
            source_step_ids=source_step_ids,
        )
    return _handle_propose_entity_changes_local(
        instance_id,
        members,
        thesis_text=thesis_text,
        thesis_facts=thesis_facts,
        analysis_state=analysis_state,
        proposed_by=proposed_by,
        suggested_priority=suggested_priority,
        source_workflow_name=source_workflow_name,
        source_workflow_receipt_id=source_workflow_receipt_id,
        source_trace_ids=source_trace_ids,
        source_step_ids=source_step_ids,
    )


def _handle_get_entity_proposal_local(
    instance_id: str,
    proposal_id: str,
) -> contracts.GetEntityProposalToolResult:
    """Get an entity proposal with its members."""
    check_permission("cruxible_get_entity_proposal")
    instance = _manager.get(instance_id)
    result = service_get_entity_proposal(instance, proposal_id)
    return contracts.GetEntityProposalToolResult(
        proposal=result.proposal.model_dump(mode="json"),
        members=[member.model_dump(mode="json") for member in result.members],
    )


def handle_get_entity_proposal(
    instance_id: str,
    proposal_id: str,
) -> contracts.GetEntityProposalToolResult:
    """Get an entity proposal with its members."""
    client = _get_client()
    if client is not None:
        return client.get_entity_proposal(instance_id, proposal_id)
    return _handle_get_entity_proposal_local(instance_id, proposal_id)


def _handle_list_entity_proposals_local(
    instance_id: str,
    *,
    status: contracts.EntityProposalStatus | None = None,
    limit: int = 50,
) -> contracts.ListEntityProposalsToolResult:
    """List entity proposals with optional status filter."""
    check_permission("cruxible_list_entity_proposals")
    instance = _manager.get(instance_id)
    result = service_list_entity_proposals(instance, status=status, limit=limit)
    return contracts.ListEntityProposalsToolResult(
        proposals=[proposal.model_dump(mode="json") for proposal in result.proposals],
        total=result.total,
    )


def handle_list_entity_proposals(
    instance_id: str,
    *,
    status: contracts.EntityProposalStatus | None = None,
    limit: int = 50,
) -> contracts.ListEntityProposalsToolResult:
    """List entity proposals with optional status filter."""
    client = _get_client()
    if client is not None:
        return client.list_entity_proposals(instance_id, status=status, limit=limit)
    return _handle_list_entity_proposals_local(instance_id, status=status, limit=limit)


def _handle_resolve_entity_proposal_local(
    instance_id: str,
    proposal_id: str,
    action: contracts.EntityProposalAction,
    *,
    rationale: str = "",
    resolved_by: contracts.EntityProposalResolvedBy = "human",
) -> contracts.ResolveEntityProposalToolResult:
    """Resolve an entity proposal."""
    check_permission("cruxible_resolve_entity_proposal", instance_id=instance_id)
    instance = _manager.get(instance_id)
    result = service_resolve_entity_proposal(
        instance,
        proposal_id,
        action,
        rationale=rationale,
        resolved_by=resolved_by,
    )
    return contracts.ResolveEntityProposalToolResult(
        proposal_id=result.proposal_id,
        action=result.action,
        entities_created=result.entities_created,
        entities_patched=result.entities_patched,
        resolution_id=result.resolution_id,
        receipt_id=result.receipt_id,
    )


def handle_resolve_entity_proposal(
    instance_id: str,
    proposal_id: str,
    action: contracts.EntityProposalAction,
    *,
    rationale: str = "",
    resolved_by: contracts.EntityProposalResolvedBy = "human",
) -> contracts.ResolveEntityProposalToolResult:
    """Resolve an entity proposal."""
    client = _get_client()
    if client is not None:
        return client.resolve_entity_proposal(
            instance_id,
            proposal_id,
            action=action,
            rationale=rationale,
            resolved_by=resolved_by,
        )
    return _handle_resolve_entity_proposal_local(
        instance_id,
        proposal_id,
        action,
        rationale=rationale,
        resolved_by=resolved_by,
    )
