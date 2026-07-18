from __future__ import annotations

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from audit_compiler.models import (
    AdmissionReason,
    AdmissionReasonCode,
    AdmissionSignals,
    CounterEvidenceSearch,
    CounterTest,
    CounterTestOutcome,
    ReplayBinding,
    ReplayInput,
    ReplaySpecification,
)

EVIDENCE_A = UUID("00000000-0000-0000-0000-000000000001")
EVIDENCE_B = UUID("00000000-0000-0000-0000-000000000002")


def test_counter_test_has_explicit_canonical_outcomes() -> None:
    assert {outcome.value for outcome in CounterTestOutcome} == {
        "present",
        "searched_absent",
        "unknown",
        "not_executed",
        "not_applicable",
        "conflicting",
    }


def test_legacy_absent_is_parsed_as_unknown() -> None:
    counter = CounterTest.model_validate(
        {"name": "reversal", "outcome": "absent", "detail": "legacy record"}
    )
    assert counter.outcome == CounterTestOutcome.UNKNOWN
    assert json.loads(counter.deterministic_json())["outcome"] == "unknown"


def test_searched_absent_requires_replayable_search_metadata() -> None:
    with pytest.raises(ValidationError, match="search metadata"):
        CounterTest(name="reversal", outcome="searched_absent", detail="none found")

    counter = CounterTest(
        name="reversal",
        outcome="searched_absent",
        detail="none found",
        search=CounterEvidenceSearch(
            scope="all journal entries",
            method="reference equality",
            searched_sources=("journals.csv", "payments.csv"),
            evidence_ids=(EVIDENCE_B, EVIDENCE_A),
        ),
    )
    assert counter.search is not None
    assert counter.search.evidence_ids == (EVIDENCE_A, EVIDENCE_B)


def test_admission_signals_default_conservatively() -> None:
    assert AdmissionSignals().model_dump() == {
        "conflicting_evidence": False,
        "material_uncertainty": False,
        "accounting_judgement": False,
        "incomplete_supporting_evidence": False,
    }


def test_replay_metadata_serializes_deterministically() -> None:
    replay = ReplaySpecification(
        engagement_id="eng-1",
        run_id="run-1",
        control_id="vendor-sod",
        control_version="2",
        runtime_version="0.1.0",
        inputs=(ReplayInput(name="z", value="2"), ReplayInput(name="a", value="1")),
        evidence_ids=(EVIDENCE_B, EVIDENCE_A),
        bindings=(
            ReplayBinding(name="vendor", evidence_id=EVIDENCE_B),
            ReplayBinding(name="amount", evidence_id=EVIDENCE_A),
        ),
    )
    payload = json.loads(replay.deterministic_json())
    assert [item["name"] for item in payload["inputs"]] == ["a", "z"]
    assert payload["evidence_ids"] == [str(EVIDENCE_A), str(EVIDENCE_B)]
    assert replay.deterministic_json() == replay.deterministic_json()


def test_admission_reasons_are_machine_readable() -> None:
    reason = AdmissionReason(
        code=AdmissionReasonCode.MATERIAL_UNCERTAINTY,
        detail="valuation range is material",
        evidence_ids=(EVIDENCE_B, EVIDENCE_A),
    )
    assert reason.model_dump(mode="json")["code"] == "material_uncertainty"
    assert reason.evidence_ids == (EVIDENCE_A, EVIDENCE_B)
