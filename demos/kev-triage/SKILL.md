# KEV Security Triage

Agent skill for operating on a KEV triage world instance.

## Governed one-off proposals

The following entity types are created via `add-entity` and linked to the graph
via `group propose`. The agent reads source material (incident reports,
post-mortems, tickets, conversations) and proposes governed relationships one at
a time. Humans approve or reject.

In this demo, sample source material lives under `data/seed/review_material/`.
The CSV files in `data/seed/` load deterministic state; the review material is
what the agent should read to create incidents, findings, new exceptions, and
proposal groups.

### Incidents and findings

When a security incident is reported or a post-mortem is written:

1. Create the Incident entity via `add-entity`
2. Propose `incident_owned_by` edge via `group propose` — who is accountable for this incident
3. Propose `incident_involved_asset` edges via `group propose` — which assets were part of this incident
4. Propose `incident_exploited_vulnerability` edges via `group propose` — which CVEs were actually exploited
5. Create Finding entities via `add-entity` for each root cause identified
6. Propose `finding_from_incident` edges via `group propose` — linking findings to the incident

Each proposal should include a thesis explaining the reasoning, e.g.:
"Post-mortem for INC-001 states the attacker used the path traversal in
CVE-2021-41773 to access server files on prod-web-01."

### Exceptions and waivers

When a patch exception is granted:

1. Create or update the Exception entity via `add-entity`
2. Propose `asset_patch_exception_for` edge via `group propose` — linking the asset to the vulnerability being waived, with the exception_id in properties

### Compensating controls

When a control is deployed to mitigate a vulnerability:

1. Create or update the CompensatingControl entity via `add-entity`
2. The `asset_has_control` edge is deterministic (loaded from seed data or added directly)
3. Propose `control_reduces_exposure_to` edge via `group propose` — the judgment that this control actually mitigates this vulnerability

## Batch workflows

For structured data imports, use the existing proposal workflows:

- `propose_asset_products` — fuzzy match software inventory to reference products
- `propose_asset_affected` — version range matching against CVEs
- `propose_asset_exposure` — exploitability assessment
- `propose_service_impact` — roll exposure up to business services

## Daily triage loop

Scheduled agent workflow that runs on a cadence:

1. Refresh the reference layer — run `build_public_kev_reference` to pick up new CVEs
2. Run the proposal chain — `propose_asset_products` through `propose_service_impact`
3. For each new exposure, query `incident_history_for_product` and `open_findings_for_asset` to enrich with organizational history
4. Summarize actionable items: new proposals awaiting review, exposures past their due date, and open findings
5. Post summary to Slack/PagerDuty or present to the user

The triage summary should distinguish between:
- New exposures with no prior incident history (standard priority)
- New exposures on products/assets with prior exploitation (elevated priority)
- Overdue exposures with no exception on file

## Key queries for triage context

- `incident_history_for_product` — has this product been exploited before?
- `open_findings_for_asset` — what unresolved root causes exist for this asset?
- `prior_exploitation_context` — what did we learn last time this CVE was exploited?
- `owner_patch_queue` — what exposed vulnerabilities does this owner need to patch?
- `service_blast_radius` — what services are impacted by this vulnerability?
