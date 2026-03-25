"""Cross-reference validation for CoreConfig.

The Pydantic schema validates structure. This module validates semantics:
relationships reference valid entity types, named queries reference valid
relationships, ingestion mappings reference valid entity/relationship types, and
workflow/provider declarations resolve correctly.
"""

from __future__ import annotations

import re
from typing import Any

from cruxible_core.config.constraint_rules import parse_constraint_rule
from cruxible_core.config.schema import CoreConfig
from cruxible_core.errors import ConfigError


def validate_config(config: CoreConfig) -> list[str]:
    """Run all cross-reference validations on a CoreConfig.

    Returns a list of warning strings. Raises ConfigError for hard errors.
    """
    errors: list[str] = []
    warnings: list[str] = []

    _validate_relationships(config, errors)
    _validate_named_queries(config, errors)
    _validate_constraints(config, warnings)
    _validate_ingestion(config, errors)
    _validate_primary_keys(config, errors)
    _validate_matching_integrations(config, errors)
    _validate_kind(config, errors)
    _validate_provider_artifacts(config, errors)
    _validate_quality_checks(config, errors)
    _validate_workflows(config, errors)
    _validate_tests(config, errors)

    if errors:
        raise ConfigError(
            f"Config has {len(errors)} cross-reference error(s)",
            errors=errors,
        )

    return warnings


def _validate_relationships(config: CoreConfig, errors: list[str]) -> None:
    """Check that relationship from/to reference valid entity types."""
    entity_names = set(config.entity_types.keys())

    for rel in config.relationships:
        if rel.from_entity not in entity_names:
            errors.append(
                f"Relationship '{rel.name}': 'from' entity type "
                f"'{rel.from_entity}' not defined in entity_types"
            )
        if rel.to_entity not in entity_names:
            errors.append(
                f"Relationship '{rel.name}': 'to' entity type "
                f"'{rel.to_entity}' not defined in entity_types"
            )

    # Check for duplicate relationship names
    seen: set[str] = set()
    for rel in config.relationships:
        if rel.name in seen:
            errors.append(f"Duplicate relationship name: '{rel.name}'")
        seen.add(rel.name)


def _validate_named_queries(config: CoreConfig, errors: list[str]) -> None:
    """Check that named queries reference valid entity types and relationships."""
    entity_names = set(config.entity_types.keys())
    rel_names = {rel.name for rel in config.relationships}

    for query_name, query in config.named_queries.items():
        if query.entry_point not in entity_names:
            errors.append(
                f"Named query '{query_name}': entry_point "
                f"'{query.entry_point}' not defined in entity_types"
            )

        for i, step in enumerate(query.traversal):
            for rel_name in step.relationship_types:
                if rel_name not in rel_names:
                    errors.append(
                        f"Named query '{query_name}' step {i}: relationship "
                        f"'{rel_name}' not defined in relationships"
                    )


def _validate_constraints(config: CoreConfig, warnings: list[str]) -> None:
    """Check that constraints reference valid relationship names."""
    rel_names = {rel.name for rel in config.relationships}

    for constraint in config.constraints:
        parsed = parse_constraint_rule(constraint.rule)
        if parsed and parsed[0] in rel_names:
            continue
        # If we can't parse it or relationship not found, just warn —
        # the constraint evaluator will handle actual validation at runtime
        warnings.append(
            f"Constraint '{constraint.name}': could not verify rule references against schema"
        )


def _validate_ingestion(config: CoreConfig, errors: list[str]) -> None:
    """Check that ingestion mappings reference valid entity/relationship types."""
    entity_names = set(config.entity_types.keys())
    rel_names = {rel.name for rel in config.relationships}

    for mapping_name, mapping in config.ingestion.items():
        if mapping.is_entity:
            if mapping.entity_type not in entity_names:
                errors.append(
                    f"Ingestion mapping '{mapping_name}': entity_type "
                    f"'{mapping.entity_type}' not defined in entity_types"
                )
        elif mapping.is_relationship:
            if mapping.relationship_type not in rel_names:
                errors.append(
                    f"Ingestion mapping '{mapping_name}': relationship_type "
                    f"'{mapping.relationship_type}' not defined in relationships"
                )


def _validate_matching_integrations(config: CoreConfig, errors: list[str]) -> None:
    """Strict mixed mode: non-empty global registry requires all matching keys to resolve."""
    registry = config.integrations
    if not registry:
        return  # Empty registry = open mode, bare labels allowed

    for rel in config.relationships:
        if rel.matching is None:
            continue
        for key in rel.matching.integrations:
            if key not in registry:
                errors.append(
                    f"Integration '{key}' in matching.integrations for "
                    f"relationship '{rel.name}' not found in global "
                    f"integrations registry"
                )


def _validate_primary_keys(config: CoreConfig, errors: list[str]) -> None:
    """Error if entity types are missing primary keys."""
    for name, entity in config.entity_types.items():
        if entity.get_primary_key() is None:
            errors.append(
                f"Entity type '{name}': no property has primary_key: true — "
                f"set primary_key: true on the ID property (e.g. "
                f"properties: {{id: {{type: string, primary_key: true}}}})"
            )


def _validate_provider_artifacts(config: CoreConfig, errors: list[str]) -> None:
    """Validate contracts, artifacts, and providers."""
    contract_names = set(config.contracts.keys())
    artifact_names = set(config.artifacts.keys())

    for artifact_name, artifact in config.artifacts.items():
        if artifact.sha256 is None or not artifact.sha256.strip():
            errors.append(f"Artifact '{artifact_name}' is missing required sha256")

    for provider_name, provider in config.providers.items():
        if provider.contract_in not in contract_names:
            errors.append(
                "Provider "
                f"'{provider_name}': contract_in '{provider.contract_in}' "
                "not found in contracts"
            )
        if provider.contract_out not in contract_names:
            errors.append(
                "Provider "
                f"'{provider_name}': contract_out '{provider.contract_out}' "
                "not found in contracts"
            )
        if provider.artifact is not None and provider.artifact not in artifact_names:
            errors.append(
                f"Provider '{provider_name}': artifact '{provider.artifact}' not found in artifacts"
            )


def _validate_quality_checks(config: CoreConfig, errors: list[str]) -> None:
    """Validate config-defined graph quality checks."""
    entity_names = set(config.entity_types.keys())
    relationship_names = {rel.name for rel in config.relationships}
    seen_names: set[str] = set()

    for check in config.quality_checks:
        if check.name in seen_names:
            errors.append(f"Duplicate quality check name: '{check.name}'")
            continue
        seen_names.add(check.name)

        kind = getattr(check, "kind", "")

        if kind == "property":
            if check.target == "entity":
                if check.entity_type not in entity_names:
                    errors.append(
                        f"Quality check '{check.name}': entity_type "
                        f"'{check.entity_type}' not defined in entity_types"
                    )
                    continue
                if check.property not in config.entity_types[check.entity_type].properties:
                    errors.append(
                        f"Quality check '{check.name}': property '{check.property}' "
                        f"not found on entity type '{check.entity_type}'"
                    )
            else:
                if check.relationship_type not in relationship_names:
                    errors.append(
                        f"Quality check '{check.name}': relationship_type "
                        f"'{check.relationship_type}' not defined in relationships"
                    )
                    continue
                rel = config.get_relationship(check.relationship_type)
                assert rel is not None
                if check.property not in rel.properties:
                    errors.append(
                        f"Quality check '{check.name}': property '{check.property}' "
                        f"not found on relationship '{check.relationship_type}'"
                    )
            if check.rule == "pattern":
                try:
                    assert check.pattern is not None
                    re.compile(check.pattern)
                except re.error as exc:
                    errors.append(
                        f"Quality check '{check.name}': invalid regex pattern "
                        f"'{check.pattern}': {exc}"
                    )

        elif kind == "json_content":
            if check.target == "entity":
                if check.entity_type not in entity_names:
                    errors.append(
                        f"Quality check '{check.name}': entity_type "
                        f"'{check.entity_type}' not defined in entity_types"
                    )
                    continue
                prop = config.entity_types[check.entity_type].properties.get(check.property)
            else:
                if check.relationship_type not in relationship_names:
                    errors.append(
                        f"Quality check '{check.name}': relationship_type "
                        f"'{check.relationship_type}' not defined in relationships"
                    )
                    continue
                rel = config.get_relationship(check.relationship_type)
                assert rel is not None
                prop = rel.properties.get(check.property)
            if prop is None:
                errors.append(
                    f"Quality check '{check.name}': property '{check.property}' not found"
                )
                continue
            if prop.type != "json":
                errors.append(
                    f"Quality check '{check.name}': json_content requires property "
                    f"'{check.property}' to have type 'json'"
                )

        elif kind == "uniqueness":
            if check.entity_type not in entity_names:
                errors.append(
                    f"Quality check '{check.name}': entity_type "
                    f"'{check.entity_type}' not defined in entity_types"
                )
                continue
            entity_props = config.entity_types[check.entity_type].properties
            for prop_name in check.properties:
                if prop_name not in entity_props:
                    errors.append(
                        f"Quality check '{check.name}': property '{prop_name}' "
                        f"not found on entity type '{check.entity_type}'"
                    )

        elif kind == "bounds":
            if check.target == "entity_count":
                if check.entity_type not in entity_names:
                    errors.append(
                        f"Quality check '{check.name}': entity_type "
                        f"'{check.entity_type}' not defined in entity_types"
                    )
            elif check.relationship_type not in relationship_names:
                errors.append(
                    f"Quality check '{check.name}': relationship_type "
                    f"'{check.relationship_type}' not defined in relationships"
                )

        elif kind == "cardinality":
            if check.entity_type not in entity_names:
                errors.append(
                    f"Quality check '{check.name}': entity_type "
                    f"'{check.entity_type}' not defined in entity_types"
                )
                continue
            rel = config.get_relationship(check.relationship_type)
            if rel is None:
                errors.append(
                    f"Quality check '{check.name}': relationship_type "
                    f"'{check.relationship_type}' not defined in relationships"
                )
                continue
            if check.direction == "outgoing" and rel.from_entity != check.entity_type:
                errors.append(
                    f"Quality check '{check.name}': outgoing cardinality on "
                    f"'{check.relationship_type}' requires entity_type '{rel.from_entity}', "
                    f"not '{check.entity_type}'"
                )
            if check.direction == "incoming" and rel.to_entity != check.entity_type:
                errors.append(
                    f"Quality check '{check.name}': incoming cardinality on "
                    f"'{check.relationship_type}' requires entity_type '{rel.to_entity}', "
                    f"not '{check.entity_type}'"
                )


def _validate_kind(config: CoreConfig, errors: list[str]) -> None:
    """Validate top-level kind gating for built world-model features."""
    if config.kind != "ontology":
        return

    if config.ingestion:
        errors.append("Config kind 'ontology' may not define ingestion mappings")
    if config.contracts:
        errors.append("Config kind 'ontology' may not define contracts")
    if config.artifacts:
        errors.append("Config kind 'ontology' may not define artifacts")
    if config.providers:
        errors.append("Config kind 'ontology' may not define providers")
    if config.workflows:
        errors.append("Config kind 'ontology' may not define workflows")
    if config.tests:
        errors.append("Config kind 'ontology' may not define workflow tests")


def _validate_workflows(config: CoreConfig, errors: list[str]) -> None:
    """Validate workflow/provider/query references and reference syntax."""
    contract_names = set(config.contracts.keys())
    provider_names = set(config.providers.keys())
    query_names = set(config.named_queries.keys())
    entity_names = set(config.entity_types.keys())
    relationship_names = {rel.name for rel in config.relationships}
    integration_names = set(config.integrations.keys())

    for workflow_name, workflow in config.workflows.items():
        if workflow.contract_in not in contract_names:
            errors.append(
                "Workflow "
                f"'{workflow_name}': contract_in '{workflow.contract_in}' "
                "not found in contracts"
            )

        produced_aliases: set[str] = set()
        step_ids: set[str] = set()
        uses_apply_steps = False
        providers_used: set[str] = set()

        for step in workflow.steps:
            if step.id in step_ids:
                errors.append(f"Workflow '{workflow_name}': duplicate step id '{step.id}'")
                continue
            step_ids.add(step.id)

            if step.query is not None:
                if step.query not in query_names:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': query '{step.query}' "
                        "not found in named_queries"
                    )
                for ref in _iter_refs(step.params):
                    _validate_workflow_ref(
                        workflow_name,
                        step.id,
                        ref,
                        produced_aliases,
                        errors,
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.provider is not None:
                if step.provider not in provider_names:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': provider "
                        f"'{step.provider}' not found in providers"
                    )
                else:
                    providers_used.add(step.provider)
                for ref in _iter_refs(step.input):
                    _validate_workflow_ref(
                        workflow_name,
                        step.id,
                        ref,
                        produced_aliases,
                        errors,
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.make_candidates is not None:
                if step.make_candidates.relationship_type not in relationship_names:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': make_candidates relationship_type "
                        f"'{step.make_candidates.relationship_type}' not found in relationships"
                    )
                for ref in _iter_refs(
                    [
                        step.make_candidates.items,
                        step.make_candidates.from_type,
                        step.make_candidates.from_id,
                        step.make_candidates.to_type,
                        step.make_candidates.to_id,
                        step.make_candidates.properties,
                    ]
                ):
                    _validate_workflow_ref(
                        workflow_name,
                        step.id,
                        ref,
                        produced_aliases,
                        errors,
                        allow_item=True,
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.map_signals is not None:
                if step.map_signals.integration not in integration_names:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': map_signals integration "
                        f"'{step.map_signals.integration}' not found in integrations"
                    )
                for ref in _iter_refs(
                    [
                        step.map_signals.items,
                        step.map_signals.from_id,
                        step.map_signals.to_id,
                        step.map_signals.evidence,
                    ]
                ):
                    _validate_workflow_ref(
                        workflow_name,
                        step.id,
                        ref,
                        produced_aliases,
                        errors,
                        allow_item=True,
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.propose_relationship_group is not None:
                if step.propose_relationship_group.relationship_type not in relationship_names:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': propose_relationship_group "
                        f"relationship_type '{step.propose_relationship_group.relationship_type}' "
                        "not found in relationships"
                    )
                if step.propose_relationship_group.candidates_from not in produced_aliases:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': candidates_from alias "
                        f"'{step.propose_relationship_group.candidates_from}' "
                        "is unknown or future"
                    )
                for alias in step.propose_relationship_group.signals_from:
                    if alias not in produced_aliases:
                        errors.append(
                            "Workflow "
                            f"'{workflow_name}' step '{step.id}': signals_from alias "
                            f"'{alias}' is unknown or future"
                        )
                for ref in _iter_refs(
                    [
                        step.propose_relationship_group.thesis_text,
                        step.propose_relationship_group.thesis_facts,
                        step.propose_relationship_group.analysis_state,
                        step.propose_relationship_group.suggested_priority,
                    ]
                ):
                    _validate_workflow_ref(
                        workflow_name,
                        step.id,
                        ref,
                        produced_aliases,
                        errors,
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.make_entities is not None:
                if step.make_entities.entity_type not in entity_names:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': make_entities entity_type "
                        f"'{step.make_entities.entity_type}' not found in entity_types"
                    )
                for ref in _iter_refs(
                    [
                        step.make_entities.items,
                        step.make_entities.entity_id,
                        step.make_entities.properties,
                    ]
                ):
                    _validate_workflow_ref(
                        workflow_name,
                        step.id,
                        ref,
                        produced_aliases,
                        errors,
                        allow_item=True,
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.make_relationships is not None:
                if step.make_relationships.relationship_type not in relationship_names:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': make_relationships "
                        f"relationship_type '{step.make_relationships.relationship_type}' "
                        "not found in relationships"
                    )
                for ref in _iter_refs(
                    [
                        step.make_relationships.items,
                        step.make_relationships.from_type,
                        step.make_relationships.from_id,
                        step.make_relationships.to_type,
                        step.make_relationships.to_id,
                        step.make_relationships.properties,
                    ]
                ):
                    _validate_workflow_ref(
                        workflow_name,
                        step.id,
                        ref,
                        produced_aliases,
                        errors,
                        allow_item=True,
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.apply_entities is not None:
                uses_apply_steps = True
                if step.apply_entities.entities_from not in produced_aliases:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': entities_from alias "
                        f"'{step.apply_entities.entities_from}' is unknown or future"
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            if step.apply_relationships is not None:
                uses_apply_steps = True
                if step.apply_relationships.relationships_from not in produced_aliases:
                    errors.append(
                        "Workflow "
                        f"'{workflow_name}' step '{step.id}': relationships_from alias "
                        f"'{step.apply_relationships.relationships_from}' is unknown or future"
                    )
                if step.as_ is not None:
                    produced_aliases.add(step.as_)
                continue

            assert step.assert_spec is not None
            for ref in _iter_refs([step.assert_spec.left, step.assert_spec.right]):
                _validate_workflow_ref(
                    workflow_name,
                    step.id,
                    ref,
                    produced_aliases,
                    errors,
                )

        if workflow.returns not in produced_aliases:
            errors.append(
                "Workflow "
                f"'{workflow_name}': returns alias '{workflow.returns}' "
                "not produced by any prior step"
            )

        if uses_apply_steps and not workflow.canonical:
            errors.append(
                f"Workflow '{workflow_name}': apply_* steps require canonical: true"
            )

        if workflow.canonical:
            for provider_name in providers_used:
                provider = config.providers[provider_name]
                if provider.runtime != "python":
                    errors.append(
                        f"Workflow '{workflow_name}': canonical provider '{provider_name}' "
                        "must use runtime 'python'"
                    )
                if not provider.deterministic:
                    errors.append(
                        f"Workflow '{workflow_name}': canonical provider '{provider_name}' "
                        "must be deterministic"
                    )
                if provider.side_effects:
                    errors.append(
                        f"Workflow '{workflow_name}': canonical provider '{provider_name}' "
                        "must not declare side_effects"
                    )
                if provider.artifact is None:
                    errors.append(
                        f"Workflow '{workflow_name}': canonical provider '{provider_name}' "
                        "must declare an artifact bundle"
                    )


def _validate_tests(config: CoreConfig, errors: list[str]) -> None:
    """Validate workflow test declarations."""
    workflow_names = set(config.workflows.keys())

    seen: set[str] = set()
    for test in config.tests:
        if test.name in seen:
            errors.append(f"Duplicate test name: '{test.name}'")
        seen.add(test.name)
        if test.workflow not in workflow_names:
            errors.append(f"Test '{test.name}': workflow '{test.workflow}' not found in workflows")


def _iter_refs(value: Any) -> list[str]:
    """Collect workflow reference strings from nested data."""
    refs: list[str] = []

    if isinstance(value, str):
        if value.startswith("$"):
            refs.append(value)
        return refs

    if isinstance(value, dict):
        for item in value.values():
            refs.extend(_iter_refs(item))
        return refs

    if isinstance(value, list):
        for item in value:
            refs.extend(_iter_refs(item))

    return refs


def _validate_workflow_ref(
    workflow_name: str,
    step_id: str,
    ref: str,
    produced_aliases: set[str],
    errors: list[str],
    *,
    allow_item: bool = False,
) -> None:
    """Validate a single workflow input/step reference."""
    if ref == "$input":
        return
    if ref.startswith("$input."):
        return
    if ref == "$item" or ref.startswith("$item."):
        if allow_item:
            return
        errors.append(f"Workflow '{workflow_name}' step '{step_id}': unsupported reference '{ref}'")
        return
    if ref == "$steps":
        errors.append(f"Workflow '{workflow_name}' step '{step_id}': invalid reference '{ref}'")
        return
    if not ref.startswith("$steps."):
        errors.append(f"Workflow '{workflow_name}' step '{step_id}': unsupported reference '{ref}'")
        return

    alias = ref[len("$steps.") :].split(".", 1)[0]
    if not alias:
        errors.append(f"Workflow '{workflow_name}' step '{step_id}': invalid reference '{ref}'")
        return
    if alias not in produced_aliases:
        errors.append(
            "Workflow "
            f"'{workflow_name}' step '{step_id}': reference '{ref}' points "
            f"to unknown or future step alias '{alias}'"
        )
