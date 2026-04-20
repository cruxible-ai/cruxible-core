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
- Cruxible daemon reachable (`cruxible server info --json` succeeds)
- The local seed or source files have been replaced with the user's own data
- `CRUXIBLE_AGENT_MODE` may be set; that's fine — this skill does not use
  blocked commands

If the daemon isn't reachable, stop and tell the user to start the project's
configured Cruxible daemon before continuing. Do not try to initialize
without a daemon.

## Flow

### 1. Check current state

```
cruxible server info --json
cruxible context show --json
```

If `context show --json` includes an `instance_id`, then run:

```
cruxible stats --json
```

Confirm `agent_mode` from `cruxible server info --json` before acting. If the
daemon was started without it, call that out explicitly because this skill's
guarded local-mode assumptions will not be exercised.

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

Server mode is the primary path for 0.2. The daemon owns the instance
directory (under `CRUXIBLE_SERVER_STATE_DIR`, default `~/.cruxible/server/
instances/inst_<id>/`). Do **not** pass `--root-dir` or create a local
`.cruxible/` directory; the daemon manages its own state.

If no instance exists:

```
cruxible init --config config.yaml
cruxible lock
```

Capture the returned `instance_id` and persist it with `cruxible context use
<instance_id>` so subsequent commands target it.

If `cruxible lock` fails with an artifact hash mismatch, pass `--force`:

```
cruxible lock --force
```

Narrate briefly: "Initialized instance with `config.yaml` extending
`kev-reference.yaml`. Daemon owns state at
`~/.cruxible/server/instances/<instance_id>/`."

### 5. Build the reference layer

Skip this step if `cruxible stats` from Step 1 shows reference entities
(`Vendor`, `Product`, `Vulnerability`) already loaded.

Canonical workflow — save the preview once, then apply from the saved preview
file so you don't have to thread `apply_digest` and `head_snapshot_id`
manually.

```
cruxible run --workflow build_public_kev_reference --save-preview preview-reference.json
cruxible apply --preview-file preview-reference.json
```

If apply fails because the head moved, rerun the preview to refresh
`preview-reference.json` and apply again from that file.

Narrate with real counts pulled from `cruxible stats --json`:
"Reference layer built — N vulnerabilities, M products, V vendors from the
public KEV feed."

### 6. Build fork state

Skip this step if `cruxible stats` from Step 1 shows fork entities
(`Asset`, `Owner`, `BusinessService`) already loaded.

Run then apply from a saved preview file:

```
cruxible run --workflow build_fork_state --save-preview preview-fork.json
cruxible apply --preview-file preview-fork.json
```

Narrate: "Fork state loaded — X assets, Y owners, Z services, plus whichever
optional surfaces (controls, exceptions, patch windows, incidents, findings)
were included to support the kept query set."

### 7. Walk the proposal chain with review gates

The four proposal workflows form a dependency chain: each one reads approved
edges from the previous one. They cannot run back-to-back without review in
between.

Use `cruxible propose` (not `cruxible run`) — `propose` bridges the workflow
output into a candidate group; `run` only executes and returns the payload.

Walk the chain one stage at a time. After each `propose`, pause for the user
to approve the group before issuing the next `propose`.

**Stage 1 — asset_runs_product:**

```
cruxible propose --workflow propose_asset_products --json
```

Capture the returned `group_id`, then inspect it:

```
cruxible group get --group <group_id>
```

Ask the user to approve. If they agree:

```
cruxible group resolve --group <group_id> --action approve \
  --source ai_review --rationale "<reason>"
```

Do not proceed to Stage 2 until this group is resolved. If the user rejects,
explain that Stages 2–4 depend on approved `asset_runs_product` edges and
will fail with `Members list must not be empty` if run now.

**Stages 2–4** follow the same pattern:

- Stage 2: `cruxible propose --workflow propose_asset_affected`
  (depends on approved Stage 1 edges)
- Stage 3: `cruxible propose --workflow propose_asset_exposure`
  (depends on approved Stage 2 edges)
- Stage 4: `cruxible propose --workflow propose_service_impact`
  (depends on approved Stage 3 edges)

After each stage, pause, show the group, request approval, resolve, then
proceed. This is the observable governance loop; it is the point of the
skill, not a workaround.

### 8. Verify the governed outputs

Named queries all require parameters. Before running them, list the final
query surface and its entry points:

```
cruxible query list --json
```

For each named query, inspect its required params and example IDs with:

```
cruxible query describe --query <query_name> --json
```

Then run each query using `--count --json` (returns only the total so the
output stays inspectable):

```
cruxible query --query <query_name> --param <key>=<value> --count --json
```

Confirm each kept query executes successfully. For queries tied to loaded
data, confirm at least one representative non-empty result.

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

### 9. Hand off

Tell the user concisely:

- The fork is live; the proposal chain walked through with reviewer approval
  at each stage
- To exercise the ongoing daily loop on this fork (incident attribution,
  waiver intake, control reviews, daily triage summary), run `kev-triage`
  next
- If they want to keep adapting the kit, the next likely changes are provider
  templates, input-file shapes, workflow params, and named queries

Approvals issued during Step 7 were user-directed governance decisions. Do
not issue further approvals outside that flow.

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
- Does not approve or reject proposals outside the Step 7 walk-through.
  Approvals in Step 7 are the user's governance decisions, issued one stage
  at a time with explicit consent.
- Does not optimize the full daily triage loop. That is the role of
  `kev-triage` once the fork is producing sane results.

## Next

Once the forked data is producing sane proposals, queries, and wiki pages,
run `kev-triage` on the same instance to exercise the ongoing daily loop and
the richer incident/outcome story.
