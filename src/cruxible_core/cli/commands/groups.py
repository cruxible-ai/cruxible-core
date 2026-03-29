"""CLI commands for the group subgroup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import click

from cruxible_client import contracts
from cruxible_core.cli.commands._common import (
    _dispatch_cli_instance,
    _groups_from_payload,
    _members_from_payload,
    console,
)
from cruxible_core.cli.formatting import group_detail_table, groups_table, resolutions_table
from cruxible_core.cli.main import handle_errors
from cruxible_core.group.types import CandidateGroup, CandidateMember, CandidateSignal
from cruxible_core.service import (
    service_get_group,
    service_list_groups,
    service_list_resolutions,
    service_propose_group,
    service_resolve_group,
    service_update_trust_status,
)


@click.group("group")
def group_group() -> None:
    """Manage candidate groups for batch edge review."""


@group_group.command("propose")
@click.option("--relationship", required=True, help="Relationship type for the group.")
@click.option(
    "--members-file",
    type=click.Path(exists=True),
    default=None,
    help="JSON file with member list.",
)
@click.option("--members", "members_json", default=None, help="Inline JSON array of members.")
@click.option("--thesis", default="", help="Human-readable thesis text.")
@click.option("--thesis-facts", default=None, help="JSON object of structured thesis facts.")
@click.option("--analysis-state", default=None, help="JSON object of opaque analysis state.")
@click.option("--integration", multiple=True, help="Integration name used in this proposal.")
@handle_errors
def group_propose(
    relationship: str,
    members_file: str | None,
    members_json: str | None,
    thesis: str,
    thesis_facts: str | None,
    analysis_state: str | None,
    integration: tuple[str, ...],
) -> None:
    """Propose a candidate group of edges for batch review."""
    if members_file and members_json:
        raise click.BadParameter("Provide --members-file or --members, not both.")
    if not members_file and not members_json:
        raise click.BadParameter("Provide --members-file or --members.")

    try:
        if members_file:
            raw_members = json.loads(Path(members_file).read_text())
        else:
            raw_members = json.loads(members_json)  # type: ignore[arg-type]
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"Members must be valid JSON: {exc}") from exc

    if not isinstance(raw_members, list):
        raise click.BadParameter("Members must be a JSON array.")

    try:
        facts = json.loads(thesis_facts) if thesis_facts else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--thesis-facts must be valid JSON") from exc

    try:
        state = json.loads(analysis_state) if analysis_state else None
    except json.JSONDecodeError as exc:
        raise click.BadParameter("--analysis-state must be valid JSON") from exc

    client_members = [
        contracts.MemberInput(
            from_type=m["from_type"],
            from_id=m["from_id"],
            to_type=m["to_type"],
            to_id=m["to_id"],
            relationship_type=m["relationship_type"],
            signals=[
                contracts.SignalInput(
                    integration=s["integration"],
                    signal=s["signal"],
                    evidence=s.get("evidence", ""),
                )
                for s in m.get("signals", [])
            ],
            properties=m.get("properties", {}),
        )
        for m in raw_members
    ]
    domain_members = [
        CandidateMember(
            from_type=m["from_type"],
            from_id=m["from_id"],
            to_type=m["to_type"],
            to_id=m["to_id"],
            relationship_type=m["relationship_type"],
            signals=[
                CandidateSignal(
                    integration=s["integration"],
                    signal=s["signal"],
                    evidence=s.get("evidence", ""),
                )
                for s in m.get("signals", [])
            ],
            properties=m.get("properties", {}),
        )
        for m in raw_members
    ]
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.propose_group(
            instance_id,
            relationship_type=relationship,
            members=client_members,
            thesis_text=thesis,
            thesis_facts=facts,
            analysis_state=state,
            integrations_used=list(integration) if integration else None,
        ),
        lambda instance: service_propose_group(
            instance,
            relationship,
            domain_members,
            thesis_text=thesis,
            thesis_facts=facts,
            analysis_state=state,
            integrations_used=list(integration) if integration else None,
        ),
    )

    click.echo(f"Group {result.group_id} proposed.")
    click.echo(f"  Status: {result.status}")
    click.echo(f"  Priority: {result.review_priority}")
    click.echo(f"  Members: {result.member_count}")
    click.echo(f"  Signature: {result.signature[:16]}...")


@group_group.command("resolve")
@click.option("--group", "group_id", required=True, help="Group ID to resolve.")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["approve", "reject"]),
    help="Resolution action.",
)
@click.option("--rationale", default="", help="Rationale for this resolution.")
@click.option(
    "--source",
    type=click.Choice(["human", "ai_review"]),
    default="human",
    help="Who resolved (default: human).",
)
@handle_errors
def group_resolve(group_id: str, action: str, rationale: str, source: str) -> None:
    """Resolve a candidate group (approve or reject)."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.resolve_group(
            instance_id,
            group_id,
            action=cast(contracts.GroupAction, action),
            rationale=rationale,
            resolved_by=cast(contracts.GroupResolvedBy, source),
        ),
        lambda instance: service_resolve_group(
            instance,
            group_id,
            action,  # type: ignore[arg-type]
            rationale=rationale,
            resolved_by=source,  # type: ignore[arg-type]
        ),
    )

    click.echo(f"Group {result.group_id} {result.action}d.")
    if result.action == "approve":
        click.echo(f"  Edges created: {result.edges_created}")
        if result.edges_skipped:
            click.echo(f"  Edges skipped: {result.edges_skipped}")
    if result.resolution_id:
        click.echo(f"  Resolution: {result.resolution_id}")
    if result.receipt_id:
        click.echo(f"  Receipt: {result.receipt_id}")


@group_group.command("trust")
@click.option("--resolution", "resolution_id", required=True, help="Resolution ID.")
@click.option(
    "--status",
    "trust_status",
    required=True,
    type=click.Choice(["watch", "trusted", "invalidated"]),
    help="Trust status to set.",
)
@click.option("--reason", default="", help="Reason for trust status change.")
@handle_errors
def group_trust(resolution_id: str, trust_status: str, reason: str) -> None:
    """Update trust status on a resolution."""
    _dispatch_cli_instance(
        lambda client, instance_id: client.update_trust_status(
            instance_id,
            resolution_id,
            trust_status=cast(contracts.GroupTrustStatus, trust_status),
            reason=reason,
        ),
        lambda instance: service_update_trust_status(
            instance,
            resolution_id,
            trust_status,  # type: ignore[arg-type]
            reason=reason,
        ),
    )
    click.echo(f"Resolution {resolution_id} trust status set to '{trust_status}'.")


@group_group.command("get")
@click.option("--group", "group_id", required=True, help="Group ID.")
@handle_errors
def group_get(group_id: str) -> None:
    """Get details of a candidate group."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.get_group(instance_id, group_id),
        lambda instance: service_get_group(instance, group_id),
    )
    if isinstance(result, contracts.GetGroupToolResult):
        console.print(
            group_detail_table(
                CandidateGroup.model_validate(result.group),
                _members_from_payload(result.members),
            )
        )
        return
    console.print(group_detail_table(result.group, result.members))


@group_group.command("list")
@click.option("--relationship", default=None, help="Filter by relationship type.")
@click.option(
    "--status",
    default=None,
    type=click.Choice(["pending_review", "auto_resolved", "applying", "resolved"]),
    help="Filter by status.",
)
@click.option("--limit", default=50, help="Max groups to show.")
@handle_errors
def group_list(relationship: str | None, status: str | None, limit: int) -> None:
    """List candidate groups."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list_groups(
            instance_id,
            relationship_type=relationship,
            status=cast(contracts.GroupStatus | None, status),
            limit=limit,
        ),
        lambda instance: service_list_groups(
            instance,
            relationship_type=relationship,
            status=status,
            limit=limit,
        ),
    )
    if isinstance(result, contracts.ListGroupsToolResult):
        groups = _groups_from_payload(result.groups)
        total = result.total
    else:
        groups = result.groups
        total = result.total
    console.print(groups_table(groups))
    click.echo(f"{len(groups)} of {total} group(s) shown.")


@group_group.command("resolutions")
@click.option("--relationship", default=None, help="Filter by relationship type.")
@click.option(
    "--action",
    default=None,
    type=click.Choice(["approve", "reject"]),
    help="Filter by action.",
)
@click.option("--limit", default=50, help="Max resolutions to show.")
@handle_errors
def group_resolutions(relationship: str | None, action: str | None, limit: int) -> None:
    """List group resolutions."""
    result = _dispatch_cli_instance(
        lambda client, instance_id: client.list_resolutions(
            instance_id,
            relationship_type=relationship,
            action=cast(contracts.GroupAction | None, action),
            limit=limit,
        ),
        lambda instance: service_list_resolutions(
            instance,
            relationship_type=relationship,
            action=action,
            limit=limit,
        ),
    )
    console.print(resolutions_table(result.resolutions))
    click.echo(f"{len(result.resolutions)} of {result.total} resolution(s) shown.")
