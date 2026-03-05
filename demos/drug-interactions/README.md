# Drug Interactions Demo

Clinical drug interaction checking with CYP450 enzyme metabolism analysis. Traces interactions between drugs, maps metabolic pathways through enzymes, and suggests therapeutic alternatives — all with receipts.

## What's in the graph

| Entity type | Count | Source |
|-------------|-------|--------|
| Drug | 46 | DDinter database + CYP450 substrate data |
| Enzyme | 6 | CYP450 metabolic enzymes |

| Relationship | Count | Description |
|-------------|-------|-------------|
| interacts_with | 484 | Known drug-drug interactions with severity (Major/Moderate/Minor) |
| metabolized_by | 102 | Drug is a substrate of a CYP450 enzyme (deterministic from dataset) |
| same_class | 96 | Drugs in the same therapeutic class (statins, SSRIs, etc.) |
| inhibits | 14 | Drug inhibits a CYP450 enzyme (AI-inferred, with confidence scores) |
| induces | 8 | Drug induces a CYP450 enzyme (AI-inferred, with confidence scores) |

Six therapeutic classes represented: statins, SSRIs, ACE inhibitors, beta blockers, PPIs, and benzodiazepines.

Curated subset of 46 drugs from [DDinter](http://ddinter.scbdd.com/) (~2,500 total) and CYP450 substrate datasets for demonstration purposes.

The `inhibits` and `induces` edges are AI-inferred relationships with `confidence`, `evidence`, and `source` properties — demonstrating the feedback loop workflow.

## Try it

The graph is pre-built. Open your AI agent in this directory and ask:

- "Check interactions for warfarin"
- "Why do fluoxetine and simvastatin interact?"
- "What's the enzyme impact of fluoxetine?"
- "Suggest an alternative to simvastatin that avoids CYP3A4"

Four named queries power these: `check_interactions`, `find_mechanism`, `enzyme_impact`, `suggest_alternative`.

### CLI

```bash
cruxible query --query check_interactions --param drug_id=warfarin
cruxible query --query find_mechanism --param drug_id=fluoxetine
cruxible query --query enzyme_impact --param drug_id=fluoxetine
cruxible query --query suggest_alternative --param drug_id=simvastatin
```
