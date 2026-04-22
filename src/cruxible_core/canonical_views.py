"""Lightweight canonical views for kit/system comprehension.

These views are read-only projections over config plus current state. They are
intentionally small: enough to standardize how kits are explained without
committing the product to a heavyweight UI layer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from cruxible_core.config.schema import CoreConfig, WorkflowStepSchema
from cruxible_core.group.types import CandidateGroup, GroupResolution


@dataclass(frozen=True)
class OntologyEntityView:
    name: str
    primary_key: str | None
    property_count: int
    description: str | None


@dataclass(frozen=True)
class OntologyRelationshipView:
    name: str
    from_entity: str
    to_entity: str
    mode: str
    cardinality: str
    reverse_name: str | None
    description: str | None
    instance_count: int | None = None


@dataclass(frozen=True)
class OntologyView:
    entity_count: int
    relationship_count: int
    governed_relationship_count: int
    entity_types: list[OntologyEntityView] = field(default_factory=list)
    relationships: list[OntologyRelationshipView] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowSummaryView:
    name: str
    mode: str
    step_count: int
    queries: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    consumes_relationships: list[str] = field(default_factory=list)
    proposes_relationships: list[str] = field(default_factory=list)
    applies_relationships: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowDependencyView:
    source_workflow: str
    target_workflow: str
    via_relationships: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowView:
    workflow_count: int
    workflows: list[WorkflowSummaryView] = field(default_factory=list)
    dependencies: list[WorkflowDependencyView] = field(default_factory=list)


@dataclass(frozen=True)
class QuerySummaryView:
    name: str
    entry_point: str
    required_params: list[str]
    returns: str
    description: str | None
    example_ids: list[str]
    traversal_summary: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueryView:
    query_count: int
    queries: list[QuerySummaryView] = field(default_factory=list)


@dataclass(frozen=True)
class GovernanceRelationshipView:
    relationship_type: str
    auto_resolve_when: str
    prior_trust_policy: str
    pending_group_count: int
    pending_tuple_count: int
    approved_resolution_count: int
    latest_trust_status: str | None


@dataclass(frozen=True)
class PendingBucketView:
    group_id: str
    relationship_type: str
    review_priority: str
    member_count: int
    signature: str
    thesis_text: str


@dataclass(frozen=True)
class GovernanceView:
    governed_relationship_count: int
    pending_group_count: int
    total_pending_groups: int
    approved_resolution_count: int
    total_resolutions: int
    pending_truncated: bool
    resolutions_truncated: bool
    relationships: list[GovernanceRelationshipView] = field(default_factory=list)
    pending_buckets: list[PendingBucketView] = field(default_factory=list)


@dataclass(frozen=True)
class OverviewView:
    ontology: OntologyView
    workflows: WorkflowView
    queries: QueryView
    governance: GovernanceView


def canonical_view_payload(view: object) -> dict[str, Any]:
    """Serialize a canonical view dataclass tree into JSON-safe dictionaries."""
    return asdict(view)


def build_ontology_view(
    config: CoreConfig,
    *,
    relationship_counts: dict[str, int] | None = None,
) -> OntologyView:
    """Build an ontology view from config and optional live edge counts."""
    entity_views = [
        OntologyEntityView(
            name=name,
            primary_key=schema.get_primary_key(),
            property_count=len(schema.properties),
            description=schema.description,
        )
        for name, schema in sorted(config.entity_types.items())
    ]
    rel_views = [
        OntologyRelationshipView(
            name=rel.name,
            from_entity=rel.from_entity,
            to_entity=rel.to_entity,
            mode="governed" if rel.matching is not None else "deterministic",
            cardinality=rel.cardinality,
            reverse_name=rel.reverse_name,
            description=rel.description,
            instance_count=(relationship_counts or {}).get(rel.name),
        )
        for rel in sorted(config.relationships, key=lambda item: item.name)
    ]
    governed_count = sum(1 for rel in rel_views if rel.mode == "governed")
    return OntologyView(
        entity_count=len(entity_views),
        relationship_count=len(rel_views),
        governed_relationship_count=governed_count,
        entity_types=entity_views,
        relationships=rel_views,
    )


def build_workflow_view(config: CoreConfig) -> WorkflowView:
    """Build a workflow view with inferred relationship dependencies."""
    produced_by_workflow: dict[str, set[str]] = {}
    consumed_by_workflow: dict[str, set[str]] = {}
    workflows: list[WorkflowSummaryView] = []

    for workflow_name, workflow in sorted(config.workflows.items()):
        alias_to_relationship: dict[str, str] = {}
        queries: list[str] = []
        providers: list[str] = []
        consumes: set[str] = set()
        proposes: set[str] = set()
        applies: set[str] = set()

        for step in workflow.steps:
            step_kind = _workflow_step_kind(step)
            if step_kind == "query" and step.query is not None:
                queries.append(step.query)
                query = config.named_queries.get(step.query)
                if query is not None:
                    for traversal_step in query.traversal:
                        consumes.update(traversal_step.relationship_types)
            elif step_kind == "provider" and step.provider is not None:
                providers.append(step.provider)
            elif step_kind == "list_relationships" and step.list_relationships is not None:
                consumes.add(step.list_relationships.relationship_type)
            elif step_kind == "make_relationships" and step.make_relationships is not None:
                alias = step.as_ or step.id
                alias_to_relationship[alias] = step.make_relationships.relationship_type
            elif (
                step_kind == "propose_relationship_group"
                and step.propose_relationship_group is not None
            ):
                proposes.add(step.propose_relationship_group.relationship_type)
            elif step_kind == "apply_relationships" and step.apply_relationships is not None:
                relationship_type = alias_to_relationship.get(
                    step.apply_relationships.relationships_from
                )
                if relationship_type:
                    applies.add(relationship_type)

        produced = sorted(proposes | applies)
        consumed = sorted(consumes)
        produced_by_workflow[workflow_name] = set(produced)
        consumed_by_workflow[workflow_name] = set(consumed)
        workflows.append(
            WorkflowSummaryView(
                name=workflow_name,
                mode="canonical" if workflow.canonical else "governed",
                step_count=len(workflow.steps),
                queries=sorted(set(queries)),
                providers=sorted(set(providers)),
                consumes_relationships=consumed,
                proposes_relationships=sorted(proposes),
                applies_relationships=sorted(applies),
            )
        )

    dependencies: list[WorkflowDependencyView] = []
    for source_name, produced in produced_by_workflow.items():
        if not produced:
            continue
        for target_name, consumed in consumed_by_workflow.items():
            if source_name == target_name:
                continue
            overlap = sorted(produced & consumed)
            if overlap:
                dependencies.append(
                    WorkflowDependencyView(
                        source_workflow=source_name,
                        target_workflow=target_name,
                        via_relationships=overlap,
                    )
                )

    dependencies.sort(key=lambda item: (item.source_workflow, item.target_workflow))
    return WorkflowView(
        workflow_count=len(workflows),
        workflows=workflows,
        dependencies=dependencies,
    )


def build_query_view(
    config: CoreConfig,
    *,
    query_infos: list[dict[str, Any]],
) -> QueryView:
    """Build a query view from config plus discovered param metadata."""
    info_by_name = {item["name"]: item for item in query_infos}
    queries: list[QuerySummaryView] = []
    for name, query in sorted(config.named_queries.items()):
        info = info_by_name.get(name, {})
        traversal_summary = [
            _format_traversal_summary(step.relationship_types, step.direction, step.max_depth)
            for step in query.traversal
        ]
        queries.append(
            QuerySummaryView(
                name=name,
                entry_point=query.entry_point,
                required_params=list(info.get("required_params", [])),
                returns=info.get("returns", query.returns),
                description=info.get("description", query.description),
                example_ids=list(info.get("example_ids", [])),
                traversal_summary=traversal_summary,
            )
        )
    return QueryView(query_count=len(queries), queries=queries)


def build_governance_view(
    config: CoreConfig,
    *,
    pending_groups: list[CandidateGroup],
    pending_total: int,
    resolutions: list[GroupResolution],
    resolution_total: int,
) -> GovernanceView:
    """Build a governance summary over governed relationships plus live queue state."""
    governed = {
        rel.name: rel.matching
        for rel in config.relationships
        if rel.matching is not None
    }

    pending_by_relationship: dict[str, list[CandidateGroup]] = {}
    for group in pending_groups:
        pending_by_relationship.setdefault(group.relationship_type, []).append(group)

    approved_by_relationship: dict[str, list[GroupResolution]] = {}
    for resolution in resolutions:
        if resolution.action != "approve":
            continue
        approved_by_relationship.setdefault(resolution.relationship_type, []).append(resolution)

    relationship_rows: list[GovernanceRelationshipView] = []
    for relationship_name, matching in sorted(governed.items()):
        pending = pending_by_relationship.get(relationship_name, [])
        approved = approved_by_relationship.get(relationship_name, [])
        latest = approved[0] if approved else None
        relationship_rows.append(
            GovernanceRelationshipView(
                relationship_type=relationship_name,
                auto_resolve_when=matching.auto_resolve_when,
                prior_trust_policy=matching.auto_resolve_requires_prior_trust,
                pending_group_count=len(pending),
                pending_tuple_count=sum(group.member_count for group in pending),
                approved_resolution_count=len(approved),
                latest_trust_status=latest.trust_status if latest is not None else None,
            )
        )

    pending_rows = [
        PendingBucketView(
            group_id=group.group_id,
            relationship_type=group.relationship_type,
            review_priority=group.review_priority,
            member_count=group.member_count,
            signature=group.signature,
            thesis_text=group.thesis_text,
        )
        for group in pending_groups
    ]

    approved_resolution_count = sum(
        1 for resolution in resolutions if resolution.action == "approve"
    )
    return GovernanceView(
        governed_relationship_count=len(governed),
        pending_group_count=len(pending_groups),
        total_pending_groups=pending_total,
        approved_resolution_count=approved_resolution_count,
        total_resolutions=resolution_total,
        pending_truncated=pending_total > len(pending_groups),
        resolutions_truncated=resolution_total > len(resolutions),
        relationships=relationship_rows,
        pending_buckets=pending_rows,
    )


def build_overview_view(
    *,
    ontology: OntologyView,
    workflows: WorkflowView,
    queries: QueryView,
    governance: GovernanceView,
) -> OverviewView:
    """Compose the four canonical primitives into one overview view."""
    return OverviewView(
        ontology=ontology,
        workflows=workflows,
        queries=queries,
        governance=governance,
    )


def render_ontology_markdown(view: OntologyView) -> str:
    """Render the ontology view as compact Markdown."""
    lines = [
        "# Ontology View",
        "",
        f"- Entity types: {view.entity_count}",
        f"- Relationships: {view.relationship_count}",
        f"- Governed relationships: {view.governed_relationship_count}",
        "",
        "## Entity Types",
        "",
        _markdown_table(
            ("Entity", "Primary Key", "Properties", "Description"),
            [
                (
                    item.name,
                    item.primary_key or "",
                    str(item.property_count),
                    item.description or "",
                )
                for item in view.entity_types
            ],
        ),
        "",
        "## Relationships",
        "",
        _markdown_table(
            ("Relationship", "From", "To", "Mode", "Cardinality", "Instances"),
            [
                (
                    item.name,
                    item.from_entity,
                    item.to_entity,
                    item.mode,
                    item.cardinality,
                    "" if item.instance_count is None else str(item.instance_count),
                )
                for item in view.relationships
            ],
        ),
    ]
    return "\n".join(lines)


def render_ontology_mermaid(view: OntologyView) -> str:
    """Render the ontology view as a Mermaid flowchart."""
    lines = ["flowchart LR"]
    for entity in view.entity_types:
        node_id = _mermaid_id(f"entity_{entity.name}")
        lines.append(f'  {node_id}["{entity.name}"]')
    for relationship in view.relationships:
        src = _mermaid_id(f"entity_{relationship.from_entity}")
        dst = _mermaid_id(f"entity_{relationship.to_entity}")
        label = _escape_mermaid_label(
            (
                relationship.name
                if relationship.mode == "deterministic"
                else f"{relationship.name} [governed]"
            )
        )
        if relationship.mode == "governed":
            lines.append(f'  {src} -. "{label}" .-> {dst}')
        else:
            lines.append(f'  {src} -- "{label}" --> {dst}')
    return "\n".join(lines)


def render_workflow_markdown(view: WorkflowView) -> str:
    """Render the workflow view as compact Markdown."""
    lines = [
        "# Workflow View",
        "",
        f"- Workflows: {view.workflow_count}",
        "",
        _markdown_table(
            (
                "Workflow",
                "Mode",
                "Steps",
                "Queries",
                "Providers",
                "Produces",
                "Consumes",
            ),
            [
                (
                    item.name,
                    item.mode,
                    str(item.step_count),
                    ", ".join(item.queries),
                    ", ".join(item.providers),
                    ", ".join(item.proposes_relationships + item.applies_relationships),
                    ", ".join(item.consumes_relationships),
                )
                for item in view.workflows
            ],
        ),
    ]

    if view.dependencies:
        lines.extend(
            [
                "",
                "## Inferred Dependencies",
                "",
                _markdown_table(
                    ("From", "To", "Via"),
                    [
                        (
                            item.source_workflow,
                            item.target_workflow,
                            ", ".join(item.via_relationships),
                        )
                        for item in view.dependencies
                    ],
                ),
            ]
        )

    return "\n".join(lines)


def render_workflow_mermaid(view: WorkflowView) -> str:
    """Render the workflow view as a Mermaid dependency graph."""
    lines = ["flowchart TD"]
    for workflow in view.workflows:
        node_id = _mermaid_id(f"workflow_{workflow.name}")
        label = _escape_mermaid_label(f"{workflow.name}\\n{workflow.mode}")
        lines.append(f'  {node_id}["{label}"]')
    if view.dependencies:
        for dependency in view.dependencies:
            src = _mermaid_id(f"workflow_{dependency.source_workflow}")
            dst = _mermaid_id(f"workflow_{dependency.target_workflow}")
            label = _escape_mermaid_label(", ".join(dependency.via_relationships))
            lines.append(f'  {src} -- "{label}" --> {dst}')
    return "\n".join(lines)


def render_query_markdown(view: QueryView) -> str:
    """Render the query view as compact Markdown."""
    lines = [
        "# Query View",
        "",
        f"- Named queries: {view.query_count}",
        "",
        _markdown_table(
            ("Query", "Entry", "Params", "Returns", "Traversal", "Examples"),
            [
                (
                    item.name,
                    item.entry_point,
                    ", ".join(item.required_params),
                    item.returns,
                    " -> ".join(item.traversal_summary),
                    ", ".join(item.example_ids),
                )
                for item in view.queries
            ],
        ),
    ]
    return "\n".join(lines)


def render_query_mermaid(view: QueryView) -> str:
    """Render the query view as a Mermaid flowchart."""
    lines = ["flowchart TD"]
    for query in view.queries:
        query_id = _mermaid_id(f"query_{query.name}")
        entry_id = _mermaid_id(f"query_{query.name}_entry")
        return_id = _mermaid_id(f"query_{query.name}_return")
        lines.append(f'  {query_id}["{_escape_mermaid_label(query.name)}"]')
        lines.append(f'  {entry_id}["entry: {_escape_mermaid_label(query.entry_point)}"]')
        lines.append(f'  {query_id} --> {entry_id}')
        previous_id = entry_id
        for index, step in enumerate(query.traversal_summary):
            step_id = _mermaid_id(f"query_{query.name}_step_{index}")
            lines.append(f'  {step_id}["{_escape_mermaid_label(step)}"]')
            lines.append(f"  {previous_id} --> {step_id}")
            previous_id = step_id
        lines.append(f'  {return_id}["returns: {_escape_mermaid_label(query.returns)}"]')
        lines.append(f"  {previous_id} --> {return_id}")
    return "\n".join(lines)


def render_governance_markdown(view: GovernanceView) -> str:
    """Render the governance view as compact Markdown."""
    lines = [
        "# Governance View",
        "",
        f"- Governed relationships: {view.governed_relationship_count}",
        f"- Pending buckets shown: {view.pending_group_count}",
        f"- Pending buckets total: {view.total_pending_groups}",
        f"- Approved resolutions shown: {view.approved_resolution_count}",
        f"- Resolutions total: {view.total_resolutions}",
    ]
    if view.pending_truncated or view.resolutions_truncated:
        lines.append("- Note: results are truncated to the requested fetch limit.")

    lines.extend(
        [
            "",
            "## Relationship Policies",
            "",
            _markdown_table(
                (
                    "Relationship",
                    "Auto-resolve",
                    "Prior Trust",
                    "Pending Groups",
                    "Pending Tuples",
                    "Approved Resolutions",
                    "Latest Trust",
                ),
                [
                    (
                        item.relationship_type,
                        item.auto_resolve_when,
                        item.prior_trust_policy,
                        str(item.pending_group_count),
                        str(item.pending_tuple_count),
                        str(item.approved_resolution_count),
                        item.latest_trust_status or "",
                    )
                    for item in view.relationships
                ],
            ),
        ]
    )
    if view.pending_buckets:
        lines.extend(
            [
                "",
                "## Pending Buckets",
                "",
                _markdown_table(
                    ("Group ID", "Relationship", "Priority", "Members", "Signature", "Thesis"),
                    [
                        (
                            item.group_id,
                            item.relationship_type,
                            item.review_priority,
                            str(item.member_count),
                            item.signature,
                            item.thesis_text,
                        )
                        for item in view.pending_buckets
                    ],
                ),
            ]
        )
    return "\n".join(lines)


def render_overview_markdown(view: OverviewView) -> str:
    """Render a readable generated overview from the canonical views."""
    deterministic = [rel for rel in view.ontology.relationships if rel.mode == "deterministic"]
    governed = [rel for rel in view.ontology.relationships if rel.mode == "governed"]
    query_groups = _group_queries_by_entry(view.queries.queries)

    lines = [
        "# Config Overview",
        "",
        (
            "This page is generated from the canonical ontology, workflow, query, "
            "and governance views."
        ),
        "",
        "## At A Glance",
        "",
        f"- Entity types: {view.ontology.entity_count}",
        f"- Relationship types: {view.ontology.relationship_count}",
        f"- Governed relationship types: {view.ontology.governed_relationship_count}",
        f"- Workflows: {view.workflows.workflow_count}",
        f"- Named queries: {view.queries.query_count}",
        f"- Pending buckets: {view.governance.total_pending_groups}",
        f"- Approved resolutions: {view.governance.total_resolutions}",
        "",
        "## Entity Types",
        "",
        _markdown_table(
            ("Entity", "Primary Key", "Properties", "Description"),
            [
                (
                    entity.name,
                    entity.primary_key or "",
                    str(entity.property_count),
                    entity.description or "",
                )
                for entity in view.ontology.entity_types
            ],
        ),
        "",
        "## Relationship Map",
        "",
        "```mermaid",
        render_ontology_mermaid(view.ontology),
        "```",
        "",
        "### Deterministic Relationships",
        "",
        _markdown_table(
            ("Relationship", "From", "To", "Instances"),
            [
                (
                    rel.name,
                    rel.from_entity,
                    rel.to_entity,
                    "" if rel.instance_count is None else str(rel.instance_count),
                )
                for rel in deterministic
            ],
        ),
        "",
        "### Governed Relationships",
        "",
        _markdown_table(
            ("Relationship", "From", "To", "Approved", "Pending", "Latest Trust"),
            [
                (
                    rel.name,
                    rel.from_entity,
                    rel.to_entity,
                    str(_governed_resolution_count(view.governance, rel.name)),
                    str(_governed_pending_count(view.governance, rel.name)),
                    _governed_latest_trust(view.governance, rel.name) or "",
                )
                for rel in governed
            ],
        ),
        "",
        "## Workflow Chain",
        "",
        "```mermaid",
        render_workflow_mermaid(view.workflows),
        "```",
        "",
        _markdown_table(
            ("Workflow", "Mode", "Produces", "Consumes"),
            [
                (
                    workflow.name,
                    workflow.mode,
                    ", ".join(workflow.proposes_relationships + workflow.applies_relationships),
                    ", ".join(workflow.consumes_relationships),
                )
                for workflow in view.workflows.workflows
            ],
        ),
        "",
        "## Query Surface",
        "",
        (
            "Queries are grouped by entry point so the surface reads like "
            "starting perspectives into the graph."
        ),
    ]

    for entry_point, queries_for_entry in query_groups:
        lines.extend(
            [
                "",
                f"### {entry_point}",
                "",
                _markdown_table(
                    ("Query", "Params", "Returns", "Traversal"),
                    [
                        (
                            query.name,
                            ", ".join(query.required_params),
                            query.returns,
                            " -> ".join(query.traversal_summary),
                        )
                        for query in queries_for_entry
                    ],
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## Governance State",
            "",
            _markdown_table(
                (
                    "Relationship",
                    "Auto-resolve",
                    "Prior Trust",
                    "Pending Groups",
                    "Approved Resolutions",
                    "Latest Trust",
                ),
                [
                    (
                        rel.relationship_type,
                        rel.auto_resolve_when,
                        rel.prior_trust_policy,
                        str(rel.pending_group_count),
                        str(rel.approved_resolution_count),
                        rel.latest_trust_status or "",
                    )
                    for rel in view.governance.relationships
                ],
            ),
        ]
    )

    if view.governance.pending_buckets:
        lines.extend(
            [
                "",
                "### Pending Buckets",
                "",
                _markdown_table(
                    ("Group ID", "Relationship", "Priority", "Members", "Thesis"),
                    [
                        (
                            bucket.group_id,
                            bucket.relationship_type,
                            bucket.review_priority,
                            str(bucket.member_count),
                            bucket.thesis_text,
                        )
                        for bucket in view.governance.pending_buckets
                    ],
                ),
            ]
        )

    return "\n".join(lines)


def _workflow_step_kind(step: WorkflowStepSchema) -> str:
    if step.query is not None:
        return "query"
    if step.provider is not None:
        return "provider"
    if step.assert_spec is not None:
        return "assert"
    if step.list_entities is not None:
        return "list_entities"
    if step.list_relationships is not None:
        return "list_relationships"
    if step.make_candidates is not None:
        return "make_candidates"
    if step.map_signals is not None:
        return "map_signals"
    if step.propose_relationship_group is not None:
        return "propose_relationship_group"
    if step.make_entities is not None:
        return "make_entities"
    if step.make_relationships is not None:
        return "make_relationships"
    if step.apply_entities is not None:
        return "apply_entities"
    if step.apply_relationships is not None:
        return "apply_relationships"
    return "unknown"


def _format_traversal_summary(
    relationships: list[str],
    direction: str,
    max_depth: int,
) -> str:
    rels = "|".join(relationships)
    if max_depth > 1:
        return f"{rels} ({direction}, depth={max_depth})"
    return f"{rels} ({direction})"


def _markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    header_row = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([header_row, divider, *body])


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _escape_mermaid_label(value: str) -> str:
    return value.replace('"', '\\"')


def _mermaid_id(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", raw)


def _group_queries_by_entry(
    queries: list[QuerySummaryView],
) -> list[tuple[str, list[QuerySummaryView]]]:
    grouped: dict[str, list[QuerySummaryView]] = {}
    for query in queries:
        grouped.setdefault(query.entry_point, []).append(query)
    return [
        (entry_point, sorted(items, key=lambda item: item.name))
        for entry_point, items in sorted(grouped.items())
    ]


def _governed_resolution_count(view: GovernanceView, relationship_name: str) -> int:
    for item in view.relationships:
        if item.relationship_type == relationship_name:
            return item.approved_resolution_count
    return 0


def _governed_pending_count(view: GovernanceView, relationship_name: str) -> int:
    for item in view.relationships:
        if item.relationship_type == relationship_name:
            return item.pending_group_count
    return 0


def _governed_latest_trust(view: GovernanceView, relationship_name: str) -> str | None:
    for item in view.relationships:
        if item.relationship_type == relationship_name:
            return item.latest_trust_status
    return None
