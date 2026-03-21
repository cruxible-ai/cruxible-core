"""Workflow lock, plan, and execution types."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from cruxible_core.group.types import CandidateSignal
from cruxible_core.provider.types import ExecutionTrace
from cruxible_core.receipt.types import Receipt


class LockedArtifact(BaseModel):
    """Artifact details captured in a generated lock file."""

    kind: str
    uri: str
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LockedProvider(BaseModel):
    """Resolved provider metadata captured in a generated lock file."""

    version: str
    ref: str
    runtime: str
    deterministic: bool
    side_effects: bool
    artifact: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowLock(BaseModel):
    """Generated lock file for workflow execution."""

    version: str = "1"
    config_digest: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    artifacts: dict[str, LockedArtifact] = Field(default_factory=dict)
    providers: dict[str, LockedProvider] = Field(default_factory=dict)


class CompiledPlanStep(BaseModel):
    """Single compiled workflow step."""

    step_id: str
    kind: Literal["query", "provider", "assert"]
    as_name: str | None = None
    query_name: str | None = None
    provider_name: str | None = None
    provider_ref: str | None = None
    provider_version: str | None = None
    artifact_name: str | None = None
    artifact_sha256: str | None = None
    params_template: dict[str, Any] = Field(default_factory=dict)
    params_preview: dict[str, Any] = Field(default_factory=dict)
    input_template: dict[str, Any] = Field(default_factory=dict)
    input_preview: dict[str, Any] = Field(default_factory=dict)
    assert_left: Any | None = None
    assert_right: Any | None = None
    assert_op: str | None = None
    message: str | None = None


class CompiledPlan(BaseModel):
    """Compiled workflow plan artifact."""

    workflow: str
    contract_in: str
    config_digest: str
    steps: list[CompiledPlanStep]
    returns: str
    input_payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionResult(BaseModel):
    """Runtime workflow execution result."""

    workflow: str
    output: Any
    receipt: Receipt
    query_receipt_ids: list[str] = Field(default_factory=list)
    traces: list[ExecutionTrace] = Field(default_factory=list)
    step_outputs: dict[str, Any] = Field(default_factory=dict)
    alias_step_ids: dict[str, str] = Field(default_factory=dict)
    step_trace_ids: dict[str, list[str]] = Field(default_factory=dict)


class WorkflowTestCaseResult(BaseModel):
    """Single workflow test case result."""

    name: str
    workflow: str
    passed: bool
    output: Any | None = None
    receipt_id: str | None = None
    error: str | None = None


class WorkflowTestRunResult(BaseModel):
    """Summary of executing config-defined workflow tests."""

    total: int
    passed: int
    failed: int
    cases: list[WorkflowTestCaseResult] = Field(default_factory=list)


class RelationshipGroupProposalMember(BaseModel):
    """Bridged workflow payload member for relationship group proposals."""

    from_type: str
    from_id: str
    to_type: str
    to_id: str
    signals: list[CandidateSignal] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationshipGroupProposalPayload(BaseModel):
    """Typed workflow output for the relationship-group bridge."""

    members: list[RelationshipGroupProposalMember]
    thesis_text: str = ""
    thesis_facts: dict[str, Any] = Field(default_factory=dict)
    analysis_state: dict[str, Any] = Field(default_factory=dict)
    integrations_used: list[str] = Field(default_factory=list)
    suggested_priority: str | None = None
