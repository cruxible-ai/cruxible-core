---
name: common-workflows
description: Quick reference for common Cruxible tool sequences.
---

# Common Workflows

## Debugging a query

1. inspect schema
2. sample entities
3. run the query
4. inspect the receipt
5. fix config or data, then repeat

## Edge-level review

1. run a query to get a `receipt_id`
2. record feedback
3. re-run the query to confirm behavior changes

## Iterative graph refinement

1. evaluate graph quality
2. search for missing edges
3. persist confirmed relationships
4. re-run evaluation and compare counts

## Auditing a decision

1. locate the relevant receipt
2. inspect the receipt
3. review attached feedback
4. review attached outcomes
