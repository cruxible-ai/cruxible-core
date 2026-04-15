"""Deterministic Markdown wiki generation from local world state."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cruxible_core.config.schema import (
    CoreConfig,
    EntityTypeSchema,
    NamedQuerySchema,
    ProviderSchema,
    RelationshipSchema,
    WorkflowSchema,
)
from cruxible_core.feedback.types import FeedbackRecord, OutcomeRecord
from cruxible_core.graph.types import EntityInstance
from cruxible_core.group.types import CandidateGroup, CandidateMember
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.provider.types import ExecutionTrace
from cruxible_core.receipt.types import Receipt

MAX_STORE_SCAN = 10_000
MANIFEST_NAME = ".cruxible-manifest.json"
DISPLAY_PROPERTY_PREFERENCE = (
    "name",
    "title",
    "hostname",
    "cve_id",
    "product_name",
    "vendor_name",
    "service_id",
    "owner_id",
    "asset_id",
    "exception_id",
    "control_id",
    "patch_window_id",
)


@dataclass(frozen=True, order=True)
class SubjectRef:
    """Stable identifier for one rendered subject page."""

    entity_type: str
    entity_id: str

    @property
    def key(self) -> str:
        return f"{self.entity_type}:{self.entity_id}"


@dataclass(frozen=True)
class WikiOptions:
    """High-level render options."""

    output_dir: Path
    focus: tuple[SubjectRef, ...] = ()
    include_types: tuple[str, ...] = ()
    all_subjects: bool = False


def render_wiki(instance: InstanceProtocol, options: WikiOptions) -> list[Path]:
    """Render a deterministic Markdown wiki to ``options.output_dir``."""
    pages = build_wiki_pages(instance, options)
    return write_wiki_pages(options.output_dir, pages)


def build_wiki_pages(instance: InstanceProtocol, options: WikiOptions) -> dict[Path, str]:
    """Build wiki pages without writing them to disk."""
    generator = _WikiGenerator(instance)
    return generator.build_pages(options)


def write_wiki_pages(output_dir: Path, pages: dict[Path, str]) -> list[Path]:
    """Write wiki pages to disk with manifest cleanup."""
    return _write_pages(output_dir, pages)


class _WikiGenerator:
    """Collect and render wiki pages from instance state."""

    def __init__(self, instance: InstanceProtocol) -> None:
        self.instance = instance
        self.config = instance.load_config()
        self.graph = instance.load_graph()
        self.head_snapshot_id = instance.get_head_snapshot_id()
        self.subject_entities = {
            SubjectRef(entity.entity_type, entity.entity_id): entity
            for entity in self.graph.iter_all_entities()
        }
        self.relationships_by_name = {
            relationship.name: relationship for relationship in self.config.relationships
        }

        self.receipts = self._load_receipts()
        self.receipt_index = self._build_receipt_index(self.receipts.values())
        self.feedback_records = self._load_feedback()
        self.feedback_by_subject = self._build_feedback_index(self.feedback_records)
        (
            self.groups,
            self.members_by_group,
            self.groups_by_subject,
            self.resolutions_by_id,
        ) = self._load_groups()
        self.outcomes = self._load_outcomes()
        self.outcomes_by_receipt = self._build_outcomes_by_receipt(self.outcomes)
        self.outcomes_by_resolution = self._build_outcomes_by_resolution(self.outcomes)
        self.traces = self._load_traces()

    def build_pages(self, options: WikiOptions) -> dict[Path, str]:
        subjects = self._select_subjects(options)
        rendered_subjects = set(subjects)
        receipt_ids = self._collect_receipt_ids(subjects)
        query_names = self._collect_query_names(receipt_ids)
        workflow_names = self._collect_workflow_names(receipt_ids, subjects)
        provider_names = self._collect_provider_names(receipt_ids)

        pages: dict[Path, str] = {}
        pages[Path("index.md")] = self._render_index_page(
            subjects,
            query_names=query_names,
            workflow_names=workflow_names,
            provider_names=provider_names,
        )
        pages[Path("governance") / "pending-review.md"] = self._render_pending_review_page(
            rendered_subjects
        )
        pages[Path("governance") / "recent-decisions.md"] = self._render_recent_decisions_page(
            rendered_subjects
        )
        pages[Path("governance") / "recent-outcomes.md"] = self._render_recent_outcomes_page(
            rendered_subjects
        )

        for subject in subjects:
            pages[self._subject_path(subject)] = self._render_subject_page(
                subject,
                rendered_subjects=rendered_subjects,
            )

        for receipt_id in receipt_ids:
            receipt = self.receipts.get(receipt_id)
            if receipt is None:
                continue
            pages[self._receipt_path(receipt_id)] = self._render_receipt_page(
                receipt,
                rendered_subjects=rendered_subjects,
            )

        for query_name in sorted(query_names):
            schema = self.config.named_queries.get(query_name)
            if schema is None:
                continue
            pages[self._query_path(query_name)] = self._render_query_page(query_name, schema)

        for workflow_name in sorted(workflow_names):
            schema = self.config.workflows.get(workflow_name)
            if schema is None:
                continue
            pages[self._workflow_path(workflow_name)] = self._render_workflow_page(
                workflow_name,
                schema,
            )

        for provider_name in sorted(provider_names):
            schema = self.config.providers.get(provider_name)
            if schema is None:
                continue
            pages[self._provider_path(provider_name)] = self._render_provider_page(
                provider_name,
                schema,
            )

        return pages

    def _load_receipts(self) -> dict[str, Receipt]:
        store = self.instance.get_receipt_store()
        try:
            summaries = store.list_receipts(limit=MAX_STORE_SCAN)
            receipts: dict[str, Receipt] = {}
            for summary in summaries:
                receipt_id = str(summary["receipt_id"])
                receipt = store.get_receipt(receipt_id)
                if receipt is not None:
                    receipts[receipt.receipt_id] = receipt
            return receipts
        finally:
            store.close()

    def _load_feedback(self) -> list[FeedbackRecord]:
        store = self.instance.get_feedback_store()
        try:
            return store.list_feedback(limit=MAX_STORE_SCAN)
        finally:
            store.close()

    def _load_groups(
        self,
    ) -> tuple[
        list[CandidateGroup],
        dict[str, list[CandidateMember]],
        dict[str, list[CandidateGroup]],
        dict[str, dict[str, Any]],
    ]:
        store = self.instance.get_group_store()
        try:
            groups = store.list_groups(limit=MAX_STORE_SCAN)
            members_by_group: dict[str, list[CandidateMember]] = {}
            groups_by_subject: dict[str, list[CandidateGroup]] = defaultdict(list)
            seen_per_subject: dict[str, set[str]] = defaultdict(set)
            for group in groups:
                members = store.get_members(group.group_id)
                members_by_group[group.group_id] = members
                for member in members:
                    for key in (
                        f"{member.from_type}:{member.from_id}",
                        f"{member.to_type}:{member.to_id}",
                    ):
                        if group.group_id not in seen_per_subject[key]:
                            seen_per_subject[key].add(group.group_id)
                            groups_by_subject[key].append(group)
            resolutions = {
                record["resolution_id"]: record
                for record in store.list_resolutions(limit=MAX_STORE_SCAN)
            }
            return groups, members_by_group, groups_by_subject, resolutions
        finally:
            store.close()

    def _load_outcomes(self) -> list[OutcomeRecord]:
        store = self.instance.get_feedback_store()
        try:
            return store.list_outcomes(limit=MAX_STORE_SCAN)
        finally:
            store.close()

    def _load_traces(self) -> dict[str, ExecutionTrace]:
        trace_ids: set[str] = set()
        for receipt in self.receipts.values():
            trace_ids.update(_extract_trace_ids_from_receipt(receipt))
        for group in self.groups:
            trace_ids.update(group.source_trace_ids)
        for outcome in self.outcomes:
            trace_ids.update(_extract_trace_ids_from_lineage(outcome.lineage_snapshot))

        store = self.instance.get_receipt_store()
        try:
            traces: dict[str, ExecutionTrace] = {}
            for trace_id in sorted(trace_ids):
                trace = store.get_trace(trace_id)
                if trace is not None:
                    traces[trace.trace_id] = trace
            return traces
        finally:
            store.close()

    def _build_receipt_index(self, receipts: Any) -> dict[str, set[str]]:
        index: dict[str, set[str]] = defaultdict(set)
        for receipt in receipts:
            for ref in _entity_refs_from_receipt(receipt):
                index[ref.key].add(receipt.receipt_id)
        return index

    def _build_feedback_index(
        self,
        feedback_records: list[FeedbackRecord],
    ) -> dict[str, list[FeedbackRecord]]:
        index: dict[str, list[FeedbackRecord]] = defaultdict(list)
        for record in feedback_records:
            index[f"{record.target.from_type}:{record.target.from_id}"].append(record)
            index[f"{record.target.to_type}:{record.target.to_id}"].append(record)
        return index

    def _build_outcomes_by_receipt(
        self,
        outcomes: list[OutcomeRecord],
    ) -> dict[str, list[OutcomeRecord]]:
        index: dict[str, list[OutcomeRecord]] = defaultdict(list)
        for outcome in outcomes:
            index[outcome.receipt_id].append(outcome)
        return index

    def _build_outcomes_by_resolution(
        self,
        outcomes: list[OutcomeRecord],
    ) -> dict[str, list[OutcomeRecord]]:
        index: dict[str, list[OutcomeRecord]] = defaultdict(list)
        for outcome in outcomes:
            if outcome.anchor_type == "resolution" and outcome.anchor_id:
                index[outcome.anchor_id].append(outcome)
        return index

    def _select_subjects(self, options: WikiOptions) -> list[SubjectRef]:
        include_types = set(options.include_types)
        subjects: set[SubjectRef] = set()

        if options.focus:
            for focus in options.focus:
                if focus not in self.subject_entities:
                    continue
                subjects.add(focus)
                inspect = self.graph.get_neighbor_relationships(
                    focus.entity_type,
                    focus.entity_id,
                    direction="both",
                )
                for row in inspect:
                    neighbor = row.get("entity")
                    if isinstance(neighbor, EntityInstance):
                        subjects.add(SubjectRef(neighbor.entity_type, neighbor.entity_id))
        elif options.all_subjects:
            subjects = set(self.subject_entities)
        else:
            for key in self.receipt_index:
                subjects.add(_subject_ref_from_key(key))
            for key in self.feedback_by_subject:
                subjects.add(_subject_ref_from_key(key))
            for key in self.groups_by_subject:
                subjects.add(_subject_ref_from_key(key))
            if not subjects:
                subjects = set(self.subject_entities)

        subjects = {subject for subject in subjects if subject in self.subject_entities}
        if include_types:
            subjects = {subject for subject in subjects if subject.entity_type in include_types}
        return sorted(subjects)

    def _collect_receipt_ids(self, subjects: list[SubjectRef]) -> set[str]:
        receipt_ids: set[str] = set()
        for subject in subjects:
            receipt_ids.update(self.receipt_index.get(subject.key, set()))
            for group in self.groups_by_subject.get(subject.key, []):
                if group.source_workflow_receipt_id:
                    receipt_ids.add(group.source_workflow_receipt_id)
        return receipt_ids

    def _collect_query_names(self, receipt_ids: set[str]) -> set[str]:
        return {
            receipt.query_name
            for receipt_id in receipt_ids
            for receipt in [self.receipts.get(receipt_id)]
            if receipt is not None and receipt.operation_type == "query"
        }

    def _collect_workflow_names(
        self,
        receipt_ids: set[str],
        subjects: list[SubjectRef],
    ) -> set[str]:
        workflow_names = {
            receipt.query_name
            for receipt_id in receipt_ids
            for receipt in [self.receipts.get(receipt_id)]
            if receipt is not None and receipt.operation_type == "workflow"
        }
        for subject in subjects:
            for group in self.groups_by_subject.get(subject.key, []):
                if group.source_workflow_name:
                    workflow_names.add(group.source_workflow_name)
        return workflow_names

    def _collect_provider_names(self, receipt_ids: set[str]) -> set[str]:
        provider_names: set[str] = set()
        for receipt_id in receipt_ids:
            receipt = self.receipts.get(receipt_id)
            if receipt is None:
                continue
            for node in receipt.nodes:
                if node.node_type != "plan_step":
                    continue
                provider_name = str(node.detail.get("provider_name", "")).strip()
                if provider_name:
                    provider_names.add(provider_name)
        return provider_names

    def _subject_receipts(self, subject: SubjectRef) -> list[Receipt]:
        receipt_ids = sorted(self.receipt_index.get(subject.key, set()))
        receipts = [
            self.receipts[receipt_id] for receipt_id in receipt_ids if receipt_id in self.receipts
        ]
        return sorted(receipts, key=lambda receipt: receipt.created_at, reverse=True)

    def _subject_outcomes(self, subject: SubjectRef) -> list[OutcomeRecord]:
        receipt_ids = self.receipt_index.get(subject.key, set())
        resolution_ids = {
            group.resolution_id
            for group in self.groups_by_subject.get(subject.key, [])
            if group.resolution_id
        }
        outcomes: list[OutcomeRecord] = []
        for receipt_id in receipt_ids:
            outcomes.extend(self.outcomes_by_receipt.get(receipt_id, []))
        for resolution_id in resolution_ids:
            outcomes.extend(self.outcomes_by_resolution.get(resolution_id, []))
        return sorted(outcomes, key=lambda record: record.created_at, reverse=True)

    def _subject_path(self, subject: SubjectRef) -> Path:
        return (
            Path("subjects") / _slugify(subject.entity_type) / f"{_slugify(subject.entity_id)}.md"
        )

    def _receipt_path(self, receipt_id: str) -> Path:
        return Path("evidence") / "receipts" / f"{_slugify(receipt_id)}.md"

    def _query_path(self, query_name: str) -> Path:
        return Path("reference") / "queries" / f"{_slugify(query_name)}.md"

    def _workflow_path(self, workflow_name: str) -> Path:
        return Path("reference") / "workflows" / f"{_slugify(workflow_name)}.md"

    def _provider_path(self, provider_name: str) -> Path:
        return Path("reference") / "providers" / f"{_slugify(provider_name)}.md"

    def _render_index_page(
        self,
        subjects: list[SubjectRef],
        *,
        query_names: set[str],
        workflow_names: set[str],
        provider_names: set[str],
    ) -> str:
        lines = [f"# {self.config.name} Wiki", ""]
        if self.config.description:
            lines.extend([self.config.description.strip(), ""])
        lines.append("## World")
        lines.append(f"- Kind: {self.config.kind}")
        if self.head_snapshot_id:
            lines.append(f"- Head snapshot: {self.head_snapshot_id}")
        lines.append(f"- Rendered subjects: {len(subjects)}")
        lines.append("")

        lines.append("## Subject Index")
        grouped: dict[str, list[SubjectRef]] = defaultdict(list)
        for subject in subjects:
            grouped[subject.entity_type].append(subject)
        for entity_type in sorted(grouped):
            lines.append(f"### {_humanize(entity_type)}")
            for subject in sorted(grouped[entity_type]):
                entity = self.subject_entities[subject]
                subject_link = _relpath(Path("index.md"), self._subject_path(subject))
                lines.append(f"- [{_display_label(entity, self.config)}]({subject_link})")
            lines.append("")

        lines.append("## Governance")
        lines.append("- [Pending review](governance/pending-review.md)")
        lines.append("- [Recent decisions](governance/recent-decisions.md)")
        lines.append("- [Recent outcomes](governance/recent-outcomes.md)")
        lines.append("")

        if query_names or workflow_names or provider_names:
            lines.append("## Reference")
            for query_name in sorted(query_names):
                query_link = _relpath(Path("index.md"), self._query_path(query_name))
                lines.append(f"- [Query: {query_name}]({query_link})")
            for workflow_name in sorted(workflow_names):
                workflow_link = _relpath(Path("index.md"), self._workflow_path(workflow_name))
                lines.append(f"- [Workflow: {workflow_name}]({workflow_link})")
            for provider_name in sorted(provider_names):
                provider_link = _relpath(Path("index.md"), self._provider_path(provider_name))
                lines.append(f"- [Provider: {provider_name}]({provider_link})")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def _render_subject_page(
        self,
        subject: SubjectRef,
        *,
        rendered_subjects: set[SubjectRef],
    ) -> str:
        entity = self.subject_entities[subject]
        entity_schema = self.config.get_entity_type(subject.entity_type)
        receipts = self._subject_receipts(subject)
        feedback_records = sorted(
            self.feedback_by_subject.get(subject.key, []),
            key=lambda record: record.created_at,
            reverse=True,
        )
        groups = sorted(
            self.groups_by_subject.get(subject.key, []),
            key=lambda group: group.created_at,
            reverse=True,
        )
        outcomes = self._subject_outcomes(subject)

        lines = [f"# {_display_label(entity, self.config)}", ""]
        lines.extend(self._render_record_section(subject, entity, entity_schema))
        lines.extend(self._render_world_state_section(subject, rendered_subjects))
        lines.extend(self._render_production_section(subject, receipts, rendered_subjects))
        lines.extend(self._render_conclusions_section(subject, groups, rendered_subjects))
        lines.extend(
            self._render_review_history_section(
                subject, feedback_records, groups, rendered_subjects
            )
        )
        lines.extend(self._render_outcome_history_section(outcomes))
        lines.extend(
            self._render_full_evidence_section(self._subject_path(subject), receipts)
        )
        return "\n".join(lines).rstrip() + "\n"

    def _render_record_section(
        self,
        subject: SubjectRef,
        entity: EntityInstance,
        entity_schema: EntityTypeSchema | None,
    ) -> list[str]:
        lines = [
            "## Record",
            f"- Type: {_humanize(subject.entity_type)}",
            f"- ID: {subject.entity_id}",
        ]
        if entity_schema and entity_schema.description:
            lines.append(f"- Description: {entity_schema.description.strip()}")
        for key, value in _sorted_properties(entity.properties).items():
            lines.append(f"- {key}: {_render_scalar(value)}")
        lines.append("")
        return lines

    def _render_world_state_section(
        self,
        subject: SubjectRef,
        rendered_subjects: set[SubjectRef],
    ) -> list[str]:
        inspect_rows = self.graph.get_neighbor_relationships(
            subject.entity_type,
            subject.entity_id,
            direction="both",
        )
        if not inspect_rows:
            return ["## Current World State", "- No linked records found.", ""]

        groups: dict[
            str, list[tuple[EntityInstance, RelationshipSchema | None, dict[str, Any]]]
        ] = defaultdict(list)
        for row in inspect_rows:
            neighbor = row.get("entity")
            if not isinstance(neighbor, EntityInstance):
                continue
            relationship_type = str(row.get("relationship_type"))
            relationship_schema = self.relationships_by_name.get(relationship_type)
            groups[neighbor.entity_type].append(
                (neighbor, relationship_schema, dict(row.get("properties", {})))
            )

        lines = ["## Current World State"]
        for entity_type in sorted(groups):
            items = sorted(
                groups[entity_type], key=lambda item: _display_label(item[0], self.config)
            )
            rendered_items = [
                item for item in items
                if SubjectRef(item[0].entity_type, item[0].entity_id) in rendered_subjects
            ]
            other_count = len(items) - len(rendered_items)

            if not rendered_items and other_count:
                lines.append(f"### {_humanize(entity_type)}")
                lines.append(f"- {other_count} linked record(s) outside current scope")
                lines.append("")
                continue

            lines.append(f"### {_humanize(entity_type)}")
            for neighbor, relationship_schema, properties in rendered_items:
                link = self._subject_markdown_link(
                    SubjectRef(neighbor.entity_type, neighbor.entity_id),
                    current_path=self._subject_path(subject),
                    rendered_subjects=rendered_subjects,
                )
                description = (
                    relationship_schema.description.strip()
                    if relationship_schema and relationship_schema.description
                    else None
                )
                line = f"- {link}"
                if description:
                    line += f" — {description}"
                lines.append(line)
                lines.extend(_render_property_bullets(properties))
            if other_count:
                lines.append(f"- +{other_count} more outside current scope")
            lines.append("")
        return lines

    def _render_production_section(
        self,
        subject: SubjectRef,
        receipts: list[Receipt],
        rendered_subjects: set[SubjectRef],
    ) -> list[str]:
        if not receipts:
            return ["## How This Was Produced", "- No receipts mention this subject yet.", ""]

        lines = ["## How This Was Produced"]
        workflow_receipts = [
            receipt for receipt in receipts if receipt.operation_type == "workflow"
        ]
        query_receipts = [receipt for receipt in receipts if receipt.operation_type == "query"]

        for receipt in workflow_receipts:
            lines.append(f"### Workflow: {receipt.query_name}")
            workflow_schema = self.config.workflows.get(receipt.query_name)
            if workflow_schema and workflow_schema.description:
                lines.append(f"- {workflow_schema.description.strip()}")
            receipt_link = _relpath(
                self._subject_path(subject),
                self._receipt_path(receipt.receipt_id),
            )
            lines.append(f"- Receipt: [{receipt.receipt_id}]({receipt_link})")
            provider_nodes = [
                node
                for node in receipt.nodes
                if node.node_type == "plan_step" and node.detail.get("kind") == "provider"
            ]
            if provider_nodes:
                for node in provider_nodes:
                    provider_name = str(node.detail.get("provider_name", "")).strip()
                    trace_id = str(node.detail.get("trace_id", "")).strip()
                    provider_href = _relpath(
                        self._subject_path(subject),
                        self._provider_path(provider_name),
                    )
                    provider_ref = (
                        f"[{provider_name}]({provider_href})"
                        if provider_name in self.config.providers
                        else provider_name or "unknown provider"
                    )
                    line = f"- Provider: {provider_ref}"
                    if trace_id and trace_id in self.traces:
                        trace = self.traces[trace_id]
                        if trace.provider_version:
                            line += f" (version {trace.provider_version})"
                        if trace.artifact_name:
                            line += f"; artifact {trace.artifact_name}"
                    lines.append(line)
            else:
                lines.append("- No provider steps recorded on this receipt.")
            lines.append("")

        for receipt in query_receipts:
            lines.append(f"### Query: {receipt.query_name}")
            query_schema = self.config.named_queries.get(receipt.query_name)
            if query_schema and query_schema.description:
                lines.append(f"- {query_schema.description.strip()}")
            receipt_link = _relpath(
                self._subject_path(subject),
                self._receipt_path(receipt.receipt_id),
            )
            lines.append(f"- Receipt: [{receipt.receipt_id}]({receipt_link})")
            result_refs = _entity_refs_from_results(receipt.results)
            if result_refs:
                lines.append("- Records returned:")
                for ref in sorted(result_refs)[:10]:
                    result_link = self._subject_markdown_link(
                        ref,
                        current_path=self._subject_path(subject),
                        rendered_subjects=rendered_subjects,
                    )
                    lines.append(f"  - {result_link}")
            lines.append("")

        return lines

    def _render_conclusions_section(
        self,
        subject: SubjectRef,
        groups: list[CandidateGroup],
        rendered_subjects: set[SubjectRef],
    ) -> list[str]:
        lines = ["## Conclusions Recorded"]
        current_groups: list[list[str]] = []
        inspect_rows = self.graph.get_neighbor_relationships(
            subject.entity_type,
            subject.entity_id,
            direction="both",
        )
        for row in inspect_rows:
            relationship_type = str(row.get("relationship_type"))
            relationship_schema = self.relationships_by_name.get(relationship_type)
            if relationship_schema is None or relationship_schema.matching is None:
                continue
            neighbor = row.get("entity")
            if not isinstance(neighbor, EntityInstance):
                continue
            neighbor_ref = SubjectRef(neighbor.entity_type, neighbor.entity_id)
            neighbor_link = self._subject_markdown_link(
                neighbor_ref,
                current_path=self._subject_path(subject),
                rendered_subjects=rendered_subjects,
            )
            subject_link = self._subject_markdown_link(
                subject,
                current_path=self._subject_path(subject),
                rendered_subjects=rendered_subjects,
            )
            if row.get("direction") == "outgoing":
                line = f"- {subject_link} →({relationship_type}) {neighbor_link}"
            else:
                line = f"- {neighbor_link} →({relationship_type}) {subject_link}"
            if relationship_schema.description:
                line += f" — {relationship_schema.description.strip()}"
            group = [line]
            group.extend(_render_property_bullets(dict(row.get("properties", {}))))
            current_groups.append(group)

        if current_groups:
            lines.append("### Current Accepted Records")
            for group in sorted(current_groups, key=lambda g: g[0]):
                lines.extend(group)
            lines.append("")

        seen_pending_ids: set[str] = set()
        pending_groups: list[CandidateGroup] = []
        for group in groups:
            if group.status == "pending_review" and group.group_id not in seen_pending_ids:
                seen_pending_ids.add(group.group_id)
                pending_groups.append(group)
        if pending_groups:
            lines.append("### Pending Review")
            for group in pending_groups:
                members = self.members_by_group.get(group.group_id, [])
                if members:
                    for member in sorted(members, key=lambda m: (m.from_id, m.to_id)):
                        from_ref = SubjectRef(member.from_type, member.from_id)
                        to_ref = SubjectRef(member.to_type, member.to_id)
                        from_link = self._subject_markdown_link(
                            from_ref,
                            current_path=self._subject_path(subject),
                            rendered_subjects=rendered_subjects,
                        )
                        to_link = self._subject_markdown_link(
                            to_ref,
                            current_path=self._subject_path(subject),
                            rendered_subjects=rendered_subjects,
                        )
                        line = f"- {from_link} →({group.relationship_type}) {to_link}"
                        if group.thesis_text:
                            line += f" — {group.thesis_text.strip()}"
                        lines.append(line)
                else:
                    line = f"- {group.relationship_type}"
                    if group.thesis_text:
                        line += f" — {group.thesis_text.strip()}"
                    lines.append(line)
                if group.source_workflow_name:
                    wf_link = _relpath(
                        self._subject_path(subject),
                        self._workflow_path(group.source_workflow_name),
                    )
                    lines.append(
                        f"  Source: [{group.source_workflow_name}]({wf_link})"
                    )
            lines.append("")

        if not current_groups and not pending_groups:
            lines.append("- No governed conclusions recorded yet.")
            lines.append("")
        return lines

    def _render_review_history_section(
        self,
        subject: SubjectRef,
        feedback_records: list[FeedbackRecord],
        groups: list[CandidateGroup],
        rendered_subjects: set[SubjectRef],
    ) -> list[str]:
        lines = ["## Review History"]
        emitted = False

        seen_resolution_ids: set[str] = set()
        resolved_groups: list[CandidateGroup] = []
        for group in groups:
            if group.resolution_id and group.resolution_id not in seen_resolution_ids:
                seen_resolution_ids.add(group.resolution_id)
                resolved_groups.append(group)
        if resolved_groups:
            lines.append("### Resolutions")
            emitted = True
            for group in resolved_groups:
                resolution = self.resolutions_by_id.get(group.resolution_id or "")
                if resolution is None:
                    continue
                line = f"- {resolution['action']} on {group.relationship_type}"
                if resolution.get("trust_status"):
                    line += f" (trust: {resolution['trust_status']})"
                if resolution.get("rationale"):
                    line += f" — {resolution['rationale']}"
                members = self.members_by_group.get(group.group_id, [])
                if members:
                    member_labels = []
                    for member in members[:3]:
                        counterpart = _counterpart_for_subject(subject, member)
                        if counterpart is not None:
                            member_labels.append(
                                self._subject_markdown_link(
                                    counterpart,
                                    current_path=self._subject_path(subject),
                                    rendered_subjects=rendered_subjects,
                                )
                            )
                    if member_labels:
                        line += f" [subjects: {', '.join(member_labels)}]"
                lines.append(line)
            lines.append("")

        if feedback_records:
            lines.append("### Feedback")
            emitted = True
            for record in feedback_records:
                counterpart = SubjectRef(record.target.to_type, record.target.to_id)
                if counterpart == subject:
                    counterpart = SubjectRef(record.target.from_type, record.target.from_id)
                counterpart_label = self._subject_markdown_link(
                    counterpart,
                    current_path=self._subject_path(subject),
                    rendered_subjects=rendered_subjects,
                )
                line = f"- {record.action} involving {counterpart_label}"
                if record.reason_code:
                    line += f" (code: {record.reason_code})"
                if record.reason:
                    line += f" — {record.reason}"
                lines.append(line)
            lines.append("")

        if not emitted:
            lines.append("- No feedback, candidate groups, or resolutions recorded yet.")
            lines.append("")
        return lines

    def _render_outcome_history_section(self, outcomes: list[OutcomeRecord]) -> list[str]:
        lines = ["## Outcome History"]
        if not outcomes:
            lines.append("- No outcome records linked yet.")
            lines.append("")
            return lines

        receipt_outcomes = [outcome for outcome in outcomes if outcome.anchor_type == "receipt"]
        resolution_outcomes = [
            outcome for outcome in outcomes if outcome.anchor_type == "resolution"
        ]

        if receipt_outcomes:
            lines.append("### Receipt-Anchored Outcomes")
            for outcome in receipt_outcomes:
                line = f"- {outcome.outcome}"
                surface_name = str(outcome.decision_context.get("surface_name", "")).strip()
                if surface_name:
                    line += f" on {surface_name}"
                if outcome.outcome_code:
                    line += f" (code: {outcome.outcome_code})"
                provider_names = _extract_provider_names_from_lineage(outcome.lineage_snapshot)
                if provider_names:
                    line += f" [providers: {', '.join(provider_names)}]"
                lines.append(line)
            lines.append("")

        if resolution_outcomes:
            lines.append("### Resolution-Anchored Outcomes")
            for outcome in resolution_outcomes:
                line = f"- {outcome.outcome}"
                if outcome.relationship_type:
                    line += f" on {outcome.relationship_type}"
                if outcome.outcome_code:
                    line += f" (code: {outcome.outcome_code})"
                provider_names = _extract_provider_names_from_lineage(outcome.lineage_snapshot)
                if provider_names:
                    line += f" [providers: {', '.join(provider_names)}]"
                lines.append(line)
            lines.append("")

        return lines

    def _render_full_evidence_section(
        self,
        current_path: Path,
        receipts: list[Receipt],
    ) -> list[str]:
        lines = ["## Full Evidence"]
        if receipts:
            for receipt in receipts:
                receipt_link = _relpath(current_path, self._receipt_path(receipt.receipt_id))
                lines.append(f"- [{receipt.receipt_id}]({receipt_link})")
            lines.append("")
        else:
            lines.append("- No evidence pages linked yet.")
            lines.append("")
        return lines

    def _render_receipt_page(
        self,
        receipt: Receipt,
        *,
        rendered_subjects: set[SubjectRef],
    ) -> str:
        operation_label = (
            "Query"
            if receipt.operation_type == "query"
            else "Workflow"
            if receipt.operation_type == "workflow"
            else "Operation"
        )
        lines = [f"# Receipt {receipt.receipt_id}", "", "## Summary"]
        lines.append(f"- {operation_label}: {receipt.query_name or receipt.operation_type}")
        lines.append(f"- Created at: {receipt.created_at.isoformat()}")
        lines.append(f"- Duration: {receipt.duration_ms}ms")
        lines.append(
            f"- Parameters: `{json.dumps(receipt.parameters, sort_keys=True, default=str)}`"
        )
        lines.append("")

        entity_refs = _entity_refs_from_receipt(receipt)
        if entity_refs:
            by_type: dict[str, int] = defaultdict(int)
            for ref in entity_refs:
                by_type[ref.entity_type] += 1
            lines.append("## Scope")
            for etype in sorted(by_type):
                lines.append(f"- {_humanize(etype)}: {by_type[etype]}")
            lines.append("")

        checks = self._render_receipt_checks(receipt)
        if checks:
            lines.append("## Checks Applied")
            lines.extend(checks)
            lines.append("")

        steps = self._render_receipt_steps(receipt)
        if steps:
            lines.append("## Workflow Steps")
            lines.extend(steps)
            lines.append("")

        changes = self._render_receipt_changes(receipt)
        if changes:
            lines.append("## Changes Recorded")
            lines.extend(changes)
            lines.append("")

        lines.extend(self._render_receipt_results(receipt, rendered_subjects))
        return "\n".join(lines).rstrip() + "\n"

    def _render_receipt_checks(self, receipt: Receipt) -> list[str]:
        lines: list[str] = []
        for node in receipt.nodes:
            if node.node_type == "filter_applied":
                status = "passed" if node.detail.get("passed") else "failed"
                filter_json = json.dumps(node.detail.get("filter", {}), sort_keys=True)
                lines.append(f"- Filter {status}: `{filter_json}`")
            elif node.node_type == "constraint_check":
                status = "passed" if node.detail.get("passed") else "failed"
                lines.append(f"- Constraint {status}: {node.detail.get('constraint', '')}")
            elif node.node_type == "validation":
                status = "passed" if node.detail.get("passed") else "failed"
                message = str(node.detail.get("message", "")).strip()
                line = f"- Validation {status}"
                if message:
                    line += f": {message}"
                lines.append(line)
        return lines

    def _render_receipt_steps(self, receipt: Receipt) -> list[str]:
        lines: list[str] = []
        for node in receipt.nodes:
            if node.node_type != "plan_step":
                continue
            step_id = str(node.detail.get("step_id", "")).strip() or node.node_id
            kind = str(node.detail.get("kind", "")).strip() or "step"
            line = f"- {step_id}: {kind}"
            provider_name = str(node.detail.get("provider_name", "")).strip()
            if provider_name:
                line += f" ({provider_name})"
            lines.append(line)
        return lines

    def _render_receipt_changes(self, receipt: Receipt) -> list[str]:
        entity_adds: dict[str, int] = defaultdict(int)
        entity_updates: dict[str, int] = defaultdict(int)
        rel_adds: dict[str, int] = defaultdict(int)
        rel_updates: dict[str, int] = defaultdict(int)
        other_lines: list[str] = []

        for node in receipt.nodes:
            if node.node_type == "entity_write":
                etype = node.entity_type or "unknown"
                if node.detail.get("is_update"):
                    entity_updates[etype] += 1
                else:
                    entity_adds[etype] += 1
            elif node.node_type == "relationship_write":
                rtype = str(node.detail.get("relationship", "unknown"))
                if node.detail.get("is_update"):
                    rel_updates[rtype] += 1
                else:
                    rel_adds[rtype] += 1
            elif node.node_type == "feedback_applied":
                status = "applied" if node.detail.get("applied") else "not applied"
                other_lines.append(f"- Feedback {status}: {node.detail.get('action', '')}")
            elif node.node_type == "ingest_batch":
                mapping = node.detail.get("mapping", "")
                added = node.detail.get("added", 0)
                updated = node.detail.get("updated", 0)
                other_lines.append(
                    f"- Ingestion batch: {mapping} (added={added}, updated={updated})"
                )

        lines: list[str] = []
        for etype in sorted(entity_adds):
            lines.append(f"- {_humanize(etype)} added: {entity_adds[etype]}")
        for etype in sorted(entity_updates):
            lines.append(f"- {_humanize(etype)} updated: {entity_updates[etype]}")
        for rtype in sorted(rel_adds):
            lines.append(f"- {rtype} links added: {rel_adds[rtype]}")
        for rtype in sorted(rel_updates):
            lines.append(f"- {rtype} links updated: {rel_updates[rtype]}")
        lines.extend(other_lines)
        return lines

    def _render_receipt_results(
        self,
        receipt: Receipt,
        rendered_subjects: set[SubjectRef],
    ) -> list[str]:
        lines = ["## Results"]
        if not receipt.results:
            lines.append("- No results recorded.")
            lines.append("")
            return lines

        entity_refs = _entity_refs_from_results(receipt.results)
        if entity_refs:
            by_type: dict[str, int] = defaultdict(int)
            for ref in entity_refs:
                by_type[ref.entity_type] += 1
            for etype in sorted(by_type):
                lines.append(f"- {_humanize(etype)}: {by_type[etype]}")
            lines.append("")
            return lines

        # Non-entity results: show compact JSON (capped to avoid bloat).
        result_json = json.dumps(receipt.results, indent=2, sort_keys=True, default=str)
        result_lines = result_json.splitlines()
        max_lines = 60
        lines.append("```json")
        lines.extend(result_lines[:max_lines])
        if len(result_lines) > max_lines:
            lines.append(f"  ... ({len(result_lines) - max_lines} more lines)")
        lines.append("```")
        lines.append("")
        return lines

    def _render_query_page(self, query_name: str, schema: NamedQuerySchema) -> str:
        lines = [f"# Reference: {query_name}", ""]
        if schema.description:
            lines.extend([schema.description.strip(), ""])
        lines.append("## Summary")
        lines.append(f"- Starting record type: {_humanize(schema.entry_point)}")
        lines.append(f"- Produces: {schema.returns}")
        lines.append("")

        lines.append("## Query Steps")
        for index, step in enumerate(schema.traversal, start=1):
            relationship_labels = []
            for relationship_name in step.relationship_types:
                relationship_schema = self.relationships_by_name.get(relationship_name)
                if relationship_schema and relationship_schema.description:
                    relationship_labels.append(
                        f"{relationship_name} ({relationship_schema.description.strip()})"
                    )
                else:
                    relationship_labels.append(relationship_name)
            relationships = ", ".join(relationship_labels)
            lines.append(
                f"- Step {index}: look for related records using {relationships} "
                f"(direction: {step.direction}, depth: {step.max_depth})"
            )
            if step.filter:
                lines.append(f"  Checks: `{json.dumps(step.filter, sort_keys=True, default=str)}`")
            if step.constraint:
                lines.append(f"  Constraint: {step.constraint}")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_workflow_page(self, workflow_name: str, schema: WorkflowSchema) -> str:
        lines = [f"# Workflow Reference: {workflow_name}", ""]
        if schema.description:
            lines.extend([schema.description.strip(), ""])
        lines.append("## Summary")
        lines.append(f"- Canonical: {schema.canonical}")
        lines.append("")

        lines.append("## Contracts")
        lines.extend(
            self._render_contract_subsection("Input", schema.contract_in)
        )
        returns_step = next(
            (step for step in schema.steps if step.id == schema.returns), None
        )
        lines.append("### Output")
        if returns_step is not None and returns_step.provider is not None:
            provider_schema = self.config.providers.get(returns_step.provider)
            if provider_schema is not None:
                out_contract = self.config.contracts.get(provider_schema.contract_out)
                if out_contract is not None and out_contract.fields:
                    for fn, fs in out_contract.fields.items():
                        line = f"- **{fn}** ({fs.type})"
                        if fs.description:
                            line += f" — {fs.description.strip()}"
                        lines.append(line)
                else:
                    lines.append(f"- Provider result from `{returns_step.provider}`")
            else:
                lines.append(f"- Provider result from `{returns_step.provider}`")
        elif returns_step is not None and returns_step.propose_relationship_group is not None:
            rtype = returns_step.propose_relationship_group.relationship_type
            lines.append(f"- Governed proposal for **{rtype}** relationships")
        elif returns_step is not None and returns_step.apply_relationships is not None:
            lines.append(f"- Applied relationships from step `{returns_step.apply_relationships.relationships_from}`")
        elif returns_step is not None and returns_step.apply_entities is not None:
            lines.append(f"- Applied entities from step `{returns_step.apply_entities.entities_from}`")
        else:
            lines.append(f"- Result of step `{schema.returns}`")
        lines.append("")

        lines.append("## Steps")
        for step in schema.steps:
            if step.provider is not None:
                lines.append(f"- {step.id}: call provider {step.provider}")
            elif step.query is not None:
                lines.append(f"- {step.id}: run query {step.query}")
            elif step.list_entities is not None:
                lines.append(
                    f"- {step.id}: list {_humanize(step.list_entities.entity_type)} records"
                )
            elif step.list_relationships is not None:
                relationship_type = step.list_relationships.relationship_type
                lines.append(f"- {step.id}: list recorded links of type {relationship_type}")
            elif step.make_candidates is not None:
                relationship_type = step.make_candidates.relationship_type
                lines.append(f"- {step.id}: build candidate links for {relationship_type}")
            elif step.map_signals is not None:
                lines.append(f"- {step.id}: map signals for {step.map_signals.integration}")
            elif step.propose_relationship_group is not None:
                lines.append(
                    f"- {step.id}: assemble review proposal for "
                    f"{step.propose_relationship_group.relationship_type}"
                )
            elif step.make_entities is not None:
                lines.append(
                    f"- {step.id}: build {_humanize(step.make_entities.entity_type)} records"
                )
            elif step.make_relationships is not None:
                lines.append(
                    f"- {step.id}: build links of type {step.make_relationships.relationship_type}"
                )
            elif step.apply_entities is not None:
                lines.append(f"- {step.id}: write records from {step.apply_entities.entities_from}")
            elif step.apply_relationships is not None:
                lines.append(
                    f"- {step.id}: write links from {step.apply_relationships.relationships_from}"
                )
            elif step.assert_spec is not None:
                lines.append(f"- {step.id}: check {step.assert_spec.message}")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_contract_subsection(self, label: str, contract_name: str) -> list[str]:
        """Render a ### Input or ### Output contract subsection."""
        lines = [f"### {label}"]
        contract = self.config.contracts.get(contract_name)
        if contract is not None and contract.fields:
            if contract.description:
                lines.append(contract.description.strip())
            for field_name, field_schema in contract.fields.items():
                parts = [f"**{field_name}**", f"({field_schema.type})"]
                if field_schema.optional:
                    parts.append("*optional*")
                if field_schema.default is not None:
                    parts.append(f"default: {field_schema.default}")
                if field_schema.enum is not None:
                    parts.append(f"one of: {', '.join(field_schema.enum)}")
                line = f"- {' '.join(parts)}"
                if field_schema.description:
                    line += f" — {field_schema.description.strip()}"
                lines.append(line)
        else:
            lines.append("- No fields required.")
        lines.append("")
        return lines

    def _render_provider_page(self, provider_name: str, schema: ProviderSchema) -> str:
        lines = [f"# Provider: {provider_name}", ""]
        if schema.description:
            lines.extend([schema.description.strip(), ""])
        lines.append("## Summary")
        lines.append(f"- Kind: {schema.kind}")
        lines.append(f"- Runtime: {schema.runtime}")
        lines.append(f"- Version: {schema.version}")
        lines.append(f"- Ref: `{schema.ref}`")
        lines.append(f"- Contract in: {schema.contract_in}")
        lines.append(f"- Contract out: {schema.contract_out}")
        lines.append(f"- Deterministic: {schema.deterministic}")
        if schema.artifact:
            lines.append(f"- Artifact: {schema.artifact}")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_pending_review_page(self, rendered_subjects: set[SubjectRef]) -> str:
        pending = [group for group in self.groups if group.status == "pending_review"]
        pending.sort(key=lambda group: group.created_at, reverse=True)
        lines = ["# Pending Review", ""]
        if not pending:
            lines.extend(["No pending candidate groups.", ""])
            return "\n".join(lines).rstrip() + "\n"

        for group in pending:
            lines.append(f"## {group.group_id}")
            lines.append(f"- Relationship: {group.relationship_type}")
            lines.append(f"- Priority: {group.review_priority}")
            if group.thesis_text:
                lines.append(f"- Thesis: {group.thesis_text}")
            if group.source_workflow_name:
                lines.append(f"- Source workflow: {group.source_workflow_name}")
            members = self.members_by_group.get(group.group_id, [])
            if members:
                lines.append("- Affected subjects:")
                for member in members[:10]:
                    from_ref = SubjectRef(member.from_type, member.from_id)
                    to_ref = SubjectRef(member.to_type, member.to_id)
                    from_link = self._subject_markdown_link(
                        from_ref,
                        current_path=Path("governance") / "pending-review.md",
                        rendered_subjects=rendered_subjects,
                    )
                    to_link = self._subject_markdown_link(
                        to_ref,
                        current_path=Path("governance") / "pending-review.md",
                        rendered_subjects=rendered_subjects,
                    )
                    lines.append(f"  - {from_link} with {to_link}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_recent_decisions_page(self, rendered_subjects: set[SubjectRef]) -> str:
        resolutions = sorted(
            self.resolutions_by_id.values(),
            key=lambda record: record["resolved_at"],
            reverse=True,
        )
        lines = ["# Recent Decisions", ""]
        if not resolutions:
            lines.extend(["No resolutions recorded.", ""])
            return "\n".join(lines).rstrip() + "\n"

        for resolution in resolutions[:50]:
            lines.append(f"## {resolution['resolution_id']}")
            lines.append(f"- Action: {resolution['action']}")
            lines.append(f"- Relationship: {resolution['relationship_type']}")
            lines.append(f"- Trust: {resolution['trust_status']}")
            if resolution.get("rationale"):
                lines.append(f"- Rationale: {resolution['rationale']}")
            group = next(
                (
                    candidate
                    for candidate in self.groups
                    if candidate.resolution_id == resolution["resolution_id"]
                ),
                None,
            )
            if group is not None:
                members = self.members_by_group.get(group.group_id, [])
                if members:
                    lines.append("- Subjects:")
                    for member in members[:10]:
                        from_ref = SubjectRef(member.from_type, member.from_id)
                        to_ref = SubjectRef(member.to_type, member.to_id)
                        from_link = self._subject_markdown_link(
                            from_ref,
                            current_path=Path("governance") / "recent-decisions.md",
                            rendered_subjects=rendered_subjects,
                        )
                        to_link = self._subject_markdown_link(
                            to_ref,
                            current_path=Path("governance") / "recent-decisions.md",
                            rendered_subjects=rendered_subjects,
                        )
                        lines.append(f"  - {from_link} with {to_link}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_recent_outcomes_page(self, rendered_subjects: set[SubjectRef]) -> str:
        outcomes = sorted(self.outcomes, key=lambda record: record.created_at, reverse=True)
        lines = ["# Recent Outcomes", ""]
        if not outcomes:
            lines.extend(["No outcomes recorded.", ""])
            return "\n".join(lines).rstrip() + "\n"

        for outcome in outcomes[:50]:
            lines.append(f"## {outcome.outcome_id}")
            lines.append(f"- Outcome: {outcome.outcome}")
            lines.append(
                f"- Anchor: {outcome.anchor_type}:{outcome.anchor_id or outcome.receipt_id}"
            )
            if outcome.outcome_code:
                lines.append(f"- Code: {outcome.outcome_code}")
            surface_name = str(outcome.decision_context.get("surface_name", "")).strip()
            if surface_name:
                lines.append(f"- Surface: {surface_name}")
            provider_names = _extract_provider_names_from_lineage(outcome.lineage_snapshot)
            if provider_names:
                lines.append(f"- Providers: {', '.join(provider_names)}")
            related_subjects = self._related_subjects_for_outcome(outcome)
            if related_subjects:
                lines.append("- Subjects:")
                for ref in related_subjects[:10]:
                    subject_link = self._subject_markdown_link(
                        ref,
                        current_path=Path("governance") / "recent-outcomes.md",
                        rendered_subjects=rendered_subjects,
                    )
                    lines.append(f"  - {subject_link}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _related_subjects_for_outcome(self, outcome: OutcomeRecord) -> list[SubjectRef]:
        refs: set[SubjectRef] = set()
        if outcome.receipt_id in self.receipts:
            refs.update(_entity_refs_from_receipt(self.receipts[outcome.receipt_id]))
        if outcome.anchor_type == "resolution" and outcome.anchor_id:
            group = next(
                (
                    candidate
                    for candidate in self.groups
                    if candidate.resolution_id == outcome.anchor_id
                ),
                None,
            )
            if group is not None:
                for member in self.members_by_group.get(group.group_id, []):
                    refs.add(SubjectRef(member.from_type, member.from_id))
                    refs.add(SubjectRef(member.to_type, member.to_id))
        return sorted(ref for ref in refs if ref in self.subject_entities)

    def _subject_markdown_link(
        self,
        subject: SubjectRef,
        *,
        current_path: Path,
        rendered_subjects: set[SubjectRef],
    ) -> str:
        entity = self.subject_entities.get(subject)
        label = _display_label(entity, self.config) if entity is not None else subject.key
        if subject not in rendered_subjects:
            return label
        return f"[{label}]({_relpath(current_path, self._subject_path(subject))})"


def parse_subject_ref(raw: str) -> SubjectRef:
    """Parse ``EntityType:EntityId`` into a subject reference."""
    entity_type, separator, entity_id = raw.partition(":")
    if not separator or not entity_type.strip() or not entity_id.strip():
        raise ValueError(f"Invalid subject reference '{raw}'. Use EntityType:EntityId.")
    return SubjectRef(entity_type.strip(), entity_id.strip())


def _sorted_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        key: properties[key]
        for key in sorted(properties)
        if properties[key] not in (None, "", [], {})
    }


def _display_label(entity: EntityInstance | None, config: CoreConfig) -> str:
    if entity is None:
        return "unknown"
    properties = entity.properties
    for key in DISPLAY_PROPERTY_PREFERENCE:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    schema = config.get_entity_type(entity.entity_type)
    if schema is not None:
        primary_key = schema.get_primary_key()
        if primary_key:
            value = properties.get(primary_key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return entity.entity_id


def _entity_refs_from_receipt(receipt: Receipt) -> set[SubjectRef]:
    refs: set[SubjectRef] = set()
    for node in receipt.nodes:
        if node.entity_type and node.entity_id:
            refs.add(SubjectRef(node.entity_type, node.entity_id))
        if node.node_type == "edge_traversal":
            from_type = str(node.detail.get("from_entity_type", "")).strip()
            from_id = str(node.detail.get("from_entity_id", "")).strip()
            if from_type and from_id:
                refs.add(SubjectRef(from_type, from_id))
    refs.update(_entity_refs_from_results(receipt.results))
    return refs


def _entity_refs_from_results(results: list[dict[str, Any]]) -> set[SubjectRef]:
    refs: set[SubjectRef] = set()
    for result in results:
        entity_type = str(result.get("entity_type", "")).strip()
        entity_id = str(result.get("entity_id", "")).strip()
        if entity_type and entity_id:
            refs.add(SubjectRef(entity_type, entity_id))
    return refs


def _extract_trace_ids_from_receipt(receipt: Receipt) -> set[str]:
    trace_ids: set[str] = set()
    for node in receipt.nodes:
        if node.node_type != "plan_step":
            continue
        trace_id = str(node.detail.get("trace_id", "")).strip()
        if trace_id:
            trace_ids.add(trace_id)
    return trace_ids


def _extract_trace_ids_from_lineage(lineage_snapshot: dict[str, Any]) -> set[str]:
    trace_set = lineage_snapshot.get("trace_set")
    if not isinstance(trace_set, dict):
        return set()
    trace_ids = trace_set.get("trace_ids")
    if not isinstance(trace_ids, list):
        return set()
    return {str(trace_id) for trace_id in trace_ids if str(trace_id).strip()}


def _extract_provider_names_from_lineage(lineage_snapshot: dict[str, Any]) -> list[str]:
    trace_set = lineage_snapshot.get("trace_set")
    if not isinstance(trace_set, dict):
        return []
    provider_names = trace_set.get("provider_names")
    if not isinstance(provider_names, list):
        return []
    return [str(name) for name in provider_names if str(name).strip()]


def _subject_ref_from_key(key: str) -> SubjectRef:
    entity_type, entity_id = key.split(":", 1)
    return SubjectRef(entity_type, entity_id)


def _counterpart_for_subject(subject: SubjectRef, member: CandidateMember) -> SubjectRef | None:
    from_ref = SubjectRef(member.from_type, member.from_id)
    to_ref = SubjectRef(member.to_type, member.to_id)
    if from_ref == subject:
        return to_ref
    if to_ref == subject:
        return from_ref
    return None



def _render_property_bullets(properties: dict[str, Any], depth: int = 1) -> list[str]:
    """Render non-empty properties as indented sub-bullets, recursing into nested structures."""
    filtered = {
        key: value
        for key, value in sorted(properties.items())
        if not key.startswith("_") and value not in (None, "", [], {})
    }
    indent = "  " * depth
    lines: list[str] = []
    for key, value in filtered.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            # If every dict has the same single key, flatten to values on one line.
            single_keys = {
                next(iter(d.keys())) for d in value
                if isinstance(d, dict) and len(d) == 1
            }
            if len(single_keys) == 1 and all(isinstance(d, dict) and len(d) == 1 for d in value):
                common_key = single_keys.pop()
                vals = [_render_scalar(d[common_key]) for d in value[:8]]
                label = f"{key} ({common_key})" if common_key != key else key
                lines.append(f"{indent}- {label}: {', '.join(vals)}")
                if len(value) > 8:
                    lines[-1] += f", (+{len(value) - 8} more)"
            else:
                lines.append(f"{indent}- {key}:")
                for item in value[:8]:
                    lines.extend(_render_property_bullets(item, depth + 1))
                if len(value) > 8:
                    lines.append(f"{indent}  (+{len(value) - 8} more)")
        elif isinstance(value, dict):
            lines.append(f"{indent}- {key}:")
            lines.extend(_render_property_bullets(value, depth + 1))
        elif isinstance(value, list):
            items = [_render_scalar(item) for item in value[:8]]
            lines.append(f"{indent}- {key}: {'; '.join(items)}")
            if len(value) > 8:
                lines.append(f"{indent}  (+{len(value) - 8} more)")
        else:
            lines.append(f"{indent}- {key}: {_render_scalar(value)}")
    return lines


def _render_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        flat = {k: v for k, v in value.items() if v not in (None, "", [], {})}
        if not flat:
            return "(empty)"
        pairs = [f"{k}: {_render_scalar(v)}" for k, v in sorted(flat.items())]
        return ", ".join(pairs)
    if isinstance(value, list):
        if not value:
            return "(none)"
        items = [_render_scalar(item) for item in value[:8]]
        result = "; ".join(items)
        if len(value) > 8:
            result += f"; (+{len(value) - 8} more)"
        return result
    return str(value)


def _humanize(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "item"


def _relpath(current_path: Path, target_path: Path) -> str:
    current_dir = current_path.parent if current_path.suffix else current_path
    return os.path.relpath(target_path, start=current_dir).replace(os.sep, "/")


def _write_pages(output_dir: Path, pages: dict[Path, str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / MANIFEST_NAME
    previous_files: set[str] = set()
    if manifest_path.exists():
        try:
            previous_files = set(json.loads(manifest_path.read_text()))
        except (OSError, ValueError, TypeError):
            previous_files = set()

    written_paths: list[Path] = []
    current_files = {relative.as_posix() for relative in pages}
    for stale in sorted(previous_files - current_files):
        stale_path = output_dir / stale
        if stale_path.exists():
            stale_path.unlink()

    for relative_path, content in pages.items():
        absolute_path = output_dir / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_text(content)
        written_paths.append(absolute_path)

    manifest_path.write_text(json.dumps(sorted(current_files), indent=2))
    written_paths.append(manifest_path)
    return sorted(written_paths)
