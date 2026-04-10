---
name: fork-and-fit
description: Fork a published reference world, use the inherited world plus any applied kit with the lowest-friction path, and only add local config or code when the current fork is not enough.
---

# Fork And Fit

Use this skill when the user wants to start from a published reference world and fit it to a local use case with the least friction.

This is the reference-world path, not the greenfield path. Start from the inherited world, use the applied `kit` if one exists, and only add local config or code when the current fork is not enough.

If the current workspace is not already a fork, create one first:

```bash
cruxible world fork --world-ref <alias> --root-dir <root_dir>
```

If that world has a configured default `kit`, it will be applied automatically. Use `--kit <kit>` to override the default `kit`, or `--no-kit` for a bare fork.

## Core Rules

- edit the local `config.yaml`, not `.cruxible/upstream/current/config.yaml`
- treat `.cruxible/composed/config.yaml` as generated output, not as the source of truth
- use the inherited world and the applied `kit` as-is if they already solve the problem
- add local extensions instead of re-declaring inherited config or graph structure
- prefer refining the local `kit` pattern over inventing new local machinery
- if a desired change really belongs in the inherited config, call it out as upstream work
- keep the local fit as small as the use case allows

## Phase 1: Establish the fork baseline

Start by inspecting the forked workspace:

```bash
cruxible world status
cruxible stats
cruxible sample --type <EntityType> --limit 5
cruxible inspect entity --type <EntityType> --id <entity_id>
```

Inspect the three config layers:

- local config: `config.yaml`
- inherited config snapshot: `.cruxible/upstream/current/config.yaml`
- active composed runtime config: `.cruxible/composed/config.yaml`

If a `kit` was applied, inspect the local files it brought in too.

Then answer:

1. what user problem are we solving in this fork?
2. what does the inherited world already provide?
3. what does the applied `kit` already provide?
4. can the current fork already handle this use case without local changes?
5. if not, what is actually missing?
6. what should stay local instead of being pushed upstream?

Keep this phase grounded in the current fork. Do not redesign the inherited world from scratch.

## Phase 2: Choose the fit strategy

Decide whether to use the fork as-is or make the smallest local fit:

1. can the inherited world, applied `kit`, and existing `workflows` handle the user's data or workflow as-is?
2. if yes, which existing `workflows`, proposal flows, or `named_queries` should be used?
3. if no, what is the smallest local change needed?
4. does the problem require new local canonical behavior, new governed behavior, new local queries, or none of those?
5. summarize the chosen path for user confirmation

If the answer is "use the current fork as-is," continue to Phase 3 and do not edit `config.yaml` yet.

If the answer is "the fork needs local changes," continue to Phase 4.

## Phase 3: Run the current fork with no local changes

If the current fork is already good enough, use it directly.

Do not edit `config.yaml` in this phase.

Instead:

1. identify which existing canonical `workflows` should be run for the user's data
2. identify which existing governed `workflows` or review surfaces should be used
3. identify which existing `named_queries` already answer the user's questions
4. run the current setup and inspect the results

Use the existing CLI surfaces that match the current fork:

```bash
cruxible run --workflow <workflow_name> --apply
cruxible propose --workflow <workflow_name>
cruxible query --query <query_name> --param key=value
cruxible explain --receipt <receipt_id>
```

If the current fork and `kit` solve the problem, stop here and hand off the working flow.

If the current setup is not enough, continue to Phase 4 and make the smallest necessary local change.

## Phase 4: Define the local fit boundary

Decide what the local config actually needs to add:

1. which local entities or relationships are truly missing?
2. which local `workflows` are actually needed?
3. which local review or governed surfaces are actually needed?
4. which local `named_queries` are actually needed?
5. what can be solved by refining the applied `kit` or local config instead of inventing new machinery?
6. summarize the local fit boundary for user confirmation

Keep this phase ownership-focused. If a change would require inherited entries or semantics to change, call that out as upstream work instead of forcing it into the local config.

## Write Step A: Update the local config

Edit only the local `config.yaml`.

Use the applied `kit` as a starting point where possible. Add only the local pieces that are actually needed:

- `entity_types`
- `relationships`
- `artifacts`
- `contracts`
- `integrations`
- `providers`
- `workflows`
- `named_queries`
- `feedback_profiles`
- `outcome_profiles`
- appended `constraints`, `quality_checks`, `decision_policies`, or `tests`

Use local names for new entries so they do not collide with inherited names.

Do not copy large chunks of inherited config into the local file. Reuse inherited structure and `kit` patterns instead.

## Phase 5: Validate and run the local canonical fit

After local config changes:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
cruxible lock
```

Run only the local canonical `workflows` you added through the local config:

```bash
cruxible run --workflow <workflow_name> --apply
```

Do not try to rebuild inherited state here. The fork should add local state and local behavior on top of what is already inherited.

Re-check the world:

```bash
cruxible stats
cruxible sample --type <EntityType> --limit 5
cruxible inspect entity --type <EntityType> --id <entity_id>
```

If the inherited world plus the applied `kit` now solve the problem, stop adding machinery.

## Phase 6: Add local governed design only if needed

Only add this phase if the local config needs reviewable, judgment-based relationships beyond what already exists.

Prefer adapting existing governed patterns from the applied `kit` before inventing new ones.

For each new local governed relationship type:

1. identify the local review surface and why canonical loading is not enough
2. define the grouping rule and unit of review
3. define the intended `thesis_facts` and `analysis_state`
4. define the evidence policy in principle
5. decide whether local queries depend on approved governed relationships
6. summarize the governed local design for user confirmation

Before implementing local proposal workflows, capture the approved design in:

```text
design/governed/<relationship_type>.yaml
```

Keep this design note local. If the governed relationship really belongs in the inherited config, call that out instead of normalizing it into the local fit.

## Phase 7: Implement local proposal workflows only when needed

Use the approved governed design note and the applied `kit` as the source of truth.

Prefer adapting existing local `providers`, `integrations`, `contracts`, and `workflows` before writing new ones.

If the local governed layer really needs implementation work:

1. identify what local graph or artifact inputs the proposal workflow needs
2. decide which local `integrations` should emit governed signals
3. decide how provider output becomes:
   - candidate relationships
   - `support`, `contradict`, or `unsure` signals
   - the fields that will populate `thesis_facts`
   - the fields that will populate `analysis_state`
   - a relationship group proposal
4. add any needed local `artifacts`, `contracts`, `integrations`, `providers`, and non-canonical proposal `workflows`
5. if a provider is implemented as code, write the provider code now and make sure it matches the contracts

Keep these `workflows` non-canonical and route them through proposal/review. Do not bypass review for local judgment-based relationship decisions.

## Phase 8: Run local proposal workflows and establish the governed layer

Only do this phase if the local query or review surface depends on approved governed relationships.

Use the real CLI surfaces:

```bash
cruxible propose --workflow <workflow_name>
cruxible group list
cruxible group get --group <group_id>
cruxible group resolve --group <group_id> --action approve
cruxible group resolve --group <group_id> --action reject
cruxible group resolutions
cruxible group trust --resolution <resolution_id> --status <watch|trusted|invalidated>
```

Validate real emitted groups against the approved local governed design.

If the grouping rule or review question is wrong, go back to Phase 6.  
If the provider output, signal mapping, or workflow wiring is wrong, go back to Phase 7.

After approving representative groups, verify the intended governed relationships now exist in world state:

```bash
cruxible stats
```

## Phase 9: Add the local query surface

Prefer inherited queries when they already answer the local question.

Add new local `named_queries` only when the inherited query surface is insufficient. Do not try to redefine inherited queries in place.

For each local query you are keeping:

1. choose the real local entry point
2. decide whether it depends on inherited state, local state, or both
3. keep the traversal as narrow and inspectable as the use case allows
4. summarize the local query surface for user confirmation

If an important local question has no clean path through the current fork, go back to the earlier phase that owns the problem:

- Phase 4 for local-boundary mistakes
- Phase 6 for governed design mistakes
- Phase 7 for proposal-workflow implementation mistakes

Write the actual local `named_queries` now in `config.yaml`, then:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
```

If local `providers`, `artifacts`, or `workflows` changed too, lock again:

```bash
cruxible lock
```

Run every local `named_query` you added, and any inherited query the handoff depends on:

```bash
cruxible query --query <query_name> --param key=value
cruxible explain --receipt <receipt_id>
```

## Phase 10: Check future upstream pull compatibility

Before handoff, confirm that the local config still stays compatible with future upstream pulls:

```bash
cruxible world status
cruxible world pull-preview
```

Inspect warnings, compatibility, and conflicts.

If the local config does not compose cleanly with the upstream preview:

- simplify the local fit
- move the conflicting change into upstream work
- or clearly document the pull risk before handoff

Only apply the pull if the user wants to test it directly:

```bash
cruxible world pull-apply --apply-digest <digest>
```

## Phase 11: Feedback, outcomes, and handoff

Only add local `feedback_profiles`, `outcome_profiles`, `quality_checks`, `constraints`, or `decision_policies` when the local config introduces real review or outcome surfaces that are not already covered.

Then summarize:

- what remains inherited
- what came from the applied `kit`
- what local entries were added
- what local canonical or proposal `workflows` were used
- what local `named_queries` were added and exercised
- whether local governed relationships were established
- the current `world status` / `pull-preview` result
- what should stay local versus what should be proposed upstream later
- next actions the user can take

Keep the local fit as small as the use case allows. Do not force local complexity that really belongs upstream.
