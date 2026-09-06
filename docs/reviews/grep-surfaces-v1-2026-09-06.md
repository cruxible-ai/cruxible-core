# Code Review

## Verdict

Approved with comments.

This is the implementer's self-review, not independent approval. The floor and
compact-view batches are implemented and benchmarked on an isolated branch;
the live daemon has not been deployed from this branch. Cold floor reconstruction
and explicit archival acceptance are disclosed limitations, not hidden cache or
authority dependencies.

## Manual Review Priority

- Priority: P1
- Reason: Shared projection parsing, source-evidence exclusion, and floor digest boundaries.
- Suggested Human Review Focus: Compact-reference failure handling; review rationale attribution; exact-content package recovery; accepted-coordinate cache keys.

## Scope Reviewed

- Branch: `codex/grep-surfaces-v1`, implementation base `a382331f9`.
- Floor batch: `a37c4bbb`; context cache follow-up: `24bce119`.
- Compact package and SDK body refresh: `a838c682`.
- Contract snapshot and matching SDK pin: `f64f6d61`.
- Changed files: floor service/content, instance memos, runtime and HTTP export route/request, client envelope/transport/workspace, middleware floor verifier; declared-block parser, block SDK, package import/export/install, coverage adapter/service, client public exports; focused tests and public contract snapshot.
- Untracked files: none excluded from this review; new implementation files and benchmark evidence are included in the branch.
- Tests examined: frozen floor v2, floor v3 completeness/rebuild/cache, workspace/CLI/MCP floor refresh, projection parsing/repin/sync/coverage, evidence windows, portable packages, sanctioned-writer inventory, and contract handshake.
- Commands run: named pytest scopes below; Ruff on changed Python; focused mypy; `git diff --check`. No full suite or journal golden corpus was run.

## Findings

No unresolved correctness findings. During review, fixed review-note-only cache
invalidation, explicit replay of an absent notes snapshot, manifest path checking
before directory creation, noncanonical archive encodings, and matching SDK
contract snapshot/handshake pins.

## Complexity Assessment

A first floor export still reconstructs accepted discovery state. Repeated exports
reuse bounded immutable-coordinate/access-profile entries; changing review notes
reuses accepted structure. Current-state serialization remains proportional to the
current Claims when review context is rebuilt. Review notes are read once per
snapshot, capped at 64 MiB; latest-change indexes fold generation-record suffixes
and never load historical artifact trees. Two entries per cache bound retained
coordinates; export/structure cache admission is capped at 32 MiB serialized bytes.

Local no-op refresh is linear in exported file bytes and file count: it verifies
actual contents rather than trusting a potentially stale/corrupt local manifest.
Changed installation stages a full directory and reuses verified unchanged files
by copying them with timestamps preserved; it does not share writable inodes.

Compact marker resolution is bounded by source, manifest-count, individual-manifest,
and package-byte ceilings. The full backing declaration still exists; moving it
out of a paragraph improves reading density without discarding integrity data.

## Architecture Assessment

Read in this order:

1. `service/playbill_floor_content.py`: full accepted statements grouped by Subject;
   latest change lookup; canonical note-pair association by candidate/actor; explicit
   separation of review context from accepted truth. The default excludes evidence
   bodies and operational authoring exhaust.
2. `service/playbill_floor.py` and `playbill/instance.py`: frozen v2 algorithm and v3
   composition, principal/body-access keys, independently pinned notes, bounded reuse.
3. Client workspace verification and middleware: format-aware digest verification,
   exact file installation, old-format readability and new configuration defaults.
4. `contracts/declared_blocks.py`: full-digest manifest references, shared bounded
   parser, identity checks, unchanged inline bytes, evidence windows that remain
   excluded even without a resolvable compact manifest.
5. `authoring/projection_package.py`: canonical portable archive, body/stamp verification,
   manifests retained before page write, explicit exact-content retention value.
   A local package is not an accepted Claim. Ledger recovery requires accepting
   that archive through the ordinary exact-content Claim/CAS path.
6. `authoring/blocks.py`, SDK, workspace observations and server coverage: explicitly
   supplied prose can be installed and repinned together; whole-source CAS protects
   concurrent edits; sync preserves compact format; server receives verified manifest
   bytes rather than reading client files.
7. Public contract snapshot: adds floor v3 and reconciles inherited optional floor
   refresh/ledger mirror fields already present at the branch base. The SDK handshake
   pin is updated in the same commit. Stored receipts and v2 digest domains are untouched.

Core still does not author prose or choose backing Claims. The shared mechanical
framer supports compact output explicitly; existing inline callers keep their byte
format. Package installation restores files but does not register a source or adopt
old backing state in another instance.

## Test Coverage Assessment

Passing named runs:

- Projection parser/repin/sync/observations, evidence-window exclusion, coverage adapter:
  111 tests.
- Floor v2/v3 plus initial compact package scope: 18 tests.
- Final floor v3 and package scope after cache hardening: 6 tests.
- Workspace and MCP regressions with packages: 31 tests.
- Contract snapshot and final five package tests: 21 tests.
- Sanctioned writer inventory: four tests passed in the combined architecture/contract run;
  that run initially exposed snapshot drift, then the 21-test snapshot/package run passed
  after the audited re-pin.
- Earlier client workspace/CLI floor run: 24 passing tests after updating new-format
  configuration expectations; the separate v3 regression was fixed and rerun.

Counts overlap and are not a unique-suite total. Focused mypy passed for eight changed
modules. Ruff and diff whitespace checks passed. Benchmarks exercise the full signed
program snapshot and a two-Claim accepted fixture followed by a real Query acceptance.
The latter preserved both `current/` files byte-for-byte across the unrelated generation.

## Documentation Assessment

`docs/searchable-floor-and-view-packages.md` defines searchable scopes, omissions,
expansion, replay coordinates, cache limits, compact SDK usage, and the explicit
archival acceptance boundary. The old manifest follow-up now links to that contract.
The benchmark JSON records raw samples, sizes, accepted coordinate, parity digest,
search hits, and measurement boundaries. `scripts/benchmark_playbill_floor.py` repeats
service/materialization measurements against a private copied instance.

## Overall Contribution

The floor now supports schema-free text discovery of full current values and reasons,
while an agent can maintain compact task-specific prose with a reusable SDK operation.
The program-instance search phrase that previously had no floor hit now appears in
its current rationale and associated change context. V2 bytes remain exactly identical.

| Measurement | Before | After |
|---|---:|---:|
| Warm service export, mean of two samples | 6.112 s | 0.0202 s |
| Warm verified local installation, mean of two | 0.0883 s | 0.0626 s |
| Combined measured warm work | 6.200 s | 0.0828 s |
| First service export after opening | 7.095 s | 7.463 s |
| Floor size / files | 2,754,959 B / 443 | 4,952,779 B / 865 |
| Fixed-string grep, median of ten | 11.4 ms; no hits | 15.9 ms; two hits |
| Policy-page opening marker | 2,153 B | 134 B |
| Policy-page size | 3,788 B | 1,769 B + 1,570 B manifest |

Review-context-only export took 194 ms with accepted tree reads instrumented to
refuse. The small two-Claim world exported in about 93 ms initially and 13 ms warm;
a new accepted Query kept both current Claim files byte-identical. Compact parsing
was about 0.076 ms, and a disk package read about 0.197 ms (200 samples).

These are isolated service and local filesystem measurements. They exclude HTTP
serialization/network time. Instance opening itself was about seven seconds in
the final run and is reported separately in the raw evidence. The expanded floor
is about 80% larger, but associated change context is only 132 KB; pre-existing
Subject profiles remain the largest scope at 2.53 MB.

## Open Questions

None blocking this branch's implementation. Merge/deployment is a separate action;
new SDK and daemon code should roll out together with the updated handshake pin.

## Suggested Follow-Ups

- Profile cold discovery reconstruction if first-export latency remains intrusive.
- Introduce scoped materialization/retention budgets only when larger-world evidence
  warrants them; full history remains outside the default floor.
- A higher-level accepted view-definition policy can automate when an authored
  package should be archived. This batch supplies the mechanism, not a new policy.
