# Sanctions Screening Demo

OFAC sanctions screening with beneficial ownership and offshore structure analysis. Traces connections between sanctioned entities (OFAC SDN list), offshore companies (ICIJ Offshore Leaks), and their officers to find hidden exposure.

## What's in the graph

| Entity type | Count | Source |
|-------------|-------|--------|
| SanctionedEntity | 30 | OFAC SDN list |
| OffshoreCompany | 9 | ICIJ Offshore Leaks |
| Officer | 18 | ICIJ Offshore Leaks |

| Relationship | Count | Description |
|-------------|-------|-------------|
| sdn_connection | 21 | Ownership/directorship links between sanctioned entities |
| officer_of | 18 | Officer roles at offshore companies |
| xref_officer | 5 | Cross-references: ICIJ officers matched to sanctioned entities |
| xref_company | 4 | Cross-references: offshore companies matched to sanctioned entities |

Three sanctions programs represented: LIBYA3, RUSSIA-EO14024, IFSR (Iran).

Curated subset of 30 entities from the [OFAC SDN list](https://sanctionssearch.ofac.treas.gov/) (~12,000 total) and [ICIJ Offshore Leaks](https://offshoreleaks.icij.org/) for demonstration purposes.

The `xref_officer` and `xref_company` edges are pre-baked AI-inferred relationships with `source`, `confidence`, `evidence`, and `match_type` properties — including both approved matches and rejected false positives.

## Try it

The graph is pre-built. Open your AI agent in this directory and ask:

- "Screen PETROPLUS LTD for sanctions exposure"
- "What shell companies is Chichenev hiding behind?"
- "Give me the full risk profile on Gordon Debono"
- "Screen a clean company — any offshore entity with no hits"

Three named queries power these: `screen_company`, `find_offshore`, `full_risk_profile`.

### CLI

```bash
cruxible query --query screen_company --param node_id=<offshore_company_node_id>
cruxible query --query find_offshore --param entity_id=<sanctioned_entity_id>
cruxible query --query full_risk_profile --param entity_id=<sanctioned_entity_id>
```

## Key subgraphs

- **Gordon Debono** (LIBYA3, Malta) — 17 connected sanctioned companies via `sdn_connection`, plus offshore cross-references through PETROPLUS LTD
- **Alexey Chichenev** (RUSSIA-EO14024) — 4 connected companies, cross-border link to HABERTON TRADING LIMITED (BVI, Pandora Papers)
- **Mehdi Najafi** (IFSR, Iran) — lighter example with officer-to-offshore link
- **LIU YANG** — false positive example with rejected `xref_officer` and `xref_company` edges, demonstrating the feedback loop
- **Clean companies** — several offshore companies with no sanctions connections, for negative screening results
