<p align="center">
  <a href="https://cruxible.ai">
    <img src="assets/cruxible_logo.png" alt="Cruxible" width="400">
  </a>
</p>

# Cruxible Core

[![PyPI version](https://img.shields.io/pypi/v/cruxible-core)](https://pypi.org/project/cruxible-core/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Deterministic decision engine with receipts.** AI agents write the configs. Core executes with proof.

Cruxible Core is an agent-native runtime for deterministic decision systems. Define entity types, relationships, queries, and constraints in YAML. Core ingests data, executes queries, and produces **receipts** — structured proofs showing exactly how every answer was derived.

The AI is *outside* Core. Claude Code, Cursor, Codex — any MCP-capable agent — generates configs, orchestrates workflows, and proposes inferred relationships. Core handles the rest — deterministic candidate detection, constraint validation, query execution, and receipts for every decision.

```
┌──────────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code, Cursor, Codex, ...)                  │
│  Writes configs, orchestrates workflows                      │
└──────────────────────┬───────────────────────────────────────┘
                       │ calls
┌──────────────────────▼───────────────────────────────────────┐
│  MCP Tools                                                   │
│  init · validate · ingest · query · feedback · evaluate ...  │
└──────────────────────┬───────────────────────────────────────┘
                       │ executes
┌──────────────────────▼───────────────────────────────────────┐
│  Cruxible Core                                               │
│  Deterministic. No LLM. No opinions. No API keys.            │
│  Config → Graph → Query → Receipt → Feedback                 │
└──────────────────────────────────────────────────────────────┘
```

## MCP Setup

```bash
pip install "cruxible-core[mcp]"
```

**Claude Code / Cursor** (project `.mcp.json` or `~/.claude.json` / `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "cruxible": {
      "command": "cruxible-mcp",
      "env": {
        "CRUXIBLE_MODE": "admin"
      }
    }
  }
}
```

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.cruxible]
command = "cruxible-mcp"

[mcp_servers.cruxible.env]
CRUXIBLE_MODE = "admin"
```

## Try an Example

Each demo includes a `.mcp.json`, config, and prebuilt graph — ready to go:

```bash
cd demos/drug-interactions
```

Open your AI agent and ask:

- "Check interactions for warfarin"
- "What's the enzyme impact of fluoxetine?"
- "Suggest an alternative to simvastatin"

Every query produces a receipt you can inspect.

## CLI Install

```bash
pip install cruxible-core
```

CLI equivalent of the example above:

```bash
cd demos/drug-interactions
cruxible query --query check_interactions --param drug_id=warfarin
```

## Why Cruxible

| LLM agents alone | With Cruxible |
|---|---|
| Relationships shift depending on how you ask | Explicit knowledge graph you can inspect |
| No structured memory between sessions | Persistent entity store across runs |
| Results vary between identical prompts | Deterministic execution, same input → same output |
| "Trust me" — no audit trail | DAG-based receipt for every decision |
| Constraints checked by vibes | Declared constraints validated before results |
| Discovers relationships only through LLM reasoning | Deterministic candidate detection finds missing relationships at scale — LLM assists where judgment is needed |
| Learns nothing from outcomes | Feedback loop calibrates edge weights over time |

### vs. RAG

| RAG | Cruxible |
|---|---|
| Retrieves text chunks by similarity | Traverses typed relationships between entities |
| Answers depend on chunk boundaries and embedding quality | Answers follow declared traversal paths — no retrieval ambiguity |
| No structure — just documents in, documents out | Schema-defined entity types, relationships, and constraints |
| Provenance = "this chunk matched" — still a black box | Every decision produces a receipt: full traversal DAG you can audit, replay, and explain |
| Can't enforce business rules | Constraints checked on every evaluation |
| Can't discover missing connections | Candidate detection finds missing relationships by property matching and shared neighbors |
| No correction mechanism — re-embed and hope | Feedback on individual relationships, persisted and applied to future queries |

## Features

- **19 MCP tools** — full lifecycle via [Model Context Protocol](docs/mcp-tools.md) for AI agent orchestration.
- **CLI mirror** — core MCP tools have [CLI equivalents](docs/cli-reference.md) for terminal workflows.
- **YAML-driven config** — define entity types, relationships, queries, constraints, and ingestion mappings in one file.
- **Receipt-based provenance** — every query produces a DAG-structured proof showing exactly how the answer was derived.
- **Candidate detection** — property matching and shared-neighbor strategies for discovering missing relationships at scale.
- **Constraint system** — define validation rules that are checked by `evaluate`. Feedback patterns can be encoded as constraints.
- **Feedback loop** — approve, reject, correct, or flag individual edges. Rejected edges are excluded from future queries.
- **Permission modes** — READ_ONLY, GRAPH_WRITE, ADMIN tiers control what tools a session can access.
- **Zero LLM dependencies** — purely deterministic runtime. No API keys, no token costs during execution.

## Demos

| Demo | Domain | What it demonstrates |
|------|--------|---------------------|
| [sanctions-screening](demos/sanctions-screening/) | Fintech / RegTech | OFAC screening with beneficial ownership chain traversal. |
| [drug-interactions](demos/drug-interactions/) | Healthcare | Multi-drug interaction checking with CYP450 enzyme data. |
| [mitre-attack](demos/mitre-attack/) | Cybersecurity | Threat modeling with ATT&CK technique and group analysis. |

## Documentation

- [Quickstart](docs/quickstart.md) — 5-minute install to first query
- [Concepts](docs/concepts.md) — Architecture and primitives
- [Config Reference](docs/config-reference.md) — Every YAML field explained
- [MCP Tools Reference](docs/mcp-tools.md) — All 19 tools with parameters and return types
- [CLI Reference](docs/cli-reference.md) — Terminal commands
- [AI Agent Guide](docs/for-ai-agents.md) — Orchestration workflows for Claude Code, Cursor, Codex, and other MCP clients

## Technology

Built on [Pydantic](https://docs.pydantic.dev/) (validation), [NetworkX](https://networkx.org/) (graph), [Polars](https://pola.rs/) (data ops), [SQLite](https://sqlite.org/) (persistence), and [FastMCP](https://github.com/jlowin/fastmcp) (MCP server).

## Cruxible Cloud

Managed deployment with expert support, full pre-built graphs, and API access.

[Coming soon →](https://cruxible.ai)

## License

MIT
