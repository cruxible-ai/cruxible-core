<p align="center">
  <a href="https://cruxible.ai">
    <img src="assets/cruxible_logo.png" alt="Cruxible" width="400">
  </a>
</p>

# Cruxible Core

[![PyPI version](https://img.shields.io/pypi/v/cruxible-core)](https://pypi.org/project/cruxible-core/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Deterministic decision engine with DAG-based receipts.** Build entity graphs, query with MCP, get auditable proof.

Define entity graphs, queries, and constraints in YAML. Run them locally from CLI or MCP, and get receipts proving exactly why each result was returned.

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

## Quick Example

**1. Define a domain in YAML:**

```yaml
entity_types:
  Drug:
    properties:
      drug_id: { type: string, primary_key: true }
      name:    { type: string }
  Enzyme:
    properties:
      enzyme_id: { type: string, primary_key: true }
      name:      { type: string }

relationships:
  - name: same_class
    from: Drug
    to: Drug
  - name: metabolized_by
    from: Drug
    to: Enzyme

named_queries:
  suggest_alternative:
    entry_point: Drug
    returns: Drug
    traversal:
      - relationship: same_class
        direction: both
      - relationship: metabolized_by
        direction: outgoing
```

**2. Load data and run a deterministic query:**

> "Suggest an alternative to simvastatin"

**3. Get a receipt — structured proof of every answer:**

*Raw receipt DAG rendered for readability:*

```
Receipt RCP-17b864830ada

Query: suggest_alternative for simvastatin

Step 1: Entry point lookup
  simvastatin -> found in graph

Step 2: Traverse same_class (both directions)
  Found 6 statins in the same therapeutic class:
  n3  atorvastatin   n4  rosuvastatin   n5  lovastatin
  n6  pravastatin    n7  fluvastatin    n8  pitavastatin

Step 3: Traverse metabolized_by (outgoing) for each alternative
  n9   atorvastatin -> CYP3A4   (CYP450 dataset)
  n10  rosuvastatin -> CYP2C9   (CYP450 dataset, human approved)
  n11  rosuvastatin -> CYP2C19  (CYP450 dataset)
  n12  lovastatin -> CYP2C19    (CYP450 dataset)
  n13  lovastatin -> CYP3A4     (CYP450 dataset)
  n14  pravastatin -> CYP3A4    (CYP450 dataset)
  n15  fluvastatin -> CYP2C9    (CYP450 dataset)
  n16  fluvastatin -> CYP2D6    (CYP450 dataset)
  n17  pitavastatin -> CYP2C9   (CYP450 dataset)

Results: atorvastatin, rosuvastatin, lovastatin, pravastatin, fluvastatin, pitavastatin
Duration: 0.41ms | 2 traversal steps
```

## Get Started

```bash
pip install "cruxible-core[mcp]"
```

> Or use `uv tool install "cruxible-core[mcp]"` if you prefer [uv](https://docs.astral.sh/uv/).

Add the MCP server to your AI agent:

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

### Try a demo

```bash
git clone https://github.com/cruxible-ai/cruxible-core
cd cruxible-core/demos/drug-interactions
```

Each demo is a starter kit with a config, prebuilt graph, example queries, and receipts. If you're new, start with `drug-interactions`.

First, load the instance:

> "You have access to the cruxible MCP, load the cruxible instance"

Then try:

- "Check interactions for warfarin"
- "What's the enzyme impact of fluoxetine?"
- "Suggest an alternative to simvastatin"

Every query produces a receipt you can inspect.

## Why Not Just Write Code?

Cruxible is useful when the same decision logic needs to be reviewed, replayed, adapted, and trusted over time. It gives you:

- A declarative spec surface in YAML
- Deterministic execution over entity graphs
- Receipts proving why a result was returned
- Constraints, evaluation, and feedback without rebuilding custom infrastructure

The same way Terraform replaced hand-rolled infrastructure scripts with plans, state, and diffs, Cruxible replaces ad-hoc decision code with declarative configs, deterministic execution, and auditable receipts.

## Why Cruxible

| LLM agents alone | With Cruxible |
|---|---|
| Relationships shift depending on how you ask | Explicit knowledge graph you can inspect |
| No structured memory between sessions | Persistent entity store across runs |
| Results vary between identical prompts | Deterministic execution, same input → same output |
| No audit trail | DAG-based receipt for every decision |
| Constraints checked by vibes | Declared constraints programmatically validated before results |
| Discovers relationships only through LLM reasoning | Deterministic candidate detection finds missing relationships at scale — LLM assists where judgment is needed |
| Learns nothing from outcomes | Feedback loop calibrates edge weights over time |

## Features

- **Receipt-based provenance:** every query produces a DAG-structured proof showing exactly how the answer was derived.
- **Constraint system:** define validation rules that are checked by `evaluate`. Feedback patterns can be encoded as constraints.
- **Feedback loop:** approve, reject, correct, or flag individual edges. Rejected edges are excluded from future queries.
- **Candidate detection:** property matching and shared-neighbor strategies for discovering missing relationships at scale.
- **YAML-driven config:** define entity types, relationships, queries, constraints, and ingestion mappings in one file.
- **Zero LLM dependencies:** purely deterministic runtime. No API keys, no token costs during execution.
- **Full MCP server:** complete lifecycle via [Model Context Protocol](docs/mcp-tools.md) for AI agent orchestration.
- **CLI mirror:** core MCP tools have [CLI equivalents](docs/cli-reference.md) for terminal workflows.
- **Permission modes:** READ_ONLY, GRAPH_WRITE, ADMIN tiers control what tools a session can access.

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
- [MCP Tools Reference](docs/mcp-tools.md) — All tools with parameters and return types
- [CLI Reference](docs/cli-reference.md) — Terminal commands
- [AI Agent Guide](docs/for-ai-agents.md) — Orchestration workflows for Claude Code, Cursor, Codex, and other MCP clients

## Technology

Built on [Pydantic](https://docs.pydantic.dev/) (validation), [NetworkX](https://networkx.org/) (graph), [Polars](https://pola.rs/) (data ops), [SQLite](https://sqlite.org/) (persistence), and [FastMCP](https://github.com/jlowin/fastmcp) (MCP server).

**Cruxible Cloud:** Managed deployment with expert support. [Coming soon.](https://cruxible.ai)

## License

MIT

<!-- mcp-name: io.github.cruxible-ai/cruxible-core -->
