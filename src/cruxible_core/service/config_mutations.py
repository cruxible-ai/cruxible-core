"""Config mutation service functions."""

from __future__ import annotations

from typing import Any

from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.schema import ConstraintSchema, DecisionPolicySchema
from cruxible_core.config.validator import validate_config
from cruxible_core.errors import ConfigError
from cruxible_core.instance_protocol import InstanceProtocol
from cruxible_core.predicate import CONSTRAINT_RULE_SYNTAX
from cruxible_core.service.types import (
    AddConstraintServiceResult,
    AddDecisionPolicyServiceResult,
)


def service_add_constraint(
    instance: InstanceProtocol,
    *,
    name: str,
    rule: str,
    severity: str = "warning",
    description: str | None = None,
) -> AddConstraintServiceResult:
    """Add a constraint rule to the active config and persist it."""
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

    config.constraints.append(
        ConstraintSchema(
            name=name,
            rule=rule,
            severity=severity,
            description=description,
        )
    )
    warnings = validate_config(config)
    instance.save_config(config)
    return AddConstraintServiceResult(
        name=name,
        added=True,
        config_updated=True,
        warnings=warnings,
    )


def service_add_decision_policy(
    instance: InstanceProtocol,
    *,
    name: str,
    applies_to: str,
    relationship_type: str,
    effect: str,
    match: dict[str, Any] | None = None,
    description: str | None = None,
    rationale: str = "",
    query_name: str | None = None,
    workflow_name: str | None = None,
    expires_at: str | None = None,
) -> AddDecisionPolicyServiceResult:
    """Add a decision policy to the active config and persist it."""
    config = instance.load_config()

    for existing in config.decision_policies:
        if existing.name == name:
            raise ConfigError(f"Decision policy '{name}' already exists in config")

    config.decision_policies.append(
        DecisionPolicySchema(
            name=name,
            description=description,
            rationale=rationale,
            applies_to=applies_to,
            query_name=query_name,
            workflow_name=workflow_name,
            relationship_type=relationship_type,
            effect=effect,
            match=match or {},
            expires_at=expires_at,
        )
    )
    warnings = validate_config(config)
    instance.save_config(config)
    return AddDecisionPolicyServiceResult(
        name=name,
        added=True,
        config_updated=True,
        warnings=warnings,
    )
