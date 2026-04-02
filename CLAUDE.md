# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GitHub:** https://github.com/cruxible-ai/cruxible-core

Cruxible Core is a deterministic decision engine with receipts. AI agents write configs and orchestrate workflows. Core executes deterministically with proof — no LLM inside.

Six primitives: **Config**, **Ingest**, **Query**, **Feedback**, **Workflow**, **World Publishing**.

Two feedback loops:
- **Loop 1** — Structured feedback on governed decisions → `analyze_feedback` → constraint/policy/quality-check suggestions
- **Loop 2** — Structured outcomes on resolutions and queries → `analyze_outcomes` → trust calibration and provider-fix suggestions

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

The MCP server name includes the version so agents and users can confirm which build is running.

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

### Three Surface Layers, One Service Core

All interfaces delegate to the **service layer** (`service/`). Never duplicate orchestration logic in handlers.

```
MCP (mcp/)  ──┐
CLI (cli/)  ──┼──▶  Service Layer (service/)  ──▶  Core Modules
HTTP (server/) ┘
```

- **MCP** (`mcp/`) — Primary interface for AI agents via FastMCP. Handlers in `handlers.py` support dual-mode: library-mode (direct calls via `runtime/local_api.py`) or server-mode (delegates to `CruxibleClient`).
- **CLI** (`cli/`) — Click CLI. Commands split into domain modules under `cli/commands/` (workflows, reads, mutations, feedback, groups, lists, world). All delegate to service functions.
- **HTTP** (`server/`) — FastAPI REST server with bearer-token auth. Routes in `server/routes/`. Supports HTTP and Unix Domain Socket transports.
- **Client** (`client/`) — Re-exports from `cruxible-client` package. `CruxibleClient` SDK for talking to HTTP servers. Mirrors all service operations.

### Runtime (`runtime/`)

Neutral home for shared instance infrastructure used by all surfaces:

- `instance.py` — `CruxibleInstance`: concrete local implementation managing the `.cruxible/` directory
- `instance_manager.py` — `InstanceManager` singleton for instance lifecycle
- `local_api.py` — Local API facade: all `_handle_*_local` functions that MCP handlers and HTTP routes delegate to

### Service Layer (`service/`)

The source of truth for all business logic. Organized by concern:

- `lifecycle.py` — Instance init, validate, reload-config
- `queries.py` — Read operations (query, schema, inspect, list, stats, sample)
- `mutations.py` — Graph mutations (add_entities, add_relationships, ingest)
- `feedback.py` — Feedback collection, outcome recording, feedback/outcome profiles, analysis
- `execution.py` — Workflow execution (plan, run, test, apply, propose, lock)
- `groups.py` — Candidate group proposal management with resolution/trust
- `analysis.py` — Constraint evaluation and candidate finding
- `snapshots.py` — World state snapshots for branching/recovery
- `world.py` — Published world releases (publish, fork, pull preview/apply, status)
- `_helpers.py` — `mutation_receipt` context manager for receipt plumbing
- `_ownership.py` — Type-level ownership guards for release-backed forks
- `types.py` — All input/output types (typed dataclasses)

Service functions have consistent signatures: accept `instance: InstanceProtocol`, return typed result dataclasses.

### Instance Protocol (`instance_protocol.py`)

Structural protocols defining abstract instance/store interfaces:
- `InstanceProtocol` — Graph/config loading, snapshot creation, upstream metadata, store access
- `ReceiptStoreProtocol`, `FeedbackStoreProtocol`, `GroupStoreProtocol`

The concrete implementation is `CruxibleInstance` in `runtime/instance.py`, which manages the `.cruxible/` directory:

```
.cruxible/
  instance.json        # Metadata (config path, version, upstream tracking)
  graph.json           # NetworkX node_link_data JSON
  cruxible.lock.yaml   # Workflow lock (provider/artifact hashes)
  receipts.db          # SQLite (receipts + execution traces)
  feedback.db          # SQLite (feedback, outcomes, groups)
  composed/config.yaml # Materialized composed config (fork instances)
  upstream/            # Cached upstream release bundles (fork instances)
  snapshots/           # Immutable world snapshots
```

### Workflow System (`workflow/`)

Deterministic workflow engine with lock-file reproducibility:

- `compiler.py` — Compiles workflows to `CompiledPlan`, generates SHA256 locks (`cruxible.lock.yaml`), resolves providers and artifacts
- `executor.py` — Runtime execution supporting 12 step types
- `contracts.py` — Payload validation against declared contracts
- `refs.py` — Step reference resolution (`$input`, `$steps.*`, `$item`)

12 step types in four phases:
1. **Read:** `query`, `list_entities`, `list_relationships`
2. **Compute:** `provider`, `assert`
3. **Build:** `make_candidates`, `map_signals`, `propose_relationship_group`, `make_entities`, `make_relationships`
4. **Write:** `apply_entities`, `apply_relationships`

Three execution modes: `run` (non-canonical), `preview` (canonical dry-run), `apply` (canonical with mutations). Canonical workflows create `WorldSnapshot` objects with lineage tracking.

### Provider System (`provider/`)

External provider execution with tracing. Providers are callables resolved by the registry (`provider/registry.py`). Each execution produces an `ExecutionTrace` (input/output, duration, status, artifact hash) persisted to receipts.db.

### Transport System (`transport/`)

Distribution layer for published world releases:

- `types.py` — `ReleaseTransport` protocol, `PulledReleaseBundle`, transport ref parsing
- `backends.py` — `FileReleaseTransport` (local/test), `OciReleaseTransport` (GHCR via `oras` CLI)

### Snapshot and Release Types (`snapshot/`)

- `WorldSnapshot` — Immutable world state with config/lock/graph digests and lineage
- `PublishedWorldManifest` — Distribution metadata for published releases (world_id, release_id, owned types, compatibility)
- `UpstreamMetadata` — Per-instance upstream tracking for release-backed forks

### Groups

Governed relationship proposals using tri-state signals (support/contradict/unsure) from integrations. `CandidateGroup` tracks status: pending_review → auto_resolved/applying → resolved. Stored in feedback.db via `GroupStore`.

### Config Composition (`config/composer.py`)

Base+overlay config composition for release-backed forks:
- `compose_configs()` — Standard merge with strict collision detection
- `compose_runtime_configs()` — Fork-specific: strips upstream canonical workflows, their providers, and their tests before merging
- `write_composed_config()` / `write_runtime_composed_config()` — Materialize to disk
- Overlay can add new types/workflows/providers but cannot redefine upstream-defined objects

### Config Schema (`config/schema.py`)

Configs define a decision domain. Top-level fields on `CoreConfig`:

- `entity_types` — Entity type definitions with properties and optional constraints
- `relationships` — Relationship definitions with properties, matching rules, and integration guardrails
- `named_queries` — Parameterized graph traversals
- `constraints` — Declarative graph constraints
- `quality_checks` — 5 types: property, json_content, uniqueness, bounds, cardinality
- `ingestion` — CSV/data mapping definitions
- `integrations` — Global integration definitions (kind + named contract reference)
- `contracts` — Named input/output contract schemas
- `artifacts` — External resources (models, data) referenced by providers
- `providers` — Deterministic callable definitions with tracing
- `workflows` — Declarative step-based execution plans
- `tests` — Workflow fixture tests
- `feedback_profiles` — Structured reason codes for Loop 1 feedback analysis
- `outcome_profiles` — Structured outcome codes for Loop 2 trust calibration
- `decision_policies` — Rules governing auto-resolve behavior and review routing

### Key Design Decisions

- **Zero LLM dependencies.** Purely deterministic runtime. AI agents provide intelligence via MCP tools.
- **Pydantic for all models.** Config schema, runtime types, receipts — all validated.
- **Polars for data operations.** Ingestion and candidate detection use Polars DataFrames.
- **NetworkX for graph.** EntityGraph wraps networkx DiGraph for entity/relationship storage.
- **SQLite for persistence.** Receipts, feedback, outcomes, groups stored in SQLite.
- **YAML for config.** Defines the full decision domain.

### Permission Modes

MCP tools are gated by `CRUXIBLE_MODE` env var. Four cumulative tiers:

| Mode | Env value | Tools |
|------|-----------|-------|
| `READ_ONLY` | `read_only` | version, prompt, init (reload), validate, schema, query, receipt, list, sample, evaluate, find_candidates, get_entity, get_relationship, get_group, list_groups, list_resolutions, get_feedback_profile, get_outcome_profile, analyze_feedback, analyze_outcomes, world_status, world_pull_preview, plan_workflow |
| `GOVERNED_WRITE` | `governed_write` | READ_ONLY + feedback, feedback_batch, outcome, run_workflow, propose_workflow, propose_group |
| `GRAPH_WRITE` | `graph_write` | GOVERNED_WRITE + add_entity, add_relationship, resolve_group, update_trust_status |
| `ADMIN` | `admin` (default) | All tools including init (create), ingest, add_constraint, add_decision_policy, lock_workflow, apply_workflow, world_publish, world_fork, world_pull_apply |

- `CRUXIBLE_ALLOWED_ROOTS` env var restricts which directories init can access.
- `CRUXIBLE_REQUIRE_SERVER` env var forces server-mode transport.

### Error Handling

All errors inherit from `CoreError` in `errors.py`. Key types: `ConfigError`, `DataValidationError`, `EntityNotFoundError`, `RelationshipNotFoundError`, `QueryNotFoundError`, `PermissionDeniedError`, `OwnershipError`, `TransportError`, `MutationError`.

### Test Organization

Tests mirror the src layout under `tests/`:
- `test_service/` — Service layer tests (primary coverage target)
- `test_mcp/` — MCP handler tests
- `test_cli/` — CLI command tests (includes server-mode testing)
- `test_config/`, `test_graph/`, `test_query/`, `test_receipt/`, `test_feedback/`, `test_workflow/` — Module-level tests
- `test_demos/` — KEV triage demo end-to-end tests
- `test_scripts/` — Publish script tests
- `test_transport/` — Transport backend tests
- `test_server/` — HTTP route and error tests
- `test_client/` — HTTP client tests
- `test_architecture/` — Boundary and import tests
- `conftest.py` — Shared fixtures including workflow config templates and `canonical_workflow_instance`
- `support/` — Test helpers (e.g., `workflow_test_providers.py`)
