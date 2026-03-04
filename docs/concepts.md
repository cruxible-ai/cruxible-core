# Concepts

Cruxible Core is a deterministic decision engine with receipts. This guide explains the architecture, primitives, and workflows that make it work.

## AI Outside, Determinism Inside

Cruxible inverts the typical AI architecture. Instead of embedding an LLM inside the decision engine, it keeps the AI entirely outside:

```
┌──────────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code, Cursor, Codex, ...)                  │
│                                                              │
│  1. Reads docs → understands user's domain                   │
│  2. Generates config YAML → validates via cruxible_validate  │
│  3. Reads raw data → reasons about relationships             │
│  4. Uses cruxible_find_candidates for mechanical matching    │
│  5. Calls cruxible_ingest to populate graph                  │
│  6. Calls cruxible_evaluate → self-reviews, surfaces low     │
│     confidence edges to human with receipts                  │
│  7. Human: review / accept all / defer / reject              │
│  8. Calls cruxible_query → presents results to human         │
│  9. Collects human feedback → calls cruxible_feedback        │
│  10. Records outcomes → calls cruxible_outcome               │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  Cruxible Core (the runtime)                                 │
│                                                              │
│  Deterministic. No LLM. No opinions. No API keys.            │
│  Config → Graph → Query → Receipt → Feedback                 │
└──────────────────────────────────────────────────────────────┘
```

The AI agent (Claude Code, Cursor, Codex, or any MCP-capable agent) provides all intelligence: understanding domains, generating configs, inferring relationships, and interpreting results. Core provides deterministic execution with full provenance.

This means:
- **No API keys** in the runtime — no LLM calls, no token costs during execution
- **Reproducible results** — same config + same data = same output, every time
- **Auditable decisions** — every answer includes a receipt showing exactly how it was derived
- **Domain-agnostic** — the agent adapts to any vertical by reading the config

## Four Primitives

Everything in Cruxible flows through four primitives:

### Config

A YAML file that defines the decision domain: entity types with typed properties, relationships between entities, declarative named queries, validation constraints, and ingestion mappings for loading data.

The config is the single source of truth. AI agents write it; Core validates and executes against it. See [Config Reference](config-reference.md) for the full schema.

### Ingest

Loading data into the entity graph. Two paths:

- **Deterministic ingestion** (`cruxible_ingest`): Bulk load from CSV/JSON through config-defined mappings. For data that explicitly exists in source files — entity records and known relationships.
- **Inferred proposals** (`cruxible_add_entity`, `cruxible_add_relationship`): For entities from free text or relationships that require judgment (classification, matching, inference). The AI agent reasons about the data and proposes edges with confidence scores and evidence.

Entity ingestion always comes before relationship ingestion — edges reference entity IDs that must exist.

### Query

Named queries are declarative traversal patterns defined in the config. Each query has an entry point (entity type), a sequence of traversal steps (follow relationships, apply filters), and a return type.

Every query produces a **receipt** — a structured proof of the traversal path, filters applied, and entities visited. Receipts are stored in SQLite and can be retrieved later for auditing.

### Feedback

Edge-level feedback tied to specific receipts:

- **approve** — Edge is correct; trusted in future traversals
- **reject** — Edge is wrong; excluded from future query results
- **correct** — Edge needs property corrections (provide a corrections dict)
- **flag** — Edge needs review; no behavior change

**Outcomes** are separate from feedback — they track whether the overall query result was correct, incorrect, partial, or unknown. Use outcomes for calibration and accuracy measurement over time.

## The Entity Graph

Cruxible stores entities and relationships in a directed graph (NetworkX DiGraph). Each node is an entity with a type and properties. Each edge is a typed relationship with its own properties.

The graph is persisted to disk and loaded on init. All mutations (ingest, add_entity, add_relationship, feedback) update the graph deterministically.

## Receipts: Provenance as a DAG

Every query produces a receipt — a directed acyclic graph of evidence nodes showing:

- Which entity was the entry point
- Which traversal steps were executed
- Which filters were applied at each step
- Which entities were visited and returned
- Timestamps for the entire operation

Receipts are stored in SQLite and can be exported as JSON, Markdown, or Mermaid diagrams. They enable full auditability: given a receipt ID, you can reconstruct exactly why a particular answer was returned.

## Constraints and Evaluation

Constraints are validation rules that check relationships against business logic:

```yaml
constraints:
  - name: replacement_same_category
    rule: "replaces.from.category == replaces.to.category"
    severity: warning
    description: "Replacement parts should be in the same category"
```

Run `cruxible_evaluate` to check the graph for:
- **Orphan entities** — entities with no relationships
- **Coverage gaps** — expected relationships that are missing
- **Constraint violations** — edges that violate defined rules
- **Low-confidence edges** — edges below the confidence threshold

### Feedback-to-Constraint Workflow

When rejection patterns emerge from feedback, encode them as constraints:

1. Use the `analyze_feedback` prompt or manually review feedback records
2. Identify repeated property mismatches in rejected edges
3. Call `cruxible_add_constraint` to encode the pattern as a rule
4. Run `cruxible_evaluate` to verify constraints flag expected violations

This creates a virtuous cycle: human feedback trains the constraint system, which then catches similar issues automatically.

## Permission Modes

The MCP server runs in one of three cumulative permission tiers, controlled by the `CRUXIBLE_MODE` environment variable:

| Mode | Tools Available |
|------|----------------|
| **READ_ONLY** | `validate`, `init` (reload only), `schema`, `query`, `receipt`, `list`, `sample`, `evaluate`, `find_candidates`, `get_entity`, `get_relationship` |
| **GRAPH_WRITE** | Everything in READ_ONLY + `add_entity`, `add_relationship`, `feedback`, `outcome` |
| **ADMIN** | Everything including `init` (create), `ingest`, `add_constraint` |

Default is `ADMIN`. Use `CRUXIBLE_ALLOWED_ROOTS` to restrict which directories `cruxible_init` can access.

## Candidate Detection

Two strategies for discovering missing relationships at scale:

### Property Match

Rules-based matching on entity properties. Define match rules that compare properties between potential source and target entities:

- `equals` — Type-strict hash-join (O(n+m))
- `iequals` — Case-insensitive hash-join (O(n+m))
- `contains` — Substring match (brute-force, fails fast on large sets)

Set `min_confidence` to control the minimum fraction of rules that must match.

### Shared Neighbors

Graph-structure matching via common connections. Finds entity pairs that share neighbors through a specified relationship. Set `min_overlap` to control the minimum neighbor overlap ratio.

**Bootstrapping pattern:** Create initial edges with `cruxible_add_relationship`, then use `shared_neighbors` to discover more entities sharing those same neighbors.

## Technology Stack

- **Pydantic** for all models — config schema, runtime types, receipts, MCP contracts
- **Polars** for data operations — ingestion and candidate detection use DataFrames
- **NetworkX** for the entity graph — DiGraph for entity/relationship storage
- **SQLite** for persistence — receipts, feedback, and outcomes
- **YAML** for config — the single source of truth for a decision domain
- **Click + Rich** for the CLI — terminal interface with formatted tables
- **FastMCP** for the MCP server — primary interface for AI agents
- **structlog** for audit logging — JSON-formatted logs to stderr
