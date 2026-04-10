---
name: review-world
description: Review an existing world, inspect evaluation, queries, governed groups, feedback, and outcomes, and surface prioritized issues with the likely fix surface before making changes.
---

# Review World

Use this skill on an existing world when the goal is diagnosis, quality review, or prioritizing follow-up work.

This skill is for:

- finding structural or behavioral problems
- inspecting representative queries and receipts
- reviewing governed groups and their outputs
- spotting repeated feedback or outcome patterns
- telling the user what is wrong and what should be fixed next

This skill is not the main build flow. By default, review first and surface findings before changing config, workflows, or graph state.

## Phase 1: Establish review scope

Start by identifying:

1. what the user is worried about
2. whether the review is about:
   - graph quality
   - governed relationships
   - query quality
   - feedback or outcome patterns
   - overall world health
3. whether the world is a root world or a fork
4. which user-facing queries or downstream decisions matter most

Then inspect the current state:

```bash
cruxible world status
cruxible stats
cruxible evaluate
```

If the world is a fork, include upstream pull status in your mental model, but do not jump into pull-preview unless the review points there.

## Phase 2: Inspect the most important surfaces

Work from the surfaces that actually affect users.

### Queries and receipts

If the world has `named_queries`, run representative ones and inspect receipts:

```bash
cruxible query --query <query_name> --param key=value
cruxible explain --receipt <receipt_id>
```

Use this to answer:

- does the query answer the real user question?
- does the receipt show a believable evidence path?
- are results missing because of graph gaps, governed gaps, or query design problems?

### Governed groups

If the world uses governed relationships, inspect the review surfaces:

```bash
cruxible group list
cruxible group get --group <group_id>
cruxible group resolutions
```

Use this to answer:

- are the right relationship types being governed?
- do groups ask the right review question?
- do `thesis_facts` and `analysis_state` look well-modeled?
- are groups getting stuck, suppressed, or producing poor signals?

### Feedback and outcomes

If the world has enough history, inspect recurring review and outcome patterns:

```bash
cruxible analyze-feedback --relationship <relationship_type>
cruxible analyze-outcomes --anchor-type <receipt|resolution> --surface-type <query|workflow|operation> --surface-name <name>
```

Use whichever filters match the review surface you are investigating. Treat these as evidence about recurring process failures, not as automatic instructions to mutate the world.

## Phase 3: Classify findings by fix surface

Do not just list problems. For each real issue, classify where the fix belongs:

- `prepare-data`: source file quality, key issues, join issues, grain issues
- `create-world`: base graph shape, canonical workflow design, governed design, named queries, or feedback/outcome structure in a root world
- `fork-and-fit`: local fit boundary, local canonical fit, local governed additions, local queries, or fork pull-compatibility issues
- provider or workflow implementation
- query design
- review policy, trust, feedback, or outcome configuration
- upstream work rather than local work

This classification is the main value of the review.

## Phase 4: Prioritize what matters

Present findings in this order:

1. broken or invalid states
2. query failures or misleading query results
3. governed-group design or workflow problems affecting important decisions
4. repeated review or outcome patterns that indicate a real systemic issue
5. missing relationships or coverage gaps
6. cleanup or simplification opportunities

Do not bury the important issues under low-value polish.

## Phase 5: Surface the review to the user

Default output is a prioritized findings report.

For each finding, include:

- what is wrong
- why it matters
- representative evidence
- the likely fix surface
- whether it should be fixed now, later, locally, or upstream

If there are no meaningful issues, say that explicitly and mention any residual blind spots, such as:

- no governed history yet
- no representative query receipts yet
- too little feedback or outcome data to infer patterns

## Optional Follow-Up

Only move from review into changes if the user asks for fixes or clearly wants you to continue.

If the next step is clear:

- use `prepare-data` for source-data issues
- use `create-world` for root-world build or redesign work
- use `fork-and-fit` for local adaptation work
