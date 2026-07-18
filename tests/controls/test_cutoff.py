from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256

import pytest

from audit_compiler.controls import (
    AdjustmentKind,
    ClosingBalanceRecord,
    ClosingRecordKind,
    ControlContext,
    CutoffAdjustmentRecord,
    CutoffInvoiceRecord,
    CutoffParameters,
    CutoffPolicyExceptionRecord,
    OutcomeStatus,
    ReceiptStatus,
    ServiceReceiptRecord,
    YearEndCutoffControl,
)
from audit_compiler.models import EvidenceRef, SourceType


def ev(row: int, value: str) -> EvidenceRef:
    return EvidenceRef(
        source_path="synthetic/cutoff.csv",
        source_type=SourceType.CSV_ROW,
        file_sha256="a" * 64,
        raw_value=value,
        raw_value_sha256=sha256(value.encode()).hexdigest(),
        row=row,
    )


def invoice(
    invoice_id: str = "I-1",
    *,
    row: int = 1,
    invoice_date: date = date(2027, 1, 10),
    posting_date: date | None = date(2027, 1, 10),
    amount: str = "100.00",
    vendor: str = "V-1",
    description: str = "Beratungsleistung consulting service",
    period_known: bool = True,
) -> CutoffInvoiceRecord:
    net = Decimal(amount)
    vat = net * Decimal("0.19")
    return CutoffInvoiceRecord(
        f"invoice-{invoice_id}",
        invoice_id,
        vendor,
        f"DOC-{invoice_id}",
        invoice_date,
        posting_date,
        net,
        vat,
        net + vat,
        (ev(row, invoice_id),),
        description=description,
        accounting_period_known=period_known,
    )


def receipt(
    invoice_id: str = "I-1",
    *,
    row: int = 2,
    occurred: date | None = date(2026, 12, 20),
    status: ReceiptStatus = ReceiptStatus.ACCEPTED,
) -> ServiceReceiptRecord:
    return ServiceReceiptRecord(
        f"receipt-{invoice_id}",
        occurred,
        (ev(row, str(occurred)),),
        invoice_id=invoice_id,
        status=status,
    )


def closing(
    invoice_id: str | None = "I-1",
    *,
    row: int = 3,
    amount: str = "100.00",
    generic: bool = False,
    vendor: str | None = "V-1",
    kind: ClosingRecordKind = ClosingRecordKind.ACCRUAL,
    posting_date: date | None = date(2026, 12, 31),
    period_known: bool = True,
) -> ClosingBalanceRecord:
    return ClosingBalanceRecord(
        f"closing-{row}",
        kind,
        posting_date,
        Decimal(amount),
        (ev(row, amount),),
        invoice_id=invoice_id,
        vendor_id=vendor,
        generic=generic,
        accounting_period_known=period_known,
    )


def params(year: int = 2026, tolerance: str = "0.00") -> CutoffParameters:
    return CutoffParameters(date(year, 1, 1), date(year, 12, 31), Decimal(tolerance))


def run(*records, parameters: CutoffParameters | None = None):
    return YearEndCutoffControl().evaluate(
        ControlContext(records=records, parameters=parameters or params())
    )


def test_december_service_invoiced_in_january_without_accrual() -> None:
    result = run(invoice(), receipt())[0]
    assert result.status == OutcomeStatus.CONFIRMED_CANDIDATE
    assert result.potentially_unrecorded_net == Decimal("100.00")
    assert result.invoice_vat_amount == Decimal("19.0000")
    assert result.invoice_gross_amount == Decimal("119.0000")


@pytest.mark.parametrize("kind", [ClosingRecordKind.LIABILITY, ClosingRecordKind.ACCRUAL])
def test_exact_transaction_level_closing_match(kind: ClosingRecordKind) -> None:
    result = run(invoice(), receipt(), closing(kind=kind))[0]
    assert result.status == OutcomeStatus.DISMISSED
    assert result.closing_coverage_net == Decimal("100.00")


def test_unrelated_generic_accrual_does_not_clear_invoice() -> None:
    result = run(invoice(), receipt(), closing(None, generic=True, amount="500"))[0]
    assert result.status == OutcomeStatus.REVIEW_NEEDED
    assert result.potentially_unrecorded_net == Decimal("100.00")
    assert "generic accrual" in result.uncertainty[0]


def test_partial_accrual_coverage() -> None:
    result = run(invoice(), receipt(), closing(amount="40"))[0]
    assert result.status == OutcomeStatus.CONFIRMED_CANDIDATE
    assert result.potentially_unrecorded_net == Decimal("60.00")


def test_invoice_already_recorded_before_year_end() -> None:
    assert not run(
        invoice(invoice_date=date(2026, 12, 30), posting_date=date(2026, 12, 30)), receipt()
    )


def test_january_service_belongs_to_january() -> None:
    assert not run(invoice(), receipt(occurred=date(2027, 1, 2)))


@pytest.mark.parametrize(
    "kind", [AdjustmentKind.CREDIT_NOTE, AdjustmentKind.REVERSAL, AdjustmentKind.CANCELLATION]
)
def test_credit_note_reversal_or_cancellation(kind: AdjustmentKind) -> None:
    adjustment = CutoffAdjustmentRecord(
        "adjust-1",
        kind,
        date(2027, 1, 15),
        Decimal("100"),
        (ev(4, kind.value),),
        invoice_id="I-1",
    )
    result = run(invoice(), receipt(), adjustment)[0]
    assert result.status == OutcomeStatus.DISMISSED
    assert result.adjustment_net == Decimal("100")


@pytest.mark.parametrize(
    "status", [ReceiptStatus.RETURNED, ReceiptStatus.REJECTED, ReceiptStatus.DISPUTED]
)
def test_returned_rejected_or_disputed_delivery(status: ReceiptStatus) -> None:
    assert run(invoice(), receipt(status=status))[0].status == OutcomeStatus.DISMISSED


def test_valid_accounting_policy_exception() -> None:
    exception = CutoffPolicyExceptionRecord(
        "policy-1", "documented policy", (ev(5, "policy"),), invoice_id="I-1"
    )
    assert run(invoice(), receipt(), exception)[0].status == OutcomeStatus.DISMISSED


def test_duplicate_records_are_deduplicated() -> None:
    inv, rec = invoice(), receipt()
    assert run(inv, rec) == run(inv, rec, inv, rec)


def test_configurable_fiscal_years_and_exact_period_end_boundary() -> None:
    inv = invoice(invoice_date=date(2025, 1, 10), posting_date=date(2025, 1, 10))
    rec = receipt(occurred=date(2024, 12, 31))
    result = run(inv, rec, parameters=params(2024))[0]
    assert result.status == OutcomeStatus.CONFIRMED_CANDIDATE


def test_amount_tolerance_boundary() -> None:
    covered = run(
        invoice(), receipt(), closing(amount="99.99"), parameters=params(tolerance="0.01")
    )[0]
    exposed = run(
        invoice(), receipt(), closing(amount="99.98"), parameters=params(tolerance="0.01")
    )[0]
    assert covered.potentially_unrecorded_net == 0
    assert exposed.potentially_unrecorded_net == Decimal("0.02")


@pytest.mark.parametrize("description", ["Dienstleistung Dezember", "December consulting service"])
def test_german_and_english_descriptions_are_language_independent(description: str) -> None:
    assert (
        run(invoice(description=description), receipt())[0].status
        == OutcomeStatus.CONFIRMED_CANDIDATE
    )


def test_missing_service_date_is_incomplete_support() -> None:
    result = run(invoice(), receipt(occurred=None))[0]
    assert result.status == OutcomeStatus.REVIEW_NEEDED
    assert "date is missing" in result.uncertainty[0]


def test_accounting_period_uncertainty_requires_review() -> None:
    assert run(invoice(period_known=False), receipt())[0].status == OutcomeStatus.REVIEW_NEEDED


def test_input_order_independence() -> None:
    records = (invoice(), receipt(), closing(amount="40"))
    assert run(*records) == run(*reversed(records))


def test_distinct_accruals_cover_multiple_invoices_without_cross_matching() -> None:
    records = (
        invoice("I-2", row=10, amount="70"),
        receipt("I-2", row=11),
        closing("I-2", row=12, amount="70"),
        invoice("I-1", row=20, amount="30"),
        receipt("I-1", row=21),
        closing("I-1", row=22, amount="30"),
    )
    outcomes = run(*records)
    assert [item.invoice_id for item in outcomes] == ["I-1", "I-2"]
    assert all(item.status == OutcomeStatus.DISMISSED for item in outcomes)
    assert [item.closing_coverage_net for item in outcomes] == [Decimal("30"), Decimal("70")]
