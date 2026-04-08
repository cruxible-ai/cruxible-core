---
name: analyze-outcomes
description: Use recorded outcomes to calibrate trust, review policy, and workflow behavior without mutating graph state directly.
---

# Analyze Outcomes

Use this skill when downstream success or failure data shows a systematic process problem.

## Workflow

1. resolve the applicable outcome profile
2. run outcome analysis
3. review:
   - trust adjustment suggestions
   - workflow review policy suggestions
   - query policy suggestions
   - provider fix candidates
   - debug packages

## Guardrails

- outcomes calibrate process trust
- outcomes do not directly rewrite graph state
- if the failure localizes to a wrong edge or bad graph fact, route that correction through feedback or graph review
- if blame is uncertain, treat the result as a debugging package rather than a direct policy change
