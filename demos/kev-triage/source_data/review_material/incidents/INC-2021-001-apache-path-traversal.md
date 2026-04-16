# Incident Report: INC-2021-001

On 2025-10-04, the SOC observed successful path traversal requests against
`prod-web-01` (`ASSET-1`) serving the Billing customer entry point. The host
was running Apache HTTP Server 2.4.49 and investigation concluded the attacker
exploited `CVE-2021-41773`.

Expected governed actions:

- Create `Incident` entity `INC-2021-001`
- Propose `incident_owned_by` to `OWNER-2`
- Propose `incident_involved_asset` to `ASSET-1`
- Propose `incident_exploited_vulnerability` to `CVE-2021-41773`
- Create findings for:
  - Apache 2.4.49 remained internet-exposed on prod-web-01
  - New virtual host bypassed standard WAF path traversal rules
