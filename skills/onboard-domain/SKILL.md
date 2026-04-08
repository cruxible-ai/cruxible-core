---
name: onboard-domain
description: Go from raw domain data to a working Cruxible world using the real CLI flow.
---

# Onboard Domain

Use this skill when a user wants to turn new data into a usable Cruxible world.

If the source files are messy, run `prepare-data` first.

## Phase 1: Understand the domain

Before writing config:

1. inspect the source files
2. identify entity types and primary keys
3. identify deterministic relationships present in the data
4. identify inferred or cross-dataset relationships that will need review or matching
5. propose 2-4 user-facing questions the world should answer
6. summarize the model for user confirmation before building

Use a concrete summary:

- entity type
- likely primary key column
- key properties
- source file
- relationship name
- from -> to
- how it gets populated
- notes or ambiguities

Do not start writing config until the model is confirmed.

## Phase 2: Write the config

Prefer deterministic loading via:

- `entity_types`
- `relationships`
- `contracts`
- `artifacts`
- `providers`
- `workflows`

Use `ingestion` only when intentionally keeping a legacy mapping-based config.

For the first pass, write:

- clear descriptions
- primary keys on entity properties
- deterministic workflows/providers/artifacts needed for loading
- constraints for obvious bad states

Do not spend time polishing named queries yet. Add them after the initial graph shape is visible.

## Phase 3: Validate and initialize

Use the real CLI:

```bash
cruxible validate --config config.yaml
cruxible init --config config.yaml --root-dir .
```

Use `--data-dir` only when the config expects a separate data directory.

Stop on validation or init errors.

## Phase 4: Load deterministic state

If the config uses workflows:

```bash
cruxible lock
cruxible run --workflow <workflow_name> --apply
```

If you need to inspect canonical preview state before committing:

```bash
cruxible run --workflow <workflow_name>
cruxible apply --workflow <workflow_name> --apply-digest <digest> --head-snapshot <snapshot_id>
```

Use `cruxible plan --workflow <workflow_name>` when you need to inspect the compiled workflow before running it.

Legacy path:

```bash
cruxible ingest --mapping <mapping_name> --file <path>
```

Do not keep going past tool errors.

## Phase 5: Inspect the loaded graph before designing queries

After loading, inspect what actually exists:

```bash
cruxible schema
cruxible stats
cruxible sample --type <EntityType> --limit 5
cruxible inspect entity --type <EntityType> --id <entity_id>
```

Confirm:

- entity types and counts look plausible
- key relationships actually exist
- sample entities have the expected properties
- representative entities have the expected neighbors

If the world shape is wrong, fix config or loaders before adding named queries.

## Phase 6: Add inferred or cross-dataset relationships

Choose the simplest path that matches the problem:

- simple exact or case-insensitive matching
- reviewed relationship creation
- free-text or ambiguous cases with explicit review

Entities from free text or outside the deterministic load must exist before you relate them:

```bash
cruxible add-entity ...
cruxible add-relationship ...
```

## Phase 7: Design named queries and reload the config

Once the graph shape is stable, add named queries to `config.yaml`.

When the config changes, do not re-init. Reload it:

```bash
cruxible validate --config config.yaml
cruxible reload-config --config config.yaml
```

If providers, artifacts, or workflows changed, lock again:

```bash
cruxible lock
```

Query-design rules:

1. choose the real entry point entity type
2. choose traversal direction carefully
3. keep fan-out controlled
4. test representative cases, not just happy-path IDs
5. inspect receipts, not just results

## Phase 8: Prove the queries work

Run at least one real query and inspect its receipt:

```bash
cruxible query --query <query_name> --param key=value
cruxible explain --receipt <receipt_id>
```

Do not hand off a world whose named queries have not been exercised.

## Phase 9: Evaluate and hand off

1. run `cruxible evaluate`
2. sample representative queries again if needed
3. run `review-graph` if the world needs deeper quality work
4. summarize:
   - entity counts
   - relationship counts
   - deterministic workflows used
   - named queries with example invocations
   - one representative query or receipt that was checked
   - next actions the user can take
