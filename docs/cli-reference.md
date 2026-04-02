# CLI Reference

Cruxible Core provides a command-line interface for all core operations. The CLI mirrors the MCP tools for terminal usage.

```bash
cruxible --help
cruxible --version
```

**Global options** (before any subcommand):

| Option | Description |
|--------|-------------|
| `--server-url` | Remote Cruxible server base URL |
| `--server-socket` | Local Cruxible server Unix socket path |
| `--instance-id` | Opaque server-mode instance ID (env: `CRUXIBLE_INSTANCE_ID`) |

Many commands accept a `--json` flag to emit structured JSON instead of Rich tables.

---

## Instance Management

### cruxible init

Initialize a new `.cruxible/` instance in the current directory.

```bash
cruxible init --config <path> [--root-dir <dir>] [--data-dir <dir>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--config` | **yes** | Path to config YAML file |
| `--root-dir` | no | Root directory for the instance (required in server mode) |
| `--data-dir` | no | Directory for data files |

**Example:**

```bash
cruxible init --config config.yaml --data-dir ./data
# Initialized .cruxible/ in /path/to/project
```

---

### cruxible validate

Validate a config YAML file without creating an instance.

```bash
cruxible validate --config <path>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--config` | **yes** | Path to config YAML file |

**Example:**

```bash
cruxible validate --config demos/drug-interactions/config.yaml
# Config 'drug_interactions_demo' is valid.
#   2 entity types, 5 relationships, 4 queries
```

---

### cruxible reload-config

Validate the active config or repoint the instance to a new config file.

```bash
cruxible reload-config [--config <path>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--config` | no | Optional new config file path to switch to |

**Example:**

```bash
cruxible reload-config
# Config validated: config.yaml

cruxible reload-config --config new-config.yaml
# Config updated: new-config.yaml
```

---

## Workflow Execution

### cruxible lock

Generate a workflow lock file for the current instance config.

```bash
cruxible lock
```

No options. Writes `cruxible.lock.yaml` with SHA256 digests for reproducible workflow execution.

**Example:**

```bash
cruxible lock
# Wrote lock file to cruxible.lock.yaml
#   digest=abc123 providers=3 artifacts=1
```

---

### cruxible plan

Compile a workflow plan for the current instance.

```bash
cruxible plan --workflow <name> [--input <json_or_yaml>] [--input-file <path>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--workflow` | **yes** | Workflow name from config |
| `--input` | no | Inline JSON or YAML workflow input |
| `--input-file` | no | JSON or YAML file providing workflow input |

Provide `--input` or `--input-file`, not both.

**Example:**

```bash
cruxible plan --workflow enrich --input '{"entity_type": "Drug"}'
# [compiled plan as JSON]
```

---

### cruxible run

Execute a workflow for the current instance.

```bash
cruxible run --workflow <name> [--input <json_or_yaml>] [--input-file <path>] \
  [--save-preview <path>] [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--workflow` | **yes** | Workflow name from config |
| `--input` | no | Inline JSON or YAML workflow input |
| `--input-file` | no | JSON or YAML file providing workflow input |
| `--save-preview` | no | Save preview state to a JSON file for use with `apply --preview-file` |
| `--json` | no | Output as JSON |

For workflows that produce group proposals, use `cruxible propose` instead.

**Example:**

```bash
cruxible run --workflow enrich --input-file input.yaml --save-preview preview.json
# Workflow enrich completed.
# Apply digest: abc123
# Receipt ID: RCP-xyz789
```

---

### cruxible apply

Apply a canonical workflow after verifying preview identity.

```bash
cruxible apply --workflow <name> --apply-digest <digest> \
  [--input <json_or_yaml>] [--input-file <path>] \
  [--head-snapshot <id>] [--json]

# Or from a saved preview file:
cruxible apply --preview-file <path> [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--workflow` | conditional | Workflow name (required unless `--preview-file` used) |
| `--input` | no | Inline JSON or YAML workflow input |
| `--input-file` | no | JSON or YAML file providing workflow input |
| `--apply-digest` | conditional | Preview apply digest from workflow run (required unless `--preview-file` used) |
| `--head-snapshot` | no | Expected head snapshot ID from workflow preview |
| `--preview-file` | no | Read preview state from a file saved by `run --save-preview` |
| `--json` | no | Output as JSON |

When `--preview-file` is used, it cannot be combined with `--workflow`, `--input`, `--input-file`, `--apply-digest`, or `--head-snapshot`.

**Example:**

```bash
cruxible apply --preview-file preview.json
# Workflow enrich applied.
# Committed snapshot: SNAP-abc123
# Receipt ID: RCP-xyz789
```

---

### cruxible test

Execute config-defined workflow tests for the current instance.

```bash
cruxible test [--name <test_name>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--name` | no | Run only a named workflow test |

**Example:**

```bash
cruxible test
# Tests: 3 passed, 0 failed, 3 total
# [PASS] basic_enrich (enrich)
# [PASS] empty_input (enrich)
# [PASS] bad_type (validation)
```

---

### cruxible propose

Execute a workflow and bridge its output into a candidate group.

```bash
cruxible propose --workflow <name> [--input <json_or_yaml>] [--input-file <path>] [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--workflow` | **yes** | Workflow name from config |
| `--input` | no | Inline JSON or YAML workflow input |
| `--input-file` | no | JSON or YAML file providing workflow input |
| `--json` | no | Output as JSON |

**Example:**

```bash
cruxible propose --workflow discover_interactions --input-file input.yaml
# Workflow discover_interactions proposed group GRP-abc123.
# Receipt ID: RCP-xyz789
# Group status: pending_review (high)
```

---

## World Publishing

### cruxible world publish

Publish the current root world-model instance as an immutable release bundle.

```bash
cruxible world publish --transport-ref <ref> --world-id <id> --release-id <id> \
  [--compatibility <level>]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--transport-ref` | **yes** | -- | Transport ref, e.g. `file://...` or `oci://...` |
| `--world-id` | **yes** | -- | Stable published world identifier |
| `--release-id` | **yes** | -- | User-supplied release identifier |
| `--compatibility` | no | `data_only` | Compatibility classification: `data_only`, `additive_schema`, or `breaking` |

**Example:**

```bash
cruxible world publish --transport-ref file://./releases \
  --world-id drug-interactions --release-id v1.0
# Published drug-interactions:v1.0
#   snapshot=SNAP-abc123
#   compatibility=data_only
```

---

### cruxible world fork

Create a new local fork instance from a published world release.

```bash
cruxible world fork --transport-ref <ref> --root-dir <dir>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--transport-ref` | **yes** | Transport ref, e.g. `file://...` or `oci://...` |
| `--root-dir` | **yes** | Root directory for the new local fork |

**Example:**

```bash
cruxible world fork --transport-ref file://./releases/drug-interactions/v1.0 \
  --root-dir ./my-fork
# Forked drug-interactions:v1.0
# Instance ID: ./my-fork
```

---

### cruxible world status

Show upstream tracking metadata for the current instance.

```bash
cruxible world status
```

No options. Prints world ID, release, transport ref, and snapshot if the instance tracks an upstream published world.

**Example:**

```bash
cruxible world status
# World: drug-interactions
# Release: v1.0
# Transport: file://./releases
# Snapshot: SNAP-abc123
```

---

### cruxible world pull-preview

Preview pulling a newer upstream release into the current fork.

```bash
cruxible world pull-preview
```

No options. Shows the current and target release, compatibility, apply digest, upstream entity/edge deltas, and any warnings or conflicts.

**Example:**

```bash
cruxible world pull-preview
# Current release: v1.0
# Target release: v1.1
# Compatibility: data_only
# Apply digest: abc123
# Upstream delta: entities=+5 edges=+12
```

---

### cruxible world pull-apply

Apply a previewed upstream release into the current fork.

```bash
cruxible world pull-apply --apply-digest <digest>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--apply-digest` | **yes** | Apply digest returned by `pull-preview` |

**Example:**

```bash
cruxible world pull-apply --apply-digest abc123
# Pulled release v1.1
# Pre-pull snapshot: SNAP-def456
```

---

## Graph Reads

### cruxible query

Execute a named query and save the receipt.

```bash
cruxible query --query <name> [--param KEY=VALUE ...] [--limit <n>] [--count] [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--query` | **yes** | Named query from config |
| `--param` | no | Query parameter as `KEY=VALUE` (repeatable) |
| `--limit` | no | Maximum results to display |
| `--count` | no | Show only summary metadata (no result rows) |
| `--json` | no | Output as JSON |

**Example:**

```bash
cruxible query --query check_interactions --param drug_id=warfarin
# 12 result(s), 1 step(s) executed.
# [table of interacting drugs with severity]
# Receipt: RCP-abc123
```

---

### cruxible schema

Display the config schema for the current instance.

```bash
cruxible schema [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--json` | no | Output as JSON |

---

### cruxible stats

Display entity and relationship counts for the current instance.

```bash
cruxible stats [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--json` | no | Output as JSON |

**Example:**

```bash
cruxible stats
# Graph: 52 entities, 704 edges
# Head snapshot: SNAP-abc123
# [table of entity and relationship type counts]
```

---

### cruxible sample

Show a sample of entities of a given type for quick inspection.

```bash
cruxible sample --type <entity_type> [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--type` | **yes** | -- | Entity type to sample |
| `--limit` | no | `5` | Number of entities to show |
| `--json` | no | -- | Output as JSON |

**Example:**

```bash
cruxible sample --type Drug --limit 3
# [table showing 3 sample drugs]
```

---

### cruxible get-entity

Look up a specific entity by type and ID.

```bash
cruxible get-entity --type <entity_type> --id <entity_id> [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--type` | **yes** | Entity type |
| `--id` | **yes** | Entity ID |
| `--json` | no | Output as JSON |

Prints "Not found." and exits 0 when the entity doesn't exist.

**Example:**

```bash
cruxible get-entity --type Drug --id warfarin
# [table showing entity properties]

cruxible get-entity --type Drug --id NONEXISTENT
# Not found.
```

---

### cruxible get-relationship

Look up a specific relationship by its endpoints and type.

```bash
cruxible get-relationship --from-type <type> --from-id <id> \
  --relationship <rel> --to-type <type> --to-id <id> [--edge-key <int>] [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--from-type` | **yes** | Source entity type |
| `--from-id` | **yes** | Source entity ID |
| `--relationship` | **yes** | Relationship type |
| `--to-type` | **yes** | Target entity type |
| `--to-id` | **yes** | Target entity ID |
| `--edge-key` | no | Edge key for multi-edge disambiguation |
| `--json` | no | Output as JSON |

Prints "Not found." and exits 0 when the relationship doesn't exist. Errors with exit 1 when multiple edges exist and `--edge-key` is not specified.

**Example:**

```bash
cruxible get-relationship --from-type Drug --from-id warfarin \
  --relationship interacts_with --to-type Drug --to-id simvastatin
# [table showing relationship properties]
```

---

### cruxible inspect entity

Inspect an entity and its immediate neighbors.

```bash
cruxible inspect entity --type <entity_type> --id <entity_id> \
  [--direction incoming|outgoing|both] [--relationship <type>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--type` | **yes** | -- | Entity type |
| `--id` | **yes** | -- | Entity ID |
| `--direction` | no | `both` | Neighbor traversal direction: `incoming`, `outgoing`, or `both` |
| `--relationship` | no | -- | Optional relationship type filter |
| `--limit` | no | -- | Max neighbors to show |
| `--json` | no | -- | Output as JSON |

**Example:**

```bash
cruxible inspect entity --type Drug --id warfarin --direction outgoing --limit 10
# [entity properties table]
# Neighbors: 15
# [neighbors table]
```

---

### cruxible list

List entities, edges, receipts, feedback, or outcomes.

#### cruxible list entities

```bash
cruxible list entities --type <entity_type> [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--type` | **yes** | -- | Entity type to list |
| `--limit` | no | `50` | Max entities to show |
| `--json` | no | -- | Output as JSON |

#### cruxible list edges

```bash
cruxible list edges [--relationship <type>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--relationship` | no | -- | Filter by relationship type |
| `--limit` | no | `50` | Max edges to show |
| `--json` | no | -- | Output as JSON |

#### cruxible list receipts

```bash
cruxible list receipts [--query-name <name>] [--operation-type <type>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--query-name` | no | -- | Filter by query name |
| `--operation-type` | no | -- | Filter by operation type |
| `--limit` | no | `50` | Max receipts to show |
| `--json` | no | -- | Output as JSON |

#### cruxible list feedback

```bash
cruxible list feedback [--receipt <id>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--receipt` | no | -- | Filter by receipt ID |
| `--limit` | no | `50` | Max records to show |
| `--json` | no | -- | Output as JSON |

#### cruxible list outcomes

```bash
cruxible list outcomes [--receipt <id>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--receipt` | no | -- | Filter by receipt ID |
| `--limit` | no | `50` | Max records to show |
| `--json` | no | -- | Output as JSON |

---

### cruxible find-candidates

Find candidate relationships using deterministic strategies.

```bash
cruxible find-candidates --relationship <type> --strategy <strategy> \
  [--rule FROM_PROP=TO_PROP ...] [--via <relationship>] [--limit <n>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--relationship` | **yes** | Relationship type to find candidates for |
| `--strategy` | **yes** | `property_match` or `shared_neighbors` |
| `--rule` | conditional | Match rule as `FROM_PROP=TO_PROP` (repeatable, for `property_match`) |
| `--via` | conditional | Via relationship (for `shared_neighbors`) |
| `--limit` | no | Max candidates (default: `20`) |

**Example:**

```bash
cruxible find-candidates --relationship interacts_with \
  --strategy shared_neighbors \
  --via metabolized_by
# [table of candidate drug pairs sharing enzymes]
# 15 candidate(s) found.
```

---

### cruxible evaluate

Assess graph quality: orphans, gaps, violations, unreviewed co-members.

```bash
cruxible evaluate [--threshold <float>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--threshold` | no | `0.5` | Confidence threshold for flagging edges |
| `--limit` | no | `100` | Max findings to show |
| `--json` | no | -- | Output as JSON |

**Example:**

```bash
cruxible evaluate
# Graph: 52 entities, 704 edges
# Findings: 3
#   orphan: 1
#   constraint_violation: 2
#   [ERROR] interacts_with edge warfarin -> warfarin violates no_self_interaction
```

---

### cruxible explain

Explain a query result using its receipt. Supports JSON, Markdown, and Mermaid output.

```bash
cruxible explain --receipt <receipt_id> [--format json|markdown|mermaid]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--receipt` | **yes** | -- | Receipt ID to explain |
| `--format` | no | `markdown` | Output format: `json`, `markdown`, or `mermaid` |

**Example:**

```bash
cruxible explain --receipt RCP-abc123 --format mermaid
```

---

## Graph Mutations

### cruxible add-entity

Add or update an entity in the graph (upsert).

```bash
cruxible add-entity --type <entity_type> --id <entity_id> [--props <json>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--type` | **yes** | Entity type (must exist in config) |
| `--id` | **yes** | Entity ID |
| `--props` | no | JSON object of entity properties |

**Example:**

```bash
cruxible add-entity --type Drug --id metoprolol \
  --props '{"drug_id": "metoprolol", "name": "Metoprolol", "therapeutic_class": "beta_blockers"}'
# Entity Drug:metoprolol added.
```

---

### cruxible add-relationship

Add or update a relationship in the graph (upsert).

```bash
cruxible add-relationship --from-type <type> --from-id <id> \
  --relationship <rel> --to-type <type> --to-id <id> [--props <json>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--from-type` | **yes** | Source entity type |
| `--from-id` | **yes** | Source entity ID |
| `--relationship` | **yes** | Relationship type (must exist in config) |
| `--to-type` | **yes** | Target entity type |
| `--to-id` | **yes** | Target entity ID |
| `--props` | no | JSON object of [edge properties](concepts.md#edge-properties) |

Both endpoint entities must exist. Direction must match config (from_type matches the relationship's `from` entity).

**Example:**

```bash
cruxible add-relationship --from-type Drug --from-id metoprolol \
  --relationship metabolized_by --to-type Enzyme --to-id CYP2D6 \
  --props '{"source": "manual"}'
# Relationship added: Drug:metoprolol -[metabolized_by]-> Enzyme:CYP2D6
```

---

### cruxible add-constraint

Add a constraint rule to the config YAML.

```bash
cruxible add-constraint --name <name> --rule <rule> \
  [--severity warning|error] [--description <text>]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--name` | **yes** | -- | Constraint name (must be unique) |
| `--rule` | **yes** | -- | Rule expression |
| `--severity` | no | `warning` | `warning` or `error` |
| `--description` | no | -- | Description of the constraint |

Rule syntax: `RELATIONSHIP.FROM.property <op> RELATIONSHIP.TO.property`

Supported operators: `==`, `!=`, `>`, `>=`, `<`, `<=`

**Example:**

```bash
cruxible add-constraint --name no_self_interaction \
  --rule "interacts_with.FROM.drug_id != interacts_with.TO.drug_id" \
  --severity error \
  --description "A drug should not interact with itself"
# Constraint 'no_self_interaction' added to config.
```

---

### cruxible add-decision-policy

Add a decision policy to the config.

```bash
cruxible add-decision-policy --name <name> --applies-to <surface> \
  --relationship <type> --effect <effect> \
  [--query-name <name>] [--workflow-name <name>] \
  [--match <json>] [--description <text>] [--rationale <text>] [--expires-at <timestamp>]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--name` | **yes** | -- | Decision policy name |
| `--applies-to` | **yes** | -- | Policy application surface: `query` or `workflow` |
| `--relationship` | **yes** | -- | Relationship type |
| `--effect` | **yes** | -- | Policy effect: `suppress` or `require_review` |
| `--query-name` | no | -- | Named query (for query policies) |
| `--workflow-name` | no | -- | Workflow name (for workflow policies) |
| `--match` | no | `{}` | JSON object for exact-match selectors |
| `--description` | no | -- | Optional description |
| `--rationale` | no | `""` | Policy rationale |
| `--expires-at` | no | -- | Optional ISO timestamp/date |

**Example:**

```bash
cruxible add-decision-policy --name suppress_low_confidence \
  --applies-to query --relationship interacts_with \
  --effect suppress --query-name check_interactions \
  --match '{"confidence_below": 0.3}' \
  --rationale "Suppress low-confidence interactions from clinical queries"
# Decision policy 'suppress_low_confidence' added to config.
```

---

### cruxible ingest

Ingest data from a file using a named mapping from the config.

```bash
cruxible ingest --mapping <name> --file <path>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--mapping` | **yes** | Ingestion mapping name from config |
| `--file` | **yes** | Path to a CSV or JSON data file |

Ingest entity mappings before relationship mappings -- edges reference entity IDs.

**Example:**

```bash
cruxible ingest --mapping drugs --file data/drugs.csv
# Ingested 46 added via mapping 'drugs'.

cruxible ingest --mapping interactions --file data/interactions.csv
# Ingested 484 added via mapping 'interactions'.
```

---

## Feedback & Outcomes

### cruxible feedback

Submit feedback on a specific edge from a query result.

```bash
cruxible feedback --receipt <id> --action <action> \
  --from-type <type> --from-id <id> \
  --relationship <rel> \
  --to-type <type> --to-id <id> \
  [--edge-key <int>] [--reason <text>] [--corrections <json>] \
  [--source <human|ai_review|system>] [--group-override]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--receipt` | **yes** | -- | Receipt ID |
| `--action` | **yes** | -- | `approve`, `reject`, `correct`, or `flag` |
| `--from-type` | **yes** | -- | Source entity type |
| `--from-id` | **yes** | -- | Source entity ID |
| `--relationship` | **yes** | -- | Relationship type |
| `--to-type` | **yes** | -- | Target entity type |
| `--to-id` | **yes** | -- | Target entity ID |
| `--edge-key` | no | -- | Edge key for multi-edge disambiguation |
| `--reason` | no | `""` | Reason for feedback |
| `--corrections` | no | -- | JSON object of edge property corrections (for `correct`) |
| `--source` | no | `human` | `human`, `ai_review`, or `system` |
| `--group-override` | no | `false` | Stamp edge with group_override property (edge must exist) |

**Example:**

```bash
cruxible feedback --receipt RCP-abc123 --action reject \
  --from-type Drug --from-id fluoxetine \
  --relationship inhibits \
  --to-type Enzyme --to-id CYP2D6 \
  --reason "Confidence too low, insufficient evidence"
# Feedback fb-xyz789 applied to graph.
```

---

### cruxible feedback-batch

Submit a batch of edge feedback with one top-level receipt.

```bash
cruxible feedback-batch --items-file <path> [--source <human|ai_review|system>]
cruxible feedback-batch --items <json_array> [--source <human|ai_review|system>]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--items-file` | conditional | -- | JSON or YAML file with batch feedback items |
| `--items` | conditional | -- | Inline JSON array of feedback items |
| `--source` | no | `human` | `human`, `ai_review`, or `system` |

Provide `--items-file` or `--items`, not both.

Each item in the array must include `receipt_id`, `action`, and `target` (with `from_type`, `from_id`, `relationship`, `to_type`, `to_id`). Optional fields: `reason`, `corrections`, `edge_key`, `group_override`.

**Example:**

```bash
cruxible feedback-batch --items-file batch.json --source ai_review
# Batch feedback recorded for 5/5 item(s).
#   Feedback IDs: fb-001, fb-002, fb-003, fb-004, fb-005
#   Receipt: RCP-batch456
```

---

### cruxible outcome

Record the outcome of a decision.

```bash
cruxible outcome --receipt <id> --outcome <value> [--detail <json>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--receipt` | **yes** | Receipt ID |
| `--outcome` | **yes** | `correct`, `incorrect`, `partial`, or `unknown` |
| `--detail` | no | JSON string with outcome details |

**Example:**

```bash
cruxible outcome --receipt RCP-abc123 --outcome correct
# Outcome out-def456 recorded.
```

---

### cruxible feedback-profile

Display the configured feedback profile for one relationship type.

```bash
cruxible feedback-profile --relationship <type>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--relationship` | **yes** | Relationship type |

Prints the feedback profile as YAML, or "Not found." if no profile is configured.

**Example:**

```bash
cruxible feedback-profile --relationship interacts_with
# [YAML feedback profile output]
```

---

### cruxible outcome-profile

Display the configured outcome profile for one anchor context.

```bash
cruxible outcome-profile --anchor-type <receipt|resolution> \
  [--relationship <type>] [--workflow <name>] \
  [--surface-type <query|workflow|operation>] [--surface-name <name>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--anchor-type` | **yes** | Anchor type: `receipt` or `resolution` |
| `--relationship` | no | Relationship type |
| `--workflow` | no | Workflow name |
| `--surface-type` | no | Receipt surface type: `query`, `workflow`, or `operation` |
| `--surface-name` | no | Receipt surface name |

Prints the outcome profile as YAML with its profile key, or "Not found." if no profile matches.

**Example:**

```bash
cruxible outcome-profile --anchor-type receipt --relationship interacts_with
# # profile_key: interacts_with
# [YAML outcome profile output]
```

---

### cruxible analyze-feedback

Analyze structured feedback and print remediation suggestions.

```bash
cruxible analyze-feedback --relationship <type> \
  [--limit <n>] [--min-support <n>] \
  [--decision-surface-type <query|workflow|operation>] \
  [--decision-surface-name <name>] \
  [--pair FROM_PROP=TO_PROP ...]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--relationship` | **yes** | -- | Relationship type |
| `--limit` | no | `200` | Rows to inspect |
| `--min-support` | no | `5` | Minimum support for suggestions |
| `--decision-surface-type` | no | -- | Optional decision surface type filter: `query`, `workflow`, or `operation` |
| `--decision-surface-name` | no | -- | Optional decision surface name filter |
| `--pair` | no | -- | Explicit mismatch pair as `FROM_PROP=TO_PROP` (repeatable) |

Prints action counts, reason code counts, constraint suggestions, decision policy suggestions, quality check candidates, provider fix candidates, and uncoded feedback.

**Example:**

```bash
cruxible analyze-feedback --relationship interacts_with --min-support 3
# Feedback analyzed: 42 row(s)
# Actions: approve=30, reject=12
# Constraint suggestions:
#   no_self_interaction: interacts_with.FROM.drug_id != interacts_with.TO.drug_id (support=8)
```

---

### cruxible analyze-outcomes

Analyze structured outcomes and print trust/debugging suggestions.

```bash
cruxible analyze-outcomes --anchor-type <receipt|resolution> \
  [--relationship <type>] [--workflow <name>] [--query <name>] \
  [--surface-type <query|workflow|operation>] [--surface-name <name>] \
  [--limit <n>] [--min-support <n>]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--anchor-type` | **yes** | -- | Outcome anchor type: `receipt` or `resolution` |
| `--relationship` | no | -- | Relationship type |
| `--workflow` | no | -- | Workflow name filter |
| `--query` | no | -- | Query name filter |
| `--surface-type` | no | -- | Explicit surface type filter: `query`, `workflow`, or `operation` |
| `--surface-name` | no | -- | Explicit surface name filter |
| `--limit` | no | `200` | Rows to inspect |
| `--min-support` | no | `5` | Minimum support for suggestions |

Output is printed as YAML.

**Example:**

```bash
cruxible analyze-outcomes --anchor-type receipt --relationship interacts_with
# [YAML output with outcome analysis]
```

---

## Group Management

### cruxible group propose

Propose a candidate group of edges for batch review.

```bash
cruxible group propose --relationship <type> \
  --members-file <path> | --members <json> \
  [--thesis <text>] [--thesis-facts <json>] \
  [--analysis-state <json>] [--integration <name> ...]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--relationship` | **yes** | -- | Relationship type for the group |
| `--members-file` | conditional | -- | JSON file with member list |
| `--members` | conditional | -- | Inline JSON array of members |
| `--thesis` | no | `""` | Human-readable thesis text |
| `--thesis-facts` | no | -- | JSON object of structured thesis facts |
| `--analysis-state` | no | -- | JSON object of opaque analysis state |
| `--integration` | no | -- | Integration name used in this proposal (repeatable) |

Provide `--members-file` or `--members`, not both. Each member must include `from_type`, `from_id`, `to_type`, `to_id`, `relationship_type`, and optionally `signals` and `properties`.

**Example:**

```bash
cruxible group propose --relationship interacts_with \
  --members-file candidates.json \
  --thesis "CYP2D6 metabolized drugs likely interact" \
  --integration nvd_lookup
# Group GRP-abc123 proposed.
#   Status: pending_review
#   Priority: high
#   Members: 5
#   Signature: a1b2c3d4e5f6...
```

---

### cruxible group resolve

Resolve a candidate group (approve or reject).

```bash
cruxible group resolve --group <group_id> --action <approve|reject> \
  [--rationale <text>] [--source <human|ai_review>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--group` | **yes** | -- | Group ID to resolve |
| `--action` | **yes** | -- | `approve` or `reject` |
| `--rationale` | no | `""` | Rationale for this resolution |
| `--source` | no | `human` | Who resolved: `human` or `ai_review` |
| `--json` | no | -- | Output as JSON |

**Example:**

```bash
cruxible group resolve --group GRP-abc123 --action approve \
  --rationale "Confirmed via clinical literature"
# Group GRP-abc123 approved.
#   Edges created: 5
#   Resolution: RES-xyz789
#   Receipt: RCP-resolve001
```

---

### cruxible group trust

Update trust status on a resolution.

```bash
cruxible group trust --resolution <resolution_id> --status <status> [--reason <text>]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--resolution` | **yes** | -- | Resolution ID |
| `--status` | **yes** | -- | Trust status: `watch`, `trusted`, or `invalidated` |
| `--reason` | no | `""` | Reason for trust status change |

**Example:**

```bash
cruxible group trust --resolution RES-xyz789 --status trusted \
  --reason "Validated by domain expert"
# Resolution RES-xyz789 trust status set to 'trusted'.
```

---

### cruxible group get

Get details of a candidate group.

```bash
cruxible group get --group <group_id> [--json]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--group` | **yes** | Group ID |
| `--json` | no | Output as JSON |

**Example:**

```bash
cruxible group get --group GRP-abc123
# [group detail table with members]
```

---

### cruxible group list

List candidate groups.

```bash
cruxible group list [--relationship <type>] [--status <status>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--relationship` | no | -- | Filter by relationship type |
| `--status` | no | -- | Filter by status: `pending_review`, `auto_resolved`, `applying`, `resolved`, or `suppressed` |
| `--limit` | no | `50` | Max groups to show |
| `--json` | no | -- | Output as JSON |

**Example:**

```bash
cruxible group list --status pending_review
# [groups table]
# 3 of 3 group(s) shown.
```

---

### cruxible group resolutions

List group resolutions.

```bash
cruxible group resolutions [--relationship <type>] [--action <approve|reject>] [--limit <n>] [--json]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--relationship` | no | -- | Filter by relationship type |
| `--action` | no | -- | Filter by action: `approve` or `reject` |
| `--limit` | no | `50` | Max resolutions to show |
| `--json` | no | -- | Output as JSON |

**Example:**

```bash
cruxible group resolutions --action approve
# [resolutions table]
# 5 of 5 resolution(s) shown.
```

---

## Snapshots

### cruxible snapshot create

Create an immutable full snapshot for the current instance.

```bash
cruxible snapshot create [--label <text>]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--label` | no | Optional human label for the snapshot |

**Example:**

```bash
cruxible snapshot create --label "pre-enrich baseline"
# Created snapshot SNAP-abc123
#   label=pre-enrich baseline
#   graph=sha256:def456...
```

---

### cruxible snapshot list

List snapshots for the current instance.

```bash
cruxible snapshot list
```

No options. Lists all snapshots with ID, timestamp, and optional label.

**Example:**

```bash
cruxible snapshot list
# SNAP-abc123 2024-01-15T10:30:00 label=pre-enrich baseline
# SNAP-def456 2024-01-15T11:00:00
```

---

### cruxible fork

Create a new local instance from a chosen snapshot.

```bash
cruxible fork --snapshot <snapshot_id> --root-dir <dir>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--snapshot` | **yes** | Snapshot ID to fork from |
| `--root-dir` | **yes** | Root directory for the new forked instance |

**Example:**

```bash
cruxible fork --snapshot SNAP-abc123 --root-dir ./experiment
# Forked snapshot SNAP-abc123 into ./experiment
```

---

## Export

### cruxible export edges

Export all edges to CSV.

```bash
cruxible export edges -o <path> [--relationship <type>] [--exclude-rejected]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--output` / `-o` | **yes** | Output file path |
| `--relationship` | no | Filter by relationship type |
| `--exclude-rejected` | no | Omit edges with `human_rejected` or `ai_rejected` review status |

**Columns:** `from_type`, `from_id`, `to_type`, `to_id`, `relationship_type`, `edge_key`, `properties_json`

The `properties_json` column is the full edge properties dict as JSON with deterministic key ordering (`sort_keys=True`). This includes config-defined properties, `review_status`, and `_provenance`. See [Edge Properties](concepts.md#edge-properties) for what these contain.

By default all edges are exported regardless of `review_status`. Use `--exclude-rejected` to omit rejected edges.

**Example:**

```bash
cruxible export edges -o edges.csv
# Exported 704 edge(s) to edges.csv

cruxible export edges -o metabolized.csv --relationship metabolized_by
# Exported 58 edge(s) to metabolized.csv

# Verify round-trip:
python -c "import csv, json; [json.loads(r['properties_json']) for r in csv.DictReader(open('edges.csv'))]; print('OK')"
```

---

## Error Handling

All commands catch `CoreError` exceptions and print a user-friendly error message to stderr with a non-zero exit code. Use `--help` on any command for usage details.
