# Searchable floor and portable views

The v3 floor is the default export. It provides a complete textual baseline for
**live accepted Claim statements**, with bounded discovery summaries beside it.
Acceptance records a statement; it does not make that statement a current,
uncontested, supported verdict.

| Scope | Included | Deliberately absent |
|---|---|---|
| `current/<subject-kind>/<subject-id>.json` | Every live Claim's full statement, literal values, roles, qualifiers, identity, artifact digest, latest-change sequence; competing values remain separate | CAS body expansion; retired revisions; inferred consensus |
| `subjects/`, `claim-types/` | Existing bounded profiles and vocabulary cards | Completeness of value previews |
| `provenance/changes/<sequence>.json` | One record per change behind a current Claim revision; accepted candidate/actor/paths; separately attributed review rationale when retained | Full evaluations; rejected proposal history; an inference that a proposal's prose was adopted |
| `provenance/snapshot.json` | Accepted Git OID, immutable review-note snapshot, availability | Authoring-intent exhaust |
| `documents/`, `procedures/` | Existing floor cards under their existing access rules | Arbitrary source bodies; complete Query/Procedure definitions |

Start a grep in `current/`; search `provenance/` when asking why a current
revision was introduced. Search both when discovering concepts without knowing
the schema. Use the normal authorized reads to expand evidence, exact-content
objects, definitions, and historical revisions. A miss in the floor is not proof
that those other surfaces lack the information.

A rationale modeled as a Claim value is present in full. A per-Claim authoring
rationale that exists only in an operational intent is not silently recovered or
presented as governed state. The export explicitly discloses that limitation.
Review rationale is associated through canonical admission/evaluation note pairs,
accepted candidate digest, and actor binding. Multiple qualifying proposals remain
multiple attributed contexts; the exporter does not choose one as the adopted reason.

## Rebuild and access

The signed accepted ledger/tree remains the authority for Claim state. Review
notes are a separate retained Git context surface. The root manifest binds both
sets of exported bytes, and `provenance/snapshot.json` identifies the two inputs.
To reproduce an export, call `export_playbill_floor(..., at=coordinate,
format_version=3, review_notes_oid=pinned_notes_oid)`. If the snapshot records no
notes, pass `review_notes_oid="absent"`; omission means resolve the current note
ref. Missing retained objects prevent exact recovery and must not be substituted.

Format 2 remains explicitly exportable and byte-identical to its frozen algorithm.
The client verifies either format, including the original digest domain. New
workspace configurations select v3. No existing receipt or digest is recomputed
under a new rule.

The export never reads evidence or exact-content bodies. Its caches are scoped
by accepted coordinate and body access profile; review context has a separate
immutable key. Explicit external reader overrides bypass these caches. At most
two entries are retained per cache, with 32 MiB serialized size admission limits
for export/structure entries and a 64 MiB review snapshot read ceiling. History
indexes fold generation records and reuse an already indexed ancestor; they do
not reconstruct historical artifact trees. Full historical export and scoped
materialization remain later work.

An unchanged workspace refresh verifies every file and keeps the directory in
place. A changed refresh stages a complete replacement, copies verified unchanged
files preserving their timestamps, verifies the copies, then swaps directories.
Local corruption, stale files, and file symlinks are repaired. The ledger never
depends on this directory or these caches.

## Author once, refresh a view

The agent supplies the prose and chooses its backing Claims or Queries. Core
contains no prose renderer. For an already catalogued source with a declared or
bootstrap block:

```python
stamp = pb.block.repin(
    "project.roadmap", "priorities",
    claims=current_claim_refs,
    body=agent_authored_markdown,  # UTF-8 text or bytes, ending in LF
    compact=True,
    evaluation_time=now,
)
```

This reads backing state, validates the whole block, retains local manifest bytes,
and replaces the block body and opening marker using a whole-file compare-and-swap.
Surrounding bytes remain intact. Omit `body` to preserve prose. Later repins
preserve compact format. `block.sync(check=True)` reports drift; it does not render
a replacement. Existing inline markers remain readable and are still the default
when `compact` is omitted on an inline/bootstrap block.

A compact opening has the form:

```markdown
<!-- playbill:block:priorities:ref:sha256:<full-64-character-digest> -->
```

The full digest commits the canonical, existing `ProjectionBlockStampV1` bytes,
including source/block identity, coordinate, backing choices, and body digest.
The reference is an additive envelope around that unchanged declaration format;
old inline bytes and stamp commitments are unchanged. A known source must match
the resolved declaration, and offline discovery learns its identity from that
same verified manifest. The closing marker is unchanged.

The manifest lives at `.playbill/manifests/<digest-hex>.json`. Shared parsing takes
an explicit bounded manifest map. Missing/corrupt manifests, identity substitution,
and exceeded limits refuse resolution. Such blocks remain excluded from
independent source evidence even when their manifests cannot be resolved. SDK
selection, sync, workspace observations, and server coverage use the same parser.
Shared mechanical framing supports compact output explicitly; existing callers
retain their inline output unless they request the new envelope.

## Transfer and durable retention

```python
from cruxible_client import ProjectionPackage

package = pb.block.package("project.roadmap")
archive = package.to_bytes()
ProjectionPackage.from_bytes(archive).install(other_workspace, "roadmap.md")

# To retain this exact authored view through governed state, stage the value
# in an ordinary reviewed Claim with your accepted exact-content ClaimType:
value = package.retention_value()
# changes.claim(subject=..., predicate=..., value=value, role=..., rationale=...,
#               supported_by=... or self_source=... under the applicable policy)
```

The archive includes the page and exactly its referenced manifests. Staging a
value is not acceptance. Only an accepted exact-content Claim and retained CAS
body provide ledger-backed recovery of this authored package. Recover the bytes
through the normal authorized exact-content read, then `from_bytes(...).install(...)`.
Local manifests and operational block declarations alone do not provide that
promise. Routine refresh remains an attributed declaration operation; archival
checkpoints use the ordinary governed loop when durable exact prose is wanted.
Installing a package restores its files; it does not register the source or
silently adopt the archived backing state in another instance.
