---
name: kev-triage
description: Run the KEV fork's daily triage loop, incident attribution, waiver intake, and control-effectiveness proposals against a KEV triage instance using governed proposal flows.
---

# KEV Security Triage

Agent skill for operating on a KEV triage world instance. Read this before
taking any action against the graph.

## What this skill does

This skill covers four agent tasks against a KEV triage instance:

1. **Incident attribution** — fold a post-mortem or incident report into the
   graph as `Incident` + `Finding` entities and governed relationships.
2. **Exception / waiver intake** — propose a patch exception when a team has a
   legitimate reason to delay remediation.
3. **Control effectiveness review** — propose that a compensating control
   materially reduces exposure to a specific CVE class.
4. **Daily triage pass** — refresh the reference layer, run the proposal
   chain, and produce an actionable summary enriched with incident history.

All four routes share one rule: **the agent proposes, a reviewer resolves.**
Nothing gets written to the graph as an accepted edge without going through
`group propose` → reviewer → `group resolve`. The reviewer may be a human or
another agent operating in review mode; the recorded attribution comes from the
`group resolve --source ...` value.

## Orient before acting

Every session, before making proposals:

1. `cruxible context show` — confirm which instance you're connected to.
2. `cruxible query list --json` — confirm the named queries used in the daily
   pass are present. Use `cruxible query describe --query <name> --json` to
   inspect required params and example IDs for the specific read surfaces you
   plan to call.
3. `cruxible schema --json` — confirm the schema includes the fork types and
   surfaces this skill expects: `Incident`, `Finding`, the governed
   relationships listed below, and the `incident_attribution` /
   `policy_review` / `control_effectiveness` integrations. If they don't
   match, stop and ask.
4. `cruxible stats` — note the current entity and edge counts so you can
   detect accidental drift later.
5. `cruxible group list --status pending_review --json` — check what's already
   awaiting review. Don't re-propose something already in the queue.

If the reviewer is about to act on proposals you make, also run:

```
cruxible query --query owner_patch_queue --param owner_id=<owner>
cruxible query --query service_blast_radius --param cve_id=<cve_id>
```

so the proposals land in context.

## Agent-mode constraints

This instance must run under `CRUXIBLE_AGENT_MODE=1`. In that mode:

- `cruxible add-relationship` is **blocked**. Agents cannot write accepted
  edges directly — only `group propose`.
- `cruxible ingest` is **blocked**. Bulk CSV import is an operator action,
  not an agent action.
- `cruxible add-entity` is allowed. Creating `Incident` / `Finding` /
  `Exception` / `CompensatingControl` records is expected agent work.

If a command fails with `PermissionDeniedError: ... disabled in agent mode`,
do not retry or try to bypass. Surface the error to the user and stop.

## Task 1 — Incident attribution

**When:** an incident report, post-mortem, or SIEM investigation references a
vulnerability and asset(s) that are already tracked.

**Inputs you need from the report:**
- Incident ID, title, severity, status, occurred_at, resolved_at (if known),
  source system, free-text summary
- The asset(s) involved — match to existing `Asset` entity IDs
- The vulnerability exploited — match to existing `Vulnerability` entity IDs
- The owner accountable — match to existing `Owner` entity IDs
- Zero or more findings (root causes)

**Steps:**

1. Create the `Incident` entity:
   ```
   cruxible add-entity --type Incident --id INC-2025-003 \
     --props '{"incident_id":"INC-2025-003","title":"WebLogic admin console RCE",
               "severity":"critical","status":"investigating",
               "occurred_at":"2025-11-08","source":"siem",
               "summary":"Attacker reached the WebLogic admin console on partner-api-01..."}'
   ```

2. Propose `incident_owned_by`:
   ```
   cruxible group propose \
     --relationship incident_owned_by \
     --members '[{"from_type":"Incident","from_id":"INC-2025-003",
                   "to_type":"Owner","to_id":"OWNER-3",
                   "relationship_type":"incident_owned_by",
                   "signals":[{"integration":"incident_attribution",
                                "signal":"support",
                                "evidence":"Report names Partner Integrations team as responders"}]}]' \
     --thesis "Partner Integrations team (OWNER-3) ran the response for INC-2025-003 per the on-call log" \
     --thesis-facts '{"incident_id":"INC-2025-003","owner_id":"OWNER-3"}' \
     --integration incident_attribution
   ```

3. Propose `incident_involved_asset` (one member per asset):
   ```
   cruxible group propose \
     --relationship incident_involved_asset \
     --members '[{"from_type":"Incident","from_id":"INC-2025-003",
                   "to_type":"Asset","to_id":"ASSET-8",
                   "relationship_type":"incident_involved_asset",
                   "properties":{"role":"target"},
                   "signals":[{"integration":"incident_attribution","signal":"support",
                                "evidence":"SIEM shows anomalous admin console access from ..."}]}]' \
     --thesis "partner-api-01 (ASSET-8) was the target host for INC-2025-003" \
     --thesis-facts '{"incident_id":"INC-2025-003","asset_id":"ASSET-8"}' \
     --integration incident_attribution
   ```

4. Propose `incident_exploited_vulnerability`:
   ```
   cruxible group propose \
     --relationship incident_exploited_vulnerability \
     --members '[{"from_type":"Incident","from_id":"INC-2025-003",
                   "to_type":"Vulnerability","to_id":"CVE-2020-14882",
                   "relationship_type":"incident_exploited_vulnerability",
                   "signals":[{"integration":"incident_attribution","signal":"support",
                                "evidence":"Exploit payload matches CVE-2020-14882 signature"}]}]' \
     --thesis "Attacker used CVE-2020-14882 admin console bypass to reach RCE on partner-api-01" \
     --thesis-facts '{"incident_id":"INC-2025-003","cve_id":"CVE-2020-14882"}' \
     --integration incident_attribution
   ```

5. Create `Finding` entities for each root cause identified in the
   post-mortem, then propose `finding_from_incident` linking them back.

**Thesis quality.** Every proposal must include a thesis that names the
evidence — the specific report line, SIEM rule, or interview note. Reviewers
use the thesis to decide; a thesis that just restates the relationship ("this
incident involved this asset") is not useful.

**One member per proposal group is fine.** The grouping matters when a single
judgment covers multiple edges (e.g., "this incident touched these five
assets"). Otherwise, a group with one member is correct and easier to review.

## Task 2 — Exception / waiver intake

**When:** a team requests a patch exception for a specific CVE on a specific
asset, with an approver, rationale, and review date.

**Steps:**

1. Create or update the `Exception` entity:
   ```
   cruxible add-entity --type Exception --id EXC-2026-001 \
     --props '{"exception_id":"EXC-2026-001",
               "reason":"Billing core freeze for Q1 close; patch window reopens 2026-04-15",
               "status":"approved","review_due_at":"2026-04-15"}'
   ```

2. Propose `asset_patch_exception_for` linking the asset to the CVE being
   waived, with `exception_id` in edge properties:
   ```
   cruxible group propose \
     --relationship asset_patch_exception_for \
     --members '[{"from_type":"Asset","from_id":"ASSET-5",
                   "to_type":"Vulnerability","to_id":"CVE-2024-38475",
                   "relationship_type":"asset_patch_exception_for",
                   "properties":{"exception_id":"EXC-2026-001"},
                   "signals":[{"integration":"policy_review","signal":"support",
                                "evidence":"Approved by CFO per change ticket CHG-40123"}]}]' \
     --thesis "Billing asset ASSET-5 has an approved Q1 freeze for CVE-2024-38475; review 2026-04-15" \
     --thesis-facts '{"exception_id":"EXC-2026-001","cve_id":"CVE-2024-38475"}' \
     --integration policy_review
   ```

The deterministic `asset_has_exception` edge is loaded from seed data or
added separately by an operator. The *governed* part is the judgment that a
specific CVE is covered by the exception.

## Task 3 — Control effectiveness review

**When:** a compensating control is already tracked (`CompensatingControl`
entity + `asset_has_control` edges from seed), and there is evidence that it
materially blocks a specific CVE class.

**Steps:**

1. Confirm the control exists:
   ```
   cruxible get-entity --type CompensatingControl --id CTRL-1
   ```

2. Propose `control_reduces_exposure_to` for the CVE the control mitigates:
   ```
   cruxible group propose \
     --relationship control_reduces_exposure_to \
     --members '[{"from_type":"CompensatingControl","from_id":"CTRL-1",
                   "to_type":"Vulnerability","to_id":"CVE-2021-41773",
                   "relationship_type":"control_reduces_exposure_to",
                   "signals":[{"integration":"control_effectiveness","signal":"support",
                                "evidence":"WAF rule set 941xx blocks path traversal payloads; tested 2025-10-15"}]}]' \
     --thesis "Edge WAF ruleset 941xx blocks exploit strings for CVE-2021-41773 path traversal" \
     --thesis-facts '{"control_id":"CTRL-1","cve_id":"CVE-2021-41773"}' \
     --integration control_effectiveness
   ```

## Task 4 — Daily triage pass

Runs on a cadence (typically daily). The agent's job is to produce a
human-actionable summary. It may safely refresh the KEV reference layer, but it
does not approve or resolve governed proposals directly.

**Steps:**

1. Refresh the reference layer:
   ```
   cruxible world status
   cruxible world pull-preview
   cruxible world pull-apply --apply-digest <digest>
   ```
   Use `world pull-*` when the fork tracks a published upstream KEV reference.
   KEV reference releases are data-safe/additive, so the agent may pull them
   directly. If this instance is a local demo root that does not track an
   upstream release, refresh the composed reference workflow instead:
   ```
   cruxible run --workflow build_public_kev_reference --apply
   ```

2. Run the fork proposal chain:
   ```
   cruxible propose --workflow propose_asset_products
   cruxible propose --workflow propose_asset_affected
   cruxible propose --workflow propose_asset_exposure
   cruxible propose --workflow propose_service_impact
   ```
   Each produces governed groups that enter the review queue.

3. For each new `asset_exposed_to_vulnerability` candidate, query prior
   exploitation context:
   ```
   cruxible query --query incident_history_for_product --param product_id=<product>
   cruxible query --query open_findings_for_asset --param asset_id=<asset>
   cruxible query --query prior_exploitation_context --param cve_id=<cve>
   ```

4. Produce a summary that distinguishes:
   - **Elevated priority**: exposures on products with prior exploitation
     history, or assets with open findings that match the new CVE class.
   - **Standard priority**: exposures with no prior history.
   - **Overdue**: exposures past `kev_due_date` with no exception on file.
   - **Waived**: exposures covered by an active exception.

5. Unless you are explicitly operating in reviewer mode, do not resolve the
   groups you just created. Hand the summary to the next reviewer step
   (human, ticket queue, or agent reviewer).

**Idempotence.** If the same proposal chain ran yesterday, today's run
produces the same groups. The group store deduplicates by signature. Safe to
re-run.

## Review feedback loop

After a reviewer resolves a group (`cruxible group resolve --group <id>
--action approve|reject --source human|ai_review`), the system records a
resolution. From there,
reviewers have two different follow-up tools:

- **Resolution trust** — if the reviewer wants to reopen doubt about a
  resolution, use:
  `cruxible group trust --resolution <resolution_id> --status watch|invalidated --reason "..."`
- **Receipt outcomes** — if later operational evidence shows a prior decision
  surface was right or wrong, record an anchored outcome on the relevant
  receipt:
  `cruxible outcome --receipt <receipt_id> --outcome correct|incorrect|partial|unknown --detail '{"reason":"..."}'`

Agents do not drive this loop — but should be aware that:

- Rejected proposals are signal that the thesis or evidence was insufficient.
  Before re-proposing a rejected relationship, read the resolution rationale
  (`cruxible group get --group <id>`) and adjust.
- `watch` or `invalidated` trust on a resolution means the reviewer wants a
  second look. Treat those as "unconfirmed" when summarizing.

## Common queries for context

| When you need... | Run |
|---|---|
| Everything affected by a CVE | `query --query kev_assets --param cve_id=<cve>` |
| Patch queue for an owner | `query --query owner_patch_queue --param owner_id=<owner>` |
| Services hit by a CVE | `query --query service_blast_radius --param cve_id=<cve>` |
| Has this product ever been exploited? | `query --query incident_history_for_product --param product_id=<product>` |
| What open findings for this asset? | `query --query open_findings_for_asset --param asset_id=<asset>` |
| Prior post-mortem for this CVE | `query --query prior_exploitation_context --param cve_id=<cve>` |
| All exceptions on an asset | `query --query asset_exception_context --param asset_id=<asset>` |
| All controls on an asset | `query --query asset_control_context --param asset_id=<asset>` |

## When to stop and ask

Stop and ask the user (don't guess) when:

- An incident report names an asset, owner, vulnerability, or product that
  does not resolve to an existing entity ID. Proposing against a wrong ID
  corrupts the graph.
- A proposal would create a relationship type not listed in the fork's
  governed relationships. The schema is authoritative.
- Review material conflicts with graph state (e.g., the report says an
  exception exists but no `Exception` entity is found).
- You hit `PermissionDeniedError` in agent mode. Retrying won't help.
- A workflow `propose` produces no reviewable group when you expected one.
  Either the upstream layer didn't populate, prerequisite approved edges are
  missing, or the matching config rejected everything — either way, surface it.

## Troubleshooting

| Symptom | Check |
|---|---|
| `cruxible group propose` rejects with "integration not declared" | The `--integration` name must match the fork's `integrations` config. Use `cruxible schema --json` and inspect the `integrations` section. |
| `cruxible run` fails with "Artifact ... sha256 mismatch" | A seed file was edited without re-pinning. Operator needs to run `cruxible lock --force`. Do not retry as agent. |
| Query returns empty when you expected results | Likely the proposal chain ran but nothing has been approved yet. `group list --status pending_review` will show the backlog. |
| `add-entity` says "entity updated" when you expected "added" | ID collision — the entity already exists. Fetch it (`get-entity`) and decide whether to continue. |
| Thesis is accepted but proposal still blocks | `group propose` enforces integration signals. A proposal with no `signals` array and no `--integration` flag will be rejected. |

## Relationship reference (fork-governed)

Every governed relationship the agent can propose:

| Relationship | From → To | Required integration |
|---|---|---|
| `asset_runs_product` | Asset → Product | `software_product_match` |
| `asset_affected_by_vulnerability` | Asset → Vulnerability | `product_version_evidence` |
| `asset_exposed_to_vulnerability` | Asset → Vulnerability | `exploitability_signal` + `control_effectiveness` |
| `service_impacted_by_vulnerability` | BusinessService → Vulnerability | `dependency_context` |
| `asset_patch_exception_for` | Asset → Vulnerability | `policy_review` |
| `control_reduces_exposure_to` | CompensatingControl → Vulnerability | `control_effectiveness` |
| `incident_owned_by` | Incident → Owner | `incident_attribution` |
| `incident_involved_asset` | Incident → Asset | `incident_attribution` |
| `incident_exploited_vulnerability` | Incident → Vulnerability | `incident_attribution` |
| `finding_from_incident` | Finding → Incident | `incident_attribution` |

The first four are typically produced by batch workflows (`propose_*`). The
last six are typically produced by one-off agent proposals from review
material.
