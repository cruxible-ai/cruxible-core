"""CLI command registration — re-exports all commands from domain submodules."""

from cruxible_core.cli.commands.feedback import (
    feedback_batch_cmd,
    feedback_cmd,
    feedback_profile_cmd,
    outcome_cmd,
    outcome_profile_cmd,
)
from cruxible_core.cli.commands.groups import (
    group_group,
)
from cruxible_core.cli.commands.lists import (
    export_group,
    list_group,
)
from cruxible_core.cli.commands.mutations import (
    add_constraint_cmd,
    add_decision_policy_cmd,
    add_entity_cmd,
    add_relationship_cmd,
    reload_config_cmd,
)
from cruxible_core.cli.commands.reads import (
    analyze_feedback_cmd,
    analyze_outcomes_cmd,
    evaluate,
    explain,
    find_candidates_cmd,
    get_entity_cmd,
    get_relationship_cmd,
    inspect_group,
    query,
    sample,
    schema,
    stats_cmd,
)
from cruxible_core.cli.commands.workflows import (
    apply_cmd,
    fork_cmd,
    ingest,
    init,
    lock_cmd,
    plan_cmd,
    propose_cmd,
    run_cmd,
    snapshot_group,
    test_cmd,
    validate,
)
from cruxible_core.cli.commands.world import world_group

__all__ = [
    "add_constraint_cmd",
    "add_decision_policy_cmd",
    "add_entity_cmd",
    "add_relationship_cmd",
    "analyze_feedback_cmd",
    "analyze_outcomes_cmd",
    "apply_cmd",
    "evaluate",
    "explain",
    "export_group",
    "feedback_batch_cmd",
    "feedback_cmd",
    "feedback_profile_cmd",
    "find_candidates_cmd",
    "fork_cmd",
    "get_entity_cmd",
    "get_relationship_cmd",
    "group_group",
    "ingest",
    "init",
    "inspect_group",
    "list_group",
    "lock_cmd",
    "world_group",
    "outcome_cmd",
    "outcome_profile_cmd",
    "plan_cmd",
    "propose_cmd",
    "query",
    "reload_config_cmd",
    "run_cmd",
    "sample",
    "schema",
    "snapshot_group",
    "stats_cmd",
    "test_cmd",
    "validate",
]
