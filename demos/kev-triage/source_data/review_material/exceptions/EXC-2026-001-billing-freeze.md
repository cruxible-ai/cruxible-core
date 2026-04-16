# Waiver Request: EXC-2026-001

The Billing team requests a temporary patch exception for `batch-worker-01`
(`ASSET-5`) because the monthly financial close window overlaps the next
available maintenance slot. The request concerns Apache exposure linked to
`CVE-2024-38475`.

Expected governed actions:

- Create `Exception` entity `EXC-2026-001`
- Propose `asset_patch_exception_for` from `ASSET-5` to `CVE-2024-38475`
