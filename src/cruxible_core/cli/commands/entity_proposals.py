"""CLI commands for the entity-proposal subgroup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import click
import yaml

from cruxible_core.cli.commands._common import (
    _dispatch_cli_instance,
    _entity_change_members_from_payload,
    _entity_proposals_from_payload,
)
from cruxible_core.cli.main import handle_errors
from cruxible_core.entity_proposal.types import EntityChangeMember, EntityChangeProposal
from cruxible_core.mcp import contracts
from cruxible_core.service import (
    service_get_entity_proposal,
    service_list_entity_proposals,
    service_propose_entity_changes,
    service_resolve_entity_proposal,
)


@click.group("entity-proposal")
def entity_proposal_group() -> None:
    """Manage governed entity create and patch proposals."""


@entity_proposal_group.command("propose")
@click.option(
    "--members-file",
    type=click.Path(exists=True),
    default=None,
    help="JSON or YAML file with proposal members.",
)
@click.option("--members", "members_json", default=None, help="Inline JSON array of members.")
@click.option("--thesis", default="", help="Human-readable thesis text.")
@click.option("--thesis-facts", default=None, help="JSON object of structured thesis facts.")
@click.option("--analysis-state", default=None, help="JSON object of opaque analysis state.")
@click.option(
    "--source",
    "proposed_by",
    type=click.Choice(["human", "ai_review"]),
    default="ai_review",
    help="Who proposed the entity changes (default: ai_review).",
)
@click.option("--suggested-priority", default=None, help="Optional suggested priority.")
@click.option("--source-workflow", default=None, help="Optional source workflow name.")
@click.option(
    "--source-workflow-receipt",
    default=None,
    help="Optional source workflow receipt ID.",
)
@click.option(
    "--source-trace-id",
    "source_trace_ids",
    multiple=True,
    help="Optional source execution trace ID (repeatable).",
)
@click.option(
    "--source-step-id",
    "source_step_ids",
    multiple=True,
    help="Optional source workflow step ID (repeatable).",
)
@handle_errors
def entity_proposal_propose(
    members_file: str | None,
    members_json: str | None,
    thesis: str,
    thesis_facts: str | None,
    analysis_state: str | None,
    proposed_by: str,
    suggested_priority: str | None,
    source_workflow: str | None,
    source_workflow_receipt: str | None,
    source_trace_ids: tuple[str, ...],
    source_step_ids: tuple[str, ...],
) -> None:
    """Propose a governed batch of entity creates or patches."""
    if members_file and members_json:
        raise click.BadParameter("Provide --members-file or --members, not both.")
    if not members_file and not members_json:
        raise click.BadParameter("Provide --members-file or --members.")

    try:
        if members_file:
            raw_members = yaml.safe_load(Path(members_file).read_text())
        else:
            raw_members = json.loads(members_json)  # type: ignore[arg-type]
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise click.BadParameter(f"Members must be valid JSON or YAML: {exc}") from exc
    if not isinstance(raw_members, list):
        raise click.BadParameter("Members must be a top-level array.")

    try:
        facts = json.loads(thesis_facts) if thesis_facts else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--thesis-facts must be valid JSON") from exc
    try:
        state = json.loads(analysis_state) if analysis_state else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--analysis-state must be valid JSON") from exc

    members = [
        contracts.EntityChangeInput(
            entity_type=item["entity_type"],
            entity_id=item["entity_id"],
            operation=item["operation"],
            properties=item.get("properties", {}),
        )
        for item in raw_members
    ]

    result = _dispatch_cli_instance(
        lambda client, instance_id: client.propose_entity_changes(
            instance_id,
            members=members,
            thesis_text=thesis,
            thesis_facts=facts,
            analysis_state=state,
            proposed_by=cast(contracts.GroupProposedBy, proposed_by),
            suggested_priority=suggested_priority,
            source_workflow_name=source_workflow,
            source_workflow_receipt_id=source_workflow_receipt,
            source_trace_ids=list(source_trace_ids) or None,
            source_step_ids=list(source_step_ids) or None,
        ),
        lambda instance: service_propose_entity_changes(
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
            thesis_text=thesis,
            thesis_facts=facts,
            analysis_state=state,
            proposed_by=cast(contracts.GroupProposedBy, proposed_by),
            suggested_priority=suggested_priority,
            source_workflow_name=source_workflow,
            source_workflow_receipt_id=source_workflow_receipt,
            source_trace_ids=list(source_trace_ids),
            source_step_ids=list(source_step_ids),
        ),
    )

    click.echo(f"Entity proposal {result.proposal_id} created.")
    click.echo(f"  Status: {result.status}")
    click.echo(f"  Members: {result.member_count}")


@entity_proposal_group.command("get")
@click.option("--proposal", "proposal_id", required=True, help="Entity proposal ID.")
@handle_errors
def entity_proposal_get(proposal_id: str) -> None:
    """Get details of a governed entity proposal."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.get_entity_proposal(instance_id, proposal_id),
        lambda instance: service_get_entity_proposal(instance, proposal_id),
    )
    if isinstance(result, contracts.GetEntityProposalToolResult):
        proposal = EntityChangeProposal.model_validate(result.proposal)
        members = _entity_change_members_from_payload(result.members)
    else:
        proposal = result.proposal
        members = result.members

    click.echo(f"Entity proposal {proposal.proposal_id}")
    click.echo(f"  Status: {proposal.status}")
    click.echo(f"  Proposed by: {proposal.proposed_by}")
    click.echo(f"  Members: {proposal.member_count}")
    for member in members:
        click.echo(
            f"  - {member.operation}: {member.entity_type}:{member.entity_id} "
            f"({len(member.properties)} property updates)"
        )


@entity_proposal_group.command("list")
@click.option(
    "--status",
    default=None,
    type=click.Choice(["pending_review", "applying", "resolved"]),
    help="Filter by status.",
)
@click.option("--limit", default=50, help="Max proposals to show.")
@handle_errors
def entity_proposal_list(status: str | None, limit: int) -> None:
    """List governed entity proposals."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list_entity_proposals(
            instance_id,
            status=cast(contracts.EntityProposalStatus | None, status),
            limit=limit,
        ),
        lambda instance: service_list_entity_proposals(instance, status=status, limit=limit),
    )
    if isinstance(result, contracts.ListEntityProposalsToolResult):
        proposals = _entity_proposals_from_payload(result.proposals)
        total = result.total
    else:
        proposals = result.proposals
        total = result.total

    for proposal in proposals:
        click.echo(
            f"{proposal.proposal_id}  {proposal.status}  "
            f"{proposal.member_count} member(s)  proposed_by={proposal.proposed_by}"
        )
    click.echo(f"{len(proposals)} of {total} proposal(s) shown.")


@entity_proposal_group.command("resolve")
@click.option("--proposal", "proposal_id", required=True, help="Entity proposal ID.")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["approve", "reject"]),
    help="Resolution action.",
)
@click.option("--rationale", default="", help="Rationale for this resolution.")
@click.option(
    "--source",
    "resolved_by",
    type=click.Choice(["human", "ai_review"]),
    default="human",
    help="Who resolved the proposal (default: human).",
)
@handle_errors
def entity_proposal_resolve(
    proposal_id: str,
    action: str,
    rationale: str,
    resolved_by: str,
) -> None:
    """Resolve a governed entity proposal."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.resolve_entity_proposal(
            instance_id,
            proposal_id,
            action=cast(contracts.GroupAction, action),
            rationale=rationale,
            resolved_by=cast(contracts.GroupResolvedBy, resolved_by),
        ),
        lambda instance: service_resolve_entity_proposal(
            instance,
            proposal_id,
            cast(contracts.GroupAction, action),
            rationale=rationale,
            resolved_by=cast(contracts.GroupResolvedBy, resolved_by),
        ),
    )

    click.echo(f"Entity proposal {result.proposal_id} {result.action}d.")
    if result.action == "approve":
        click.echo(f"  Entities created: {result.entities_created}")
        click.echo(f"  Entities patched: {result.entities_patched}")
    if result.resolution_id:
        click.echo(f"  Resolution: {result.resolution_id}")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")
