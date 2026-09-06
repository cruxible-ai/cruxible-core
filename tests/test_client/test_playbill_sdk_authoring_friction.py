"""Concise authoring preserves explicit evidence and lowering semantics."""

from pathlib import Path

import pytest

from cruxible_client import ClaimRole, Playbill
from tests.test_client.test_playbill_sdk import _Client, _workspace


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
