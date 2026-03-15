"""Cross-reference validation for CoreConfig.

The Pydantic schema validates structure. This module validates semantics:
relationships reference valid entity types, named queries reference valid
relationships, ingestion mappings reference valid entity/relationship types, etc.
"""

from __future__ import annotations

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
