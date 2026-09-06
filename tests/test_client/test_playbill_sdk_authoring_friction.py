"""Concise authoring preserves explicit evidence and lowering semantics."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from cruxible_client import ClaimRole, Playbill
from cruxible_client import contracts as api
from tests.test_client.test_playbill_sdk import _COORDINATE, _Client, _workspace


@pytest.fixture
def pb(tmp_path: Path):
    _workspace(tmp_path)
    return Playbill._from_client(_Client(), instance_id="inst_test", workspace=tmp_path)


def claim_args():
    return dict(
        subject="sec.vuln/cve-2026-0001",
        predicate="sec.vuln.affects_package",
        value="sec.package/demo",
        role=ClaimRole.OBSERVATION,
        rationale="Record observed package.",
    )


@pytest.mark.parametrize("batch", [False, True])
def test_omitted_options_preserve_payload_expectations_and_stamp(pb, batch):
    def build(**options):
        target = pb.changes(rationale="Package observation") if batch else pb
        result = target.claim(**claim_args(), self_source="affected package", **options)
        return result._compiled() if batch else result

    concise = build()
    explicit = build(
        supported_by=None,
        copied_from=None,
        qualifier=None,
        effective_period=None,
        revises=None,
        dispositions={},
        subject_definition=None,
        claim_type_definition=None,
    )
    assert concise.payload == explicit.payload
    assert concise.reference_expectations == explicit.reference_expectations
    assert concise.program_stamp == explicit.program_stamp


@pytest.mark.parametrize("batch", [False, True])
def test_evidence_choice_and_claim_rationale_remain_required(pb, batch):
    target = pb.changes(rationale="Whole change rationale") if batch else pb
    with pytest.raises(ValueError, match="exactly one"):
        target.claim(**claim_args())
    args = claim_args()
    del args["rationale"]
    with pytest.raises(TypeError, match="rationale"):
        target.claim(**args, self_source="affected package")


def test_proposal_uses_submit_result_without_status_read(pb, monkeypatch):
    intent = pb.claim(**claim_args(), self_source="affected package").prepare()
    assert intent.proposal is None
    status = api.PlaybillCandidateStatus(
        state="ready_to_activate",
        proposal_id="proposal-one",
        current_accepted_coordinate=_COORDINATE,
    )
    calls = []

    def submit(*args):
        calls.append("submit")
        return api.PlaybillAuthoringSubmitResult(intent=intent._raw, status=status)

    def refresh(*args):
        calls.append("status")
        return status.model_copy(update={"proposal_id": "proposal-two"})

    monkeypatch.setattr(pb._client, "submit_playbill_authoring_intent", submit, raising=False)
    monkeypatch.setattr(pb._client, "playbill_authoring_intent_status", refresh, raising=False)
    intent.submit()
    original = intent.proposal
    assert original.proposal_id == "proposal-one"
    assert intent.proposal.proposal_id == "proposal-one"
    assert calls == ["submit"]
    intent.status()
    assert intent.proposal.proposal_id == "proposal-two"
    assert original.proposal_id == "proposal-one"
    assert calls == ["submit", "status"]


@pytest.mark.parametrize("operation", ["prepare", "reprepare", "rebase", "submit"])
@pytest.mark.parametrize("fails", [False, True])
def test_mutations_clear_previous_candidate_even_on_uncertain_failure(
    pb, monkeypatch, operation, fails
):
    draft = pb.claim(**claim_args(), self_source="affected package")
    intent = draft.prepare()
    intent._candidate_status = api.PlaybillCandidateStatus(
        state="ready_to_activate", proposal_id="old", current_accepted_coordinate=_COORDINATE
    )
    methods = {
        "prepare": "preflight_playbill_authoring_intent",
        "reprepare": "compile_playbill_authoring",
        "rebase": "rebase_playbill_authoring_intent",
        "submit": "submit_playbill_authoring_intent",
    }

    def response(*args, **kwargs):
        if fails:
            raise TimeoutError("Remote outcome unknown")
        if operation in ("prepare", "reprepare"):
            return intent._preflight
        return SimpleNamespace(intent=intent._raw, status=None)

    monkeypatch.setattr(pb._client, methods[operation], response, raising=False)
    options = {"draft": draft} if operation == "reprepare" else {}
    if fails:
        with pytest.raises(TimeoutError):
            getattr(intent, operation)(**options)
    else:
        getattr(intent, operation)(**options)
    assert intent.proposal is None
