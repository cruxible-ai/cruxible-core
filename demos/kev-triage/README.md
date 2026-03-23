# KEV Triage

Forkable cyber world model for vulnerability and KEV triage.

## What this models

This demo is intentionally split into two layers that live in the same private
fork:

- **Public reference layer**
  - vendors
  - products
  - vulnerabilities
  - vulnerability-to-product mappings
- **Private operational layer**
  - assets
  - business services
  - owners
  - scanner findings
  - compensating controls
  - exceptions
  - patch windows

The compounding asset is not the KEV feed itself. It is the accepted local
judgment layer:

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
public sources. A company then forks that model and mutates the fork with its
internal CMDB, cloud inventory, scanner findings, service mappings, controls,
and exceptions.

## Example queries

- `kev_assets`
- `service_blast_radius`
- `owner_patch_queue`
- `product_kev_exposure`
- `asset_exception_context`
- `asset_control_context`

## Notes

- This is a world-model-first candidate, not just a recipe.
- The published model is the reference layer.
- The private fork is what actually gets mutated and accumulates accepted local
  judgment over time.
