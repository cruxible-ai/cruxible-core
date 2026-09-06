# SDK authoring friction batch

Branch: `codex/sdk-authoring-friction`, based on `7b5eea00`.
Work is isolated from the primary Playbill checkout and the projection-policy branch.

## Before and after

| Step | Before | After |
| --- | --- | --- |
| Minimal Claim call | 14 keyword arguments, including unused options | 6: subject, predicate, value, role, rationale, and one evidence choice |
| Batch Claim call | Same unused-argument ceremony | Same defaults as the singular call |
| Obtain proposal after submit | Submit, status request, construct proposal handle | Submit, then `intent.proposal`; no additional request |
| Author recommendation | Manually repeat prose into Claims and authored source | Example typed object supplies two field Claims and retained input |
| Revise recommendation | Manually assemble the changed fields | Example stages changed fields with caller-selected replacement Claim refs |
| Readable recommendation | Separately maintained prose | Example renders selected accepted Claim values, refusing missing or competing values |

The example is an application vocabulary adapter, not a new public SDK record abstraction.
It does not install a vocabulary, change admission policy, publish a governed block, or
claim Procedure execution. Its rendered string is a body for the existing publication
surface. Authored source records a recommendation; acceptance does not mean the
maintainer adopted its proposed policy.

## Review guide

1. `3dd63513`: public Claim methods default unused options. Exactly one evidence
   branch and an explicit per-Claim rationale remain required. No mutable mapping
   default; lowering, reference expectations, and program stamps are unchanged.
2. `a3bb4c74`: `Intent.proposal` reads the last observed candidate status locally.
   It is an identity handle, not fresh eligibility or approval. Explicit `status()`
   refreshes it. Prepare, reprepare, rebase, and submit invalidate the prior association
   before remote mutation, including uncertain failures. The public approval example
   consumes the new handle and concise Claim calls.
3. `7acf097d`: typed recommendation example and focused checks. Caller-supplied
   typed references preserve SDK coordinate assertions. Replacements must name
   precisely the changed fields; the helper explicitly contradicts those prior Claims.
   It does not discover or resolve competing Claims. Rendering requires complete
   rows from one accepted coordinate, supplied by the caller.

## Verification

All execution used the isolated worktree with the existing Python environment and
`PYTHONPATH=src:packages/cruxible-client/src`.

- Claim default parity, SDK, and Claim identity scopes: 40 passed, 1.90 seconds.
- Expanded authoring-friction tests plus the real HTTP public approval workflow:
  14 passed, 7.42 seconds. Covers reviewed signing, acceptance, source drift, and repair.
- Recommendation example: 2 passed, final run 1.02 seconds. Covers authored source
  preservation, one-field revision, explicit replacement requirements, and derived
  prose refusal on missing, competing, unsupported, or retired Claims.
- 52 distinct tests across those overlapping runs.
- Scoped Ruff checks and formatting passed; `git diff --check` passed.
- Mypy with `--follow-imports=silent` passed for SDK and recommendation example.

No daemon performance benchmark was run. The demonstrated performance change is one
fewer HTTP status request per submit-to-review handoff; server compute is unchanged.
The record example was validated locally, not accepted into the live program instance.
Staging may read vocabulary when refs lack embedded type metadata.

## Remaining friction and next experiment

Use the adapter pattern on a small set of actual projection-policy recommendations,
then review/accept, project, revise once, and inspect the resulting state and prose.
That should determine whether a reusable record API earns its complexity.

- Vocabulary and authored-evidence admission setup remain verbose. Do not hide
  authority policy behind automatic convenience defaults.
- The caller still reconstructs a previous typed record and selects exact Claim
  replacements. Safe convenience requires retaining read coordinates and exposing
  unresolved alternatives.
- SDK diagnostics currently point into the example adapter. A reusable record API
  would need to map those back to the author's record fields.
- This does not implement first-class projection definitions, publication receipts,
  compact markers, or the proposed refresh policy. Those remain separate work.
