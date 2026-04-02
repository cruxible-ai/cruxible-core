# MCP Tools Reference

Cruxible Core exposes MCP tools through the [Model Context Protocol](https://modelcontextprotocol.io) (MCP). AI agents (Claude Code, Cursor, Codex, etc.) use these tools to orchestrate the full decision lifecycle: validate configs, lock and execute workflows, query the graph, provide feedback, and evaluate quality.

## Setup

Install the MCP runtime with:

```bash
pip install "cruxible-core[mcp]"
```

If you are writing a separate HTTP client that talks to an already-running daemon, install `cruxible-client` in that agent environment instead of `cruxible-core`.

Add to your MCP client config (Claude Code / Cursor use `.mcp.json`; see [README](../README.md#mcp-setup) for Codex):

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

## Permission Modes

Each tool requires a minimum permission tier. Set via the `CRUXIBLE_MODE` environment variable.

| Mode | Env Value | Description |
|------|-----------|-------------|
| `READ_ONLY` | `read_only` | Query, inspect, validate, plan workflows — no mutations |
| `GOVERNED_WRITE` | `governed_write` | READ_ONLY + receipt-persisting workflow runs, governed proposals, feedback |
| `GRAPH_WRITE` | `graph_write` | GOVERNED_WRITE + raw graph mutation and proposal resolution |
| `ADMIN` | `admin` | All tools including canonical workflow apply, ingest, config mutation, world publishing |

Default is `ADMIN` if unset.

These tiers are enforced at the daemon boundary. They are meaningful when an agent talks to a running Cruxible daemon through MCP/HTTP, not when it can import `cruxible-core` runtime modules directly in the same environment.

---

## Utility Tools

### cruxible_version

Return the cruxible-core version. Use this to confirm which build is running.

**Permission:** READ_ONLY

_No parameters._

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Installed cruxible-core version (e.g., `"0.3.3"`) |

---

### cruxible_prompt

Read a workflow prompt, or list all available prompts.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt_name` | string | no | Prompt to read (omit to list all) |
| `args` | dict | no | Arguments for the prompt (e.g., `{"domain": "drug interactions"}`) |

**List mode** (no arguments): Returns all available prompts with descriptions and required args.

**Read mode** (with `prompt_name`): Returns the full prompt content for the specified workflow.

**Available prompts:**

| Prompt | Args | Description |
|--------|------|-------------|
| `onboard_domain` | `domain` | Full workflow from raw data to working graph |
| `prepare_data` | `data_description` | Checklist for profiling and cleaning data before ingestion |
| `review_graph` | `instance_id` | Review and improve an existing graph's quality |
| `user_review` | `instance_id` | Collaborative edge review session with a human |
| `analyze_feedback` | `instance_id`, `relationship_type` | Discover rejection patterns worth encoding as constraints |
| `common_workflows` | _(none)_ | Common multi-tool sequences for debugging, review, and auditing |

---

## Lifecycle Tools

### cruxible_validate

Validate a config without creating an instance. Always run this before `cruxible_init`.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config_path` | string | conditional | Path to a YAML config file |
| `config_yaml` | string | conditional | Raw YAML string |

Provide exactly one of `config_path` or `config_yaml`.

**Returns:** `ValidateResult`

| Field | Type | Description |
|-------|------|-------------|
| `valid` | bool | Whether the config passed validation |
| `name` | string | Config name |
| `entity_types` | list[string] | Entity type names |
| `relationships` | list[string] | Relationship names |
| `named_queries` | list[string] | Query names |
| `warnings` | list[string] | Non-fatal warnings |

---

### cruxible_init

Create a new instance or reload an existing one.

**Permission:** READ_ONLY (reload) / ADMIN (create)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `root_dir` | string | **yes** | Directory for the `.cruxible/` instance |
| `config_path` | string | conditional | Path to a YAML config file (new instance) |
| `config_yaml` | string | conditional | Raw YAML string (new instance) |
| `data_dir` | string | no | Directory for data files |

To create a new instance, provide exactly one of `config_path` or `config_yaml`. To reload, omit both.

**Returns:** `InitResult`

| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | string | Unique instance identifier (use in all subsequent calls) |
| `status` | string | `"initialized"` or `"loaded"` |
| `warnings` | list[string] | Non-fatal warnings |

---

### cruxible_ingest

Ingest data through a named ingestion mapping.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID from `cruxible_init` |
| `mapping_name` | string | **yes** | Ingestion mapping name from config |
| `file_path` | string | conditional | Path to a CSV or JSON file |
| `data_csv` | string | conditional | Inline CSV string |
| `data_json` | string or list | conditional | Inline JSON array of row objects |
| `data_ndjson` | string | conditional | Inline NDJSON string (one JSON object per line) |
| `upload_id` | string | conditional | Reserved for cloud mode |

Deprecated for new configs: prefer workflow-based deterministic loading with `cruxible_lock_workflow`, `cruxible_run_workflow`, and `cruxible_apply_workflow`.

Provide exactly one data source. Ingest entity mappings before relationship mappings.

**Returns:** `IngestResult`

| Field | Type | Description |
|-------|------|-------------|
| `records_ingested` | int | Number of records loaded |
| `records_updated` | int | Number of records updated |
| `mapping` | string | Mapping name used |
| `entity_type` | string or null | Entity type (if entity mapping) |
| `relationship_type` | string or null | Relationship type (if relationship mapping) |
| `receipt_id` | string or null | Receipt ID for provenance tracking |

---

## Workflow Execution Tools

### cruxible_lock_workflow

Generate the workflow lock file for the current instance config.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID from `cruxible_init` |

Use this after changing workflow config, providers, or artifacts and before planning or executing workflows.

**Returns:** `WorkflowLockResult`

| Field | Type | Description |
|-------|------|-------------|
| `lock_path` | string | Path to the generated lock file |
| `config_digest` | string | SHA256 digest of the config |
| `providers_locked` | int | Number of providers locked |
| `artifacts_locked` | int | Number of artifacts locked |

---

### cruxible_plan_workflow

Compile a configured workflow into a concrete execution plan.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `workflow_name` | string | **yes** | Workflow name from config |
| `input_payload` | dict | no | Structured workflow input |

**Returns:** `WorkflowPlanResult`

| Field | Type | Description |
|-------|------|-------------|
| `plan` | dict | Compiled execution plan |

---

### cruxible_run_workflow

Execute a configured workflow and return its output, receipt, and traces.

**Permission:** GOVERNED_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `workflow_name` | string | **yes** | Workflow name from config |
| `input_payload` | dict | no | Structured workflow input |

Canonical workflows run in preview mode and return `apply_digest` plus `head_snapshot_id`. Pass those to `cruxible_apply_workflow` to commit.

**Returns:** `WorkflowRunResult`

| Field | Type | Description |
|-------|------|-------------|
| `workflow` | string | Workflow name |
| `output` | any | Workflow output |
| `receipt_id` | string | Receipt ID |
| `mode` | string | Execution mode (`"run"`) |
| `canonical` | bool | Whether the workflow is canonical |
| `apply_digest` | string or null | Digest for canonical apply verification |
| `head_snapshot_id` | string or null | Current head snapshot ID |
| `apply_previews` | dict | Preview of mutations to apply |
| `query_receipt_ids` | list[string] | Receipt IDs for queries executed during the workflow |
| `trace_ids` | list[string] | Provider execution trace IDs |
| `receipt` | dict or null | Inline receipt data |
| `traces` | list[dict] | Provider execution traces |

---

### cruxible_apply_workflow

Apply a canonical workflow after verifying the preview identity.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `workflow_name` | string | **yes** | Canonical workflow name |
| `expected_apply_digest` | string | **yes** | Preview digest from `cruxible_run_workflow` |
| `expected_head_snapshot_id` | string | no | Snapshot ID returned by preview |
| `input_payload` | dict | no | Structured workflow input |

**Returns:** `WorkflowApplyResult`

| Field | Type | Description |
|-------|------|-------------|
| `workflow` | string | Workflow name |
| `output` | any | Workflow output |
| `receipt_id` | string | Receipt ID |
| `mode` | string | Execution mode (`"apply"`) |
| `canonical` | bool | Always `true` |
| `committed_snapshot_id` | string or null | Snapshot ID created by the apply |
| `apply_previews` | dict | Applied mutations |
| `query_receipt_ids` | list[string] | Receipt IDs for queries executed during the workflow |
| `trace_ids` | list[string] | Provider execution trace IDs |
| `receipt` | dict or null | Inline receipt data |
| `traces` | list[dict] | Provider execution traces |

---

### cruxible_propose_workflow

Execute a configured workflow and bridge its output into a governed relationship group.

**Permission:** GOVERNED_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `workflow_name` | string | **yes** | Workflow name from config |
| `input_payload` | dict | no | Structured workflow input |

Use this when a repeated decision procedure should propose relationship state through Cruxible's proposal/review/trust boundary instead of writing edges directly. The workflow must return a relationship proposal artifact from a `propose_relationship_group` step.

**Returns:** `WorkflowProposeResult`

| Field | Type | Description |
|-------|------|-------------|
| `workflow` | string | Workflow name |
| `output` | any | Workflow output |
| `receipt_id` | string | Receipt ID |
| `group_id` | string or null | Proposed group ID (null if suppressed) |
| `group_status` | string | Group lifecycle status |
| `review_priority` | string | Review priority level |
| `suppressed` | bool | Whether the proposal was suppressed by a decision policy |
| `query_receipt_ids` | list[string] | Receipt IDs for queries executed during the workflow |
| `trace_ids` | list[string] | Provider execution trace IDs |
| `prior_resolution` | dict or null | Prior resolution if auto-resolved |
| `policy_summary` | dict | Decision policy match counts |
| `receipt` | dict or null | Inline receipt data |
| `traces` | list[dict] | Provider execution traces |

---

## Query Tools

### cruxible_query

Run a named query and return results with a receipt.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `query_name` | string | **yes** | Named query from config |
| `params` | dict | no | Query parameters (e.g., `{"drug_id": "warfarin"}`) |
| `limit` | int | no | Maximum results to return |

**Returns:** `QueryToolResult`

| Field | Type | Description |
|-------|------|-------------|
| `results` | list[dict] | Matched entities with properties |
| `receipt_id` | string or null | Receipt ID for provenance tracking |
| `receipt` | dict or null | Inline receipt data |
| `total_results` | int | Total number of results |
| `truncated` | bool | Whether results were truncated by limit |
| `steps_executed` | int | Number of traversal steps executed |
| `policy_summary` | dict | Decision policy match counts |

---

### cruxible_receipt

Fetch a stored receipt from a previous query.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `receipt_id` | string | **yes** | Receipt ID from a prior `cruxible_query` |

**Returns:** Full receipt dict with traversal evidence, timestamps, and provenance chain.

---

### cruxible_find_candidates

Find missing-relationship candidates using deterministic strategies.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `relationship_type` | string | **yes** | Relationship type to find candidates for |
| `strategy` | string | **yes** | `"property_match"` or `"shared_neighbors"` |
| `match_rules` | list[dict] | conditional | Rules for `property_match` (each: `{from_property, to_property, operator}`) |
| `via_relationship` | string | conditional | Relationship for `shared_neighbors` |
| `min_overlap` | float | no | Minimum neighbor overlap (default: `0.5`) |
| `min_confidence` | float | no | Minimum confidence threshold (default: `0.5`) |
| `limit` | int | no | Maximum candidates to return (default: `20`) |
| `min_distinct_neighbors` | int | no | Minimum neighbors per entity for `shared_neighbors` (default: `2`) |

**Strategy: `property_match`** — Requires `match_rules`. Operators:
- `equals` (default): Type-strict hash-join, O(n+m)
- `iequals`: Case-insensitive hash-join, O(n+m)
- `contains`: Substring match, brute-force scan

**Strategy: `shared_neighbors`** — Requires `via_relationship`. Finds entity pairs sharing common neighbors through the specified relationship.

**Returns:** `CandidatesResult`

| Field | Type | Description |
|-------|------|-------------|
| `candidates` | list[dict] | Candidate relationship pairs with confidence scores |
| `total` | int | Total candidates found |

---

## Feedback Tools

### cruxible_feedback

Record edge-level feedback tied to a receipt.

**Permission:** GOVERNED_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `receipt_id` | string | **yes** | Receipt ID the feedback applies to |
| `action` | string | **yes** | `"approve"`, `"reject"`, `"correct"`, or `"flag"` |
| `source` | string | **yes** | `"human"`, `"ai_review"`, or `"system"` |
| `from_type` | string | **yes** | Source entity type |
| `from_id` | string | **yes** | Source entity ID |
| `relationship` | string | **yes** | Relationship type |
| `to_type` | string | **yes** | Target entity type |
| `to_id` | string | **yes** | Target entity ID |
| `edge_key` | int | no | Edge key for multi-edge disambiguation |
| `reason` | string | no | Reason for the feedback (default: `""`) |
| `reason_code` | string | no | Structured reason code for analysis |
| `scope_hints` | dict | no | Contextual scope hints for analysis |
| `corrections` | dict | no | Property corrections (for `action="correct"`) |
| `group_override` | bool | no | Stamp edge with group_override property (default: `false`) |

**Returns:** `FeedbackResult`

| Field | Type | Description |
|-------|------|-------------|
| `feedback_id` | string | Unique feedback record ID |
| `applied` | bool | Whether the feedback was applied to the graph edge |
| `receipt_id` | string or null | Mutation receipt ID |

**Behavior:**
- `reject`: Excluded from future query results
- `approve`: Trusted in traversals
- `correct`: Updates edge properties (pass `corrections` dict)
- `flag`: Marks for review without changing behavior

Set `group_override=true` to stamp the edge with a group_override property, marking it as pre-approved for group resolve. The edge must already exist in the graph.

---

### cruxible_feedback_batch

Record batch edge feedback under one top-level mutation receipt.

**Permission:** GOVERNED_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `items` | list[FeedbackBatchItemInput] | **yes** | Batch of feedback items |
| `source` | string | no | `"human"`, `"ai_review"`, or `"system"` (default: `"human"`) |

Each `FeedbackBatchItemInput`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `receipt_id` | string | **yes** | Receipt ID the feedback applies to |
| `action` | string | **yes** | `"approve"`, `"reject"`, `"correct"`, or `"flag"` |
| `target` | EdgeTargetInput | **yes** | Edge target (see below) |
| `reason` | string | no | Reason for the feedback (default: `""`) |
| `reason_code` | string | no | Structured reason code |
| `scope_hints` | dict | no | Contextual scope hints |
| `corrections` | dict | no | Property corrections (for `action="correct"`) |
| `group_override` | bool | no | Stamp edge with group_override property (default: `false`) |

Each `EdgeTargetInput`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `from_type` | string | **yes** | Source entity type |
| `from_id` | string | **yes** | Source entity ID |
| `relationship` | string | **yes** | Relationship type |
| `to_type` | string | **yes** | Target entity type |
| `to_id` | string | **yes** | Target entity ID |
| `edge_key` | int | no | Edge key for multi-edge disambiguation |

**Returns:** `FeedbackBatchResult`

| Field | Type | Description |
|-------|------|-------------|
| `feedback_ids` | list[string] | Feedback record IDs |
| `applied_count` | int | Number of feedback items applied to the graph |
| `total` | int | Total items processed |
| `receipt_id` | string or null | Mutation receipt ID |

---

### cruxible_outcome

Record the outcome of a decision (query result accuracy or resolution result).

**Permission:** GOVERNED_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `outcome` | string | **yes** | `"correct"`, `"incorrect"`, `"partial"`, or `"unknown"` |
| `receipt_id` | string | no | Receipt ID (convenience alias for `anchor_id` when `anchor_type="receipt"`) |
| `anchor_type` | string | no | `"receipt"` or `"resolution"` (default: `"receipt"`) |
| `anchor_id` | string | no | Anchor ID (receipt ID or resolution ID) |
| `source` | string | no | `"human"`, `"ai_review"`, or `"system"` (default: `"human"`) |
| `outcome_code` | string | no | Structured outcome code for analysis |
| `scope_hints` | dict | no | Contextual scope hints for analysis |
| `outcome_profile_key` | string | no | Outcome profile key for matching config profiles |
| `detail` | dict | no | Additional outcome details |

**Returns:** `OutcomeResult`

| Field | Type | Description |
|-------|------|-------------|
| `outcome_id` | string | Unique outcome record ID |

---

## Feedback Analysis Tools

### cruxible_get_feedback_profile

Return the configured feedback profile for one relationship type.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `relationship_type` | string | **yes** | Relationship type |

**Returns:** `FeedbackProfileResult`

| Field | Type | Description |
|-------|------|-------------|
| `found` | bool | Whether a profile was found |
| `relationship_type` | string | Relationship type |
| `profile` | dict | Feedback profile configuration |

---

### cruxible_get_outcome_profile

Return the configured outcome profile for one anchor context.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `anchor_type` | string | **yes** | `"receipt"` or `"resolution"` |
| `relationship_type` | string | no | Relationship type filter |
| `workflow_name` | string | no | Workflow name filter |
| `surface_type` | string | no | Decision surface type filter |
| `surface_name` | string | no | Decision surface name filter |

**Returns:** `OutcomeProfileResult`

| Field | Type | Description |
|-------|------|-------------|
| `found` | bool | Whether a profile was found |
| `profile_key` | string or null | Matched profile key |
| `anchor_type` | string | `"receipt"` or `"resolution"` |
| `profile` | dict | Outcome profile configuration |

---

### cruxible_analyze_feedback

Analyze structured feedback into deterministic remediation suggestions.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `relationship_type` | string | **yes** | Relationship type to analyze |
| `limit` | int | no | Maximum feedback records to analyze (default: `200`) |
| `min_support` | int | no | Minimum occurrences for a suggestion (default: `5`) |
| `decision_surface_type` | string | no | Filter by decision surface type |
| `decision_surface_name` | string | no | Filter by decision surface name |
| `property_pairs` | list[PropertyPairInput] | no | Property pairs for constraint suggestion mining |

Each `PropertyPairInput`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `from_property` | string | **yes** | Source entity property name |
| `to_property` | string | **yes** | Target entity property name |

**Returns:** `AnalyzeFeedbackResult`

| Field | Type | Description |
|-------|------|-------------|
| `relationship_type` | string | Relationship type analyzed |
| `feedback_count` | int | Total feedback records analyzed |
| `action_counts` | dict | Counts by action type |
| `source_counts` | dict | Counts by feedback source |
| `reason_code_counts` | dict | Counts by reason code |
| `coded_groups` | list[FeedbackGroupSummary] | Grouped feedback by reason code |
| `uncoded_feedback_count` | int | Feedback records without reason codes |
| `uncoded_examples` | list[UncodedFeedbackExample] | Sample uncoded feedback for labeling |
| `constraint_suggestions` | list[ConstraintSuggestion] | Suggested constraints based on rejection patterns |
| `decision_policy_suggestions` | list[DecisionPolicySuggestion] | Suggested decision policies |
| `quality_check_candidates` | list[QualityCheckCandidate] | Potential quality check additions |
| `provider_fix_candidates` | list[ProviderFixCandidate] | Provider issues to investigate |
| `warnings` | list[string] | Non-fatal warnings |

---

### cruxible_analyze_outcomes

Analyze structured outcomes into trust and debugging suggestions.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `anchor_type` | string | **yes** | `"receipt"` or `"resolution"` |
| `relationship_type` | string | no | Relationship type filter |
| `workflow_name` | string | no | Workflow name filter |
| `query_name` | string | no | Query name filter |
| `surface_type` | string | no | Decision surface type filter |
| `surface_name` | string | no | Decision surface name filter |
| `limit` | int | no | Maximum outcome records to analyze (default: `200`) |
| `min_support` | int | no | Minimum occurrences for a suggestion (default: `5`) |

**Returns:** `AnalyzeOutcomesResult`

| Field | Type | Description |
|-------|------|-------------|
| `anchor_type` | string | Anchor type analyzed |
| `outcome_count` | int | Total outcome records analyzed |
| `outcome_counts` | dict | Counts by outcome value |
| `outcome_code_counts` | dict | Counts by outcome code |
| `coded_groups` | list[OutcomeGroupSummary] | Grouped outcomes by code |
| `uncoded_outcome_count` | int | Outcomes without codes |
| `uncoded_examples` | list[UncodedOutcomeExample] | Sample uncoded outcomes for labeling |
| `trust_adjustment_suggestions` | list[TrustAdjustmentSuggestion] | Suggested trust status changes |
| `workflow_review_policy_suggestions` | list[OutcomeDecisionPolicySuggestion] | Suggested workflow review policies |
| `query_policy_suggestions` | list[QueryPolicySuggestion] | Suggested query-level policies |
| `provider_fix_candidates` | list[OutcomeProviderFixCandidate] | Provider issues to investigate |
| `debug_packages` | list[DebugPackage] | Debug packages for failing anchors |
| `workflow_debug_packages` | list[DebugPackage] | Debug packages for workflow anchors |
| `warnings` | list[string] | Non-fatal warnings |

---

### cruxible_add_decision_policy

Add a decision policy to the config for query/workflow execution.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `name` | string | **yes** | Unique policy name |
| `applies_to` | string | **yes** | `"query"` or `"workflow"` |
| `relationship_type` | string | **yes** | Relationship type the policy targets |
| `effect` | string | **yes** | `"suppress"` or `"require_review"` |
| `match` | DecisionPolicyMatchInput | no | Match conditions (see below) |
| `description` | string | no | Human-readable description |
| `rationale` | string | no | Rationale for the policy (default: `""`) |
| `query_name` | string | no | Scope to a specific query (when `applies_to="query"`) |
| `workflow_name` | string | no | Scope to a specific workflow (when `applies_to="workflow"`) |
| `expires_at` | string | no | ISO 8601 expiration timestamp |

`DecisionPolicyMatchInput` fields:

| Field | Type | Description |
|-------|------|-------------|
| `from` | dict | Match conditions on the source entity properties |
| `to` | dict | Match conditions on the target entity properties |
| `edge` | dict | Match conditions on edge properties |
| `context` | dict | Match conditions on execution context |

**Returns:** `AddDecisionPolicyResult`

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Policy name |
| `added` | bool | Whether the policy was added |
| `config_updated` | bool | Whether the YAML file was updated |
| `warnings` | list[string] | Non-fatal warnings |

---

## Group / Proposal Tools

### cruxible_propose_group

Propose a candidate group of edges for batch review.

**Permission:** GOVERNED_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `relationship_type` | string | **yes** | Relationship type for the group |
| `members` | list[MemberInput] | **yes** | Member edges with signals |
| `thesis_text` | string | no | Human-readable thesis (default: `""`) |
| `thesis_facts` | dict | no | Structured facts hashed into the deterministic signature |
| `analysis_state` | dict | no | Opaque agent data (NOT hashed into signature) |
| `integrations_used` | list[string] | no | Integration names used to produce signals |
| `proposed_by` | string | no | `"human"` or `"ai_review"` (default: `"ai_review"`) |
| `suggested_priority` | string | no | Agent-suggested review priority |

Each `MemberInput`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `from_type` | string | **yes** | Source entity type |
| `from_id` | string | **yes** | Source entity ID |
| `to_type` | string | **yes** | Target entity type |
| `to_id` | string | **yes** | Target entity ID |
| `relationship_type` | string | **yes** | Relationship type |
| `signals` | list[SignalInput] | no | Tri-state signals from integrations |
| `properties` | dict | no | Edge properties |

Each `SignalInput`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `integration` | string | **yes** | Integration name |
| `signal` | string | **yes** | `"support"`, `"contradict"`, or `"unsure"` |
| `evidence` | string | no | Supporting evidence (default: `""`) |

If a prior trusted resolution exists for the same thesis signature and all signals meet the auto-resolve policy, the group is auto-resolved. Otherwise it enters `pending_review` with a Cruxible-derived review priority.

**Returns:** `ProposeGroupToolResult`

| Field | Type | Description |
|-------|------|-------------|
| `group_id` | string or null | Group ID (null if suppressed) |
| `signature` | string | Deterministic thesis signature |
| `status` | string | Group status |
| `review_priority` | string | Assigned review priority |
| `member_count` | int | Number of members in the group |
| `prior_resolution` | dict or null | Prior resolution if auto-resolved |
| `suppressed` | bool | Whether the proposal was suppressed by a decision policy |
| `policy_summary` | dict | Decision policy match counts |

---

### cruxible_resolve_group

Resolve a candidate group by approving or rejecting it.

**Permission:** GRAPH_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `group_id` | string | **yes** | Candidate group ID |
| `action` | string | **yes** | `"approve"` or `"reject"` |
| `rationale` | string | no | Resolution rationale (default: `""`) |
| `resolved_by` | string | no | `"human"` or `"ai_review"` (default: `"human"`) |

Approve creates edges in the graph for valid members (skipping members whose edges already exist). Reject records the resolution without graph mutation. Both persist the resolution for audit and future auto-resolve precedent.

**Returns:** `ResolveGroupToolResult`

| Field | Type | Description |
|-------|------|-------------|
| `group_id` | string | Group ID |
| `action` | string | Resolution action |
| `edges_created` | int | Number of edges created (approve only) |
| `edges_skipped` | int | Number of edges skipped (already existed) |
| `resolution_id` | string or null | Resolution record ID |
| `receipt_id` | string or null | Mutation receipt ID |

---

### cruxible_get_group

Get a candidate group by ID, including its members and resolution.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `group_id` | string | **yes** | Candidate group ID |

Returns the group metadata (thesis, status, review_priority) and the full list of members with their signals. If the group has been resolved, includes the resolution details (action, trust_status, rationale).

**Returns:** `GetGroupToolResult`

| Field | Type | Description |
|-------|------|-------------|
| `group` | dict | Group metadata |
| `members` | list[dict] | Member edges with signals |

---

### cruxible_list_groups

List candidate groups with optional filters.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `relationship_type` | string | no | Filter by relationship type |
| `status` | string | no | Filter by status: `"pending_review"`, `"auto_resolved"`, `"applying"`, `"resolved"`, or `"suppressed"` |
| `limit` | int | no | Maximum groups to return (default: `50`) |

Results are sorted by review_priority descending (critical first).

**Returns:** `ListGroupsToolResult`

| Field | Type | Description |
|-------|------|-------------|
| `groups` | list[dict] | Group summaries |
| `total` | int | Total groups matching filters |

---

### cruxible_list_resolutions

List group resolutions with optional filters.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `relationship_type` | string | no | Filter by relationship type |
| `action` | string | no | Filter by action: `"approve"` or `"reject"` |
| `limit` | int | no | Maximum resolutions to return (default: `50`) |

Returns stored resolutions including analysis_state (for agent reuse), thesis_facts, trust_status, and trust_reason.

**Returns:** `ListResolutionsToolResult`

| Field | Type | Description |
|-------|------|-------------|
| `resolutions` | list[dict] | Resolution records |
| `total` | int | Total resolutions matching filters |

---

### cruxible_update_trust_status

Update the trust status on a confirmed approved resolution.

**Permission:** GRAPH_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `resolution_id` | string | **yes** | Resolution ID |
| `trust_status` | string | **yes** | `"trusted"`, `"watch"`, or `"invalidated"` |
| `reason` | string | no | Reason for the trust change (default: `""`) |

Trust is thesis-scoped: the latest confirmed approval for a signature governs auto-resolve eligibility. Promote `watch` to `trusted` to enable auto-resolve. Set `invalidated` to block auto-resolve and escalate future proposals to critical priority.

**Returns:** `UpdateTrustStatusToolResult`

| Field | Type | Description |
|-------|------|-------------|
| `resolution_id` | string | Resolution ID |
| `trust_status` | string | Updated trust status |

---

## World Publishing Tools

### cruxible_world_publish

Publish a root world-model instance as an immutable release bundle.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `transport_ref` | string | **yes** | Transport reference (e.g., directory path for local transport) |
| `world_id` | string | **yes** | World identifier |
| `release_id` | string | **yes** | Release identifier |
| `compatibility` | string | **yes** | `"data_only"`, `"additive_schema"`, or `"breaking"` |

**Returns:** `WorldPublishResult`

| Field | Type | Description |
|-------|------|-------------|
| `manifest` | PublishedWorldManifest | Published release manifest |

`PublishedWorldManifest` fields:

| Field | Type | Description |
|-------|------|-------------|
| `format_version` | int | Manifest format version |
| `world_id` | string | World identifier |
| `release_id` | string | Release identifier |
| `snapshot_id` | string | Snapshot ID at time of publish |
| `compatibility` | string | Compatibility level |
| `owned_entity_types` | list[string] | Entity types owned by this world |
| `owned_relationship_types` | list[string] | Relationship types owned by this world |
| `parent_release_id` | string or null | Previous release in the chain |

---

### cruxible_world_fork

Create a new local fork from a published world release.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `transport_ref` | string | **yes** | Transport reference to the published release |
| `root_dir` | string | **yes** | Directory for the new forked instance |

**Returns:** `WorldForkResult`

| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | string | New instance ID for the fork |
| `manifest` | PublishedWorldManifest | Manifest of the upstream release |

---

### cruxible_world_status

Return upstream tracking metadata for a release-backed fork.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |

**Returns:** `WorldStatusResult`

| Field | Type | Description |
|-------|------|-------------|
| `upstream` | UpstreamMetadataResult or null | Upstream tracking metadata (null if not a fork) |

---

### cruxible_world_pull_preview

Preview pulling a newer upstream release into a release-backed fork.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |

**Returns:** `WorldPullPreviewResult`

| Field | Type | Description |
|-------|------|-------------|
| `current_release_id` | string or null | Currently tracked release |
| `target_release_id` | string | Release to pull |
| `compatibility` | string | Compatibility level of the target release |
| `apply_digest` | string | Digest for verifying the apply |
| `warnings` | list[string] | Non-fatal warnings |
| `conflicts` | list[string] | Detected conflicts |
| `lock_changed` | bool | Whether the lock file changed |
| `upstream_entity_delta` | int | Net entity count change |
| `upstream_edge_delta` | int | Net edge count change |

---

### cruxible_world_pull_apply

Apply a previewed upstream release into a release-backed fork.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `expected_apply_digest` | string | **yes** | Digest from `cruxible_world_pull_preview` |

**Returns:** `WorldPullApplyResult`

| Field | Type | Description |
|-------|------|-------------|
| `release_id` | string | Applied release ID |
| `apply_digest` | string | Applied digest |
| `pre_pull_snapshot_id` | string | Snapshot ID before the pull |

---

## Inspection Tools

### cruxible_list

List entities, edges, receipts, feedback, or outcomes with optional filters.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `resource_type` | string | **yes** | `"entities"`, `"edges"`, `"receipts"`, `"feedback"`, or `"outcomes"` |
| `entity_type` | string | conditional | Required when `resource_type="entities"` |
| `relationship_type` | string | no | Filter edges by relationship type (only for `resource_type="edges"`) |
| `query_name` | string | no | Filter receipts by query name |
| `receipt_id` | string | no | Filter feedback/outcomes by receipt |
| `limit` | int | no | Maximum items (default: `50`) |
| `property_filter` | dict | no | Exact property matches, AND semantics (entities and edges only) |
| `operation_type` | string | no | Filter receipts by operation type (e.g., `"query"`, `"add_entity"`, `"ingest"`) |

**Returns:** `ListResult`

| Field | Type | Description |
|-------|------|-------------|
| `items` | list[dict] | Resource items |
| `total` | int | Total count |

**Edge items** (when `resource_type="edges"`):

| Field | Type | Description |
|-------|------|-------------|
| `from_type` | string | Source entity type |
| `from_id` | string | Source entity ID |
| `to_type` | string | Target entity type |
| `to_id` | string | Target entity ID |
| `relationship_type` | string | Relationship type |
| `edge_key` | int | Edge key for use with `cruxible_feedback` |
| `properties` | dict | [Edge properties](concepts.md#edge-properties) |

---

### cruxible_schema

Return the active config schema for an instance.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |

**Returns:** Full config schema dict including entity types, relationships, queries, and constraints.

---

### cruxible_sample

Return a sample of entities for quick data inspection.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `entity_type` | string | **yes** | Entity type to sample |
| `limit` | int | no | Max entities (default: `5`) |

**Returns:** `SampleResult`

| Field | Type | Description |
|-------|------|-------------|
| `entities` | list[dict] | Sampled entity records |
| `entity_type` | string | Entity type sampled |
| `count` | int | Number returned |

---

### cruxible_evaluate

Run graph quality checks: orphan entities, coverage gaps, and constraint violations.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `confidence_threshold` | float | no | Threshold for flagging low-confidence edges (default: `0.5`) |
| `max_findings` | int | no | Maximum findings to return (default: `100`) |
| `exclude_orphan_types` | list[string] | no | Entity types to skip in orphan checks (for reference/taxonomy types) |

**Returns:** `EvaluateResult`

| Field | Type | Description |
|-------|------|-------------|
| `entity_count` | int | Total entities in graph |
| `edge_count` | int | Total edges in graph |
| `findings` | list[dict] | Quality findings (orphans, gaps, violations) |
| `summary` | dict | Counts by finding category |
| `constraint_summary` | dict | Counts by constraint name |
| `quality_summary` | dict | Counts by quality check |

---

### cruxible_get_entity

Look up a specific entity by type and ID.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `entity_type` | string | **yes** | Entity type |
| `entity_id` | string | **yes** | Entity ID |

**Returns:** `GetEntityResult`

| Field | Type | Description |
|-------|------|-------------|
| `found` | bool | Whether the entity exists |
| `entity_type` | string | Entity type |
| `entity_id` | string | Entity ID |
| `properties` | dict | Entity properties |

---

### cruxible_get_relationship

Look up a specific relationship by its endpoints and type.

**Permission:** READ_ONLY

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `from_type` | string | **yes** | Source entity type |
| `from_id` | string | **yes** | Source entity ID |
| `relationship_type` | string | **yes** | Relationship type |
| `to_type` | string | **yes** | Target entity type |
| `to_id` | string | **yes** | Target entity ID |
| `edge_key` | int | no | Edge key for multi-edge disambiguation |

Pass `edge_key` when multiple same-type edges exist between the same endpoints. Without it, an error is raised if ambiguous.

**Returns:** `GetRelationshipResult`

| Field | Type | Description |
|-------|------|-------------|
| `found` | bool | Whether the relationship exists |
| `from_type` | string | Source entity type |
| `from_id` | string | Source entity ID |
| `relationship_type` | string | Relationship type |
| `to_type` | string | Target entity type |
| `to_id` | string | Target entity ID |
| `edge_key` | int or null | Edge key |
| `properties` | dict | [Edge properties](concepts.md#edge-properties) |

---

## Mutation Tools

### cruxible_add_entity

Add or update entities in the graph (upsert).

**Permission:** GRAPH_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `entities` | list[EntityInput] | **yes** | Entities to add/update |

Each `EntityInput`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_type` | string | **yes** | Entity type name |
| `entity_id` | string | **yes** | Entity ID |
| `properties` | dict | no | Entity properties (default: `{}`) |

Re-submitting an existing entity replaces all its properties (full overwrite, not merge).

**Returns:** `AddEntityResult`

| Field | Type | Description |
|-------|------|-------------|
| `entities_added` | int | New entities created |
| `entities_updated` | int | Existing entities updated |
| `receipt_id` | string or null | Mutation receipt ID |

---

### cruxible_add_relationship

Add or update relationships in the graph (upsert).

**Permission:** GRAPH_WRITE

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `relationships` | list[RelationshipInput] | **yes** | Relationships to add/update |

Each `RelationshipInput`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `from_type` | string | **yes** | Source entity type |
| `from_id` | string | **yes** | Source entity ID |
| `relationship` | string | **yes** | Relationship type name |
| `to_type` | string | **yes** | Target entity type |
| `to_id` | string | **yes** | Target entity ID |
| `properties` | dict | no | [Edge properties](concepts.md#edge-properties) (default: `{}`) |

Entities must already exist. Re-submitting an existing edge replaces its properties. Include `source`, `confidence`, and `evidence` in properties for provenance tracking.

**Returns:** `AddRelationshipResult`

| Field | Type | Description |
|-------|------|-------------|
| `added` | int | New relationships created |
| `updated` | int | Existing relationships updated |
| `receipt_id` | string or null | Mutation receipt ID |

---

### cruxible_add_constraint

Add a constraint rule to the config and write it back to YAML.

**Permission:** ADMIN

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `instance_id` | string | **yes** | Instance ID |
| `name` | string | **yes** | Unique constraint name |
| `rule` | string | **yes** | Rule expression (see [Config Reference](config-reference.md#rule-syntax)) |
| `severity` | string | no | `"warning"` (default) or `"error"` |
| `description` | string | no | Human-readable description |

**Returns:** `AddConstraintResult`

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Constraint name |
| `added` | bool | Whether the constraint was added |
| `config_updated` | bool | Whether the YAML file was updated |
| `warnings` | list[string] | Warnings (e.g., unknown property names) |
