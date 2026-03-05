# CLAUDE.md

## Project Overview

**GitHub:** https://github.com/cruxible-ai/cruxible-core

Cruxible Core is a deterministic decision engine with receipts. AI agents (Claude Code, etc.) write configs and orchestrate workflows. Core executes deterministically with proof — no LLM inside.

Four primitives: **Config**, **Ingest**, **Query**, **Feedback**.

## Commands

```bash
# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run single test file
uv run pytest tests/test_config/test_schema.py -v

# Lint
uv run ruff check src tests

# Format
uv run ruff format src tests

# Type check
uv run mypy src
```

## Git Conventions

- Do NOT include `Co-Authored-By` lines in commit messages.
- When implementing multi-fix plans, commit each logical fix as it's completed (source + tests together). Don't defer all commits to the end — partial staging across shared files is error-prone. After all commits, prepare a review guide covering the full set.

## Versioning

Version lives in two places — keep them in sync:
- `pyproject.toml` (`version = "X.Y.Z"`)
- `src/cruxible_core/__init__.py` (`__version__ = "X.Y.Z"`)

The MCP server name includes the version (`cruxible-core v0.2.0`) so agents and users can confirm which build is running.

**When to bump:**
- **Patch (0.2.x):** Bug fixes, doc/prompt wording changes, test additions
- **Minor (0.x.0):** New features (tools, evaluate checks, config capabilities), breaking prompt changes
- **Major (x.0.0):** Breaking API changes (tool signatures, config schema, storage format)

**Release process:**
1. Bump version in both files
2. Commit: `Bump to vX.Y.Z`
3. Tag: `git tag vX.Y.Z`
4. Push: `git push && git push --tags`

## Architecture

### Package Layout

```
src/cruxible_core/
  config/       # Pydantic models for YAML config, loader, validator
  graph/        # EntityGraph (networkx), ontology, runtime types
  query/        # QueryEngine, traversal, constraints, candidate detection
  receipt/      # Receipt DAG (ReceiptNode, EvidenceEdge), serializers
  feedback/     # FeedbackRecord, OutcomeRecord, graph updates
  ingest/       # CSV/JSON -> EntityGraph via config mappings
  mcp/          # MCP server (primary interface for AI agents)
  cli/          # Click CLI (secondary interface)
  storage/      # SQLite backend for receipts + feedback
  errors.py     # CoreError hierarchy
```

### Key Design Decisions

- **Zero LLM dependencies.** Core is purely deterministic. Claude Code provides all intelligence via MCP tools.
- **Pydantic for all models.** Config schema, runtime types, receipts — all validated.
- **Polars for data operations.** Ingestion and candidate detection use Polars DataFrames.
- **NetworkX for graph.** EntityGraph wraps networkx DiGraph for entity/relationship storage.
- **SQLite for persistence.** Receipts, feedback, outcomes stored in SQLite.
- **YAML for config.** Defines entity types, relationships, named queries, constraints, ingestion mappings.

### Config Schema

Configs define a decision domain:
- `entity_types`: Entity definitions with typed properties
- `relationships`: Edges between entities with properties and cardinality
- `named_queries`: Declarative traversal patterns (entry_point + traversal steps)
- `constraints`: Rule expressions with severity levels
- `ingestion`: Column mappings from CSV/JSON to entities and relationships

### MCP Tools

Core tools: `cruxible_init`, `cruxible_validate`, `cruxible_ingest`, `cruxible_query`, `cruxible_receipt`, `cruxible_feedback`, `cruxible_outcome`, `cruxible_list`, `cruxible_evaluate`, `cruxible_schema`, `cruxible_sample`, `cruxible_find_candidates`, `cruxible_add_relationship`, `cruxible_add_entity`

Lookup tools: `cruxible_get_entity`, `cruxible_get_relationship`

Config mutation: `cruxible_add_constraint` — writes constraints to YAML via `save_config()`

### Feedback-to-Constraint Workflow

When rejection patterns emerge from feedback, encode them as constraints:
1. Use `analyze_feedback` MCP prompt or manually review feedback
2. Call `cruxible_add_constraint` to encode the pattern as a rule
3. Run `cruxible_evaluate` to verify constraints flag expected violations

Config write-back uses atomic temp-file + rename via `config/loader.py:save_config()`.

### Permission Modes

MCP tools are gated by server-side permission modes via `CRUXIBLE_MODE` env var. Three cumulative tiers:

| Mode | Env value | Tools |
|------|-----------|-------|
| `READ_ONLY` | `read_only` | `init` (reload only), `validate`, `schema`, `query`, `receipt`, `list`, `sample`, `evaluate`, `find_candidates`, `get_entity`, `get_relationship` |
| `GRAPH_WRITE` | `graph_write` | READ_ONLY + `add_entity`, `add_relationship`, `feedback`, `outcome` |
| `ADMIN` | `admin` (default) | All tools including `init` (new instance), `ingest`, `add_constraint` |

- Default is `ADMIN` (backward compatible). Invalid values raise `ConfigError` at startup.
- `cruxible_init` reload path (no `config_path`) is `READ_ONLY`; create path requires `ADMIN`.
- `cruxible_query` is `READ_ONLY` even though it writes receipts to SQLite (audit trail, not agent-controlled mutation).
- `CRUXIBLE_ALLOWED_ROOTS` env var (comma-separated absolute paths) restricts which directories `cruxible_init` can access.
- Audit logging uses structlog to stderr. The safe stderr default is set in `mcp/permissions.py`; `main()` reconfigures with JSON formatting for production.

### Error Handling

All errors inherit from `CoreError`. Key types:
- `ConfigError`: Invalid config YAML
- `DataValidationError`: Data doesn't match config schema
- `EntityNotFoundError`: Entity ID not in graph
- `RelationshipNotFoundError`: Relationship type not in schema
- `QueryNotFoundError`: Named query not in config
- `PermissionDeniedError`: MCP tool call denied due to insufficient permission mode
