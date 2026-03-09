"""MCP prompt registrations.

Provides workflow templates that AI agents can request
to guide common tasks like onboarding a new domain or
reviewing graph quality.

Prompt functions are module-level so they can be called both
by the MCP prompt protocol (user slash commands) and by the
``cruxible_prompt`` tool (agent-initiated).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Prompt content functions
# ---------------------------------------------------------------------------


def _prepare_data(data_description: str) -> str:
    return f"""\
You are preparing data for ingestion into Cruxible.
Cruxible ingests and evaluates; cleaning and transforms are external.
This prompt covers data cleaning only — profiling, deduplication, key validation.
Cross-dataset matching (linking entities across different source files) happens
later via `find_candidates` in the onboard workflow.
Use your own tools (Python, Polars, etc.) to fix issues found below.

Data description: {data_description}

## Step 1 — Profile Each File
- Row count, column names, dtypes, null counts, sample rows

## Step 2 — Validate Entity Primary Keys
- Uniqueness (duplicates → dedup or wrong grain)
- Null/empty values (will fail ingestion)
- Whitespace, prefix chars, sentinels (`*`, `#`)

## Step 3 — Validate Relationship Foreign Keys
- Source/target ID columns exist
- FK values appear in referenced entity data (orphan FKs → broken edges)
- Duplicate (from, to, relationship_type) triples in batch

## Step 4 — Check Join Keys Across Files
- Key columns present in both files
- Value overlap (zero overlap = wrong join key)
- Type consistency (string vs int)

## Step 5 — Identify Junk Rows
- Sentinel categories (`#Dropbox`, `Discontinued`, `N/A`)
- Test/placeholder rows, all-null property rows

## Step 6 — Check Cardinality
- One-row-per-entity or one-row-per-relationship?
- Rows duplicated across a secondary dimension → dedup

## Step 7 — Verify Text Fields
- Embedded structured data (dates, IDs) to extract
- Encoding issues (mojibake, HTML entities)

## Step 8 — Validate Against Config (if applicable)
- Compare CSV columns to ingestion mapping fields
  (`id_column`, `from_column`, `to_column`, `column_map`)
- Flag mismatches before attempting ingest

## Step 9 — Report
Fix issues using external tools, then report:

- **readiness**: `ready` | `ready_with_warnings` | `blocked`
- **blocking_issues**: list of issues that prevent ingestion
- **warnings**: list of non-blocking concerns
- **cleaned_files**: paths to cleaned files for ingestion
"""


def _onboard_domain(domain: str) -> str:
    return f"""\
You are onboarding a new domain: {domain}

Follow this compact checklist.

## Step 1 — Discover the Domain

Before writing any config, understand the domain and the data.

- **Locate data files.** Ask the user for file paths if not already known.
  Open each file and inspect: schema, column names, dtypes, row counts,
  sample rows. Use your own tools (Python, Polars, file reading).
- **Understand the domain.** Combine what you see in the data with your
  general knowledge of {domain}. What are the core entities? What
  relationships connect them? What properties matter for decisions?
- **Identify entity types and relationships.** For each candidate entity
  type, note the likely primary key column and important properties. For
  each relationship, note which columns link source to target and whether
  the relationship is explicit in the data or must be inferred.
- **Brainstorm use cases.** What questions should this graph answer? What
  decisions does it support? Draft 2–4 candidate named queries in plain
  language.
- **Propose a domain model.** Present a structured summary for the user to
  confirm or adjust before proceeding:

  | Entity Type | Primary Key Column | Key Properties | Source File |
  |-------------|-------------------|----------------|-------------|
  | _(each)_    | _col_             | _prop1, prop2_ | _file.csv_  |

  | Relationship | From → To | How Populated | Notes |
  |--------------|-----------|---------------|-------|
  | _(each)_     | _Type → Type_ | _source data / find_candidates / inferred_ | |

  Candidate use cases:
  - _(plain-language question the graph should answer)_

Wait for user confirmation before proceeding. Adjustments here are cheap;
adjustments after ingestion are expensive.

## Step 2 — Prepare Data

Run the `prepare_data` prompt if you haven't already. Use the entity types
and relationships identified in Step 1 to focus cleaning on the columns and
join keys that matter.

## Step 3 — Write the YAML Config

Define the required sections:
- `entity_types`: Dict keyed by type name. Mark the ID property with `primary_key: true`.
  Example:
    entity_types:
      Vehicle:
        properties:
          vehicle_id: {{type: string, primary_key: true}}
          make: {{type: string}}
- `relationships`: from/to types and optional edge properties. Include cross-dataset
  relationship types (e.g. xref matches) — but do NOT create ingestion mappings for
  them. They will be populated through `cruxible_find_candidates` in Step 6.
- `named_queries`: leave this section empty for now. You'll design queries in Step 7
  after seeing what's actually in the graph.
- `constraints`: validation expressions with severity.
- `ingestion`: mappings for entity files and deterministic relationship files only.

Write `description` on every section — the config should be understandable
without external docs:
- Top-level `description`: the business problem this graph solves.
- Named query descriptions: the question in plain language
  (e.g. "Is this company connected to any sanctioned entity?").
- Ingestion mapping descriptions: what data the mapping expects
  (e.g. "CSV of SDN entities with sdn_id, name, country columns").

## Step 4 — Validate and Initialize

1. `cruxible_validate` config first.
2. `cruxible_init` only after validation passes.
3. Keep the returned `instance_id` for all later calls.

## Step 5 — Ingest Source Data

1. Ingest **entities** from cleaned data files.
2. Ingest **deterministic relationships** that exist explicitly in source data
   (e.g. known fitments, explicit FK mappings).
3. Stop and handle tool errors from MCP before continuing.

## Step 6 — Discover Cross-References

For entities from free text or external sources (no CSV available):
- Use `cruxible_add_entity` — entities must exist before adding relationships to them.

For each cross-dataset relationship type in your config, ask:
can `cruxible_find_candidates` with `property_match` express this match?

If yes, use it — candidates are reproducible, auditable, and iterative:
1. Use `cruxible_sample` to inspect entities on both sides.
2. Use `property_match` with `iequals` on name fields to cross-reference entities
   across types/datasets.
3. Use `shared_neighbors` when entities share connections through an intermediary.
4. Review candidates and persist confirmed matches with `cruxible_add_relationship`
   — include `source`, `confidence`, and `evidence` in properties for provenance.

**Confidence guidelines** — always set `confidence` on every edge you add:

| Score     | Meaning                                                      |
|-----------|--------------------------------------------------------------|
| ≥ 0.9     | Unambiguous match — no plausible alternatives exist          |
| 0.7 – 0.9 | Inspected and reasonable, but alternatives exist             |
| 0.5 – 0.7 | Ambiguous — decent guess, other candidates similarly plausible |
| < 0.5     | Speculative — likely needs human review before trusting      |

Be honest with yourself — if multiple candidates could fit, that is not 0.9.
Edges below 0.7 will be surfaced for review by `cruxible_evaluate`.

`cruxible_find_candidates` only does exact/iequals matching. If the domain needs
fuzzy matching, transliteration, abbreviation handling, or other logic it can't
express — use your own approach. Write and run custom scripts (Python, Polars,
etc.) for bulk comparison, or manually inspect entities and use your judgment.
Regardless of method, persist matches with `cruxible_add_relationship` and include
`source`, `confidence`, and `evidence` in properties for provenance.

## Step 7 — Design Named Queries

Now that you can see what entities and relationships are in the graph, design
the named queries. Start from the use cases proposed in Step 1.

If the user specified queries or clear use cases in their request, use those.
If the requirements are underspecified, ask what decisions or lookups the graph
should support — suggest 2–3 based on the data shape and let the user refine.
Don't proceed with guessed queries.

Key considerations:
- **Entry point**: which entity type does the user start from? Queries should
  start from the entity being looked up, not the answer entity.
- **Traversal direction**: outgoing follows ownership chains; incoming finds
  who owns/controls the entry entity.
- **Multi-relationship fan-out**: a single step can traverse multiple
  relationship types (e.g. `[owns, directs]`) for comprehensive views.

Add the named queries to the YAML config, re-validate with `cruxible_validate`,
and reload with `cruxible_init(root_dir=...)` (omit `config_path` to reload).

## Step 8 — Validate Graph Quality

`cruxible_evaluate` checks structural health — orphans, violations, coverage
gaps. It cannot detect cross-dataset mismatches (e.g., a drug with interactions
but no enzyme pathway, or an entity with edges from one source but missing from
another). Run `review_graph` to discover these gaps through sampling and the
intelligence pass.

Run `cruxible_prompt("review_graph", {{"instance_id": "<instance_id>"}})` now.
Do not skip this step even if evaluate is clean.

## Step 9 — Run Sample Queries

1. Run `cruxible_query` on representative cases. The `params` dict must
   include the primary-key property of the entry_point entity type
   (the property marked `primary_key: true` in the config).
2. Inspect receipt traversal and filters.
3. Confirm output matches domain expectations.

## Step 10 — Provide Feedback

1. Use `cruxible_feedback` on key edges (pass `source="ai_review"` when you
   are the reviewer, `source="human"` when relaying a human's judgment).
2. Record end-to-end correctness with `cruxible_outcome`.
3. Use `cruxible_find_candidates` to discover missing links.
4. Use `cruxible_add_relationship` to persist confirmed candidates.

## Step 11 — Handoff

Present what was built so the user knows what they have and how to use it.

### Graph Summary

| Entity Type | Count | Source |
|-------------|-------|--------|
| _(each type)_ | _N_ | _(file or method that produced it)_ |

| Relationship | Count | How Added |
|--------------|-------|-----------|
| _(each type)_ | _N_ | _source data / find_candidates / AI-inferred_ |

### Named Queries

For each query, provide:
- Plain-language description of what it answers
- Example `params` dict the user can copy-paste
- Example finding from the test run (if available)

### What You Can Do Next

- **Query**: ask any of the named queries listed above
- **Audit**: ask to see how any result was determined
- **Review edges**: ask to review the graph's connections — especially
  low-confidence and AI-inferred ones. Your feedback compounds: approved
  edges are trusted in future queries, corrections persist, and rejection
  patterns can become automatic rules.
- **Discover**: ask to search for missing connections across datasets
- **Health check**: ask to evaluate overall graph quality
- **Add rules**: ask to add constraints that flag bad data automatically
"""


def _review_graph(instance_id: str) -> str:
    return f"""\
You are reviewing the quality of cruxible graph instance: {instance_id}

Use this loop to assess and improve quality.

## Step 1 — Run Evaluation

Run `cruxible_evaluate` for `{instance_id}` (use `exclude_orphan_types` for
reference/taxonomy types that are expected to be unconnected).

## Step 2 — Prioritize Findings

Work through findings by priority:

1. **Constraint violations**: data in the graph that breaks rules — fix source
   data, mappings, or remove bad edges.
2. **Low confidence edges**: proposed matches needing review. Review these
   autonomously with `source="ai_review"`. Prefer `correct` (adjust
   confidence or evidence) over `reject` — an edge with adjusted confidence
   is more valuable than a deleted edge. Use these confidence guidelines
   when correcting:
   - **≥ 0.9**: Unambiguous — no plausible alternatives
   - **0.7 – 0.9**: Reasonable but alternatives exist
   - **0.5 – 0.7**: Ambiguous — decent guess, flag for review
   - **< 0.5**: Speculative — needs human review
   If you find a recurring pattern (e.g. several rejections share a property
   mismatch) or an ambiguous edge you can't resolve confidently, escalate to
   the user — show the edge with entity details from both sides and let them
   decide (`source="human"`).
   `cruxible_feedback` requires a `receipt_id` — use one from a previous
   `cruxible_query` run. If no receipts exist yet, run any named query to
   generate one. If the config has no named queries, ask the user to add
   one or complete the onboard workflow first — feedback is anchored to
   query receipts for auditability.
3. **Unreviewed co-members**: entities sharing an intermediary with a
   cross-referenced entity but not yet linked — run `cruxible_find_candidates`
   on flagged entities with looser matching to find near-misses.
4. **Coverage gaps**: entity/relationship types in config but absent from graph
   — check missing source data vs. restrictive mapping rules.
5. **Orphan entities**: some orphans are expected (reference data, incomplete
   samples). If orphan count is >100 or >10% for a cross-referenced entity
   type, investigate at least 5 examples in Step 4.

## Step 3 — Review Feedback History

Use `cruxible_list(instance_id, resource_type="feedback")` to find repeated
reject/flag patterns. If 3+ rejections share a property mismatch (e.g., all
rejected edges have mismatched country values), encode it as a constraint via
`cruxible_add_constraint` so future evaluations flag the pattern automatically.

## Step 4 — Discover Missing Relationships

If you approved or rejected edges in Step 2, start by learning from them — what
distinguished real matches from false positives? (e.g., matching countries
corroborated real matches, common names without corroborating properties were
false positives). Use those patterns to guide which properties to match on below.
If no feedback exists yet, skip directly to the strategies.

For each cross-reference relationship type, work through these strategies:

1. **Sample orphans.** Use `cruxible_sample` on entity types with high orphan
   counts. Look at their names and properties — do they look like they should
   match something? Orphans are your primary lead for missing edges.

2. **Direct property matching.** Run `cruxible_find_candidates` with
   `property_match`. Start with `iequals` on name fields (skip if the onboard
   pass already ran this). Then try matching on other properties that
   corroborated real matches — e.g., adding `country` or `jurisdiction` as
   additional `match_rules` to find matches the name-only pass missed.

3. **Transitive discovery.** Think about the graph topology — which intermediate
   entities could connect orphans to known matches? For example, if officers
   bridge companies to sanctioned entities, and you found new officer matches,
   trace their company connections to find indirectly exposed entities. Use
   `shared_neighbors` or manual traversal as appropriate.

4. **Investigate specific orphans.** Pick 3–5 orphans that look like they should
   be connected (recognizable names, high-risk jurisdictions, properties that
   overlap with matched entities). Use `cruxible_get_entity` to inspect them,
   then run targeted `cruxible_find_candidates` to search for their matches.

5. **Intelligence pass.** `cruxible_find_candidates` only does exact/iequals
   matching — it will miss abbreviations, transliterations, aliases, partial
   names, and domain-specific patterns. After exhausting it, use your own
   judgment: sample entities from both sides, read their properties, and look
   for matches that mechanical rules can't express. You can also write and run
   custom scripts (Python, Polars, etc.) for fuzzy matching, normalization, or
   bulk comparison. This is where you add the most value.

When a strategy hits a pair limit or returns zero results, note why and move to
the next one. Don't stop after one failure.

Regardless of method, persist matches with `cruxible_add_relationship` and
include `source`, `confidence`, and `evidence` in properties for provenance.

## Step 5 — Iterate

After each discovery batch:

1. Re-run `cruxible_evaluate` and compare to the previous run.
2. Count new edges added this iteration. If zero after working through
   all strategies in Step 4, you've plateaued — stop.
3. If edges were added, go back to Step 1 — new edges may create new
   `shared_neighbors` opportunities or change orphan counts.
4. For categories that didn't improve, sample findings and inspect with
   `cruxible_get_entity` / `cruxible_get_relationship`. Common patterns:
   name variations (honorifics, transliterations), property mismatches,
   entity types that never connect. Adjust matching rules accordingly.
"""


def _analyze_feedback(instance_id: str, relationship_type: str) -> str:
    return f"""\
Review recent feedback for '{relationship_type}' edges in \
instance '{instance_id}'.

## Steps

1. Call cruxible_list with resource_type="feedback" to get recent feedback \
records.
   NOTE: cruxible_list returns ALL feedback (approve, reject, correct, \
flag) with no
   action or relationship filter. You must filter client-side:
   - Keep only records where action == "reject"
   - Keep only records where target.relationship == "{relationship_type}"
2. For each rejected edge:
   - Use cruxible_get_relationship (pass from_type, from_id, \
relationship_type,
     to_type, to_id, and edge_key if present in the feedback target) to \
see the edge
     properties (confidence, source, review_status).
   - Use cruxible_get_entity to look up source and target entity properties.
   Feedback records only contain entity IDs — you need to cross-reference.
3. Compare the properties of rejected edges: look for shared property \
mismatches
   (e.g. "most rejected edges have different Category values on source vs \
target")
   and shared edge property patterns (e.g. "all rejected edges had \
source=property_match").
4. For each pattern you find:
   - Count how many rejections share this pattern
   - Check if a constraint already exists for it (call cruxible_schema)
   - Only propose a constraint if it checks a **different property** than \
the one
     used to create the edge. If edges were created by matching on a \
property via
     `find_candidates`, adding a constraint on that same property is \
redundant —
     alter the matching rule instead.
   - The pattern should be strong (5+ rejections)
5. For each proposed constraint:
   - Use the rule format: RELATIONSHIP.FROM.property == \
RELATIONSHIP.TO.property
   - Call cruxible_add_constraint to add it
   - Use severity "warning" unless the rejection rate is very high (>80%), \
then "error"
6. After adding constraints, call cruxible_evaluate to verify the new \
constraints
   flag the expected edges.

Keep it focused: only propose constraints backed by concrete rejection data.
"""


def _user_review(instance_id: str) -> str:
    return f"""\
You are running a collaborative edge review session for instance: {instance_id}

The user wants to review and provide feedback on edges in the graph. Their
feedback compounds: approved edges are trusted, corrections persist adjusted
properties, and rejection patterns can become constraints.

## Step 1 — Identify Review Candidates

Find edges worth reviewing:

1. `cruxible_schema(instance_id="{instance_id}")` — identify cross-reference
   relationship types. These are the most likely to have AI-inferred edges.
2. For each cross-reference relationship type, use
   `cruxible_list(instance_id="{instance_id}", resource_type="edges",
   relationship_type="<type>")` to enumerate edges. Filter for edges where
   `properties.source` indicates non-deterministic origin ("property_match",
   "ai_inferred", "clinical_literature", or similar).
3. `cruxible_list(instance_id="{instance_id}", resource_type="feedback")` —
   see what's already been reviewed so you can skip those edges.

Prioritize for review:
- Low-confidence edges (confidence < 0.7) that haven't been reviewed
- AI-inferred edges without human feedback
- Edges flagged as `pending_review` (review_status property)

## Step 2 — Present Edges for Review

For each edge, show the user:
- Both entities with their key properties (use `cruxible_get_entity` with
  the `entity_type` and `entity_id` from the edge listing)
- The edge properties (confidence, source, evidence)
- Why this edge exists (how it was created)
- What impact it has (which queries use this relationship type)

Then ask the user to choose one of four actions:

- **approve** — "this is correct, trust it"
- **correct** — "this is close but needs adjustment" (user provides updated
  properties like confidence, evidence, or other fields via `corrections` dict)
- **flag** — "I'm not sure, come back to this later" (sets `pending_review`)
- **reject** — "this is wrong, exclude from results"

Record each decision with `cruxible_feedback` using `source="human"`. You
need a `receipt_id` — use one from a previous `cruxible_query` run, or run
any named query to generate a fresh one. If the config has no named queries,
add one first — feedback is anchored to query receipts for auditability, and
a graph without queries isn't ready for review. The receipt doesn't need to
traverse the specific edge being reviewed. Pass the `edge_key` from the edge
listing to avoid ambiguity errors on multi-edge pairs.

## Step 3 — Batch and Confirm

After each batch of ~5 edges:
- Summarize what was approved, corrected, flagged, and rejected
- Ask if the user wants to continue or stop
- If 3+ rejections share a pattern, suggest encoding it as a constraint
  via `cruxible_add_constraint`

## Step 4 — Summary

When the session ends, report:
- Total edges reviewed and breakdown by action
- Any constraints added from rejection patterns
- Suggested next steps in user-facing language — e.g., "ask to review more
  edges", "ask to run a health check", "try querying [drug] to see how your
  feedback changed the results." Never surface tool names to the user.
"""


def _common_workflows() -> str:
    return """\
Common cruxible tool sequences.

## Debugging a Query

1. `cruxible_schema` to verify query/traversal definitions.
2. `cruxible_sample` to confirm source entities are present.
3. `cruxible_query` with focused params.
4. `cruxible_receipt` for traversal trace.
5. Fix config or ingest, then repeat.

## Edge-Level Review

1. `cruxible_query` to get `receipt_id`.
2. `cruxible_feedback` action=`approve|reject|flag|correct`,
   `source="ai_review"` (when you are the reviewer).
3. Re-run query to confirm behavior changes.

## Iterative Graph Refinement

1. `cruxible_evaluate` for current findings.
2. `cruxible_find_candidates` for likely missing edges.
3. `cruxible_add_relationship` to persist confirmed candidates.
4. Re-run evaluate and compare counts.

## Auditing a Decision

1. `cruxible_list(instance_id, resource_type="receipts")` to locate the run.
2. `cruxible_receipt` for traversal evidence.
3. `cruxible_list(instance_id, resource_type="feedback", receipt_id=...)`.
4. `cruxible_list(instance_id, resource_type="outcomes", receipt_id=...)`.

## Data Readiness

1. Run `prepare_data` prompt with file descriptions.
2. Fix blocking issues using external tools.
3. Re-run until readiness is `ready` or `ready_with_warnings`.
4. Proceed to `onboard_domain` or `cruxible_ingest`.
"""


# ---------------------------------------------------------------------------
# Registry: name → (function, description)
# ---------------------------------------------------------------------------

PROMPT_REGISTRY: dict[str, tuple[Callable[..., str], str]] = {
    "prepare_data": (
        _prepare_data,
        "Checklist for profiling and cleaning data files before ingestion.",
    ),
    "onboard_domain": (
        _onboard_domain,
        "Step-by-step guide for going from raw data files to a working graph.",
    ),
    "review_graph": (
        _review_graph,
        "Guide for reviewing and improving an existing graph's quality.",
    ),
    "analyze_feedback": (
        _analyze_feedback,
        "Analyze recent feedback to discover patterns worth encoding as constraints.",
    ),
    "user_review": (
        _user_review,
        "Collaborative session for reviewing and providing feedback on graph edges.",
    ),
    "common_workflows": (
        _common_workflows,
        "Common multi-tool sequences for debugging, review, refinement, and auditing.",
    ),
}


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------


def register_prompts(server: FastMCP) -> None:
    """Register all cruxible prompts on the FastMCP server.

    Prompts are also accessible programmatically via :data:`PROMPT_REGISTRY`
    (used by the ``cruxible_prompt`` tool).
    """
    for name, (fn, desc) in PROMPT_REGISTRY.items():
        server.prompt(name=name, description=desc)(fn)
