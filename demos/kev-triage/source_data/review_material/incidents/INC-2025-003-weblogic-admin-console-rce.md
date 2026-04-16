# Post-Mortem: INC-2025-003

## Summary

On 2026-01-11, `partner-api-01` (`ASSET-8`) received a sequence of crafted
requests against the WebLogic administrative path after a temporary partner
network routing change widened the allowed source range. The host was running
Oracle WebLogic Server 12.2.1.4.0.

The response team attributed the exploit attempt and follow-on code execution
to `CVE-2020-14882`. Access was contained by restoring the stricter partner
allowlist, rotating credentials, and rebuilding the middleware image during the
next approved patch window.

## Candidate graph facts

- Incident entity:
  `incident_id=INC-2025-003`
  `title=WebLogic admin console compromise on partner-api-01`
  `severity=high`
  `status=resolved`
  `occurred_at=2026-01-11`
  `resolved_at=2026-01-12`
  `source=pagerduty`
- Proposed `incident_owned_by`:
  `INC-2025-003 -> OWNER-3`
- Proposed `incident_involved_asset`:
  `INC-2025-003 -> ASSET-8`
  `role=target`
- Proposed `incident_exploited_vulnerability`:
  `INC-2025-003 -> CVE-2020-14882`

## Findings to create

### FIND-2025-020

- `title=Temporary partner route expansion exposed WebLogic admin path to a broader source range`
- `category=exposure_gap`
- `status=remediated`
- `remediation_action=Require security approval and automatic rollback timers for partner allowlist expansions`

### FIND-2025-021

- `title=Credential rotation for middleware administrators was not automated after emergency network changes`
- `category=process_gap`
- `status=open`
- `remediation_action=Automate post-change credential rotation for externally reachable administrative services`

Both findings should be linked to `INC-2025-003` with `finding_from_incident`.
