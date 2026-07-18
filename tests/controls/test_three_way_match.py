from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from audit_compiler.controls import ControlContext, OutcomeStatus
from audit_compiler.controls.three_way_match import (
    GoodsReceiptRecord,
    MatchAdjustmentKind,
    MatchConfidence,
    MatchFinding,
    PurchaseAdjustmentRecord,
    PurchaseClassification,
    PurchaseInvoiceRecord,
    PurchaseOrderRecord,
    ReceiptStatus,
    ThreeWayMatchControl,
    ThreeWayMatchParameters,
)
from audit_compiler.models import EvidenceRef, SourceType

D = Decimal
DAY = date(2026, 4, 10)


def ev(row: int, value: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef.canonical(
            source_path="synthetic/three-way.csv",
            source_type=SourceType.CSV_ROW,
            file_sha256="a" * 64,
            raw_value=value,
            raw_value_sha256=sha256(value.encode()).hexdigest(),
            row=row,
        ),
    )


def invoice(
    record_id: str = "inv-1",
    *,
    ref: str = "INV-1",
    vendor: str = "V-1",
    net: str = "100",
    vat: str = "19",
    gross: str = "119",
    classification: PurchaseClassification = PurchaseClassification.GOODS,
    po: str | None = "PO-1",
    receipt: str | None = None,
    quantity: str | None = "10",
    day: date = DAY,
) -> PurchaseInvoiceRecord:
    return PurchaseInvoiceRecord(
        record_id,
        ref,
        vendor,
        day,
        D(net),
        D(vat),
        D(gross),
        classification,
        ev(abs(hash(record_id)) % 10000 + 1, record_id),
        po,
        receipt,
        D(quantity) if quantity is not None else None,
    )


def order(
    record_id: str = "po-1",
    *,
    ref: str = "PO-1",
    vendor: str = "V-1",
    net: str = "100",
    vat: str = "19",
    gross: str = "119",
    quantity: str | None = "10",
    variance: str = "0",
) -> PurchaseOrderRecord:
    return PurchaseOrderRecord(
        record_id,
        ref,
        vendor,
        DAY - timedelta(days=10),
        D(net),
        D(vat),
        D(gross),
        ev(abs(hash(record_id)) % 10000 + 1, record_id),
        quantity=D(quantity) if quantity else None,
        approved_price_variance=D(variance),
    )


def receipt(
    record_id: str = "gr-1",
    *,
    ref: str = "GR-1",
    vendor: str = "V-1",
    net: str = "100",
    vat: str | None = "19",
    gross: str | None = "119",
    invoice_ref: str | None = "INV-1",
    po: str | None = "PO-1",
    quantity: str | None = "10",
    classification: PurchaseClassification = PurchaseClassification.GOODS,
    status: ReceiptStatus = ReceiptStatus.ACCEPTED,
    day: date = DAY,
) -> GoodsReceiptRecord:
    return GoodsReceiptRecord(
        record_id,
        ref,
        vendor,
        day,
        D(net),
        ev(abs(hash(record_id)) % 10000 + 1, record_id),
        D(vat) if vat is not None else None,
        D(gross) if gross is not None else None,
        invoice_ref,
        po,
        D(quantity) if quantity is not None else None,
        classification,
        status,
    )


def adjustment(
    kind: MatchAdjustmentKind,
    *,
    record_id: str = "adj-1",
    net: str = "100",
    vat: str = "19",
    gross: str = "119",
) -> PurchaseAdjustmentRecord:
    return PurchaseAdjustmentRecord(
        record_id,
        kind,
        "V-1",
        DAY,
        D(net),
        D(vat),
        D(gross),
        ev(9000, record_id),
        invoice_reference="INV-1",
    )


def run(*records: object, tolerance: str = "0.01", window: int = 7):
    context = ControlContext(
        records=records,
        parameters=ThreeWayMatchParameters(D(tolerance), D("0"), window),
    )
    return ThreeWayMatchControl().evaluate(context)


def by_subject(results, subject: str):
    return next(item for item in results if item.subject_record_id == subject)


def test_exact_three_way_match_and_evidence_preservation() -> None:
    inv, po, gr = invoice(), order(), receipt()
    result = run(inv, po, gr)[0]
    assert (result.finding, result.confidence, result.status) == (
        MatchFinding.MATCHED,
        MatchConfidence.EXACT,
        OutcomeStatus.DISMISSED,
    )
    assert set(result.evidence_refs) == set(inv.evidence_refs + po.evidence_refs + gr.evidence_refs)


def test_vat_aware_matching_never_substitutes_net_for_gross() -> None:
    matched = run(invoice(), receipt())[0]
    assert (matched.matched_net, matched.matched_vat, matched.matched_gross) == (
        D("100"),
        D("19"),
        D("119"),
    )
    missing_dimensions = run(invoice(), receipt(vat=None, gross=None))[0]
    assert missing_dimensions.net_difference == 0
    assert (missing_dimensions.vat_difference, missing_dimensions.gross_difference) == (
        D("19"),
        D("119"),
    )


def test_legitimate_service_invoice_without_receipt_is_not_fraud_signal() -> None:
    result = run(invoice(classification=PurchaseClassification.SERVICE), order())[0]
    assert result.finding == MatchFinding.SERVICE_WITHOUT_RECEIPT
    assert result.status == OutcomeStatus.DISMISSED


def test_service_acceptance_matches_service_invoice() -> None:
    result = run(
        invoice(classification=PurchaseClassification.SERVICE),
        receipt(classification=PurchaseClassification.SERVICE),
    )[0]
    assert result.finding == MatchFinding.MATCHED


def test_unknown_invoice_classification_requires_review() -> None:
    result = run(invoice(classification=PurchaseClassification.UNKNOWN), receipt())[0]
    assert result.finding == MatchFinding.REVIEW_CLASSIFICATION
    assert result.status == OutcomeStatus.REVIEW_NEEDED


def test_invoice_without_receipt() -> None:
    result = run(invoice(), order())[0]
    assert (result.finding, result.exposure_amount) == (MatchFinding.UNMATCHED_INVOICE, D("100"))


def test_receipt_without_invoice() -> None:
    result = run(receipt(invoice_ref=None))[0]
    assert (result.finding, result.exposure_amount) == (MatchFinding.UNMATCHED_RECEIPT, D("100"))


def test_one_invoice_can_cover_multiple_receipts() -> None:
    results = run(
        invoice(),
        receipt("gr-a", net="40", vat="7.6", gross="47.6", quantity="4"),
        receipt("gr-b", net="60", vat="11.4", gross="71.4", quantity="6"),
    )
    result = by_subject(results, "inv-1")
    assert result.matched_record_ids == ("gr-a", "gr-b")
    assert result.net_difference == 0


def test_multiple_invoices_allocate_one_order_once() -> None:
    inv_a = invoice("inv-a", ref="INV-A", net="40", vat="7.6", gross="47.6", quantity="4")
    inv_b = invoice("inv-b", ref="INV-B", net="60", vat="11.4", gross="71.4", quantity="6")
    results = run(
        inv_a,
        inv_b,
        order(),
        receipt("gr-a", net="40", vat="7.6", gross="47.6", invoice_ref="INV-A", quantity="4"),
        receipt("gr-b", net="60", vat="11.4", gross="71.4", invoice_ref="INV-B", quantity="6"),
    )
    assert {by_subject(results, "inv-a").finding, by_subject(results, "inv-b").finding} == {
        MatchFinding.MATCHED
    }


def test_partial_delivery_and_backorder_are_retained_as_partial() -> None:
    result = by_subject(
        run(invoice(), order(), receipt(net="60", vat="11.4", gross="71.4", quantity="6")), "inv-1"
    )
    assert result.finding == MatchFinding.PARTIAL_DELIVERY
    assert result.quantity_difference == D("4")


def test_approved_price_variance_suppresses_net_variance() -> None:
    result = run(
        invoice(net="102", vat="19", gross="121"),
        order(net="100", variance="2"),
        receipt(net="100", vat="19", gross="121"),
    )[0]
    assert result.net_difference == 0
    assert result.finding == MatchFinding.MATCHED


def test_duplicate_invoice_is_detected_but_duplicate_source_representation_is_deduped() -> None:
    inv = invoice()
    assert len(run(inv, inv, receipt())) == 1
    results = run(inv, invoice("inv-copy"), receipt())
    assert by_subject(results, "inv-1").finding == MatchFinding.DUPLICATE_INVOICE
    assert by_subject(results, "inv-copy").finding == MatchFinding.DUPLICATE_INVOICE


@pytest.mark.parametrize(
    "kind",
    [
        MatchAdjustmentKind.CREDIT_NOTE,
        MatchAdjustmentKind.REVERSAL,
        MatchAdjustmentKind.CANCELLATION,
    ],
)
def test_credit_note_cancellation_and_reversal(kind: MatchAdjustmentKind) -> None:
    result = run(invoice(), adjustment(kind))[0]
    assert result.exposure_amount == 0
    if kind != MatchAdjustmentKind.CREDIT_NOTE:
        assert result.finding == MatchFinding.CANCELLED_OR_REVERSED


def test_returned_goods_do_not_supply_accepted_coverage() -> None:
    returned = receipt(status=ReceiptStatus.RETURNED)
    result = run(invoice(), returned)[0]
    assert result.finding == MatchFinding.UNMATCHED_INVOICE
    assert returned.evidence_refs[0] in result.evidence_refs
    assert (
        next(
            item for item in result.counter_tests if item.name == "return or rejection"
        ).status.value
        == "accounted_for"
    )


def test_vendor_mismatch_blocks_equal_amount_match() -> None:
    results = run(invoice(), receipt(vendor="V-2", invoice_ref=None))
    assert by_subject(results, "inv-1").finding == MatchFinding.UNMATCHED_INVOICE
    assert by_subject(results, "gr-1").finding == MatchFinding.UNMATCHED_RECEIPT


def test_equal_vendor_amount_outside_date_window_does_not_fallback_match() -> None:
    results = run(invoice(po=None), receipt(invoice_ref=None, po=None, day=DAY - timedelta(days=8)))
    assert by_subject(results, "inv-1").finding == MatchFinding.UNMATCHED_INVOICE


def test_tolerance_boundary_is_inclusive_and_just_outside_is_not() -> None:
    at = run(invoice(net="100.01"), receipt(), tolerance="0.01")[0]
    assert at.net_difference == 0
    outside = run(invoice(net="100.02"), receipt(), tolerance="0.01")[0]
    assert outside.net_difference == D("0.02")


def test_results_are_input_order_independent() -> None:
    records = (invoice(), order(), receipt())
    forward = run(*records)
    reverse = run(*reversed(records))
    assert forward == reverse


def test_fallback_is_clearly_low_confidence_review() -> None:
    result = run(invoice(po=None), receipt(invoice_ref=None, po=None))[0]
    assert (result.finding, result.confidence, result.status) == (
        MatchFinding.FALLBACK_MATCH,
        MatchConfidence.LOW,
        OutcomeStatus.REVIEW_NEEDED,
    )


def test_missing_optional_purchase_order_data_still_allows_explicit_receipt_match() -> None:
    result = run(invoice(po=None, receipt="GR-1"), receipt(invoice_ref=None, po=None))[0]
    assert result.finding == MatchFinding.MATCHED


def test_receipt_allocated_by_explicit_reference_cannot_match_second_invoice() -> None:
    first = invoice("a", ref="INV-A", po=None, receipt="GR-1")
    second = invoice("b", ref="INV-B", po=None, receipt="GR-1")
    gr = receipt(invoice_ref=None, po=None)
    results = run(second, gr, first)
    assert by_subject(results, "a").finding == MatchFinding.MATCHED
    assert by_subject(results, "b").finding == MatchFinding.UNMATCHED_INVOICE


def test_non_decimal_money_is_rejected() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        PurchaseInvoiceRecord(
            "x",
            "i",
            "v",
            DAY,
            100,
            D("19"),
            D("119"),  # type: ignore[arg-type]
            PurchaseClassification.GOODS,
            ev(9999, "x"),
        )
