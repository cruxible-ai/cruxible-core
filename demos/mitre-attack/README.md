# MITRE ATT&CK Demo

Threat analysis using the MITRE ATT&CK Enterprise knowledge base. Maps threat groups to techniques, software, campaigns, mitigations, and detection strategies — answering questions like "what TTPs does APT28 use?" and "how do we defend against credential dumping?"

## What's in the graph

| Entity type | Count | Description |
|-------------|-------|-------------|
| Technique | 383 | ATT&CK techniques and sub-techniques |
| DetectionStrategy | 342 | Detection guidance for identifying adversary behavior |
| Software | 100 | Malware and legitimate tools used by adversaries |
| Mitigation | 44 | Defensive countermeasures |
| Tactic | 14 | Phases of the adversary lifecycle |
| Campaign | 4 | Named threat operations |
| Group | 4 | Threat actor groups (APT28, Lazarus Group, Kimsuky, APT41) |

| Relationship | Count | Description |
|-------------|-------|-------------|
| software_uses_technique | 1344 | Software implements a technique |
| mitigates | 878 | Mitigation addresses a technique |
| technique_in_tactic | 480 | Technique belongs to a tactical phase |
| group_uses_technique | 375 | Group observed using a technique |
| detects | 342 | Detection strategy identifies a technique |
| subtechnique_of | 220 | Sub-technique is a variant of a parent technique |
| campaign_uses_technique | 125 | Campaign employed a technique |
| group_uses_software | 103 | Group observed using software |
| campaign_uses_software | 15 | Campaign employed software |
| campaign_attributed_to | 4 | Campaign attributed to a group |

Data sourced from MITRE ATT&CK STIX 2.1 (v16, October 2024). Subset covers 4 threat groups and all connected entities.

## Try it

The graph is pre-built. Open your AI agent in this directory and ask:

- "What techniques does APT28 use?"
- "How do we defend against process injection?"
- "How do we detect credential dumping?"
- "What malware does Lazarus Group use?"
- "Who uses phishing techniques?"
- "What TTPs were used in campaign C0027?"

14 named queries power these: `group_techniques`, `technique_mitigations`, `technique_detections`, `group_software`, `technique_groups`, `campaign_techniques`, `group_campaigns`, `technique_tactics`, `technique_software`, `software_techniques`, `software_groups`, `tactic_techniques`, `campaign_breakdown`, `mitigation_coverage`.

### CLI

```bash
cruxible query --query group_techniques --param group_id=G0007
cruxible query --query technique_mitigations --param technique_id=T1055
cruxible query --query technique_detections --param technique_id=T1055
cruxible query --query group_software --param group_id=G0032
```
