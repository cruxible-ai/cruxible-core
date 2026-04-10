---
name: prepare-data
description: Profile and prepare raw source files before world creation or local fitting; validate keys, grain, joins, and transformation needs, then produce a concrete readiness report.
---

# Prepare Data

Use this skill before `create-world`, and before `fork-and-fit` whenever local source files need to be loaded into a fork.

Cruxible validates, loads, and evaluates. File cleaning and transforms are external.

This skill is about source-data preparation only:

- profiling files
- validating keys and joins
- checking grain and cardinality
- identifying cleaning and transform work
- producing cleaned files or a preparation plan

It is not for cross-dataset matching or governed relationship design. Those happen later in the world-building flow.

Use your own tools freely here: Python, Polars, SQL, spreadsheets, or shell tooling. The goal is to hand the later world-building skill source files that are understood, defensible, and ready.

## Workflow

## Phase 1: Inventory the files

For each file, identify:

- what the file appears to represent
- whether it looks like an entity source, deterministic relationship source, reference file, or unknown source
- what later world surface it is likely to support

If a draft world model or config already exists, use it to anchor the review. Otherwise, infer the likely role of each file from the data itself.

## Phase 2: Profile each file

For every source file, inspect:

- row count
- columns
- dtypes
- null counts
- sample rows
- obvious schema inconsistencies across files of the same kind

Do not stop at one-line summaries. The point is to understand what later loaders or workflows would actually consume.

## Phase 3: Validate entity keys and relationship joins

For likely entity files, check:

- duplicate primary keys
- null or empty IDs
- whitespace, prefix garbage, or sentinel values in IDs
- whether the file grain is really one row per entity

For likely deterministic relationship files, check:

- source and target key columns exist
- foreign keys actually resolve against the referenced entity files
- duplicate `(from, to, relationship_type)` rows
- whether the file grain is really one row per relationship

Across files, check:

- shared join columns exist where expected
- values actually overlap
- types are compatible
- normalization work is needed before joins can succeed

## Phase 4: Identify cleaning and transform needs

Look for:

- junk rows
- placeholders and test records
- all-null or effectively empty rows
- repeated rows caused by a secondary dimension
- text normalization issues
- encoding issues
- embedded dates, IDs, or structured values worth extracting

Keep preparation scoped to what the world-building flow will actually need. Do not over-clean for its own sake.

## Phase 5: Compare against the intended world shape

If there is already a draft config, skill output, or user-confirmed world model, compare the files against it:

- expected entity ID columns
- expected relationship join columns
- expected properties
- deterministic workflow assumptions
- obvious column rename or reshape requirements

If the current files do not support the intended world shape cleanly, say exactly what has to change before world work should continue.

## Phase 6: Produce the preparation result

End with a concrete result, not just observations.

## Output

Report:

- `readiness`: `ready` | `ready_with_warnings` | `blocked`
- `blocking_issues`
- `warnings`
- `cleaned_files`
- `required_transforms`
- `join_or_key_risks`
- `recommended_next_step`

`recommended_next_step` should usually be one of:

- start `create-world`
- continue `fork-and-fit`
- clean specific files first
- clarify the intended world shape with the user before cleaning further
