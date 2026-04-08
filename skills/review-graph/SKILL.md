---
name: review-graph
description: Review graph quality, discover missing relationships, and iterate using evaluation, sampling, and feedback.
---

# Review Graph

Use this skill on an existing world when the goal is quality improvement, not initial setup.

## Loop

1. run evaluation
2. prioritize findings
3. inspect representative examples
4. add or correct relationships
5. re-run evaluation
6. stop when a pass produces no meaningful new improvements

## Priority order

1. constraint violations
2. low-confidence or suspicious edges
3. repeated rejection patterns
4. coverage gaps
5. high-orphan slices that should probably connect

## Before reviewing edges

If you plan to persist feedback, make sure you have a usable `receipt_id`.

- if receipts already exist, reuse one
- if not, run a representative named query first
- if the world has no named queries yet, finish onboarding before doing deep review

## Discovery sequence

When trying to find missing relationships:

1. sample likely orphans
2. try direct property matching
3. try shared-neighbor or transitive discovery
4. inspect a few high-value specific cases by hand
5. if exact matching has plateaued, do an intelligence pass with your own tooling or judgment

Do not stop after the first failed strategy.

## Guardrails

- consider a constraint when a repeated rejection pattern is real
- prefer correcting confidence or evidence over deleting useful but imperfect edges
- escalate ambiguous tails to the user instead of pretending certainty
