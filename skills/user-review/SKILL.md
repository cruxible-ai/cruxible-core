---
name: user-review
description: Run a collaborative human review session for graph edges and persist the resulting feedback.
---

# User Review

Use this skill when a human wants to review edge quality directly.

## Step 1: Identify review candidates

Focus on:

- low-confidence edges
- AI-inferred or non-deterministic edges
- pending-review edges
- high-impact relationship types used by important queries

If the edge list is ambiguous between the same endpoints, keep the `edge_key`.

## Step 2: Present each edge clearly

Show:

- both entities
- key properties
- edge properties
- why the edge exists
- what decisions or queries it affects

## Step 3: Record one of four actions

- approve
- correct
- flag
- reject

You need a `receipt_id` for feedback. If there is no usable receipt yet, run a representative query first.

## Step 4: Batch and summarize

After a small batch:

- summarize what changed
- ask whether to continue
- note repeated rejection patterns worth turning into constraints

End in user-facing language:

- how many edges were reviewed
- how many were approved, corrected, flagged, or rejected
- any repeated patterns worth encoding as rules
- what the user should do next
