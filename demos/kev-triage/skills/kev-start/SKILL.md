---
name: kev-start
description: Adapt the KEV triage kit to your own asset, inventory, and service-mapping data. Build the reference and fork layers, run the proposal chain, and verify that your data participates in the governed loop cleanly.
---

# KEV Start

Use this skill when a developer is adapting the KEV kit to their own data.
The goal is to build a working KEV-shaped world on their inventory: reference
layer loaded, fork layer built from their assets/owners/software/services,
proposal chain run, and governed outputs visible in queries and the wiki.

## Goal

Produce a working KEV fork in one pass:

- The public KEV reference layer is loaded
- The fork layer is built from the user's asset, owner, software, and service
  inputs
- The proposal chain has run and the review queue is populated
- Every named query in the final config executes successfully against the
  user's data. Queries that should have data in this pass are proven with at
  least one non-empty invocation; queries that are intentionally retained but
  currently empty are called out explicitly. Queries that don't match the
  user's domain are removed or modified, and new queries may be added for
  common traversals the kit doesn't cover
- At least one rendered subject page shows the user's assets or services with
  linked context

## Done When

- Reference and fork state both build without drift or missing-input errors
- The proposal queue reflects the user's inventory
- Every kept named query executes successfully, with at least one
  representative non-empty invocation for the queries tied to loaded data
- One subject page in the wiki renders with the user's linked context

## Preconditions

- Run from `demos/kev-triage/` (or a fork of it)
- Cruxible daemon reachable (`cruxible context show` succeeds)
- The local seed or source files have been replaced with the user's own data
- `CRUXIBLE_AGENT_MODE` may be set; that's fine — this skill does not use
  blocked commands

If the daemon isn't reachable, stop and tell the user to start one
(`cruxible server start` or equivalent). Do not try to initialize without a
daemon.

## Flow

### 1. Check current state

```
cruxible context show --json
cruxible stats --json
```

Use this step to decide which milestone already exists:

- Reference layer built
- Fork layer built
- Proposal queue already populated

Do not treat "nonzero entities" as the only branch. A partially built world is
common when adapting inputs. Resume from the first missing milestone instead of
starting over blindly.

### 2. Prepare and verify the input files

Before building the fork layer, make sure the local source files are usable as
KEV inputs, not just present on disk. At this stage, verify only the minimum
base surfaces needed for a KEV-shaped fork:

- assets
- owners
- software inventory
- service mapping

If one of these base surfaces is missing, stop and name exactly which input is
not present. Do not compensate by inventing graph state manually.

Sanity-check the prepared inputs before continuing:

- asset IDs are stable and unique
- owner IDs are stable and unique
- service IDs are stable and unique
- service mappings reference known assets and services
- software inventory rows reference known assets
- each software row has product name, version, and vendor — enough to
  fingerprint against reference CPEs. Without all three, `propose_asset_products`
  will emit nothing.

If the source files are too messy to normalize cleanly, stop and switch to
`prepare-data` or the general `create-world` skill rather than forcing bad
state into the KEV fork.

### 3. Tailor named queries to the user's data

The exit condition for onboarding is that every named query in the final
config is validated against the user's fork. Walk through `config.yaml`'s
`named_queries` section with the user and decide per query:

- **Keep** if the user's data covers its entry point and traversal
- **Modify** if the user's data has the same shape under different property
  names or different traversal endpoints
- **Remove** if it depends on data the user doesn't have and doesn't plan to
  add in this pass (e.g., drop the incident queries if no incidents are being
  loaded)
- **Add** if the user's domain has a common traversal the kit doesn't cover

Once the final query surface is chosen, verify that any additional required
surfaces for the kept queries and workflows are actually present. This is
where optional inputs such as exceptions, controls, patch windows, incidents,
and findings become required if the user chooses to keep the queries or
workflows that depend on them.

Confirm the final query surface with the user before initializing. The
remaining steps verify that every surviving query executes, and that the ones
backed by loaded data have at least one known-good non-empty invocation. A
query may be intentionally kept even if this dataset is expected to leave it
empty.

### 4. Initialize and lock

If no instance exists:

```
cruxible init . --config config.yaml
cruxible lock
```

If `cruxible lock` fails with an artifact hash mismatch, pass `--force`:

```
cruxible lock --force
```

Narrate briefly: "Initialized instance with `config.yaml` extending
`kev-reference.yaml`."

### 5. Build the reference layer

Skip this step if `cruxible stats` from Step 1 shows reference entities
(`Vendor`, `Product`, `Vulnerability`) already loaded.

Canonical workflow — `run` returns an apply digest, then `apply` commits.

```
cruxible run --workflow build_public_kev_reference --json
```

Capture `apply_digest` from the JSON output, then:

```
cruxible apply --workflow build_public_kev_reference --expected-apply-digest <digest>
```

Narrate with real counts pulled from `cruxible stats --json`:
"Reference layer built — N vulnerabilities, M products, V vendors from the
public KEV feed."

### 6. Build fork state

Skip this step if `cruxible stats` from Step 1 shows fork entities
(`Asset`, `Owner`, `BusinessService`) already loaded.

```
cruxible run --workflow build_fork_state --json
```

Capture digest, then:

```
cruxible apply --workflow build_fork_state --expected-apply-digest <digest>
```

Narrate: "Fork state loaded — X assets, Y owners, Z services, plus whichever
optional surfaces (controls, exceptions, patch windows, incidents, findings)
were included to support the kept query set."

### 7. Run the proposal chain

Four non-canonical workflows. Each produces governed groups, not accepted
edges. `run` is sufficient — no `apply` step.

```
cruxible run --workflow propose_asset_products
cruxible run --workflow propose_asset_affected
cruxible run --workflow propose_asset_exposure
cruxible run --workflow propose_service_impact
```

Narrate one line per workflow: what it proposed and how many candidates. Pull
counts from the run output.

### 8. Verify the governed outputs

```
cruxible group list --status pending_review --json --limit 20
```

Narrate the aggregate: "N proposals are in the review queue across K
relationship types. This is where governance enters — every relationship the
engine isn't certain about waits for a reviewer."

Then run every named query in the final config and confirm each executes
successfully. For the queries tied to loaded data, use a param value drawn
from the user's loaded data and confirm at least one representative non-empty
result:

```
cruxible query --query <query_name> --param <key>=<value>
```

If a kept query that should have data returns empty, stop and diagnose before
moving on:

- If the user's data doesn't support that query, go back to Step 3 and remove
  or modify it, then re-run the affected steps
- If an upstream proposal workflow hasn't produced the needed edges, approve
  a related proposal (or adjust the proposal workflow) and retry
- Do not ship an onboarded fork with a query that should have data but still
  returns empty — either the query or the data needs to change

If a kept query is expected to be empty for this dataset, note that explicitly
in the hand-off instead of treating it as a failure.

Render the wiki and inspect at least one subject page (a user asset or
service) to confirm the linked context renders correctly.

### 9. Spot-check one proposal in detail

Pick one pending group and inspect it closely. Prefer an
`asset_exposed_to_vulnerability` proposal if one exists. Otherwise
`asset_runs_product` or `service_impacted_by_vulnerability`.

```
cruxible group get --group <group_id> --json
```

Narrate what the output shows:
- The proposed edge (from → to)
- The thesis text — the reasoning the proposal is making
- The signals from each integration — the evidence
- The provenance trail back to the workflow step that produced it

Explain why these fields matter together:

- thesis = the claim being proposed
- signals = the structured evidence for and against it
- provenance = where the judgment came from
- pending-review state = the governance boundary before graph mutation

This is the evidence pack a reviewer sees. The same audit trail shape is used
for deterministic and judgment-based steps; there is no separate ad hoc AI
output path.

### 10. Hand off

Tell the user concisely:

- The fork is live; the review queue is populated; nothing has been
  auto-accepted
- If they want to test the governance loop, resolve one proposal
- To exercise the ongoing daily loop on this fork, run `kev-triage` next
- If they want to keep adapting the kit, the next likely changes are provider
  templates, input-file shapes, workflow params, and named queries

Do NOT resolve any proposals on the user's behalf. The governance loop is
part of the adaptation surface — leave it intact unless the user explicitly
wants to exercise reviewer mode.

## When to stop and ask

- Daemon not reachable. Stop; tell the user how to start one.
- Input files cannot be normalized into stable KEV surfaces. Stop and switch
  to `prepare-data` or `create-world`.
- Required input surfaces for the kept queries are missing. Stop and name
  the missing source (or go back to Step 3 and remove queries that depend on
  it).
- The world is partially built. Resume from the first missing milestone rather
  than restarting blindly.
- Any `run` / `apply` command fails. Surface the full error and stop — do
  not retry blindly. Common cause: artifact hash drift (see step 4) or
  missing seed data.
- Review queue is empty after the proposal chain. Something upstream didn't
  produce candidates; surface it. Likely causes: empty software inventory,
  schema drift, reference layer not built.
- Any kept query that should have data returns empty after proposals were
  created. Go back to Step 3 to remove or modify the query, or fix the data
  or proposal workflow that should have supplied its results. Do not proceed
  to hand-off with unexplained empty results for supported queries.

## What this skill does NOT do

- Does not redesign the KEV ontology. This skill assumes the KEV kit shape is
  broadly correct and focuses on adapting data to it.
- Does not create a new world from scratch. Use the general `create-world`
  skill for that.
- Does not force every optional KEV data surface on the fork. Surfaces are
  required only for queries and workflows the user chooses to keep in Step 3.
- Does not approve or reject proposals. That's the reviewer's call.
- Does not optimize the full daily triage loop. That is the role of
  `kev-triage` once the fork is producing sane results.

## Next

Once the forked data is producing sane proposals, queries, and wiki pages,
run `kev-triage` on the same instance to exercise the ongoing daily loop and
the richer incident/outcome story.
