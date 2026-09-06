"""Resumable project-state exercise; public SDK, explicit review, existing custody."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from cruxible_client import ClaimRef, Playbill
from cruxible_client.authoring.insertions import replace_publication_file
from cruxible_client.contracts.artifacts import ArtifactLifecycle
from cruxible_client.contracts.captures import (
    COORDINATOR_SELF_SOURCE_CAPTURE_CONTRACT,
    capture_contract_digest,
)
from cruxible_client.contracts.policies import (
    ClaimAdmissionPolicyV1,
    ClaimEvidenceAdmissionPolicyV1,
    ClaimEvidenceAdmissionRuleV1,
    ClaimResolutionPolicyV1,
)

REPO = Path(__file__).resolve().parents[2]
WORK = Path("/private/tmp/playbill-projection-loop-workspace")
STATE = WORK / "loop.json"
INSTANCE = "inst_ebe8a0b27e50487d"
SOCKET = Path.home() / ".cruxible-dogfood-hr/daemon.sock"
KIND = "dev.recommendation"
IDS = ("projection-floor-20260906", "projection-working-views-20260906")
FIELDS = ("rule", "rationale")
SOURCE = "program-projection-product-loop-20260906"
BLOCK = "projection-policy-recommendations"
EXAMPLE = runpy.run_path(str(REPO / "packages/cruxible-client/examples/authored_recommendation.py"))
Recommendation, stage, render = (EXAMPLE[key] for key in ("Recommendation", "stage", "render"))


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def timed(state, name, call):
    start = time.perf_counter()
    try:
        return call()
    finally:
        elapsed = time.perf_counter() - start
        state.setdefault("timings", {})[name] = elapsed
        save(STATE, state)
        print(json.dumps({"stage": name, "seconds": elapsed}), flush=True)


def connect(state, phase):
    secret = (Path.home() / ".cruxible/auth/playbill-state-manager.txt").read_text()
    token = re.search(r"[A-Za-z0-9_.-]{30,}", secret)
    if token is None:
        raise ValueError("Manager token unavailable")
    os.environ.setdefault("CRUXIBLE_CLIENT_TIMEOUT_S", "1800")
    return timed(
        state,
        phase + ".connect",
        lambda: Playbill.connect(
            target="unix:" + str(SOCKET),
            instance=INSTANCE,
            token=SecretStr(token.group()),
            workspace=WORK,
            context=WORK / "unused-context.json",
        ),
    )


def definition(pb, field):
    definition = pb.claim_type(
        predicate=KIND + "." + field,
        subject_kinds=(KIND,),
        object_kind="literal",
        value_schema={"type": "string", "minLength": 1},
        object_subject_kinds=(),
        cardinality="one",
        permitted_roles=("normative",),
        referent_sensitivity="identity",
        sources=(),
        admission_policy=ClaimAdmissionPolicyV1(),
        resolution_policy=ClaimResolutionPolicyV1(
            cardinality="one", eligible_verdicts=("supported",), selector="only_contender"
        ),
        pins=(),
        evidence_freshness=None,
    ).definition
    # Explicit authored-recommendation admission, matching the manager's roadmap
    # pattern. No instance authority policy or existing ClaimType changes.
    policy = ClaimEvidenceAdmissionPolicyV1(
        rules=(
            ClaimEvidenceAdmissionRuleV1(
                rule_id="authored-recommendation",
                claim_roles=("normative",),
                capture_contract_digests=(
                    capture_contract_digest(COORDINATOR_SELF_SOURCE_CAPTURE_CONTRACT).tagged,
                ),
                evidence_kinds=("self_asserted",),
                admission="direct",
                subject_binding="exact_claim_subject",
            ),
        )
    )
    return type(definition).model_validate(
        {
            **definition.model_dump(mode="json"),
            "evidence_admission_policy": policy.model_dump(mode="json"),
        }
    )


def submit(pb, state, phase, change, records):
    assert phase not in state, "Existing phase; inspect and resume instead of duplicating"
    state[phase] = {"base": pb.coordinate.model_dump(mode="json"), "records": records}
    intent = timed(state, phase + ".prepare", change.prepare)
    state[phase]["intent_id"] = intent.intent_id
    state[phase]["preflight"] = {
        "refused": intent.refused,
        "diagnostics": [asdict(d) for d in intent.diagnostics],
    }
    save(STATE, state)
    assert not intent.refused, state[phase]["preflight"]
    timed(state, phase + ".submit", intent.submit)
    proposal = intent.proposal
    assert proposal is not None
    state[phase]["proposal_id"] = proposal.proposal_id
    save(STATE, state)
    reviewed = timed(state, phase + ".review", proposal.review)
    details = reviewed.details.model_dump(mode="json")
    save(WORK / (phase + "-review.json"), details)
    state[phase]["candidate_digest"] = details["candidate_digest"]
    save(STATE, state)
    print(
        json.dumps(
            {
                "proposal_id": proposal.proposal_id,
                "candidate": details["candidate_digest"],
                "members": len(details["members"]),
            }
        ),
        flush=True,
    )


def prepare_first(state):
    pb = connect(state, "first")
    world = timed(state, "first.world", pb.world)
    assert KIND not in world.kinds, "Reconcile an existing vocabulary before bootstrapping"
    change = pb.changes(
        rationale=(
            "Record agent recommendations for useful grep surfaces; "
            "no adoption or dispatch of policy."
        )
    )
    fields = {field: change.claim_type(definition(pb, field)) for field in FIELDS}
    records = {
        IDS[0]: Recommendation(
            (
                "Keep the deterministic floor as the baseline discovery surface and asses"
                "s whether its compact profiles let agents find the explanations they nee"
                "d before expanding the floor contract."
            ),
            (
                "Playbill should let an agent begin with a phrase rather than a predicate"
                ". The floor provides a stable starting point; test whether the phrase 'd"
                "iscovery without schema knowledge' remains searchable when a recommendat"
                "ion includes a substantial explanation. This is an authored recommendati"
                "on, not a claim that the floor is complete."
            ),
        ),
        IDS[1]: Recommendation(
            (
                "Let agents choose and maintain their own task-oriented grep surfaces thr"
                "ough projections, with receipted routine refresh and governed review whe"
                "n the accepted definition requires it."
            ),
            (
                "A design notebook organized by questions or a roadmap organized by produ"
                "ct loops can cross many Subjects and predicates. Derive those working vi"
                "ews from the same authored state, preserve useful explanation, and avoid"
                " a separate extraction pass after writing Markdown. The refresh policy r"
                "eflects the maintainer's stated direction; this record recommends the wo"
                "rkflow and does not implement it."
            ),
        ),
    }
    for sid, record in records.items():
        subject = change.subject(
            pb.subject(subject=KIND + "/" + sid, pins=(), lifecycle=ArtifactLifecycle())
        )
        assert stage(change, subject, fields, record) is change
    submit(pb, state, "first", change, {sid: asdict(r) for sid, r in records.items()})
    pb.close()


def accept(state, phase):
    entry = state[phase]
    assert "activation" not in entry and not entry.get("activation_attempted"), (
        "Reconcile a previous activation attempt first"
    )
    review = json.loads((WORK / (phase + "-review.json")).read_text())
    approval = json.loads((WORK / (phase + "-review-check.json")).read_text())
    assert approval["candidate_digest"] == review["candidate_digest"] and approval["approved"]
    pb = connect(state, phase + ".accept")
    assert pb.coordinate.git_oid == review["base_oid"], "Base moved; reconcile before activation"
    current = timed(
        state, phase + ".review_recheck", pb.proposal(entry["proposal_id"]).review
    ).details
    assert current.candidate_digest == review["candidate_digest"]
    entry["activation_attempted"] = True
    save(STATE, state)
    receipt = timed(state, phase + ".accept", lambda: pb.accept(entry["proposal_id"]))
    entry["activation"] = receipt.model_dump(mode="json")
    save(STATE, state)
    assert receipt.status == "accepted"
    pb.close()


def read_records(pb, state, phase):
    world = timed(state, phase + ".world", pb.world)
    rows = timed(
        state,
        phase + ".read",
        lambda: world.prefetch(
            subjects=tuple(KIND + "/" + sid for sid in IDS),
            predicates=tuple(KIND + "." + field for field in FIELDS),
        ),
    )
    assert len(rows) == 4
    fields = {field: KIND + "." + field for field in FIELDS}
    bodies = [render(f"subjects/{KIND}/{sid}.json", fields, rows) for sid in IDS]
    state[phase]["readback"] = [
        {
            **{key: value for key, value in asdict(row).items() if key != "captures"},
            "capture_digests": [capture.capture_digest for capture in row.captures],
        }
        for row in rows
    ]
    state[phase]["read_coordinate"] = pb.coordinate.model_dump(mode="json")
    expected = {**state["first"]["records"], **state[phase]["records"]}
    for row in rows:
        sid = row.subject.rsplit("/", 1)[1].removesuffix(".json")
        assert row.value == expected[sid][row.predicate.rsplit(".", 1)[1]]
    return world, rows, bodies


def observe(state, phase):
    pb = connect(state, phase + ".observe")
    assert (
        pb.coordinate.model_dump(mode="json") == state[phase]["activation"]["accepted_coordinate"]
    )
    _, rows, bodies = read_records(pb, state, phase)
    page = WORK / "projection-policy.md"
    content = (
        "# Projection policy working notes\n\nAccepted agent recommendations; propo"
        "sed policy is not adopted by this publication.\n\n"
    )
    content += (
        f"<!-- playbill:block:{BLOCK} -->\n"
        + "\n".join(bodies)
        + f"<!-- /playbill:block:{BLOCK} -->\n"
    )
    if page.exists():
        previous = page.read_bytes()
        save(
            WORK / (phase + "-prior-publication.json"),
            {"sha256": hashlib.sha256(previous).hexdigest()},
        )
        replace_publication_file(page, expected=previous, replacement=content.encode())
    else:
        with page.open("x") as out:
            out.write(content)
    stamp = timed(
        state,
        phase + ".repin",
        lambda: pb.block.repin(
            SOURCE,
            BLOCK,
            claims=tuple(row.claim_id for row in rows),
            evaluation_time=datetime.now(UTC),
        ),
    )
    state[phase]["stamp"] = stamp.model_dump(mode="json")
    floor = timed(state, phase + ".floor_refresh", lambda: pb.refresh_workspace(at=pb.coordinate))
    state[phase]["floor"] = floor.model_dump(mode="json")
    save(STATE, state)
    assert floor.status == "refreshed", floor
    result = timed(
        state, phase + ".block_check", lambda: pb.block.sync("projection-policy.md", check=True)
    )
    state[phase]["block_check"] = result.model_dump(mode="json")
    save(STATE, state)
    assert not result.has_refusals and len(result.items) == 1
    assert result.items[0].outcome == "unchanged"
    pb.close()


def prepare_revision(state):
    evidence_path = REPO / "docs/reviews/projection-loop-first-observation-2026-09-06.json"
    evidence = json.loads(evidence_path.read_text())
    assert evidence["floor_matches"] == [] and evidence["projection_matches"]
    pb = connect(state, "second")
    state["second_read"] = {"records": {}}
    world, rows, _ = read_records(pb, state, "second_read")
    sid = IDS[0]
    own = {
        row.predicate.rsplit(".", 1)[1]: row
        for row in rows
        if row.subject.endswith("/" + sid + ".json")
    }
    previous = Recommendation(**{field: own[field].value for field in FIELDS})
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    record = Recommendation(
        (
            "Keep compact floor profiles for orientation, but provide a permission-aw"
            "are searchable expansion of full accepted values and explanations; let a"
            "gents choose their task-oriented projections above that baseline."
        ),
        (
            "The first live product-loop export retained four accepted recommendation"
            " Claims, yet grep found 'discovery without schema knowledge' in the agen"
            "t projection and nowhere in the exported floor. Both recommendation prof"
            "iles declared object_preview_omitted. The profiles remain useful for ori"
            "entation, but cannot supply complete prose discovery. Preserve the floor"
            "/projection split and address expansion coverage rather than adding anot"
            "her baseline system. Observation record SHA-256: "
        )
        + evidence_digest
        + ". This is a proposed response to the observed gap, not a completed implementation.",
    )
    refs = {field: ClaimRef(own[field].claim_id, world.coordinate) for field in FIELDS}
    change = stage(
        pb,
        world.kind(KIND)[sid],
        {field: world.claim_type(KIND + "." + field) for field in FIELDS},
        record,
        previous=previous,
        replacements=refs,
    )
    submit(pb, state, "second", change, {sid: asdict(record)})
    pb.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "accept", "observe", "revise"))
    parser.add_argument("--phase", choices=("first", "second"), default="first")
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    state = (
        json.loads(STATE.read_text())
        if STATE.exists()
        else {"instance": INSTANCE, "workspace": str(WORK)}
    )
    if args.action == "prepare":
        config = WORK / ".playbill"
        config.mkdir(exist_ok=True)
        save(
            config / "coverage.json",
            {
                "tag": "playbill-coverage-workspace-config-v2",
                "instance_id": INSTANCE,
                "server_socket": str(SOCKET),
                "floor_output": {
                    "tag": "playbill-floor-output-v1",
                    "format": "playbill-floor-export-v2",
                },
            },
        )
        save(
            config / "sources.yaml",
            {
                "tag": "playbill-source-catalog-v1",
                "catalog_kind": "portable",
                "entries": [
                    {
                        "name": SOURCE,
                        "locator": "projection-policy.md",
                        "document_id": SOURCE,
                        "document_kind": "program_page",
                        "title": "Projection policy working notes",
                        "media_type": "text/markdown",
                        "governance_scope": ["dev"],
                    }
                ],
            },
        )
        prepare_first(state)
    elif args.action == "accept":
        accept(state, args.phase)
    elif args.action == "observe":
        observe(state, args.phase)
    else:
        prepare_revision(state)


if __name__ == "__main__":
    main()
