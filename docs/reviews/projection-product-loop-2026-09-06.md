# Live projection product loop

The complete loop succeeded in the shared program instance: author two typed
recommendations, review and accept, read and project, test discovery, revise from
the observation, detect the stale view, then refresh the same view from accepted
state. Recommendations remain proposed policy; no priorities were adopted.

Branch: `codex/projection-product-loop`, based on the SDK friction branch.
The daemon remained at `7b5eea00`; no Core deployment or implementation changed.

## Observed result

Four normative Claims retain two rules and their explanations. The first proposal
also creates two Subjects and two explicitly configured ClaimTypes. The second
proposal revises only the floor recommendation's two Claims. Their identities and
earlier evidence remain intact; the other recommendation stays at revision 1.
All four final readbacks are supported under the authored-recommendation policy.
This grade does not establish independent empirical support or maintainer adoption.

Initial accepted tree: `420e55c50c463741500915e2948464759bedd1ef`.
Final accepted tree: `968e294fcee5b1a87946b4142cb2173bf33971ea`.
The main project's derived floor was also refreshed to this coordinate in 6.54 s,
so subsequent work in the canonical checkout can discover the new Subjects.
Both exact candidates received same-agent manager review, not independent review
or a cryptographic approval. The existing authority policy required no approval
attestations. No instance authority policy or existing vocabulary was changed.

Searching the first exported floor with `rg --hidden --no-ignore -n -F` found
no occurrence of “discovery without schema knowledge” across 443 files. The same
phrase was present in the accepted rationale and the agent-authored working view.
Both new Subject profiles declared `object_preview_omitted`. This supports a
specific coverage limitation, not a claim that the floor is generally useless.
The exact observation was committed in `9de98f3a` before proposing the revision.

The revised recommendation preserves compact floor profiles for orientation and
proposes permission-aware searchable expansion of full values and explanations.
Agent-chosen projections remain the preferred task-oriented reading surface.
Neither recommendation implements this proposed expansion or refresh policy.

Before republication, the targeted check returned `block_backing_changed` and
named exactly the two revised Claims. It did not change the old page. The author
then regenerated the body from current accepted values, repinned, and checked it
again: one unchanged block, four backings, no refusals. This checks backing and
byte integrity; it is not a general proof of prose correctness.

## Measured stages

These are single live observations, not controlled performance comparisons.
The first write has eight members including vocabulary; the second has two.

| Stage | First pass | Revision pass |
| --- | ---: | ---: |
| Prepare | 2.69 s | 1.08 s |
| Submit | 12.69 s | 6.35 s |
| Candidate review | 0.54 s | 0.50 s |
| Accept | 13.42 s | 11.21 s |
| Read four accepted Claims | 0.85 s | 0.83 s |
| Repin working view | 1.91 s | 1.66 s |
| Export and materialize floor | 5.97 s | 6.50 s |
| Check refreshed block | 0.59 s | 0.007 s |

The revision pass also read the prior accepted values in 0.83 s and detected the
stale block in 0.48 s. Connections took roughly 2.0–2.3 s warm; the first connection
after each acceptance took 6.8–6.9 s. Fresh review rechecks added about 0.82 s.
The 7 ms check follows repinning in the same client and is a warm result.

## Customer feedback

The second pass reused the vocabulary, Claim identities, original explanation,
and projection layout. I changed the recommendation as a typed record and did
not separately rewrite its Markdown explanation. That is the intended benefit.

Setup remains too large. The operational driver handles credentials, workspace
attachment, source catalog, vocabulary admission, exact candidate checks, timing,
and evidence persistence. That harness is not a claim that ordinary authoring
requires hundreds of lines, but it exposes integration work a comfortable
project-management workflow should provide once.

One concrete friction was fixed: the recommendation adapter now accepts an
existing ChangeSetDraft, so vocabulary, Subjects, and records compose in one
proposal. Three focused example tests passed; scoped Mypy and Ruff passed.

Remaining priorities exposed by this exercise:

1. Define the floor's searchable-expansion contract, preserving access boundaries
   and its role as baseline discovery.
2. Make attaching and maintaining an agent-chosen view a reusable SDK workflow.
   Correct attachment made targeted checks work here; the earlier scratch example
   lacked it and received `workspace_not_attached`.
3. Keep reducing recurring submission/acceptance cost: the two-Claim revision
   still spent 17.56 s there, excluding preparation, review, and connections.
4. Finish compact markers. The opening marker is 2,152 bytes: 57% of the final
   3,788-byte page. This is the previously identified deferred work.
5. Improve authored-evidence and record ergonomics: explicit vocabulary admission
   currently requires rebuilding a ClaimType contract; revision-target selection
   and field-level diagnostics still need application glue. The observation hash
   also appears in prose because this adapter has no separate basis field.

The computation here was ordinary Python and shell work. It was not a Playbill
Procedure run or production Reading emitter. The search observation is retained
in Git; the authored recommendation and its explanation are retained as self-source
evidence in Playbill. This distinction remains important for the Procedure track.

## Artifacts

- Current working view:
  `/private/tmp/playbill-projection-loop-workspace/projection-policy.md`.
- Operational workspace/config, full reviews, and phase state:
  `/private/tmp/playbill-projection-loop-workspace/`.
- Committed machine-readable results:
  [projection-product-loop-results-2026-09-06.json](projection-product-loop-results-2026-09-06.json).
- Committed search observation:
  [projection-loop-first-observation-2026-09-06.json](projection-loop-first-observation-2026-09-06.json).
- Operational driver:
  [project_policy_loop.py](../examples/project_policy_loop.py).

The working view remains in its attached workspace. No duplicate stamped page
was committed. The code/example branch is committed separately and not merged.
