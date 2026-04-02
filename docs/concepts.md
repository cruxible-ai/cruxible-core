# Concepts

Cruxible Core is a deterministic world-model runtime with receipts. This guide explains the architecture, primitives, and workflows that make it work.

## World Model, Not Agent Scratch Memory

Cruxible is for shared domain state: entities, relationships, constraints, named queries, and accepted judgments that need to persist across agents, users, and runs.

It is not a scratchpad for an individual agent's temporary notes or prompt context.

- **Agent memory** is agent-centric, heuristic, and useful for continuity.
- **Cruxible state** is domain-centric, explicit, reviewable, and meant to be operationally trusted.
- **Receipts** explain how a result or proposal was produced.
- **Feedback and outcomes** calibrate accepted judgment over time.

## Coherence and Shared Truth

LLM agents do not expose a stable, inspectable internal state. What looks like "state" is really a transient encoding of the current prompt, retrieved context, and recent tool outputs.

That becomes a coherence problem as soon as more than one agent or human is involved. Two capable agents can start from nearly the same material and still diverge because they:

- saw different slices of context
- summarized prior work differently
- retrieved different evidence
- interpreted procedure or policy differently
- carried forward different local assumptions

In practice this creates three different coherence problems:

- **factual coherence**: what is true?
- **procedural coherence**: what workflow are we following?
- **judgment coherence**: what has already been approved, rejected, corrected, or deferred?

Without an external shared substrate, each agent is effectively carrying a lossy private replica of reality. That is acceptable for lightweight tasks. It breaks down for repeated, collaborative, or high-stakes work.

Cruxible addresses this by externalizing the parts that should not live only in prompt-local context:

- accepted facts and relationships
- named queries and constraints
- review status and governed judgments
- provenance and receipts explaining how state was produced

Agents can still keep private working memory, but they coordinate against the same operational state instead of against incompatible internal summaries.

## AI Outside, Determinism Inside

Cruxible inverts the typical AI architecture. Instead of embedding an LLM inside the decision engine, it keeps the AI entirely outside:

```
┌──────────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code, Cursor, Codex, ...)                  │
│                                                              │
│  Writes configs, orchestrates workflows, reasons about       │
│  relationships, interprets results, proposes governed edges  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  Cruxible Core (the runtime)                                 │
│                                                              │
│  Deterministic. No LLM. No opinions. No API keys.            │
│  Config → Workflow → Graph → Query → Receipt → Feedback      │
└──────────────────────────────────────────────────────────────┘
```

This means:
- **No API keys** in the runtime — no LLM calls, no token costs during execution
- **Reproducible results** — same config + same data = same output, every time
- **Auditable decisions** — every answer includes a receipt showing exactly how it was derived
- **Domain-agnostic** — the agent adapts to any vertical by reading the config

## Six Primitives

### Config

A YAML file that defines the decision domain: entity types with typed properties, relationships between entities, declarative named queries, validation constraints, ingestion mappings, workflows, providers, integrations, quality checks, feedback profiles, outcome profiles, and decision policies.

The config is the single source of truth for a shared domain/world model. AI agents write it; Core validates and executes against it. See [Config Reference](config-reference.md) for the full schema.

### Ingest

Loading data into the entity graph. Three paths:

- **Deterministic ingestion** (`cruxible_ingest`): Bulk load from CSV/JSON through config-defined mappings.
- **Canonical workflows** (`cruxible_apply_workflow`): Declarative step-based pipelines that build graph state from provider outputs with lock-file reproducibility.
- **Direct mutations** (`cruxible_add_entity`, `cruxible_add_relationship`): For individual entities and relationships proposed by AI agents.

### Query

Named queries are declarative traversal patterns defined in the config. Each query has an entry point (entity type), a sequence of traversal steps (follow relationships, apply filters), and a return type.

Every query produces a **receipt** — a structured proof of the traversal path, filters applied, and entities visited.

### Feedback

Edge-level feedback tied to specific receipts:

- **approve** — Edge is correct; trusted in future traversals
- **reject** — Edge is wrong; excluded from future query results
- **correct** — Edge needs property corrections (provide a corrections dict)
- **flag** — Edge needs review; no behavior change

### Workflow

Declarative step-based execution plans that combine reads, provider calls, graph construction, and governed proposals into reproducible pipelines. Canonical workflows produce immutable snapshots with digest verification. See [Workflows](#workflows) below.

### World Publishing

Immutable release bundles published to OCI registries. Forkable by downstream consumers who add their own data, workflows, and governed judgment on top. See [World Publishing](#world-publishing) below.

## Workflows

Workflows are the primary execution mechanism. A workflow is a sequence of typed steps defined in the config:

### Step Types

| Phase | Steps | Purpose |
|-------|-------|---------|
| **Read** | `query`, `list_entities`, `list_relationships` | Pull data from the graph |
| **Compute** | `provider`, `assert` | Call external providers, guard conditions |
| **Build** | `make_candidates`, `map_signals`, `propose_relationship_group`, `make_entities`, `make_relationships` | Structure results for graph mutation |
| **Write** | `apply_entities`, `apply_relationships` | Mutate the graph (canonical apply mode only) |

### Execution Modes

- **`run`** — Non-canonical execution. Runs all steps, produces receipts and traces, but does not create snapshots or require digest verification.
- **`preview`** — Canonical dry-run. Computes what would change and returns an `apply_digest`.
- **`apply`** — Canonical execution with mutations. Requires a matching `apply_digest` from a prior preview, verifies the lock file and head snapshot haven't changed, then commits.

### Lock Files

`cruxible.lock.yaml` pins provider versions, artifact hashes, and config digests. Canonical workflows verify the lock before execution. If any dependency changes, the lock must be regenerated with `cruxible lock`.

### Providers

Providers are external callables (Python functions, HTTP endpoints, shell commands) that execute with full tracing. Each call produces an `ExecutionTrace` recording input, output, duration, status, and artifact hash.

## Governed Proposals

For relationships that require judgment (not just mechanical matching), Cruxible provides a governed proposal flow:

1. **Propose** — A workflow or agent creates a `CandidateGroup` with members and integration signals (support/contradict/unsure).
2. **Review** — Based on the relationship's `matching` config, groups may auto-resolve (if all required integration signals support) or require manual review.
3. **Resolve** — A human or AI reviewer approves or rejects the group, materializing the edges into the graph.
4. **Trust** — Resolution history builds trust profiles per integration, adjusting future auto-resolve thresholds.

Each step produces receipts. The entire lifecycle is auditable.

## Loop 1: Feedback Analysis

Structured feedback on governed decisions feeds into pattern analysis:

1. Reviewers attach **reason codes** from `feedback_profiles` when providing feedback (e.g., `jurisdiction_mismatch`, `holding_misread`).
2. `analyze_feedback` scans accumulated feedback and proposes operational improvements:
   - **Constraints** — from repeated structural violations
   - **Decision policies** — from repeated review patterns
   - **Quality checks** — from repeated data quality issues
   - **Provider fixes** — from repeated provider errors

Suggestions are proposed, not auto-applied. They become operational rules only after review.

## Loop 2: Outcome Analysis

Structured outcomes on prior resolutions and query results feed into trust calibration:

1. Reviewers record **outcome codes** from `outcome_profiles` when assessing whether a prior decision was correct (e.g., `overstated_impact`, `missed_material_opinion`).
2. `analyze_outcomes` scans accumulated outcomes and produces:
   - **Trust adjustments** — lower or raise auto-resolve confidence for specific integrations in specific contexts
   - **Review requirements** — flag integration/context combinations that need manual review
   - **Provider fix suggestions** — identify providers producing systematically wrong signals

This is the compounding loop: each resolved case that gets an outcome assessment makes future governed decisions more precise.

## World Publishing

Cruxible supports publishing immutable world releases to OCI registries and forking them for downstream customization:

### Reference Worlds

A published world is an immutable release bundle containing:
- `manifest.json` — world_id, release_id, owned types, compatibility level
- `config.yaml` — the full config at publish time
- `graph.json` — the complete entity graph
- `cruxible.lock.yaml` — locked provider/artifact hashes
- `snapshot.json` — snapshot metadata with digests

### Forks

A fork creates a new instance from a published release:
- The upstream graph becomes read-only reference data
- The fork adds an overlay config with new entity types, relationships, workflows, and providers
- Ownership is type-level: upstream-owned types cannot be mutated by the fork
- Fork-owned relationships can reference upstream-owned entities (this is the primary use case)

### Pull Updates

When the upstream publishes a new release, forks can pull updates:
1. **Preview** — compare current and target releases, check for conflicts
2. **Apply** — create a pre-pull snapshot, replace upstream state, recompose config, merge graphs

Fork-owned data is preserved across pulls. The upstream and fork layers compose cleanly because type-level ownership prevents conflicts.

### Fork Runtime Composition

When a fork is created, the config composer:
- Strips upstream canonical workflows (build-time concerns, not fork runtime)
- Strips providers only used by those canonical workflows
- Strips tests targeting those canonical workflows
- Merges the remaining upstream config with the fork's overlay

This means forks read upstream data from the published graph (via `list_entities`/`list_relationships` steps), not from upstream raw build artifacts.

## The Entity Graph

Cruxible stores entities and relationships in a directed graph (NetworkX DiGraph). Each node is an entity with a type and properties. Each edge is a typed relationship with its own properties.

### Edge Properties

Every edge carries a `properties` dict from three sources:

**Config-defined properties** are declared in the relationship schema. Examples: `verified`, `confidence`, `source`, `evidence`.

**`review_status`** is set by feedback actions:

| Feedback action | Source | review_status |
|-----------------|--------|---------------|
| approve / correct | human | `human_approved` |
| approve / correct | ai_review | `ai_approved` |
| reject | human | `human_rejected` |
| reject | ai_review | `ai_rejected` |
| flag | any | `pending_review` |

**`_provenance`** is internal metadata tracking edge origin:
- `source` — origin system (e.g. `"ingest"`, `"mcp_add"`, `"cli_add"`)
- `created_at` — ISO 8601 timestamp
- `source_ref` — reference identifier
- `last_modified_at` — updated on edge replacement or feedback
- `last_modified_by` — what modified it

## Receipts: Provenance as a DAG

Every operation produces a receipt — a directed acyclic graph of evidence nodes. Query receipts show traversal paths, filters, and visited entities. Mutation receipts track what was changed and why. Workflow receipts include execution traces for every provider call.

Receipts are stored in SQLite and can be exported as JSON, Markdown, or Mermaid diagrams.

## Constraints and Evaluation

Constraints are validation rules that check relationships against business logic:

```yaml
constraints:
  - name: replacement_same_category
    rule: "replaces.FROM.category == replaces.TO.category"
    severity: warning
```

Run `cruxible_evaluate` to check the graph for orphan entities, coverage gaps, constraint violations, low-confidence edges, unreviewed co-members, and config-defined quality checks.

## Permission Modes

MCP tools are gated by `CRUXIBLE_MODE` env var. Four cumulative tiers:

| Mode | Tools Available |
|------|----------------|
| **READ_ONLY** | version, prompt, init (reload), validate, schema, query, receipt, list, sample, evaluate, find_candidates, get_entity, get_relationship, get_group, list_groups, list_resolutions, get_feedback_profile, get_outcome_profile, analyze_feedback, analyze_outcomes, world_status, world_pull_preview, plan_workflow |
| **GOVERNED_WRITE** | READ_ONLY + feedback, feedback_batch, outcome, run_workflow, propose_workflow, propose_group |
| **GRAPH_WRITE** | GOVERNED_WRITE + add_entity, add_relationship, resolve_group, update_trust_status |
| **ADMIN** | All tools including init (create), ingest, add_constraint, add_decision_policy, lock_workflow, apply_workflow, world_publish, world_fork, world_pull_apply |

Default is `ADMIN`. Use `CRUXIBLE_ALLOWED_ROOTS` to restrict which directories init can access. Use `CRUXIBLE_REQUIRE_SERVER` to force server-mode transport.

## Technology Stack

- **Pydantic** for all models — config schema, runtime types, receipts, MCP contracts
- **Polars** for data operations — ingestion and candidate detection use DataFrames
- **NetworkX** for the entity graph — DiGraph for entity/relationship storage
- **SQLite** for persistence — receipts, feedback, outcomes, groups
- **YAML** for config — the single source of truth for a decision domain
- **Click + Rich** for the CLI — terminal interface with formatted tables
- **FastMCP** for the MCP server — primary interface for AI agents
- **FastAPI** for the HTTP server — REST API with bearer-token auth, UDS support
- **structlog** for audit logging — JSON-formatted logs to stderr
