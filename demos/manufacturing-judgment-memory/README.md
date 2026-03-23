# Manufacturing Judgment Memory

Recipe-first internal manufacturing model for turning spreadsheet logic and
one-off operational decisions into governed company memory.

## What this models

The config splits state into two layers:

- **Operational backbone**
  - parts, revisions, assemblies, plants, lines, tools, specs, suppliers,
    materials, processes, lots, shipments, change orders, deviations, defects
- **Accepted judgment layer**
  - alternates
  - plant and line qualifications
  - customer approvals
  - waivers and blocking constraints
  - suspected defect causes
  - impacted shipments
  - reinspection requirements
  - safe substitutions and non-interchangeability decisions

The intended deterministic inputs come from internal ERP, PLM, MES, and QMS
exports. The intended governed state is the company-specific judgment layer
that would otherwise live in spreadsheets, emails, tickets, and tribal
knowledge.

## Why it exists

This is not a flagship public world model. It is a recipe-shaped demo that
captures a promising enterprise pattern:

- stable operational backbone
- accepted operational judgments as typed relationships
- scope on those judgments
- lineage for why the company believes them
- downstream impact analysis over trusted state

That makes each resolved decision a reusable input for the next one.

## Example queries

- `where_can_revision_run`
- `approved_alternates_for_revision`
- `change_blast_radius`
- `defect_traceback`
- `reinspection_queue`
- `blocked_revisions_for_spec`

## Notes

- This config is intentionally **internal-data-first**.
- It does not assume rich public seed data.
- It is a strong recipe candidate, not the ideal public flagship.
