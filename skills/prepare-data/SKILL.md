---
name: prepare-data
description: Validate and clean raw source files before loading them into Cruxible.
---

# Prepare Data

Use this skill before writing loader workflows or legacy ingestion mappings.

Cruxible validates, loads, and evaluates. Data cleaning and transforms are external.

## Workflow

1. Profile each source file.
   - row count
   - columns
   - dtypes
   - null counts
   - sample rows
2. Validate entity primary keys.
   - duplicates
   - null or empty IDs
   - whitespace or sentinel values
3. Validate relationship foreign keys.
   - source and target columns exist
   - foreign keys actually resolve
   - duplicate `(from, to, relationship_type)` rows
4. Check join keys across files.
   - shared columns exist
   - values overlap
   - types match
5. Remove junk rows.
   - sentinels
   - placeholders
   - all-null records
6. Check grain and cardinality.
   - one row per entity?
   - one row per relationship?
   - duplicated rows caused by a secondary dimension?
7. Inspect text fields.
   - encoding issues
   - embedded IDs or dates worth extracting
8. If a draft config exists, compare the files against it.
   - expected ID columns
   - expected relationship columns
   - workflow loader assumptions
   - column rename requirements

## Output

Report:

- `readiness`: `ready` | `ready_with_warnings` | `blocked`
- `blocking_issues`
- `warnings`
- `cleaned_files`
