# Third-Party Data Attribution

The demo graphs in this repository are derived from the following public datasets.

## Drug Interactions Demo

- **DDinter** — Drug-Drug Interaction database. Academic use.
  Xiong G, et al. "DDInter: an online drug-drug interaction database." *Nucleic Acids Research*, 2022.
  https://ddinter.scbdd.com/

- **CYP450 Substrate Data** — Cytochrome P450 enzyme-substrate relationships compiled from publicly available pharmacokinetic literature and drug labeling.

## Sanctions Screening Demo

- **OFAC SDN List** — Office of Foreign Assets Control Specially Designated Nationals list. US Treasury Department, public domain.
  https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists

- **ICIJ Offshore Leaks Database** — International Consortium of Investigative Journalists. Licensed under the Open Database License (ODbL). The data must be attributed to ICIJ.
  https://offshoreleaks.icij.org/

## MITRE ATT&CK Demo

- **MITRE ATT&CK** — Adversarial Tactics, Techniques, and Common Knowledge framework, version 16 (October 2024). Licensed under Apache License 2.0.
  https://attack.mitre.org/
  STIX data: https://github.com/mitre-attack/attack-stix-data

## Notes

- Demo graphs contain curated subsets of these datasets, not full copies.
- AI-inferred relationships (e.g., `inhibits`, `induces`, `xref_officer`) are marked with `source`, `confidence`, and `evidence` properties to distinguish them from deterministic data.
- No personally identifiable information beyond what is already published in the source datasets is included.