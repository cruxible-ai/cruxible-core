# Post-Mortem: INC-2024-002

## Summary

On 2026-02-18, `prod-web-02` (`ASSET-6`) served attacker-controlled rewrite
content that mapped requests to filesystem locations outside intended routes.
The host was internet-facing and running Apache HTTP Server 2.4.58.

The response team attributed the exploit path to `CVE-2024-38475`. Traffic was
contained by enabling the emergency WAF policy and deploying a patched Apache
build during the next web patch window.

## Candidate graph facts

- Incident entity:
  `incident_id=INC-2024-002`
  `title=Apache mod_rewrite exploit on prod-web-02`
  `severity=critical`
  `status=resolved`
  `occurred_at=2026-02-18`
  `resolved_at=2026-02-19`
  `source=pagerduty`
- Proposed `incident_owned_by`:
  `INC-2024-002 -> OWNER-2`
- Proposed `incident_involved_asset`:
  `INC-2024-002 -> ASSET-6`
  `role=target`
- Proposed `incident_exploited_vulnerability`:
  `INC-2024-002 -> CVE-2024-38475`

## Findings to create

### FIND-2024-010

- `title=Unsafe rewrite rule pattern deployed without security review`
- `category=misconfiguration`
- `status=remediated`
- `remediation_action=Require security review for Apache rewrite rules that resolve to filesystem paths`

### FIND-2024-011

- `title=Emergency WAF policy was not pre-enabled on secondary production web tier`
- `category=process_gap`
- `status=open`
- `remediation_action=Pre-stage emergency WAF policy on all production web assets`

Both findings should be linked to `INC-2024-002` with `finding_from_incident`.
