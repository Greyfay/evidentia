from datetime import date
from decimal import Decimal

import pytest

from audit_compiler.controls import (
    Control,
    ControlContext,
    CounterTestStatus,
    OutcomeStatus,
    PaymentRecord,
    SplitPaymentControl,
    SplitPaymentParameters,
)
from audit_compiler.models import EvidenceRef, SourceType


def _evidence(row: int, raw_value: str) -> EvidenceRef:
    return EvidenceRef(
        source_path="synthetic/payments.csv",
        source_type=SourceType.CSV_ROW,
        file_sha256="a" * 64,
        raw_value=raw_value,
        row=row,
    )


def _payment(
    payment_id: str,
    amount: str,
    *,
    row: int,
    payee: str = "Example GmbH",
    payment_date: date = date(2026, 1, 15),
    reference: str = "Batch A",
    reversal_of: str | None = None,
    obligation_id: str | None = None,
    installment_plan_id: str | None = None,
    second_approval_evidence_refs: tuple[EvidenceRef, ...] = (),
) -> PaymentRecord:
    return PaymentRecord(
        payment_id=payment_id,
        payee=payee,
        payment_date=payment_date,
        payment_reference=reference,
        amount=Decimal(amount),
        evidence_refs=(_evidence(row, amount),),
        reversal_of=reversal_of,
        obligation_id=obligation_id,
        installment_plan_id=installment_plan_id,
        second_approval_evidence_refs=second_approval_evidence_refs,
    )


def _evaluate(
    *payments: PaymentRecord, threshold: str = "10000"
) -> tuple:
    return SplitPaymentControl().evaluate(
        ControlContext(
            records=payments,
            parameters=SplitPaymentParameters(threshold=Decimal(threshold)),
        )
    )


def test_control_protocol_and_confirmed_candidate_are_replayable() -> None:
    control = SplitPaymentControl()
    assert isinstance(control, Control)

    outcomes = control.evaluate(
        ControlContext(
            records=(
                _payment("p-2", "4000", row=2, payee=" example   gmbh ", reference="batch a"),
                _payment("p-1", "6000", row=1),
            ),
            parameters=SplitPaymentParameters(threshold=Decimal("10000")),
        )
    )

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status == OutcomeStatus.CONFIRMED_CANDIDATE
    assert outcome.group_key == (
        ("payee", "EXAMPLE GMBH"),
        ("date", "2026-01-15"),
        ("payment_reference", "BATCH A"),
    )
    assert outcome.exposure_amount == Decimal("10000")
    assert outcome.rule_parameters == (
        ("threshold", "10000"),
        ("minimum_payment_count", "2"),
    )
    assert outcome.calculation_steps[0].expression == "6000 + 4000 = 10000"
    assert outcome.calculation_steps[-1].result == "true"
    assert outcome.counter_tests[0].status == CounterTestStatus.NOT_FOUND
    assert {evidence.row for evidence in outcome.evidence_refs} == {1, 2}


def test_nonqualifying_groups_do_not_emit_outcomes() -> None:
    one_payment = _evaluate(_payment("p-1", "11000", row=1))
    one_at_threshold = _evaluate(
        _payment("p-1", "10000", row=1),
        _payment("p-2", "1", row=2),
    )
    separate_references = _evaluate(
        _payment("p-1", "6000", row=1, reference="A"),
        _payment("p-2", "6000", row=2, reference="B"),
    )
    aggregate_below_threshold = _evaluate(
        _payment("p-3", "4000", row=3),
        _payment("p-4", "5000", row=4),
    )
    one_payment_above_threshold = _evaluate(
        _payment("p-5", "11000", row=5),
        _payment("p-6", "100", row=6),
    )

    assert one_payment == ()
    assert one_at_threshold == ()
    assert separate_references == ()
    assert aggregate_below_threshold == ()
    assert one_payment_above_threshold == ()


def test_different_payees_dates_and_references_form_separate_groups() -> None:
    different_payees = _evaluate(
        _payment("p-1", "6000", row=1, payee="First GmbH"),
        _payment("p-2", "6000", row=2, payee="Second GmbH"),
    )
    different_dates = _evaluate(
        _payment("p-3", "6000", row=3, payment_date=date(2026, 1, 15)),
        _payment("p-4", "6000", row=4, payment_date=date(2026, 1, 16)),
    )
    different_references = _evaluate(
        _payment("p-5", "6000", row=5, reference="First"),
        _payment("p-6", "6000", row=6, reference="Second"),
    )

    assert different_payees == ()
    assert different_dates == ()
    assert different_references == ()


def test_distinct_obligations_dismiss_legitimate_separate_payments() -> None:
    outcome = _evaluate(
        _payment("p-1", "6000", row=1, obligation_id=" invoice-a "),
        _payment("p-2", "5000", row=2, obligation_id="INVOICE-B"),
    )[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    counter_test = next(
        test for test in outcome.counter_tests if test.name == "distinct_contractual_obligations"
    )
    assert counter_test.status == CounterTestStatus.ACCOUNTED_FOR
    assert outcome.uncertainty == ()


def test_explicit_reversal_dismisses_candidate_and_retains_all_evidence() -> None:
    outcome = _evaluate(
        _payment("p-1", "6000", row=1),
        _payment("p-2", "5000", row=2),
        _payment(
            "r-2",
            "-5000",
            row=3,
            payment_date=date(2026, 1, 16),
            reversal_of="p-2",
        ),
    )[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert outcome.exposure_amount == Decimal("6000")
    assert outcome.counter_tests[0].status == CounterTestStatus.ACCOUNTED_FOR
    assert {evidence.row for evidence in outcome.evidence_refs} == {1, 2, 3}
    assert outcome.calculation_steps[2].expression == "6000 = 6000"
    assert outcome.calculation_steps[3].result == "false"


def test_unique_equal_and_opposite_payment_is_treated_as_reversal() -> None:
    outcome = _evaluate(
        _payment("p-1", "7000", row=1),
        _payment("p-2", "4000", row=2),
        _payment("r-2", "-4000", row=3, payment_date=date(2026, 1, 20)),
    )[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert "equal-and-opposite" in outcome.counter_tests[0].description


def test_ambiguous_reversal_requires_review() -> None:
    outcome = _evaluate(
        _payment("p-1", "6000", row=1),
        _payment("p-2", "6000", row=2),
        _payment("r-1", "-6000", row=3, payment_date=date(2026, 1, 20)),
    )[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert outcome.exposure_amount == Decimal("12000")
    assert outcome.counter_tests[0].status == CounterTestStatus.UNRESOLVED
    assert "multiple payments" in outcome.counter_tests[0].description
    assert outcome.uncertainty == ("multiple payments could match the reversal",)
    assert {evidence.row for evidence in outcome.evidence_refs} == {1, 2, 3}


def test_control_is_deterministic_across_input_order() -> None:
    first = _payment("p-1", "6000", row=1)
    second = _payment("p-2", "5000", row=2)

    forward = _evaluate(first, second)
    reverse = _evaluate(second, first)

    assert forward == reverse


def test_predated_explicit_reversal_requires_review() -> None:
    outcome = _evaluate(
        _payment("p-1", "6000", row=1),
        _payment("p-2", "5000", row=2),
        _payment(
            "r-2",
            "-5000",
            row=3,
            payment_date=date(2026, 1, 14),
            reversal_of="p-2",
        ),
    )[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert outcome.counter_tests[0].status == CounterTestStatus.UNRESOLVED
    assert outcome.uncertainty == ("explicit reversal predates its referenced payment",)


def test_installment_plan_or_second_approval_dismisses_candidate() -> None:
    installment = _evaluate(
        _payment("p-1", "6000", row=1, installment_plan_id="plan-a"),
        _payment("p-2", "5000", row=2, installment_plan_id=" PLAN-A "),
    )[0]
    approval = _evaluate(
        _payment(
            "p-3",
            "6000",
            row=3,
            second_approval_evidence_refs=(_evidence(30, "approved"),),
        ),
        _payment("p-4", "5000", row=4),
    )[0]

    assert installment.status == OutcomeStatus.DISMISSED
    assert approval.status == OutcomeStatus.DISMISSED
    assert any(
        test.name == "valid_installment_plan"
        and test.status == CounterTestStatus.ACCOUNTED_FOR
        for test in installment.counter_tests
    )
    assert any(
        test.name == "second_approval" and test.status == CounterTestStatus.ACCOUNTED_FOR
        for test in approval.counter_tests
    )
    assert {evidence.row for evidence in approval.evidence_refs} == {3, 4, 30}


def test_duplicate_payment_ids_fail_before_evaluation() -> None:
    with pytest.raises(ValueError, match="duplicate payment_id"):
        _evaluate(
            _payment("duplicate", "6000", row=1),
            _payment("duplicate", "5000", row=2),
        )


@pytest.mark.parametrize(
    ("field", "value", "expected_exception"),
    [
        ("payment_id", " ", ValueError),
        ("payee", " ", ValueError),
        ("payment_reference", " ", ValueError),
        ("payment_date", None, TypeError),
        ("amount", None, TypeError),
        ("evidence_refs", (), ValueError),
    ],
)
def test_missing_required_fields_fail_safely(
    field: str, value: object, expected_exception: type[Exception]
) -> None:
    values = {
        "payment_id": "p-1",
        "payee": "Example GmbH",
        "payment_date": date(2026, 1, 15),
        "payment_reference": "Batch A",
        "amount": Decimal("1"),
        "evidence_refs": (_evidence(1, "1"),),
    }
    values[field] = value

    with pytest.raises(expected_exception):
        PaymentRecord(**values)  # type: ignore[arg-type]


def test_parameters_and_payment_amounts_reject_float() -> None:
    with pytest.raises(TypeError):
        SplitPaymentParameters(threshold=10000.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        PaymentRecord(
            payment_id="p-1",
            payee="Example GmbH",
            payment_date=date(2026, 1, 15),
            payment_reference="Batch A",
            amount=1.5,  # type: ignore[arg-type]
            evidence_refs=(_evidence(1, "1.5"),),
        )


@pytest.mark.parametrize("threshold", [Decimal("NaN"), Decimal("Infinity")])
def test_parameters_reject_nonfinite_threshold(threshold: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        SplitPaymentParameters(threshold=threshold)


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity")])
def test_payments_reject_nonfinite_amount(amount: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        PaymentRecord(
            payment_id="p-1",
            payee="Example GmbH",
            payment_date=date(2026, 1, 15),
            payment_reference="Batch A",
            amount=amount,
            evidence_refs=(_evidence(1, str(amount)),),
        )
