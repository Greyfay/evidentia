from __future__ import annotations

from uuid import UUID

import pytest

from audit_compiler.admission import admit
from audit_compiler.casebuilder import case_dict
from audit_compiler.models import (
    AdmissionReasonCode,
    AdmissionSignals,
    CalculationInput,
    CanonicalCalculation,
    ControlOutcome,
    CounterEvidenceSearch,
    CounterTest,
    EvidenceRef,
    ReplayBinding,
    ReplayInput,
    ReplaySpecification,
    SourceType,
)


def evidence(number: int, raw: str | None = None) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=UUID(int=number),
        source_path=f"source-{number}.csv",
        source_type=SourceType.CSV_ROW,
        file_sha256=f"{number:064x}",
        raw_value=raw or str(number),
        row=number,
    )


def searched_absent(name: str, ref: EvidenceRef) -> CounterTest:
    return CounterTest(
        name=name,
        outcome="searched_absent",
        detail="No matching record found.",
        evidence=(ref,),
        search=CounterEvidenceSearch(
            scope="all records in the engagement run",
            method="exact deterministic reference match",
            searched_sources=(ref.source_path,),
            evidence_ids=(ref.evidence_id,),
        ),
    )


def outcome(
    *,
    refs: tuple[EvidenceRef, ...] | None = None,
    counters: tuple[CounterTest, ...] | None = None,
    signals: AdmissionSignals | None = None,
    replay: ReplaySpecification | None | bool = True,
    sql: str = "SELECT :amount",
    expression: str = "amount",
    inputs: tuple[CalculationInput, ...] | None = None,
    control_id: str = "control-a",
    control_version: str = "2",
    uncertainty: str | None = None,
    status: str = "candidate",
) -> ControlOutcome:
    refs = refs if refs is not None else (evidence(1), evidence(2))
    inputs = inputs if inputs is not None else (
        CalculationInput(label="amount", value="10", evidence_id=refs[0].evidence_id),
    )
    counters = counters if counters is not None else (searched_absent("reversal", refs[1]),)
    if replay is True:
        replay = ReplaySpecification(
            engagement_id="eng-1",
            run_id="run-1",
            control_id=control_id,
            control_version=control_version,
            runtime_version="schema-2/runtime-1",
            inputs=(ReplayInput(name="amount", value="10"),),
            evidence_ids=tuple(ref.evidence_id for ref in refs),
            bindings=(ReplayBinding(name="amount", evidence_id=refs[0].evidence_id),),
        )
    return ControlOutcome(
        outcome_id=UUID(int=100),
        engagement_id="eng-1",
        run_id="run-1",
        control_id=control_id,
        control_version=control_version,
        status=status,
        subject="subject-a",
        exposure_amount="10",
        calculation=CanonicalCalculation(
            expression=expression,
            inputs=inputs,
            result="10",
            sql=sql,
        ),
        evidence_refs=refs,
        counter_tests=counters,
        admission_signals=signals or AdmissionSignals(),
        replay=replay if replay is not True else None,
        uncertainty=uncertainty,
    )


def codes(candidate: ControlOutcome) -> tuple[AdmissionReasonCode, ...]:
    return tuple(reason.code for reason in admit(candidate).reasons)


def test_missing_evidence_chain_is_rejected() -> None:
    candidate = outcome().model_copy(update={"evidence_refs": ()})
    assert admit(candidate).verdict == "REJECTED"
    assert AdmissionReasonCode.EVIDENCE_CHAIN_MISSING in codes(candidate)


def test_missing_deterministic_control_is_rejected() -> None:
    candidate = outcome().model_copy(update={"control_id": ""})
    assert admit(candidate).verdict == "REJECTED"
    assert AdmissionReasonCode.CONTROL_SUPPORT_MISSING in codes(candidate)


def test_unresolved_evidence_id_is_rejected() -> None:
    bad_input = CalculationInput(label="amount", value="10", evidence_id=UUID(int=99))
    candidate = outcome(inputs=(bad_input,))
    assert admit(candidate).verdict == "REJECTED"


def test_uncited_financial_amount_is_rejected() -> None:
    candidate = outcome(inputs=())
    assert admit(candidate).verdict == "REJECTED"
    assert AdmissionReasonCode.CALCULATION_SUPPORT_MISSING in codes(candidate)


def test_missing_replay_specification_is_rejected() -> None:
    assert admit(outcome(replay=None)).verdict == "REJECTED"


def test_sql_replay_without_bindings_is_rejected() -> None:
    base = outcome()
    assert base.replay is not None
    replay = base.replay.model_copy(update={"bindings": ()})
    assert admit(base.model_copy(update={"replay": replay})).verdict == "REJECTED"


def test_expression_replay_without_cited_inputs_is_rejected() -> None:
    assert admit(outcome(sql="", inputs=())).verdict == "REJECTED"


def test_valid_replay_specification_confirms() -> None:
    assert admit(outcome()).verdict == "CONFIRMED"


def test_present_refuter_with_evidence_dismisses() -> None:
    ref = evidence(1)
    counter = CounterTest(name="correction", outcome="present", detail="corrected", evidence=(ref,))
    assert admit(outcome(counters=(counter,))).verdict == "DISMISSED"


def test_documented_searched_absent_can_confirm() -> None:
    assert admit(outcome()).verdict == "CONFIRMED"


def test_searched_absent_without_complete_search_metadata_requires_review() -> None:
    ref = evidence(1)
    search = CounterEvidenceSearch(scope="all", method="match", evidence_ids=(ref.evidence_id,))
    counter = CounterTest(
        name="reversal",
        outcome="searched_absent",
        detail="none",
        evidence=(ref,),
        search=search,
    )
    assert admit(outcome(counters=(counter,))).verdict == "HUMAN_REVIEW"


@pytest.mark.parametrize("counter_outcome", ["unknown", "not_executed"])
def test_incomplete_required_counter_tests_require_review(counter_outcome: str) -> None:
    counter = CounterTest(name="approval", outcome=counter_outcome, detail="incomplete")
    assert admit(outcome(counters=(counter,))).verdict == "HUMAN_REVIEW"


def test_unsupported_not_applicable_requires_review() -> None:
    counter = CounterTest(name="approval", outcome="not_applicable", detail="")
    assert admit(outcome(counters=(counter,))).verdict == "HUMAN_REVIEW"


def test_supported_not_applicable_is_resolved() -> None:
    ref = evidence(1)
    counter = CounterTest(
        name="approval",
        outcome="not_applicable",
        detail="No approval exists for this event type.",
        evidence=(ref,),
    )
    assert admit(outcome(counters=(counter,))).verdict == "CONFIRMED"


def test_conflicting_counter_evidence_requires_review() -> None:
    ref = evidence(1)
    counter = CounterTest(
        name="approval", outcome="conflicting", detail="conflict", evidence=(ref,)
    )
    assert admit(outcome(counters=(counter,))).verdict == "HUMAN_REVIEW"


@pytest.mark.parametrize(
    ("signals", "code"),
    [
        (AdmissionSignals(material_uncertainty=True), AdmissionReasonCode.MATERIAL_UNCERTAINTY),
        (AdmissionSignals(accounting_judgement=True), AdmissionReasonCode.ACCOUNTING_JUDGEMENT),
        (
            AdmissionSignals(incomplete_supporting_evidence=True),
            AdmissionReasonCode.SUPPORTING_EVIDENCE_INCOMPLETE,
        ),
    ],
)
def test_admission_signals_require_review(
    signals: AdmissionSignals, code: AdmissionReasonCode
) -> None:
    candidate = outcome(signals=signals)
    assert admit(candidate).verdict == "HUMAN_REVIEW"
    assert code in codes(candidate)


def test_supported_innocent_explanation_dismisses() -> None:
    ref = evidence(1)
    explanation = CounterTest(
        name="independent approval",
        outcome="present",
        detail="Independent approver cleared the event.",
        evidence=(ref,),
    )
    assert admit(outcome(counters=(explanation,))).verdict == "DISMISSED"


def test_fully_supported_candidate_confirms() -> None:
    decision = admit(outcome())
    assert decision.verdict == "CONFIRMED"
    assert codes(outcome()) == (AdmissionReasonCode.EVIDENCE_AND_CONTROLS_SUPPORT,)


@pytest.mark.parametrize("status", ["candidate", "cleared", "inconclusive"])
def test_control_status_cannot_force_a_verdict(status: str) -> None:
    assert admit(outcome(status=status)).verdict == "CONFIRMED"


def test_external_verdict_field_cannot_bypass_gate() -> None:
    candidate = outcome(replay=None)
    object.__setattr__(candidate, "verdict", "CONFIRMED")
    assert admit(candidate).verdict == "REJECTED"


def test_input_order_does_not_change_decision_or_serialization() -> None:
    refs = (evidence(1), evidence(2), evidence(3))
    counters = (searched_absent("z", refs[2]), searched_absent("a", refs[1]))
    forward = outcome(refs=refs, counters=counters)
    reverse = forward.model_copy(
        update={"evidence_refs": tuple(reversed(refs)), "counter_tests": tuple(reversed(counters))}
    )
    forward_decision = admit(forward)
    reverse_decision = admit(reverse)
    assert forward_decision.deterministic_json() == reverse_decision.deterministic_json()
    assert case_dict(forward, forward_decision) == case_dict(reverse, reverse_decision)


def test_reasons_are_stably_ordered_and_display_text_is_derived() -> None:
    signals = AdmissionSignals(
        conflicting_evidence=True,
        material_uncertainty=True,
        accounting_judgement=True,
        incomplete_supporting_evidence=True,
    )
    decision = admit(outcome(signals=signals))
    assert decision.reasons == tuple(
        sorted(
            decision.reasons,
            key=lambda item: list(AdmissionReasonCode).index(item.code),
        )
    )
    assert decision.reason
    assert decision.deterministic_json() == decision.deterministic_json()


def test_casebuilder_consumes_admission_decision() -> None:
    candidate = outcome()
    decision = admit(candidate.model_copy(update={"replay": None}))
    built = case_dict(candidate, decision)
    assert built["verdict"] == "REJECTED"
    assert built["admission_reasons"] == [
        reason.model_dump(mode="json") for reason in decision.reasons
    ]
    assert built["verdict_reason"] == decision.reason
