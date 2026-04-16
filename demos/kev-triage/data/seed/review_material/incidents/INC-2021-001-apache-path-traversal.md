# Incident Report: INC-2021-001

## Summary

On 2025-10-04, the SOC observed successful path traversal requests against the
internet-facing host `prod-web-01` (`ASSET-1`) serving the Billing customer
entry point. The host was running Apache HTTP Server 2.4.49 and exposed an
alias-backed file path that should not have been directly reachable.

Investigation concluded the attacker exploited `CVE-2021-41773`. The impacted
service owner accepted a temporary outage window while the host was rebuilt and
the vulnerable version removed.

## Candidate graph facts

- Incident entity:
  `incident_id=INC-2021-001`
  `title=Apache path traversal on prod-web-01`
  `severity=high`
  `status=resolved`
  `occurred_at=2025-10-04`
  `resolved_at=2025-10-05`
  `source=siem`
- Proposed `incident_owned_by`:
  `INC-2021-001 -> OWNER-2`
- Proposed `incident_involved_asset`:
  `INC-2021-001 -> ASSET-1`
  `role=target`
- Proposed `incident_exploited_vulnerability`:
  `INC-2021-001 -> CVE-2021-41773`

## Findings to create

### FIND-2021-001

- `title=Apache 2.4.49 remained internet-exposed on prod-web-01`
- `category=stale_data`
- `status=remediated`
- `remediation_action=Rebuild prod-web-01 on Apache 2.4.54 and validate package pinning`

### FIND-2021-002

- `title=New virtual host bypassed standard WAF path traversal rules`
- `category=missing_control`
- `status=open`
- `remediation_action=Extend Edge WAF policy set to all internet-facing Apache virtual hosts`

Both findings should be linked to `INC-2021-001` with `finding_from_incident`.
