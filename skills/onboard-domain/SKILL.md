---
name: onboard-domain
description: Go from raw domain data to a working Cruxible world through staged understanding, config writes, loading, and review-loop design.
---

# Onboard Domain

Use this skill when a user wants to turn new data into a usable Cruxible world.

If the source files are messy, run `prepare-data` first.

Work in stages. Do not try to design the graph, workflows, queries, and review loop all at once.

## Phase 1: Understand the domain shape

Before writing config:

1. inspect the source files
2. identify entity types and likely primary keys
   - a primary key is the stable property that uniquely identifies one real entity across reloads and updates
   - prefer durable source IDs or external identifiers
   - avoid names, titles, or other mutable text unless there is no better identifier
   - if no good primary key exists, stop and design one before continuing
3. identify deterministic relationships between entities that can be loaded directly from the source data
4. identify any obvious bad states that should remain invalid across future ingests, refreshes, and graph updates, and should later become constraints or quality checks
   - do not invent constraints just to fill the slot
   - if there are no clear durable invalid states yet, leave this empty for now
5. identify the major user-facing query and use-case categories the world should eventually support
6. summarize the structural model for user confirmation

Use a concrete summary:

- entity type
- likely primary key column
- key properties
- source file
- relationship name
- from -> to
- how it gets populated
- notes or ambiguities

Ask targeted questions only about domain shape in this phase. Do not jump ahead to workflow design unless the user raises it.

## Write Step A: Write the base graph config

Write only the minimum needed for the base graph:

- `entity_types`
- `relationships`
- obvious `constraints`
- minimal `contracts` only if clearly required

Do not spend time on named queries, review loops, or advanced workflows yet.

## Phase 2: Validate the base graph config

Use the real CLI:

```bash
cruxible validate --config config.yaml
cruxible init --config config.yaml --root-dir .
```

At this stage, the goal is not to design or run the full operational loading path yet. The goal is to confirm that the base graph definition is coherent enough to proceed.

Stop on validation or init errors. Do not continue with a broken base config.

## Phase 3: Understand the operational workflows

Once the base graph shape is real, figure out how this world is built and maintained over time.

Start with the operating loop, not the config nouns. Ask:

1. where does new data come from?
2. what repeatable steps turn raw inputs into graph state?
3. which steps are deterministic and repeatable?
4. which steps require judgment, matching, or review?
5. what should be automatically committed versus proposed for review?
6. summarize the workflow plan for user confirmation

Ask targeted questions only about operations in this phase:

- how often does data refresh?
- what should be automatically rebuilt?
- what should be proposed instead of directly applied?
- where is human review required?

Then translate those answers into Cruxible terms:

- `artifacts`: input files, bundles, or external data sources the workflow depends on
- `providers`: reusable logic, model calls, or external processing steps
- `contracts`: structured workflow input and output shapes
- `workflows`: repeatable procedures that build, refresh, or propose graph state
- `canonical` workflows: workflows whose results are written directly into world state instead of first becoming reviewable proposals. Use this only for deterministic or otherwise highly trusted operations that are safe to commit without a proposal/review step.

At the end of this phase, separate the workflow plan into two buckets:

- canonical workflows to design now
- judgment-based workflows that should become reviewable proposals later

For the later judgment-based workflows, define the task and the expected input/output shape now, but defer detailed provider and proposal-workflow design until after the graph and query surfaces are clearer.

## Write Step B: Add workflow machinery

Fully design the canonical workflow path now. Extend the config with:

- `artifacts`
- `contracts`
- `providers` needed for deterministic or otherwise trusted steps
- deterministic `workflows`

For judgment-based tasks that will need model judgment, matching, ranking, or review:

- add only the `contracts` needed to describe their input and output shapes
- do not build the provider-backed proposal workflows yet
- do not mark these tasks `canonical`

Do not introduce Cruxible workflow machinery just because the schema allows it.

## Phase 4: Build and inspect the world for the first time

After workflow config changes:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
cruxible lock
```

Use `cruxible plan --workflow <workflow_name>` when you need to inspect the compiled workflow before running it.

Then run every canonical build or refresh workflow you defined in Step B, in dependency order:

```bash
cruxible run --workflow <workflow_name> --apply
```

This is the first real population step. Use it to build or refresh the world through the full canonical workflow path you designed in Step B.

Do not run judgment-based or proposal workflows in this phase. This phase is only for the workflows that are safe to apply directly to world state.

Re-check the world with:

```bash
cruxible stats
cruxible sample --type <EntityType> --limit 5
cruxible inspect entity --type <EntityType> --id <entity_id>
```

## Phase 5: Design the governed group layer

Only add this phase if the domain needs reviewable, judgment-based relationships beyond the canonical layer.

Before choosing providers or proposal workflow steps, understand the proposal process at a high level:

- a non-canonical proposal workflow should produce candidate relationships and a relationship-group proposal
- those candidate relationships do not go directly into world state
- instead, Cruxible turns them into a reviewable group for one relationship type
- an `integration` is the named source of judgment used in governed relationship proposals
- a `provider` may produce the raw output, but the `integration` name is what Cruxible uses for signal guardrails, review policy, and trust reuse
- a `signal` is one integration's judgment about one candidate relationship:
  - `support`: this integration supports the relationship
  - `contradict`: this integration argues against the relationship
  - `unsure`: this integration cannot support the relationship strongly enough to approve it
- signals should carry short evidence that explains why the integration produced that judgment
- the group carries:
  - a human-readable `thesis_text`
  - structured `thesis_facts` that define the stable identity/signature of the proposal
  - `analysis_state` for useful context that should help review but should not define identity
  - member-level signals
- the group is then reviewed, approved, rejected, or reused through prior trust
- approved groups create relationships later; rejected groups still matter because they establish precedent and trust context

Before choosing providers or proposal workflow steps, design the governed group structure itself. Ask:

1. which relationship types should be proposed and reviewed instead of written canonically?
2. what candidate relationships belong in the same group, and what should be split into separate groups?
3. what is the unit of review for this relationship type, and what single judgment should one reviewable group ask the reviewer to make?
4. what human-readable thesis should explain why this group exists?
5. what structured `thesis_facts` should define the group's stable identity and signature?
6. what useful reviewer context should stay in `analysis_state` instead of the signature?
7. which integrations or evidence sources should contribute signals?
8. which integrations are `blocking`, `required`, or `advisory`?
9. should `unsure` always force review for any integration?
10. should this relationship type ever auto-resolve, and if so under what prior trust rule?
11. do the user-facing named queries depend on approved governed relationships, or only on canonical state?
12. summarize the governed group design for user confirmation

Ask targeted questions only about group semantics in this phase:

- what is the actual unit of review?
- what facts should define "the same thesis" across repeated proposals?
- what information is useful for analysis but should not affect signature reuse?
- when should a new proposal inherit prior trust?
- when should it be forced into review or critical review?

## Write Step C: Add governed-group structure

Add the config pieces that define the governed relationship layer:

- relationship `matching` config where needed
- `contracts` for proposal artifact inputs and outputs
- any schema structure needed to support group proposals later

Do not choose providers or build proposal workflows yet. First make the group semantics explicit.

## Phase 6: Design provider-backed proposal workflows

Only after the governed group structure is clear:

1. identify which ambiguous tasks need provider-backed matching, classification, ranking, or recommendation
2. identify what raw inputs each task needs from the graph or artifacts
3. identify what outputs the provider should produce before signal mapping
4. decide how provider output becomes candidates, signals, and finally a relationship group proposal
5. decide which workflows should end in `propose_relationship_group`
6. summarize the proposal-workflow design for user confirmation

Ask targeted questions only about provider-backed judgment in this phase:

- what exactly is the model or logic deciding?
- what evidence should the provider emit for each candidate?
- what should become a `support`, `contradict`, or `unsure` signal?
- what should be proposed as a group instead of directly persisted?

## Write Step D: Add proposal workflows and providers

Add the later-stage judgment machinery that is actually justified:

- provider-backed proposal workflows for judgment-based tasks
- any additional `providers` those workflows require
- any additional `contracts` those workflows require

Keep judgment-based workflows non-canonical unless there is a compelling reason to bypass the proposal/review step.

## Phase 7: Run proposal workflows and establish the governed layer

Only do this phase if named queries or downstream review depend on approved governed relationships.

Run the proposal workflows, inspect the resulting groups, and review enough representative groups to make the intended governed layer real.

Use the real CLI surfaces for this work:

```bash
cruxible propose --workflow <workflow_name>
cruxible group list
cruxible group get --group <group_id>
cruxible group resolve --group <group_id> --action approve
```

If trust or reuse behavior matters, inspect prior resolutions and trust status before moving on.

Do not design the final query surface against a world that is still missing the governed relationships it is supposed to rely on.

## Phase 8: Understand the user-facing query surface

Only after the graph and workflows are real:

1. identify the repeated user questions that matter most
2. choose the real entry-point entity type for each question
3. decide the traversal direction and fan-out needed
4. identify what evidence path a human should be able to inspect
5. summarize the planned query surface for user confirmation

Ask targeted questions only about usage in this phase:

- what does the user start from?
- what answer shape do they want back?
- what neighboring context is required?
- what would make an answer trustworthy?

## Write Step E: Add named queries

Add `named_queries` only after the graph shape is stable.

When the config changes:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
```

If providers, artifacts, or workflows changed too, lock again:

```bash
cruxible lock
```

Query-design rules:

1. choose the real entry point entity type
2. choose traversal direction deliberately
3. keep fan-out controlled
4. test representative cases, not just happy-path IDs
5. inspect receipts, not just results

## Phase 9: Prove the queries work

Run at least one real query and inspect its receipt:

```bash
cruxible query --query <query_name> --param key=value
cruxible explain --receipt <receipt_id>
```

Do not hand off a world whose named queries have not been exercised.

## Phase 10: Understand the feedback and outcome flywheel

Only after the base world, proposal layer, and named queries are in place:

1. identify where humans will review relationships, proposals, or decisions
2. identify what repeated failure modes should become constraints, quality checks, or decision policies
3. identify what structured feedback should be captured
4. identify what downstream outcomes should be recorded
5. identify what feedback and outcome flywheels should improve the world over time
6. summarize the feedback and outcome flywheel for user confirmation

Ask targeted questions only about the flywheel in this phase:

- what gets reviewed?
- what gets approved or rejected?
- what later real-world outcome tells you whether the system was right?
- what repeated failure should become a rule instead of a one-off correction?

## Write Step F: Add feedback and outcome structure

Add the later-stage governance pieces that are actually justified:

- `quality_checks`
- `constraints`
- `decision_policies`
- `feedback_profiles`
- `outcome_profiles`

Design these around real recurring review and outcome surfaces, not speculative completeness.

## Phase 11: Evaluate and hand off

Run:

```bash
cruxible evaluate
```

Then summarize:

- entity counts
- relationship counts
- deterministic workflows used
- named queries with example invocations
- one representative query or receipt that was checked
- review surfaces and feedback/outcome plans
- next actions the user can take

Simple domains may stop earlier. Do not force every domain to use every later-stage feature.
