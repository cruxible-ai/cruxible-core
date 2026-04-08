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

## Phase 5: Understand the user-facing query surface

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

## Write Step C: Add named queries

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

## Phase 6: Prove the queries work

Run at least one real query and inspect its receipt:

```bash
cruxible query --query <query_name> --param key=value
cruxible explain --receipt <receipt_id>
```

Do not hand off a world whose named queries have not been exercised.

## Phase 7: Understand the judgment, review, and learning loop

Only after the base world, workflows, and named queries are in place:

1. identify which matching, classification, ranking, or recommendation tasks should become provider-backed proposal workflows
2. identify where humans will review edges, proposals, or decisions
3. identify what repeated failure modes should become constraints, quality checks, or decision policies
4. identify what structured feedback should be captured
5. identify what downstream outcomes should be recorded
6. identify what feedback and outcome flywheels should improve the world over time
7. summarize the judgment, review, and learning loop for user confirmation

Ask targeted questions only about the flywheel in this phase:

- which ambiguous tasks need provider-backed judgment instead of deterministic loading?
- what gets reviewed?
- what gets approved or rejected?
- what later real-world outcome tells you whether the system was right?
- what repeated failure should become a rule instead of a one-off correction?

## Write Step D: Add proposal, feedback, and outcome structure

Add the later-stage governance pieces that are actually justified:

- provider-backed proposal workflows for judgment-based tasks
- any additional `providers` those workflows require
- `quality_checks`
- `constraints`
- `decision_policies`
- `feedback_profiles`
- `outcome_profiles`

Design these around real recurring review and outcome surfaces, not speculative completeness. Keep judgment-based workflows non-canonical unless there is a compelling reason to bypass the proposal/review step.

## Phase 8: Evaluate and hand off

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
