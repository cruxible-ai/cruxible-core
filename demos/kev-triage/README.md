# KEV Triage

Forkable cyber world model for vulnerability and KEV triage.

## Structure

This demo has two configs that represent the two layers:

- **`kev-reference.yaml`** — the published upstream world model. Contains only
  public entity types (Vendor, Product, Vulnerability), deterministic reference
  relationships, plus a canonical workflow that builds accepted reference state
  from the bundled hashed KEV/NVD/EPSS artifact. This is what Cruxible hosts
  and keeps updated from public feeds. Read-only to forks.

- **`config.yaml`** — a customer fork that uses `extends: kev-reference.yaml`.
  Adds internal entity types, deterministic internal mappings, governed judgment
  relationships, feedback and outcome profiles, quality checks, and named queries
  that traverse across both layers.

## Schema Diagram

Entity types and relationships, color-coded by layer. Dashed lines are governed
relationships that go through the proposal/group resolution flow.

```mermaid
graph LR
  classDef ref fill:#4a90d9,stroke:#2c5f8a,color:#fff
  classDef fork fill:#6ab04c,stroke:#3d7a28,color:#fff

  %% Reference layer entities
  Vendor:::ref
  Product:::ref
  Vulnerability:::ref

  %% Fork entities
  Asset:::fork
  BusinessService:::fork
  Owner:::fork
  CompensatingControl:::fork
  Exception:::fork
  PatchWindow:::fork
  Incident:::fork
  Finding:::fork

  %% Reference relationships (deterministic)
  Product -->|product_from_vendor| Vendor
  Vulnerability -->|vulnerability_affects_product| Product

  %% Fork deterministic relationships
  BusinessService -->|service_depends_on_asset| Asset
  Asset -->|asset_owned_by| Owner
  Asset -->|asset_has_control| CompensatingControl
  Asset -->|asset_has_exception| Exception
  Asset -->|asset_patch_window| PatchWindow

  %% Governed relationships (cross-layer and judgment)
  Asset -.->|asset_runs_product| Product
  Asset -.->|asset_affected_by_vulnerability| Vulnerability
  Asset -.->|asset_exposed_to_vulnerability| Vulnerability
  BusinessService -.->|service_impacted_by_vulnerability| Vulnerability
  Asset -.->|asset_patch_exception_for| Vulnerability
  CompensatingControl -.->|control_reduces_exposure_to| Vulnerability
  Incident -.->|incident_owned_by| Owner
  Incident -.->|incident_involved_asset| Asset
  Incident -.->|incident_exploited_vulnerability| Vulnerability
  Finding -.->|finding_from_incident| Incident

  linkStyle 7,8,9,10,11,12,13,14,15,16 stroke:#e74c3c
```

**Legend:** Blue = reference layer (upstream, read-only) | Green = fork (internal) | Solid lines = deterministic | Dashed red lines = governed (proposal/review)

## Governed Relationships

Each governed relationship has a `matching` block, integrations that provide signals, and linked feedback/outcome profiles for the Loop 1/2 flywheel.

| Relationship | Integrations | Roles | Auto-resolve | Feedback Profile | Outcome Profile |
|---|---|---|---|---|---|
| `asset_runs_product` | `software_product_match` | required | all_support | `asset_runs_product` | `asset_runs_product_resolution` |
| `asset_affected_by_vulnerability` | `product_version_evidence` | required | all_support | `asset_affected_by_vulnerability` | `asset_affected_resolution` |
| `asset_exposed_to_vulnerability` | `exploitability_signal`, `control_effectiveness` | required, required | all_support | `asset_exposed_to_vulnerability` | `asset_exposed_resolution` |
| `service_impacted_by_vulnerability` | `dependency_context` | required | all_support | `service_impacted_by_vulnerability` | — |
| `asset_patch_exception_for` | `policy_review` | required | all_support | `asset_patch_exception_for` | — |
| `control_reduces_exposure_to` | `control_effectiveness` | required | all_support | `control_reduces_exposure_to` | — |
| `incident_owned_by` | `incident_attribution` | required | — | `incident_owned_by` | — |
| `incident_involved_asset` | `incident_attribution` | required | — | `incident_involved_asset` | — |
| `incident_exploited_vulnerability` | `incident_attribution` | required | — | `incident_exploited_vulnerability` | `incident_attribution_resolution` |
| `finding_from_incident` | `incident_attribution` | required | — | `finding_from_incident` | — |

### Integration signals

| Integration | Kind | Notes |
|---|---|---|
| `software_product_match` | software_product_fuzzy_match | Fuzzy match internal software names to CPE product IDs |
| `product_version_evidence` | product_version_match | Check installed version against NVD affected ranges |
| `exploitability_signal` | exploitability_assessment | Is the vulnerability practically exploitable on this asset? |
| `control_effectiveness` | compensating_control_review | Does a control block the exploit path? |
| `dependency_context` | service_dependency_context | Does a real dependency path connect service to affected asset? |
| `policy_review` | remediation_policy_review | Is the patch exception still valid per policy? |
| `incident_attribution` | incident_investigation | Agent/human judgment linking incidents to assets, vulnerabilities, and findings |

## Rules Summary

### Constraints

No fork-specific constraints yet — these emerge from feedback analysis (Loop 1).

### Quality checks

| Name | Kind | Target | Severity | What it checks |
|---|---|---|---|---|
| `assets_have_one_owner` | cardinality | Asset -> asset_owned_by (out) | warning | Every asset has exactly one owner |
| `minimum_assets_loaded` | bounds | Asset count >= 5 | warning | CMDB load isn't empty |
| `assets_have_hostname` | property | Asset.hostname non_empty | warning | No blank hostnames |
| `no_empty_affected_version_objects`* | json_content | vulnerability_affects_product.affected_versions | error | No empty objects in version arrays |
| `affected_versions_have_useful_keys`* | json_content | vulnerability_affects_product.affected_versions | warning | At least one version range key present |
| `products_have_exactly_one_vendor`* | cardinality | Product -> product_from_vendor (out) | error | Every product has exactly one vendor |

*From the reference layer (inherited via composition).

## Feedback Profiles (Loop 1)

Structured reason codes agents attach to feedback, enabling `analyze_feedback` to
produce constraint and decision policy suggestions.

| Profile | Reason Codes | Scope Keys |
|---|---|---|
| `asset_runs_product` | `wrong_product_match` (provider_fix), `version_mismatch` (quality_check), `stale_inventory` (provider_fix) | product, hostname, evidence_source |
| `asset_affected_by_vulnerability` | `version_not_in_range` (constraint), `product_mismatch` (provider_fix) | cve, product, hostname |
| `asset_exposed_to_vulnerability` | `control_mitigates` (decision_policy), `not_internet_reachable` (constraint), `epss_score_stale` (provider_fix) | cve, criticality, environment |
| `service_impacted_by_vulnerability` | `no_dependency_path` (constraint), `service_decommissioned` (quality_check) | service, cve |
| `asset_patch_exception_for` | `exception_expired` (constraint), `scope_mismatch` (decision_policy) | cve, exception_id |
| `control_reduces_exposure_to` | `control_not_validated` (quality_check), `wrong_vulnerability_class` (constraint) | control_type, cve |

Remediation hints in parentheses tell `analyze_feedback` what kind of suggestion to produce.

## Outcome Profiles (Loop 2)

Structured outcome codes for trust calibration (resolution-anchored) and query
surface assessment (receipt-anchored).

### Resolution-anchored (was this proposal resolution correct?)

| Profile | Relationship | Outcome Codes |
|---|---|---|
| `asset_runs_product_resolution` | asset_runs_product | `wrong_product_match` (trust_adjustment), `version_drift` (provider_fix) |
| `asset_affected_resolution` | asset_affected_by_vulnerability | `wrong_affected_judgment` (trust_adjustment), `missed_affected_asset` (require_review), `version_range_error` (provider_fix) |
| `asset_exposed_resolution` | asset_exposed_to_vulnerability | `overestimated_exposure` (trust_adjustment), `underestimated_exposure` (require_review) |

### Receipt-anchored (did this query give a good answer?)

| Profile | Surface | Outcome Codes |
|---|---|---|
| `kev_assets_query` | query: kev_assets | `missing_results` (graph_fix), `false_positive_result` (graph_fix) |
| `owner_patch_queue_query` | query: owner_patch_queue | `stale_priority` (graph_fix), `missing_exposure` (workflow_fix) |

## Named Queries

Cross-layer traversals that start from one entity type and follow relationships
across the reference and fork layers.

| Query | Entry Point | Returns | Traversal |
|---|---|---|---|
| `kev_assets` | Vulnerability | Asset | <- asset_affected_by_vulnerability |
| `service_blast_radius` | Vulnerability | BusinessService | <- service_impacted_by_vulnerability |
| `owner_patch_queue` | Owner | Vulnerability | <- asset_owned_by -> asset_exposed_to_vulnerability |
| `product_kev_exposure` | Product | Asset | <- vulnerability_affects_product <- asset_affected_by_vulnerability |
| `asset_exception_context` | Asset | Exception | -> asset_has_exception |
| `asset_control_context` | Asset | CompensatingControl | -> asset_has_control |
| `incident_history_for_product` | Product | Incident | <- vulnerability_affects_product <- incident_exploited_vulnerability |
| `open_findings_for_asset` | Asset | Finding | <- incident_involved_asset <- finding_from_incident (target_filter: status=open) |
| `prior_exploitation_context` | Vulnerability | Finding | <- incident_exploited_vulnerability <- finding_from_incident |
| `finding_status_for_incident` | Incident | Finding | <- finding_from_incident |

## Workflows

The fork defines four non-canonical proposal workflows plus one canonical seed
load workflow.

| Workflow | Canonical | Steps | Purpose |
|---|---|---|---|
| `build_fork_state` | yes | 23 | Load deterministic entities (Assets, Owners, Services, Controls, Exceptions, PatchWindows) and relationships from seed data, apply to graph |
| `propose_asset_products` | no | 7 | Load software inventory, list published `Product` entities from the reference graph, fuzzy match, build candidates, map signals, propose governed `asset_runs_product` edges |
| `propose_asset_affected` | no | 6 | Read approved `asset_runs_product` and public `vulnerability_affects_product` edges, compare installed versions to affected ranges, propose `asset_affected_by_vulnerability` edges |
| `propose_asset_exposure` | no | 9 | Read approved affected edges plus asset/control context, derive exploitability and control signals, propose `asset_exposed_to_vulnerability` edges |
| `propose_service_impact` | no | 6 | Read approved exposure edges plus service dependencies, roll impact up to business services, propose `service_impacted_by_vulnerability` edges |

The reference layer also contributes `build_public_kev_reference` (11 steps, canonical) via composition.

### Providers

| Provider | Input | Output | Artifact | Purpose |
|---|---|---|---|---|
| `load_fork_seed_data` | EmptyInput | ForkSeedData | fork_seed_bundle | Load all seed CSVs into structured arrays |
| `load_software_inventory` | EmptyInput | SoftwareInventory | fork_seed_bundle | Load software_inventory.csv |
| `match_software_to_products` | SoftwareMatchInput | SoftwareMatchResults | — | Fuzzy match software names to CPE product IDs |
| `assess_asset_affected` | AssetAffectedAssessmentInput | AssetAffectedAssessmentResults | — | Join approved asset-product edges to public vulnerability-product edges and compare versions |
| `assess_asset_exposure` | AssetExposureAssessmentInput | AssetExposureAssessmentResults | — | Derive exploitability and control-review signals for approved affected assets |
| `assess_service_impact` | ServiceImpactAssessmentInput | ServiceImpactAssessmentResults | — | Aggregate exposed assets into service-impact candidates |

The reference layer also contributes `load_public_kev_rows` via composition.

### Execution order

1. `build_public_kev_reference` — build the reference graph (Vendor, Product, Vulnerability)
2. `build_fork_state` — load internal entities and deterministic edges
3. `propose_asset_products` — fuzzy match software inventory against reference products, propose governed edges
4. `propose_asset_affected` — assess whether approved installed products are actually within KEV-affected version ranges
5. `propose_asset_exposure` — assess whether approved affected assets are materially exposed
6. `propose_service_impact` — roll approved exposure up to impacted business services

Steps 3-6 each produce group proposals that enter the resolution lifecycle based
on the target relationship's `matching` config. Approving those groups is what
materializes the triage graph used by `kev_assets`, `owner_patch_queue`,
`service_blast_radius`, and `product_kev_exposure`.

## Seed Data

Synthetic test data lives in `data/seed/`. These CSVs represent what a business
would have readily available from internal systems — CMDB exports, software
inventory, service catalogs, and operations data — using the business's own
naming conventions, not CPE identifiers. The gap between internal names and
reference-layer product IDs is the fuzzy matching problem that the
`asset_runs_product` governed relationship solves through the proposal flow.

See `data/seed/software_inventory.csv` for the key file — it contains software
names and versions as the business knows them, which need to be matched to
reference-layer products through `software_product_match` proposals.

The seed bundle now includes a richer internal environment: multiple owners,
services, internet-facing Apache hosts on different versions, patch windows,
active controls, and one legacy exception record from a source-of-record
system.

Source material for governed agent actions lives under
`data/seed/review_material/`. Those files are not loaded by
`build_fork_state`; they are synthetic incident reports, waiver requests, and
control reviews meant to drive `add-entity` and `group propose`.

## Incident History Layer

Adds incident investigation knowledge that compounds across triage cycles. The
vulnerability triage layer tells you what's exposed *now*. The incident layer
tells you what's been exploited *before* — and what you learned from it.

### Why this compounds

When a new CVE drops and the triage agent runs the exposure assessment, it can
also query `incident_history_for_product` to check: "has this product been
exploited before in our environment?" If yes, the triage summary includes what
happened last time — which assets were hit, what the root cause was, what
findings are still open. The priority isn't just CVSS × EPSS anymore; it's
informed by organizational history.

### Proposed entity types

| Entity | Properties | Source |
|---|---|---|
| `Incident` | incident_id (PK), title, severity, status (open/investigating/resolved/closed), occurred_at, resolved_at, source, summary | PagerDuty export, SIEM, manual |
| `Finding` | finding_id (PK), title, category (misconfiguration/missing_control/stale_data/access_violation/process_gap), detail, status (open/remediated/accepted_risk), remediation_action, remediated_at | Post-mortem extraction (agent or manual) |

### Proposed relationships

| Relationship | From → To | Governed? | How it's created |
|---|---|---|---|
| `incident_owned_by` | Incident → Owner | Yes | Agent proposes accountable owner for incident |
| `incident_involved_asset` | Incident → Asset | Yes | Agent reads incident report, proposes link |
| `incident_exploited_vulnerability` | Incident → Vulnerability | Yes | Agent reads post-mortem, proposes CVE attribution |
| `finding_from_incident` | Finding → Incident | Yes | Agent extracts findings from post-mortem |

### Proposed named queries

| Query | Traversal | What it answers |
|---|---|---|
| `incident_history_for_product` | Product ← vulnerability_affects_product ← incident_exploited_vulnerability | "Has this product been exploited before?" |
| `open_findings_for_asset` | Asset ← incident_involved_asset ← finding_from_incident (status = open) | "What open findings still need action for this asset?" |
| `prior_exploitation_context` | Vulnerability ← incident_exploited_vulnerability → finding_from_incident | "What did we learn last time this CVE was exploited?" |
| `finding_status_for_incident` | Incident ← finding_from_incident | "Are all findings from this incident remediated?" |
