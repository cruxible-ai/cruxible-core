# Guide for AI Agents

This guide explains how AI agents (Claude Code, Cursor, Codex, or any MCP-capable agent) should orchestrate Cruxible Core. You provide the intelligence; Core provides deterministic execution with proof.

**MCP is the recommended interface** for domain onboarding and graph building. The CLI supports prompts and all core operations, but MCP returns structured data that agents can reason over more effectively.

## Role Separation

**You (the AI agent):**
- Understand the user's domain by reading docs and data
- Generate YAML configs defining entity types, relationships, queries, and constraints
- Reason about data to infer relationships (classification, matching, similarity)
- Propose entities and relationships with confidence scores and evidence
- Interpret query results and present them to humans
- Collect and record feedback

**Core (the runtime):**
- Validates configs against the schema
- Ingests data into the entity graph
- Executes named queries deterministically
- Produces receipts (structured proofs) for every query
- Stores and applies feedback
- Evaluates graph quality and constraint compliance

Scripts are appropriate for data cleaning and transforms, but not for inference tasks like classification or matching — use your judgment and `cruxible_add_relationship` for those.

## Start Here

The fastest way to get running is with a demo directory. Each demo includes a `.mcp.json` (MCP server config), `config.yaml`, and a prebuilt graph — everything needed for a self-contained workspace.

**Recommended starting point:** `demos/drug-interactions/`

```bash
cd demos/drug-interactions
# The .mcp.json here configures cruxible-mcp automatically
```

The graph is prebuilt. Load it and start querying:

```
1. cruxible_init(root_dir=".")                          # loads existing graph
2. cruxible_query("check_interactions", params={"drug_id": "warfarin"})
3. cruxible_query("enzyme_impact", params={"drug_id": "fluoxetine"})
```

Other named queries available: `find_mechanism`, `suggest_alternative`.

Every demo directory is a self-contained MCP workspace — the `.mcp.json` points at `cruxible-mcp` so agents can discover tools automatically when opened in that directory.

## Workflow Prompts

Cruxible includes guided workflow prompts that provide step-by-step instructions for common tasks. Use `cruxible_prompt()` to list them, or `cruxible_prompt("name", {args})` to read one.

| Prompt | Args | Description |
|--------|------|-------------|
| `onboard_domain` | `domain` | Full workflow from raw data to working graph (11 steps) |
| `prepare_data` | `data_description` | Checklist for profiling and cleaning data before ingestion |
| `review_graph` | `instance_id` | Review and improve an existing graph's quality |
| `user_review` | `instance_id` | Collaborative edge review session with a human |
| `analyze_feedback` | `instance_id`, `relationship_type` | Discover rejection patterns worth encoding as constraints |
| `common_workflows` | _(none)_ | Common multi-tool sequences for debugging, review, and auditing |

**Start with `onboard_domain`** for new domains, or **`review_graph`** for existing graphs. The prompts contain detailed checklists that go deeper than the summaries below.

```
cruxible_prompt("onboard_domain", {"domain": "drug interactions"})
```

## Lifecycle

The standard lifecycle follows this order:

```
validate → init → ingest → add entities/relationships → query → feedback → outcome → evaluate
```

### Ordering Rules

1. `cruxible_validate` before `cruxible_init` — fail fast on bad config
2. Ingest entities before relationships — edges reference entity IDs
3. For inferred relationships, use `cruxible_add_relationship` after ingestion
4. For entities from free text, use `cruxible_add_entity` (entities must exist before adding relationships to them)
5. Use the `instance_id` from `cruxible_init` in all subsequent calls

## Onboarding a New Domain

Follow this workflow when going from raw data to a working graph.

### Step 1 — Discover the Domain

Before writing any config, understand the domain and the data:
- Explore data files: schema, columns, dtypes, row counts, sample rows
- Identify entity types, relationships, and key properties
- Brainstorm 2–4 questions the graph should answer
- Propose the domain model to the user; wait for confirmation before writing config

### Step 2 — Prepare Data

Profile and clean data files before ingestion:
- Check row counts, column types, null counts
- Validate primary key uniqueness (duplicates = wrong grain)
- Validate foreign keys (orphan FKs = broken edges)
- Check join keys across files (zero overlap = wrong join key)
- Remove junk rows (sentinels, test data, all-null rows)
- Fix encoding issues and extract embedded structured data

Use external tools (Python, Polars, etc.) for all cleaning. Cruxible ingests and evaluates; cleaning is external.

### Step 3 — Write the YAML Config

Define all required sections:

- **entity_types**: Dict keyed by type name. Mark the ID property with `primary_key: true` (on the property, not the entity).
- **relationships**: `from`/`to` entity types, optional edge properties, cardinality. Include cross-dataset relationship types — but do NOT create ingestion mappings for them. They'll be populated via `cruxible_find_candidates` in Step 6.
- **named_queries**: Leave this section empty for now. You'll design queries in Step 7 after seeing what's actually in the graph.
- **constraints**: Validation rules with severity levels.
- **ingestion**: Mappings for entity files and deterministic relationship files only.

See the [Config Reference](config-reference.md) for the full schema.

### Step 4 — Validate and Initialize

```
1. cruxible_validate(config_path="config.yaml")
2. cruxible_init(root_dir=".", config_path="config.yaml")
3. Save the instance_id for all subsequent calls
```

### Step 5 — Ingest Source Data

Load entities first, then relationships. Ingestion mappings are defined in the config — use the mapping name, not the filename:

```
1. cruxible_ingest(instance_id, "<entity_mapping>", file_path="data/<entities>.csv")
2. cruxible_ingest(instance_id, "<another_entity_mapping>", file_path="data/<other_entities>.csv")
3. cruxible_ingest(instance_id, "<relationship_mapping>", file_path="data/<relationships>.csv")
```

Check for errors after each ingestion step before continuing. Use `cruxible_schema` to see available mapping names if unsure.

### Step 6 — Discover Cross-References

For entities from free text or external sources (no CSV):
- Use `cruxible_add_entity` — entities must exist before you can add relationships to them.

For each cross-dataset relationship type, use `cruxible_find_candidates`:

1. Use `cruxible_sample` to inspect entities on both sides
2. Use `property_match` with `iequals` on name fields to cross-reference entities across types/datasets
3. Use `shared_neighbors` when entities share connections through an intermediary
4. Review candidates and persist confirmed matches with `cruxible_add_relationship` — include `source`, `confidence`, and `evidence` in properties

`cruxible_find_candidates` only does exact/iequals matching. For fuzzy matching, transliteration, or abbreviation handling, use your own tools (Python, Polars, etc.) and persist matches with `cruxible_add_relationship`.

### Step 7 — Design Named Queries

Now that you can see what entities and relationships are in the graph, design the named queries. Start from the use cases proposed in Step 1.

Key considerations:
- **Entry point**: which entity type does the user start from?
- **Traversal direction**: outgoing follows ownership chains; incoming finds who owns/controls the entry entity
- **Multi-relationship fan-out**: a single step can traverse multiple relationship types

Add the named queries to the YAML config, re-validate with `cruxible_validate`, and reload with `cruxible_init(root_dir=...)` (omit `config_path` to reload).

### Step 8 — Validate Graph Quality

`cruxible_evaluate` checks structural health — orphans, violations, coverage gaps. For deeper review including cross-dataset gap analysis and intelligence-driven discovery, run the `review_graph` prompt:

```
cruxible_prompt("review_graph", {"instance_id": "<instance_id>"})
```

### Step 9 — Run Sample Queries

1. Run `cruxible_query` on representative cases. The `params` dict must include the primary-key property of the entry_point entity type.
2. Inspect receipt traversals to confirm correctness.
3. Confirm output matches domain expectations.

### Step 10 — Provide Feedback

1. Use `cruxible_feedback` on key edges (pass `source="ai_review"` when you are the reviewer, `source="human"` when relaying a human's judgment)
2. Record end-to-end correctness with `cruxible_outcome`
3. Use `cruxible_find_candidates` to discover missing links
4. Use `cruxible_add_relationship` to persist confirmed candidates

### Step 11 — Handoff

Present what was built so the user knows what they have and how to use it:
- Entity type counts and sources
- Relationship counts and how they were added (source data, find_candidates, AI-inferred)
- Named queries with example `params` dicts the user can copy-paste
- Suggested next steps (query, audit, review edges, discover, health check, add rules)

## Common Workflows

### Debugging a Query

1. `cruxible_schema` — verify query and traversal definitions exist
2. `cruxible_sample` — confirm source entities are present in the graph
3. `cruxible_query` — run with focused parameters
4. `cruxible_receipt` — inspect the traversal trace for unexpected paths
5. Fix config or data, then repeat

### Edge-Level Review

1. `cruxible_query` — get a `receipt_id`
2. `cruxible_feedback` — approve, reject, flag, or correct specific edges
3. Re-run the query to confirm behavior changes

### Iterative Graph Refinement

1. `cruxible_evaluate` — get current findings
2. `cruxible_find_candidates` — discover likely missing edges
3. `cruxible_add_relationship` — persist confirmed candidates
4. Re-evaluate and compare counts

### Auditing a Decision

1. `cruxible_list(resource_type="receipts")` — locate the query run
2. `cruxible_receipt` — get traversal evidence
3. `cruxible_list(resource_type="feedback", receipt_id=...)` — see feedback
4. `cruxible_list(resource_type="outcomes", receipt_id=...)` — see outcomes

### Feedback-to-Constraint Workflow

When rejection patterns emerge from feedback:

1. List feedback records and filter for `action="reject"` on the target relationship
2. For each rejected edge, look up source and target entity properties with `cruxible_get_entity`
3. Compare rejected edges — look for shared property mismatches
4. If a pattern is strong (5+ rejections), propose a constraint
5. Call `cruxible_add_constraint` with the rule expression
6. Run `cruxible_evaluate` to verify the new constraint flags expected violations

## Config Authoring Tips

### Entity Types
- Mark the ID property with `primary_key: true` on the property itself
- Properties are required by default; use `optional: true` for nullable fields
- Use `enum: [...]` to restrict property values
- Use `indexed: true` for properties you'll filter on frequently

### Relationships
- `from`/`to` must reference existing entity type names
- Include `source`, `confidence`, and `evidence` in [edge properties](concepts.md#edge-properties) for AI-inferred relationships
- Use `inverse` for bidirectional traversal

### Ingestion Mappings
- One mapping per data source (entity or relationship)
- Use `column_map` to rename CSV columns to property names: `{csv_column: property_name}`
- For inferred relationships, use `cruxible_add_relationship` instead of writing scripts to batch-produce CSVs

### Named Queries
- Keep traversals focused — one clear question per query
- Use `filter` on traversal steps to narrow results
- Use `constraint` for runtime parameter binding (e.g., `target.drug_id == $drug_id`)

### Constraints
- Rule format: `RELATIONSHIP.FROM.property == RELATIONSHIP.TO.property`
- Use `severity: warning` unless the violation rate is very high, then use `error`
- Constraints are evaluated by `cruxible_evaluate`, not during ingestion

## Anti-Patterns

- **Embedding LLM calls in scripts that batch-produce CSVs** — Use `cruxible_add_relationship` for inference tasks instead. Scripts are for cleaning, not reasoning.
- **Ingesting relationships before entities** — Edges reference entity IDs. Ingest entities first.
- **Skipping validation** — Always run `cruxible_validate` before `cruxible_init`. Fail fast.
- **Ignoring evaluate results** — Run `cruxible_evaluate` after every major change. Orphans and gaps indicate data problems.
- **Omitting `source`, `confidence`, and `evidence` on inferred edges** — Always include these [edge properties](concepts.md#edge-properties) when proposing AI-inferred relationships. They enable meaningful feedback and constraint analysis.
- **Overloading a single query** — Split complex questions into multiple focused named queries rather than one query with many traversal steps.
