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

## Write Step B: Add workflow machinery

Extend the config with:

- `artifacts`
- `providers`
- `contracts`
- deterministic `workflows`

Add proposal or review-oriented workflows only where the need is already clear. Do not introduce Cruxible workflow machinery just because the schema allows it.

## Phase 4: Lock, run, and inspect the workflowed world

After workflow config changes:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
cruxible lock
```

Use `cruxible plan --workflow <workflow_name>` when you need to inspect the compiled workflow before running it.

Then run representative workflows:

```bash
cruxible run --workflow <workflow_name> --apply
```

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

## Phase 7: Understand the review and learning loop

Only after the base world, workflows, and named queries are in place:

1. identify where humans will review edges, proposals, or decisions
2. identify what repeated failure modes should become constraints, quality checks, or decision policies
3. identify what structured feedback should be captured
4. identify what downstream outcomes should be recorded
5. identify what feedback and outcome flywheels should improve the world over time
6. summarize the review and learning loop for user confirmation

Ask targeted questions only about the flywheel in this phase:

- what gets reviewed?
- what gets approved or rejected?
- what later real-world outcome tells you whether the system was right?
- what repeated failure should become a rule instead of a one-off correction?

## Write Step D: Add review, feedback, and outcome structure

Add the later-stage governance pieces that are actually justified:

- `quality_checks`
- `constraints`
- `decision_policies`
- `feedback_profiles`
- `outcome_profiles`

Design these around real recurring review and outcome surfaces, not speculative completeness.

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
