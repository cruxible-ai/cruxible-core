# Code Review

## Verdict

Approved with comments. Implementer self-review; not independent approval.
Integration includes the floor/compact-package review in
`grep-surfaces-v1-2026-09-06.md`, the SDK authoring work from the branch base,
and two fixes: `baee80ef` and `5f31f4ad`.

## Manual Review Priority

P1: shared projection parsing and SDK recovery across uncertain remote outcomes.

## Scope Reviewed

`7b5eea00..5f31f4ad`, branch `codex/grep-surfaces-v1`. Canonical playbill and
origin/playbill remained at the base during review. The measurement track is
outside this integration. No tracked canonical edits or unrelated untracked
files are included.

## Findings

No unresolved blocking findings. A valid compact block adjacent to an unstamped
draft previously caused observation validation to fail. The adapter now permits
bootstrap blocks during observation, matching inline behavior; authoritative
publication checks remain unchanged. Regression failed before the fix.

The SDK now reopens existing authoring intents through the existing resume
endpoint. It restores latest revision, persisted preflight and observed candidate
identity without preparing or submitting again. Local source-map locations and
response-only lint are explicitly unavailable after restart.

## Complexity Assessment

Recovery performs one existing GET, with no additional status read. Server intent
refresh costs still depend on the underlying lifecycle; this is not a claim of
constant time. The floor cache improvements retain the previously documented
cold reconstruction cost. Larger-instance submit/accept latency remains open.

## Architecture Assessment

Ledger authority and frozen receipt algorithms are preserved. Recovery restores
an operational handle, not acceptance authority. Review tokens are process-local
and must be reacquired before signing in a new process. No new wire schema,
renderer, signing policy, or cache authority was introduced by recovery.

## Test Coverage Assessment

- Compact observation, SDK authoring, example, HTTP approval, observations and
  coverage adapter: 60 passed.
- Recovery, full SDK and real HTTP review/repair integration: 51 passed.
- Ruff and focused mypy passed; diff whitespace checks passed.
- Both wheels built offline and installed into separate clean environments.
- Client-only process had no Core or test imports. Full source-backed claim,
  independent-signature approval, acceptance, drift and repair loop passed.
- Four further installed-client processes prepared, resumed/submitted, recovered
  the proposal/reviewed/approved/accepted, and recovered acceptance/read back the
  third revision/refreshed the configured floor. No proposal ID crossed the
  submission-process checkpoint. The same intent recovered its proposal.

These are named scopes, not a full suite; test counts overlap earlier runs.
Installed dependency resolution also exercised Pydantic 2.13.5 and cryptography
50.0.1. The disposable daemon's transport authentication was disabled; managed
authentication is a separate deployment check.

## Documentation Assessment

Client README documents recovery, missing process-local information, and explicit
review/acceptance boundaries. Raw installed measurements accompany this review
in `sdk-recovery-installed-2026-09-06.json`.

## Overall Contribution

The installed small-world loop took 5.014 s for two governed revisions and repair.
A third revision across process boundaries took 0.967 s to submit and 0.953 s to
accept; reopening took 2–8 ms. Actual floor export/installation took 78 ms first,
20 ms warm. These are single local samples, not project-world or production SLOs.

## Open Questions

No maintainer design ruling needed for this integration. Larger project-world
write latency still needs fresh profiling; existing cold floor cost is disclosed.

## Suggested Follow-Ups

Deploy matching SDK and daemon; record the resulting project-instance coordinate
and actual managed workflow timing. Profile on a private instance copy before
changing the expensive write stages. Lifecycle hooks remain proposed follow-up.
