---
name: analyze-feedback
description: Turn repeated feedback patterns into constraints, decision policies, or concrete follow-up work.
---

# Analyze Feedback

Use this skill after enough feedback has accumulated to show patterns.

## Workflow

1. resolve the applicable feedback profile
2. run feedback analysis
3. review:
   - constraint suggestions
   - decision policy suggestions
   - quality check candidates
   - provider fix candidates
4. apply only the suggestions that match the real failure mode

Treat uncoded examples as advisory. They are examples, not machine-grouped evidence.

## Decision rule

- bad graph state -> constraint
- behavioral/process change -> decision policy
- data/provider issue -> capture as follow-up, do not force it into a constraint
