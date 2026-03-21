"""Workflow lock generation and compilation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.provider.registry import resolve_provider
from cruxible_core.workflow.contracts import validate_contract_payload
from cruxible_core.workflow.refs import preview_value
from cruxible_core.workflow.types import (
    CompiledPlan,
    CompiledPlanStep,
    LockedArtifact,
    LockedProvider,
    WorkflowLock,
)

LOCK_FILE_NAME = "cruxible.lock.yaml"


def compute_lock_config_digest(config: CoreConfig) -> str:
    """Compute a stable config digest for lock generation."""
    dumped = json.dumps(
        config.model_dump(mode="python", by_alias=True, exclude_none=True),
        sort_keys=True,
        default=str,
    )
    return f"sha256:{hashlib.sha256(dumped.encode()).hexdigest()}"


def get_lock_path(instance: InstanceProtocol) -> Path:
    """Return the workflow lock path for an instance."""
    return instance.get_config_path().parent / LOCK_FILE_NAME


def build_lock(config: CoreConfig) -> WorkflowLock:
    """Generate a workflow lock from config/provider/artifact declarations."""
    for provider_name, provider in config.providers.items():
        resolve_provider(provider_name, provider)

    return WorkflowLock(
        config_digest=compute_lock_config_digest(config),
        artifacts={
            name: LockedArtifact(
                kind=artifact.kind,
                uri=artifact.uri,
                sha256=artifact.sha256 or "",
                metadata=artifact.metadata,
            )
            for name, artifact in config.artifacts.items()
        },
        providers={
            name: LockedProvider(
                version=provider.version,
                ref=provider.ref,
                runtime=provider.runtime,
                deterministic=provider.deterministic,
                side_effects=provider.side_effects,
                artifact=provider.artifact,
                config=provider.config,
            )
            for name, provider in config.providers.items()
        },
    )


def write_lock(lock: WorkflowLock, path: Path) -> None:
    """Write a generated workflow lock to disk."""
    data = lock.model_dump(mode="python", exclude_none=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def load_lock(path: Path) -> WorkflowLock:
    """Load a workflow lock from disk."""
    if not path.exists():
        raise ConfigError(f"Lock file not found: {path}. Run `cruxible lock` first.")

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ConfigError(f"Lock file at {path} must contain a YAML mapping")
    return WorkflowLock.model_validate(raw)


def compile_workflow(
    config: CoreConfig,
    lock: WorkflowLock,
    workflow_name: str,
    input_payload: dict[str, Any],
) -> CompiledPlan:
    """Compile a workflow and validate input against its contract."""
    digest = compute_lock_config_digest(config)
    if lock.config_digest != digest:
        raise ConfigError(
            "Lock file config digest does not match current config. Run `cruxible lock`."
        )

    workflow = config.workflows.get(workflow_name)
    if workflow is None:
        raise ConfigError(f"Workflow '{workflow_name}' not found in workflows")

    normalized_input = validate_contract_payload(
        config,
        workflow.contract_in,
        input_payload,
        subject=f"Workflow '{workflow_name}' input",
        error_factory=ConfigError,
    )

    compiled_steps: list[CompiledPlanStep] = []
    for step in workflow.steps:
        if step.query is not None:
            if step.query not in config.named_queries:
                raise ConfigError(
                    f"Workflow '{workflow_name}' references unknown query '{step.query}'"
                )
            compiled_steps.append(
                CompiledPlanStep(
                    step_id=step.id,
                    kind="query",
                    as_name=step.as_,
                    query_name=step.query,
                    params_template=step.params,
                    params_preview=preview_value(step.params, normalized_input),
                )
            )
            continue

        if step.provider is not None:
            locked = lock.providers.get(step.provider)
            if locked is None:
                raise ConfigError(
                    f"Provider '{step.provider}' missing from lock file. Run `cruxible lock`."
                )
            compiled_steps.append(
                CompiledPlanStep(
                    step_id=step.id,
                    kind="provider",
                    as_name=step.as_,
                    provider_name=step.provider,
                    provider_ref=locked.ref,
                    provider_version=locked.version,
                    artifact_name=locked.artifact,
                    artifact_sha256=(
                        lock.artifacts[locked.artifact].sha256 if locked.artifact else None
                    ),
                    input_template=step.input,
                    input_preview=preview_value(step.input, normalized_input),
                )
            )
            continue

        assert step.assert_spec is not None
        compiled_steps.append(
            CompiledPlanStep(
                step_id=step.id,
                kind="assert",
                assert_left=preview_value(step.assert_spec.left, normalized_input),
                assert_right=preview_value(step.assert_spec.right, normalized_input),
                assert_op=step.assert_spec.op,
                message=step.assert_spec.message,
            )
        )

    return CompiledPlan(
        workflow=workflow_name,
        contract_in=workflow.contract_in,
        config_digest=digest,
        steps=compiled_steps,
        returns=workflow.returns,
        input_payload=normalized_input,
    )
