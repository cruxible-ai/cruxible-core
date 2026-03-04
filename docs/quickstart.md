# Quickstart

Get from install to first query in 5 minutes.

## Prerequisites

- Python 3.11 or later

## Install

```bash
pip install cruxible-core
```

For MCP server support (AI agent integration):

```bash
pip install "cruxible-core[mcp]"
```

## Try a Demo

Cruxible ships with prebuilt demo graphs. The fastest way to get started:

```bash
cd demos/drug-interactions
```

### MCP (AI Agent)

Each demo includes a `.mcp.json` with the MCP server preconfigured. Open your AI agent in the demo directory and ask:

- "Check interactions for warfarin"
- "What's the enzyme impact of fluoxetine?"
- "Suggest an alternative to simvastatin"

The agent calls `cruxible_query` behind the scenes. Every query produces a receipt you can inspect.

### CLI

```bash
cruxible query --query check_interactions --param drug_id=warfarin
```

This returns matching drugs and a receipt ID. The receipt captures the full traversal path.

### Inspect the Receipt

```bash
cruxible explain --receipt <receipt_id>
```

Receipts show exactly how the answer was derived — which entities were visited, which filters applied, which relationships traversed.

### Evaluate Graph Quality

```bash
cruxible evaluate
```

Checks for orphan entities, coverage gaps, and constraint violations.

## Build Your Own

To create a graph from scratch (not using a prebuilt demo):

### 1. Write a Config

Define entity types, relationships, queries, and ingestion mappings in YAML. See the [Config Reference](config-reference.md) for every field.

### 2. Validate and Initialize

```bash
cruxible validate --config your_config.yaml
cruxible init --config your_config.yaml --data-dir ./data
```

### 3. Ingest Data

```bash
cruxible ingest --mapping <mapping_name> --file data/<your_data>.csv
```

Load entities first, then relationships (entities must exist before edges can reference them).

### 4. Query

```bash
cruxible query --query <query_name> --param <primary_key>=<value>
```

## MCP Setup

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

## Next Steps

- [Concepts](concepts.md) — Architecture and primitives
- [Config Reference](config-reference.md) — Every YAML field explained
- [MCP Tools Reference](mcp-tools.md) — All 19 tools with parameters and return types
- [CLI Reference](cli-reference.md) — Terminal commands
- [AI Agent Guide](for-ai-agents.md) — Orchestration workflows and best practices
