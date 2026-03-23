# KEV Triage

Forkable cyber world model for vulnerability and KEV triage.

## Structure

This demo has two configs that represent the two layers:

- **`kev-reference.yaml`** — the published upstream world model. Contains only
  public entity types (Vendor, Product, Vulnerability), deterministic reference
  relationships, and public ingestion mappings. This is what Cruxible hosts and
  keeps updated from KEV, NVD, and CPE feeds. Read-only to forks.

- **`config.yaml`** — a customer fork. Contains the full reference layer (merged
  inline for now) plus all internal additions: private entity types, deterministic
  internal mappings, accepted judgment relationships, named queries, and internal
  ingestion mappings. When config composition lands, the reference layer will be
  replaced by `extends: cruxible/kev-reference`.

## What the fork adds

The fork extends the reference graph with two kinds of state:

**Deterministic internal mappings** (from existing systems, no review needed):
- assets, services, owners, scanner findings, controls, exceptions, patch windows
- edges like `asset_runs_product`, `service_depends_on_asset`, `asset_owned_by`

**Accepted judgment relationships** (governed, require proposal/review):
- `asset_affected_by_vulnerability`
- `asset_exposed_to_vulnerability`
- `service_impacted_by_vulnerability`
- `asset_patch_exception_for`
- `control_reduces_exposure_to`

Those are the decisions an organization keeps having to make. In most security
stacks, they are fragmented across scanner state, tickets, exception systems,
and analyst notes. Here they become governed state.

## Why this is a strong flagship shape

- strong public seed data
- obvious private fork
- recurring downstream work
- clear proposal/review/value loop

The public model can be built from KEV, NVD, CPE/vendor mappings, and related
public sources. A company then forks that model and extends it with its
internal CMDB, cloud inventory, scanner findings, service mappings, controls,
and exceptions.

## Example queries

- `kev_assets`
- `service_blast_radius`
- `owner_patch_queue`
- `product_kev_exposure`
- `asset_exception_context`
- `asset_control_context`
