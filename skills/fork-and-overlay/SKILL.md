---
name: fork-and-overlay
description: Fork a published reference world, adapt a local kit and overlay, and keep the result pullable by refining inherited config instead of rebuilding the world from scratch.
---

# Fork And Overlay

Use this skill when a user wants to start from a published reference world and adapt it to a local context.

Assume there is a local kit with starter config, providers, contracts, workflows, docs, or examples. Prefer adapting the inherited world and the kit before writing new local machinery.

## Core Rules

- edit the local overlay `config.yaml`, not `.cruxible/upstream/current/config.yaml`
- treat `.cruxible/composed/config.yaml` as generated output, not as the source of truth
- keep the overlay append-only and pull-friendly
- prefer `cruxible world fork --world-ref ...` over raw `--transport-ref` unless the user truly needs an ad hoc source
- if the desired change really belongs in the reference world, note it as upstream work instead of forcing it into the overlay
- prefer refining the kit over adding new code

## Overlay Rules

The runtime composer is strict. Keep these rules in mind before writing overlay config:

- keyed-map sections are add-only:
  - `entity_types`
  - `named_queries`
  - `integrations`
  - `contracts`
  - `artifacts`
  - `providers`
  - `workflows`
  - `feedback_profiles`
  - `outcome_profiles`
- `relationships` are add-only by relationship name
- `constraints`, `quality_checks`, `tests`, and `decision_policies` append
- only `name` and `description` should be treated as directly replaceable

If the desired local change would redefine an upstream `relationship`, `named_query`, `provider`, `workflow`, `feedback_profile`, or `outcome_profile`, that is not an overlay change. Treat it as upstream work.

## Phase 1: Understand the local goal and the kit

Before forking:

1. inspect the local kit and identify what it already provides
2. identify the local problem the reference world is supposed to solve or extend
3. identify what the user wants to refine locally instead of rebuilding from scratch
4. summarize the local objective for user confirmation

Keep this phase focused on refinement. Do not redesign the entire world from scratch unless the user is actually in the wrong skill.

## Phase 2: Fork and inspect the baseline

Create the local fork unless you are already inside the target fork instance:

```bash
cruxible world fork --world-ref <alias> --root-dir <root_dir>
```

Use `alias@release` only when the user intentionally wants to start from a specific older release:

```bash
cruxible world fork --world-ref <alias@release> --root-dir <root_dir>
```

Use raw `--transport-ref` only as a fallback for unpublished, ad hoc, or explicitly manual sources.

Then inspect the forked baseline:

```bash
cruxible world status
cruxible stats
cruxible sample --type <EntityType> --limit 5
cruxible inspect entity --type <EntityType> --id <entity_id>
```

Also inspect the three config layers:

- local overlay: `config.yaml`
- inherited upstream config: `.cruxible/upstream/current/config.yaml`
- active composed runtime config: `.cruxible/composed/config.yaml`

Use this phase to understand what the inherited reference world already provides before changing the overlay.

If you forked from `alias@release`, remember what that means:

- the fork starts from that specific published release
- later `world pull-preview` and `world pull-apply` use the fork's tracked upstream metadata
- you do not keep re-supplying the alias after the fork is created

## Phase 3: Define the overlay boundary

Decide what kind of change this really is:

1. what does the inherited reference world already provide?
2. what does the local kit already provide?
3. what needs local refinement instead of local invention?
4. what truly needs new local entities, relationships, workflows, queries, or review surfaces?
5. what should stay local versus be proposed upstream later?
6. summarize the overlay boundary for user confirmation

Keep this phase ownership-focused. If a change would require redefining upstream keyed entries, relationship names, or semantics, call that out as upstream work instead of forcing it into the overlay.

## Write Step A: Apply the kit and write the local overlay

Edit the local overlay `config.yaml` only.

Use the kit as the starting point where possible. Extend the overlay with only the local pieces that are actually needed:

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

Use local names for new overlay entries so they do not collide with upstream keys.

Do not copy large parts of the reference world into the overlay. Reuse inherited config and kit patterns wherever possible.

## Phase 4: Validate and build the local canonical layer

After overlay changes:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
cruxible lock
```

Run only the local canonical `workflows` you added through the overlay:

```bash
cruxible run --workflow <workflow_name> --apply
```

Do not try to rebuild the upstream reference world here. The inherited reference state is already materialized; the local overlay should add local state and local behavior on top of it.

Re-check the local world with:

```bash
cruxible stats
cruxible sample --type <EntityType> --limit 5
cruxible inspect entity --type <EntityType> --id <entity_id>
```

If the inherited world plus the kit already solve the user’s local problem, stop adding machinery.

## Phase 5: Add local governed relationship design only if needed

Only add this phase if the local context needs reviewable, judgment-based relationships beyond the inherited world.

Prefer adapting existing governed patterns from the kit before inventing new ones.

For each new local governed relationship type:

1. identify the local review surface and why canonical loading is not enough
2. define the grouping rule and unit of review
3. define the intended `thesis_facts` and `analysis_state`
4. identify the evidence policy in principle
5. decide whether local queries depend on approved governed relationships
6. summarize the governed overlay design for user confirmation

Before implementing local proposal workflows, capture the approved design in:

```text
design/governed/<relationship_type>.yaml
```

Keep this design note local and overlay-specific. If the governed relationship should really be part of the reference world, call that out instead of normalizing it into the overlay.

## Phase 6: Implement local proposal workflows only when needed

Use the approved governed design note and the kit as the source of truth.

Prefer adapting existing kit `providers`, `integrations`, `contracts`, and `workflows` before writing new ones.

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

## Phase 7: Run local proposal workflows and establish the governed layer

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

If the grouping rule or review question is wrong, go back to Phase 5.
If the provider output, signal mapping, or workflow wiring is wrong, go back to Phase 6.

After approving representative groups, verify the intended governed relationships now exist in world state:

```bash
cruxible stats
```

## Phase 8: Add the local query surface

Prefer inherited queries when they already answer the local question.

Add new local `named_queries` only when the inherited query surface is insufficient. Do not try to redefine upstream queries in place.

For each local query you are keeping:

1. choose the real local entry point
2. decide whether it depends on inherited state, local overlay state, or both
3. keep the traversal as narrow and inspectable as the use case allows
4. summarize the local query surface for user confirmation

If an important local question has no clean path through the current world, go back to the earlier phase that owns the problem:

- Phase 3 for overlay-boundary mistakes
- Phase 5 for governed design mistakes
- Phase 6 for proposal-workflow implementation mistakes

Write the actual local `named_queries` now in `config.yaml`, then:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
```

If local `providers`, `artifacts`, or `workflows` changed too, lock again:

```bash
cruxible lock
```

Run every local `named_query` you added, and any inherited query the local handoff depends on:

```bash
cruxible query --query <query_name> --param key=value
cruxible explain --receipt <receipt_id>
```

## Phase 9: Prove pullability

Before handoff, confirm that the overlay still behaves like a pullable fork:

```bash
cruxible world status
cruxible world pull-preview
```

Inspect warnings, compatibility, and conflicts. These commands use the fork's tracked upstream metadata; they do not require the original `world_ref` to be provided again.

If the overlay does not compose cleanly with the upstream preview:

- simplify the overlay
- move the conflicting change into upstream work
- or clearly document the pull risk before handoff

Only apply the pull if the user wants to test it directly:

```bash
cruxible world pull-apply --apply-digest <digest>
```

## Phase 10: Feedback, outcomes, and handoff

Only add local `feedback_profiles`, `outcome_profiles`, `quality_checks`, `constraints`, or `decision_policies` when the local overlay introduces real review or outcome surfaces that the inherited world does not already cover.

Then summarize:

- what stays inherited from the reference world
- what came from the local kit
- what local overlay entries were added
- what local canonical or proposal `workflows` were used
- what local `named_queries` were added and exercised
- whether governed local relationships were established
- the current `world status` / `pull-preview` result
- what should stay local versus what should be proposed upstream later
- next actions the user can take

Keep the overlay as small and pull-friendly as the local problem allows. Do not force local complexity that really belongs upstream.
