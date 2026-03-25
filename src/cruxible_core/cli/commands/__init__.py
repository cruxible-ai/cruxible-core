"""CLI command registration — re-exports all commands from domain submodules."""

from cruxible_core.cli.commands.entity_proposals import (
    entity_proposal_group,
)
from cruxible_core.cli.commands.feedback import (
    feedback_batch_cmd,
    feedback_cmd,
    outcome_cmd,
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
    add_entity_cmd,
    add_relationship_cmd,
    reload_config_cmd,
)
from cruxible_core.cli.commands.reads import (
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

__all__ = [
    "add_constraint_cmd",
    "add_entity_cmd",
    "add_relationship_cmd",
    "apply_cmd",
    "entity_proposal_group",
    "evaluate",
    "explain",
    "export_group",
    "feedback_batch_cmd",
    "feedback_cmd",
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
    "outcome_cmd",
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
