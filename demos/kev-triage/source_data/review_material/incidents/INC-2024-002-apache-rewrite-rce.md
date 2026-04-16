# Post-Mortem: INC-2024-002

On 2026-02-18, `prod-web-02` (`ASSET-6`) served attacker-controlled rewrite
content that mapped requests to filesystem locations outside intended routes.
The response team attributed the exploit path to `CVE-2024-38475`.

Expected governed actions:

- Create `Incident` entity `INC-2024-002`
- Propose `incident_owned_by` to `OWNER-2`
- Propose `incident_involved_asset` to `ASSET-6`
- Propose `incident_exploited_vulnerability` to `CVE-2024-38475`
- Create findings for:
  - Unsafe rewrite rule pattern deployed without security review
  - Emergency WAF policy was not pre-enabled on secondary production web tier
