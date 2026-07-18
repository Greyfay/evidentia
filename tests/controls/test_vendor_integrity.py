from datetime import date
from decimal import Decimal

from audit_compiler.controls.base import ControlContext, CounterTestStatus, OutcomeStatus
from audit_compiler.controls.vendor_integrity import (
    ApprovalLogRecord,
    OutgoingPaymentRecord,
    PermissionKind,
    PriorVendorHistoryRecord,
    PurchaseKind,
    SupplierInvoiceRecord,
    SupportingEvidenceKind,
    UserPermissionRecord,
    VendorEventKind,
    VendorIntegrityControl,
    VendorIntegrityParameters,
    VendorLifecycleEvent,
    VendorSignalType,
    VendorSupportingEvidenceRecord,
)
from audit_compiler.models import EvidenceRef, SourceType


def _evidence(row: int, value: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            source_path="synthetic/vendor-control.csv",
            source_type=SourceType.CSV_ROW,
            file_sha256="b" * 64,
            raw_value=value,
            row=row,
        ),
    )


def _parameters(**overrides: object) -> VendorIntegrityParameters:
    values = {"analysis_date": date(2026, 1, 31)}
    values.update(overrides)
    return VendorIntegrityParameters(**values)  # type: ignore[arg-type]


def _high_risk_records(
    *,
    creation_date: date = date(2026, 1, 1),
    invoice_date: date = date(2026, 1, 2),
    payment_date: date = date(2026, 1, 3),
) -> tuple:
    return (
        VendorLifecycleEvent(
            "life-create",
            "vendor-risk",
            VendorEventKind.CREATED,
            "user-risk",
            creation_date,
            _evidence(1, "created"),
        ),
        VendorLifecycleEvent(
            "life-approve",
            "vendor-risk",
            VendorEventKind.APPROVED,
            "user-risk",
            creation_date,
            _evidence(2, "approved"),
        ),
        UserPermissionRecord(
            "permission-create",
            "user-risk",
            PermissionKind.CREATE_VENDOR,
            True,
            _evidence(3, "create vendor"),
        ),
        UserPermissionRecord(
            "permission-pay",
            "user-risk",
            PermissionKind.EXECUTE_PAYMENT,
            True,
            _evidence(4, "execute payment"),
        ),
        SupplierInvoiceRecord(
            "invoice-record",
            "vendor-risk",
            "invoice-one",
            "user-risk",
            invoice_date,
            PurchaseKind.SERVICE,
            Decimal("100.00"),
            Decimal("19.00"),
            _evidence(5, "invoice"),
        ),
        OutgoingPaymentRecord(
            "payment-record",
            "vendor-risk",
            "payment-one",
            "invoice-one",
            "user-risk",
            payment_date,
            Decimal("119.00"),
            _evidence(6, "payment"),
        ),
        PriorVendorHistoryRecord(
            "history-record",
            "vendor-risk",
            0,
            _evidence(7, "no prior activity"),
        ),
    )


def _evaluate(records: tuple, parameters: VendorIntegrityParameters | None = None):
    return VendorIntegrityControl().evaluate(
        ControlContext(records=records, parameters=parameters or _parameters())
    )


def _signal_types(outcome) -> set[VendorSignalType]:
    return {signal.signal_type for signal in outcome.signals}


def test_high_risk_vendor_emits_separate_conflict_and_timing_signals() -> None:
    outcome = _evaluate(_high_risk_records())[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert _signal_types(outcome) == set(VendorSignalType) - {
        VendorSignalType.MISSING_VENDOR_CREATION_EVENT
    }
    assert outcome.gross_cash_paid == Decimal("119.00")
    assert outcome.invoice_net_amount == Decimal("100.00")
    assert outcome.invoice_tax_amount == Decimal("19.00")
    assert outcome.exposure_amount == outcome.gross_cash_paid
    assert outcome.uncertainty
    assert all(signal.evidence_refs for signal in outcome.signals)
    assert all(step.expression and step.result for step in outcome.calculation_steps)
    assert {counter.name for counter in outcome.counter_tests} == {
        "independent_approval",
        "contract",
        "deliverables",
        "service_acceptance",
        "prior_activity",
        "goods_receipt",
        "reversal",
        "legitimate_four_eyes_setup",
    }


def test_honest_twin_is_dismissed_by_four_eyes_and_real_delivery() -> None:
    records = (
        VendorLifecycleEvent(
            "create",
            "vendor-honest",
            VendorEventKind.CREATED,
            "user-one",
            date(2026, 1, 1),
            _evidence(1, "created"),
        ),
        VendorLifecycleEvent(
            "approve",
            "vendor-honest",
            VendorEventKind.APPROVED,
            "user-two",
            date(2026, 1, 1),
            _evidence(2, "approved independently"),
        ),
        ApprovalLogRecord(
            "approval-log",
            "vendor-honest",
            "user-two",
            date(2026, 1, 1),
            _evidence(3, "approval log"),
        ),
        SupplierInvoiceRecord(
            "invoice",
            "vendor-honest",
            "invoice-honest",
            "user-three",
            date(2026, 1, 4),
            PurchaseKind.GOODS,
            Decimal("50"),
            Decimal("9.5"),
            _evidence(4, "goods invoice"),
        ),
        OutgoingPaymentRecord(
            "payment",
            "vendor-honest",
            "payment-honest",
            "invoice-honest",
            "user-four",
            date(2026, 1, 10),
            Decimal("59.5"),
            _evidence(5, "goods payment"),
        ),
        PriorVendorHistoryRecord(
            "history",
            "vendor-honest",
            0,
            _evidence(6, "new vendor"),
        ),
        VendorSupportingEvidenceRecord(
            "receipt",
            "vendor-honest",
            SupportingEvidenceKind.GOODS_RECEIPT,
            True,
            _evidence(7, "goods received"),
        ),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert VendorSignalType.MISSING_INDEPENDENT_APPROVAL not in _signal_types(outcome)
    assert VendorSignalType.MISSING_APPROVAL_LOG not in _signal_types(outcome)
    assert VendorSignalType.MISSING_SERVICE_OR_DELIVERY_EVIDENCE not in _signal_types(
        outcome
    )
    counters = {counter.name: counter for counter in outcome.counter_tests}
    assert counters["independent_approval"].status == CounterTestStatus.ACCOUNTED_FOR
    assert counters["goods_receipt"].status == CounterTestStatus.ACCOUNTED_FOR
    assert counters["legitimate_four_eyes_setup"].status == CounterTestStatus.ACCOUNTED_FOR


def test_service_vendor_needs_no_goods_receipt_when_service_acceptance_exists() -> None:
    records = (
        VendorLifecycleEvent(
            "create",
            "vendor-service",
            VendorEventKind.CREATED,
            "maker",
            date(2026, 1, 1),
            _evidence(1, "created"),
        ),
        VendorLifecycleEvent(
            "approve",
            "vendor-service",
            VendorEventKind.APPROVED,
            "checker",
            date(2026, 1, 2),
            _evidence(2, "approved"),
        ),
        ApprovalLogRecord(
            "log",
            "vendor-service",
            "checker",
            date(2026, 1, 2),
            _evidence(3, "logged"),
        ),
        SupplierInvoiceRecord(
            "invoice",
            "vendor-service",
            "service-invoice",
            "poster",
            date(2026, 1, 20),
            PurchaseKind.SERVICE,
            Decimal("200"),
            None,
            _evidence(4, "service invoice"),
        ),
        OutgoingPaymentRecord(
            "payment",
            "vendor-service",
            "service-payment",
            "service-invoice",
            "payer",
            date(2026, 1, 25),
            Decimal("200"),
            _evidence(5, "service payment"),
        ),
        PriorVendorHistoryRecord(
            "history",
            "vendor-service",
            4,
            _evidence(6, "prior activity"),
        ),
        VendorSupportingEvidenceRecord(
            "contract",
            "vendor-service",
            SupportingEvidenceKind.CONTRACT,
            True,
            _evidence(7, "contract"),
        ),
        VendorSupportingEvidenceRecord(
            "acceptance",
            "vendor-service",
            SupportingEvidenceKind.SERVICE_ACCEPTANCE,
            True,
            _evidence(8, "accepted service"),
        ),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert VendorSignalType.MISSING_SERVICE_OR_DELIVERY_EVIDENCE not in _signal_types(
        outcome
    )
    goods_receipt = next(
        counter for counter in outcome.counter_tests if counter.name == "goods_receipt"
    )
    assert goods_receipt.status == CounterTestStatus.UNRESOLVED
    assert not any("goods_receipt" in uncertainty for uncertainty in outcome.uncertainty)


def test_missing_goods_receipt_alone_never_confirms_a_finding() -> None:
    records = (
        VendorLifecycleEvent(
            "create",
            "vendor-goods",
            VendorEventKind.CREATED,
            "maker",
            date(2024, 1, 1),
            _evidence(1, "created"),
        ),
        VendorLifecycleEvent(
            "approve",
            "vendor-goods",
            VendorEventKind.APPROVED,
            "checker",
            date(2024, 1, 2),
            _evidence(2, "approved"),
        ),
        ApprovalLogRecord(
            "log",
            "vendor-goods",
            "checker",
            date(2024, 1, 2),
            _evidence(3, "logged"),
        ),
        SupplierInvoiceRecord(
            "invoice",
            "vendor-goods",
            "goods-invoice",
            "poster",
            date(2026, 1, 10),
            PurchaseKind.GOODS,
            Decimal("100"),
            Decimal("19"),
            _evidence(4, "goods invoice"),
        ),
        OutgoingPaymentRecord(
            "payment",
            "vendor-goods",
            "goods-payment",
            "goods-invoice",
            "payer",
            date(2026, 1, 20),
            Decimal("119"),
            _evidence(5, "goods payment"),
        ),
        PriorVendorHistoryRecord(
            "history",
            "vendor-goods",
            8,
            _evidence(6, "prior activity"),
        ),
        VendorSupportingEvidenceRecord(
            "receipt-search",
            "vendor-goods",
            SupportingEvidenceKind.GOODS_RECEIPT,
            False,
            _evidence(7, "receipt search completed"),
        ),
    )

    outcome = _evaluate(records)[0]

    assert _signal_types(outcome) == {
        VendorSignalType.MISSING_SERVICE_OR_DELIVERY_EVIDENCE
    }
    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert "alone is not proof" in outcome.uncertainty[0]


def test_duplicate_records_do_not_inflate_amounts_or_signals() -> None:
    records = _high_risk_records()
    duplicated = (*records, records[4], records[5], records[5])

    original = _evaluate(records)[0]
    duplicate_result = _evaluate(duplicated)[0]

    assert duplicate_result == original
    assert duplicate_result.gross_cash_paid == Decimal("119.00")
    assert duplicate_result.invoice_net_amount == Decimal("100.00")


def test_reversed_payment_is_removed_from_cash_exposure() -> None:
    records = _high_risk_records()
    reversal = OutgoingPaymentRecord(
        "reversal-record",
        "vendor-risk",
        "payment-reversal",
        "invoice-one",
        "user-risk",
        date(2026, 1, 4),
        Decimal("-119.00"),
        _evidence(8, "reversal"),
        reversal_of="payment-one",
    )

    outcome = _evaluate((*records, reversal))[0]

    assert outcome.gross_cash_paid == Decimal("0")
    reversal_test = next(
        counter for counter in outcome.counter_tests if counter.name == "reversal"
    )
    assert reversal_test.status == CounterTestStatus.ACCOUNTED_FOR
    assert VendorSignalType.RAPID_FIRST_PAYMENT not in _signal_types(outcome)
    assert VendorSignalType.INVOICE_PAID_UNUSUALLY_QUICKLY not in _signal_types(outcome)


def test_missing_optional_counter_evidence_requires_review() -> None:
    outcome = _evaluate(_high_risk_records())[0]
    counters = {counter.name: counter for counter in outcome.counter_tests}

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert counters["contract"].status == CounterTestStatus.UNRESOLVED
    assert counters["deliverables"].status == CounterTestStatus.UNRESOLVED
    assert counters["service_acceptance"].status == CounterTestStatus.UNRESOLVED
    assert any("contract" in uncertainty for uncertainty in outcome.uncertainty)
    assert any("service" in uncertainty for uncertainty in outcome.uncertainty)


def test_missing_optional_evidence_remains_review_with_high_score_threshold() -> None:
    outcome = _evaluate(
        _high_risk_records(),
        _parameters(review_score_threshold=Decimal("100")),
    )[0]

    assert outcome.severity_score < Decimal("100")
    assert outcome.status == OutcomeStatus.REVIEW_NEEDED


def test_legitimate_evidence_does_not_erase_direct_sod_conflicts() -> None:
    records = (
        *_high_risk_records(),
        VendorLifecycleEvent(
            "independent-event",
            "vendor-risk",
            VendorEventKind.APPROVED,
            "independent-user",
            date(2026, 1, 2),
            _evidence(20, "independent approval"),
        ),
        ApprovalLogRecord(
            "independent-log",
            "vendor-risk",
            "independent-user",
            date(2026, 1, 2),
            _evidence(21, "approval logged"),
        ),
        VendorSupportingEvidenceRecord(
            "contract-present",
            "vendor-risk",
            SupportingEvidenceKind.CONTRACT,
            True,
            _evidence(22, "contract"),
        ),
        VendorSupportingEvidenceRecord(
            "acceptance-present",
            "vendor-risk",
            SupportingEvidenceKind.SERVICE_ACCEPTANCE,
            True,
            _evidence(23, "accepted service"),
        ),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert {
        VendorSignalType.CREATOR_EQUALS_APPROVER,
        VendorSignalType.CREATE_AND_PAY_PERMISSION,
        VendorSignalType.SAME_USER_CREATES_POSTS_PAYS,
    } <= _signal_types(outcome)
    assert any("does not resolve" in uncertainty for uncertainty in outcome.uncertainty)


def test_missing_creation_event_emits_review_instead_of_omitting_vendor() -> None:
    records = (
        SupplierInvoiceRecord(
            "invoice-without-creation",
            "vendor-incomplete",
            "invoice-incomplete",
            "poster",
            date(2026, 1, 10),
            PurchaseKind.SERVICE,
            Decimal("100"),
            Decimal("19"),
            _evidence(30, "invoice"),
        ),
        OutgoingPaymentRecord(
            "payment-without-creation",
            "vendor-incomplete",
            "payment-incomplete",
            "invoice-incomplete",
            "payer",
            date(2026, 1, 11),
            Decimal("119"),
            _evidence(31, "payment"),
        ),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert _signal_types(outcome) == {
        VendorSignalType.MISSING_VENDOR_CREATION_EVENT
    }
    assert outcome.gross_cash_paid == Decimal("119")
    assert outcome.invoice_net_amount == Decimal("100")
    assert {evidence.row for evidence in outcome.evidence_refs} == {30, 31}


def test_multiple_vendor_outcomes_are_sorted_by_normalized_vendor_id() -> None:
    records = (
        VendorLifecycleEvent(
            "create-z",
            "vendor-z",
            VendorEventKind.CREATED,
            "maker-z",
            date(2026, 1, 1),
            _evidence(40, "created z"),
        ),
        VendorLifecycleEvent(
            "create-a",
            "vendor-a",
            VendorEventKind.CREATED,
            "maker-a",
            date(2026, 1, 1),
            _evidence(41, "created a"),
        ),
    )

    outcomes = _evaluate(records)

    assert [outcome.vendor_id for outcome in outcomes] == ["VENDOR-A", "VENDOR-Z"]


def test_complete_negative_counter_searches_emit_candidate_not_confirmed_fraud() -> None:
    records = (
        *_high_risk_records(),
        ApprovalLogRecord(
            "same-user-log",
            "vendor-risk",
            "user-risk",
            date(2026, 1, 1),
            _evidence(50, "same user approval log"),
        ),
        *(
            VendorSupportingEvidenceRecord(
                f"negative-{kind.value}",
                "vendor-risk",
                kind,
                False,
                _evidence(51 + index, f"searched {kind.value}"),
            )
            for index, kind in enumerate(
                (
                    SupportingEvidenceKind.CONTRACT,
                    SupportingEvidenceKind.DELIVERABLE,
                    SupportingEvidenceKind.SERVICE_ACCEPTANCE,
                    SupportingEvidenceKind.LEGITIMATE_FOUR_EYES,
                )
            )
        ),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.CONFIRMED_CANDIDATE
    assert outcome.status.value != "confirmed"
    assert outcome.uncertainty == ()


def test_output_is_independent_of_input_order() -> None:
    records = _high_risk_records()

    forward = _evaluate(records)
    reverse = _evaluate(tuple(reversed(records)))

    assert forward == reverse


def test_configurable_timing_boundaries_are_inclusive() -> None:
    records = _high_risk_records(
        creation_date=date(2026, 1, 1),
        invoice_date=date(2026, 1, 4),
        payment_date=date(2026, 1, 6),
    )
    exact_weights = tuple(
        (signal, Decimal("9") if signal == VendorSignalType.RAPID_FIRST_INVOICE else Decimal("1"))
        for signal in VendorSignalType
    )
    exact = _evaluate(
        records,
        _parameters(
            analysis_date=date(2026, 1, 11),
            new_vendor_window_days=10,
            rapid_first_invoice_days=3,
            rapid_first_payment_days=5,
            rapid_invoice_payment_days=2,
            severity_weights=exact_weights,
        ),
    )[0]
    outside = _evaluate(
        records,
        _parameters(
            analysis_date=date(2026, 1, 11),
            new_vendor_window_days=9,
            rapid_first_invoice_days=2,
            rapid_first_payment_days=4,
            rapid_invoice_payment_days=1,
        ),
    )[0]

    exact_signals = _signal_types(exact)
    outside_signals = _signal_types(outside)
    assert {
        VendorSignalType.NEW_VENDOR,
        VendorSignalType.RAPID_FIRST_INVOICE,
        VendorSignalType.RAPID_FIRST_PAYMENT,
        VendorSignalType.INVOICE_PAID_UNUSUALLY_QUICKLY,
    } <= exact_signals
    assert not {
        VendorSignalType.NEW_VENDOR,
        VendorSignalType.RAPID_FIRST_INVOICE,
        VendorSignalType.RAPID_FIRST_PAYMENT,
        VendorSignalType.INVOICE_PAID_UNUSUALLY_QUICKLY,
    } & outside_signals
    rapid_signal = next(
        signal
        for signal in exact.signals
        if signal.signal_type == VendorSignalType.RAPID_FIRST_INVOICE
    )
    assert rapid_signal.weight == Decimal("9")
