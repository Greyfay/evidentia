"""Isolated deterministic purchase invoice/order/receipt matching control.

The control is intentionally record-oriented and is not registered for production use.
Adapters may later translate canonical events into these local immutable records.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from audit_compiler.controls.base import (
    CalculationStep,
    ControlContext,
    ControlOutcome,
    CounterTestResult,
    CounterTestStatus,
    OutcomeStatus,
    SupportingEvidence,
)
from audit_compiler.models import EvidenceRef
from audit_compiler.normalization import normalize_identifier

ZERO = Decimal("0")


class PurchaseClassification(StrEnum):
    GOODS = "goods"
    SERVICE = "service"
    UNKNOWN = "unknown"


class ReceiptStatus(StrEnum):
    ACCEPTED = "accepted"
    RETURNED = "returned"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class MatchAdjustmentKind(StrEnum):
    CREDIT_NOTE = "credit_note"
    REVERSAL = "reversal"
    CANCELLATION = "cancellation"
    RETURN = "return"


class MatchConfidence(StrEnum):
    EXACT = "exact"
    HIGH = "high"
    LOW = "low"
    NONE = "none"


class MatchFinding(StrEnum):
    MATCHED = "matched"
    FALLBACK_MATCH = "fallback_match"
    REVIEW_CLASSIFICATION = "review_classification"
    UNMATCHED_INVOICE = "unmatched_invoice"
    UNMATCHED_RECEIPT = "unmatched_receipt"
    AMOUNT_DIFFERENCE = "amount_difference"
    QUANTITY_DIFFERENCE = "quantity_difference"
    DUPLICATE_INVOICE = "duplicate_invoice"
    OVER_INVOICED = "over_invoiced"
    SERVICE_WITHOUT_RECEIPT = "service_without_receipt"
    PARTIAL_DELIVERY = "partial_delivery"
    CANCELLED_OR_REVERSED = "cancelled_or_reversed"


def _text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _money(name: str, value: Decimal | None, *, signed: bool = False) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or (not signed and value < ZERO):
        raise ValueError(f"{name} must be finite and non-negative")


def _refs(value: tuple[EvidenceRef, ...]) -> None:
    if not value:
        raise ValueError("each record requires exact EvidenceRefs")
    if not all(isinstance(item, EvidenceRef) for item in value):
        raise TypeError("evidence_refs must contain only EvidenceRefs")


def _norm(value: str | None) -> str:
    return normalize_identifier(value) if value else ""


@dataclass(frozen=True, slots=True)
class ThreeWayMatchParameters:
    amount_tolerance: Decimal = Decimal("0.01")
    quantity_tolerance: Decimal = Decimal("0")
    date_window_days: int = 7

    def __post_init__(self) -> None:
        _money("amount_tolerance", self.amount_tolerance)
        _money("quantity_tolerance", self.quantity_tolerance)
        if type(self.date_window_days) is not int or self.date_window_days < 0:
            raise ValueError("date_window_days must be a non-negative integer")

    def as_items(self) -> tuple[tuple[str, str], ...]:
        return (
            ("amount_tolerance", str(self.amount_tolerance)),
            ("quantity_tolerance", str(self.quantity_tolerance)),
            ("date_window_days", str(self.date_window_days)),
        )


@dataclass(frozen=True, slots=True)
class PurchaseInvoiceRecord:
    record_id: str
    invoice_reference: str
    vendor_id: str
    invoice_date: date
    net_amount: Decimal
    vat_amount: Decimal
    gross_amount: Decimal
    classification: PurchaseClassification | None
    evidence_refs: tuple[EvidenceRef, ...]
    purchase_order_reference: str | None = None
    goods_receipt_reference: str | None = None
    quantity: Decimal | None = None
    cancelled: bool = False

    def __post_init__(self) -> None:
        for name in ("record_id", "invoice_reference", "vendor_id"):
            _text(name, getattr(self, name))
        if type(self.invoice_date) is not date:
            raise TypeError("invoice_date must be a date")
        for name in ("net_amount", "vat_amount", "gross_amount", "quantity"):
            _money(name, getattr(self, name))
        if self.classification is not None and not isinstance(
            self.classification, PurchaseClassification
        ):
            raise TypeError("classification must be PurchaseClassification")
        _refs(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class PurchaseOrderRecord:
    record_id: str
    order_reference: str
    vendor_id: str
    order_date: date
    net_amount: Decimal
    vat_amount: Decimal
    gross_amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    invoice_reference: str | None = None
    receipt_reference: str | None = None
    quantity: Decimal | None = None
    approved_price_variance: Decimal = ZERO
    reusable: bool = False
    cancelled: bool = False

    def __post_init__(self) -> None:
        for name in ("record_id", "order_reference", "vendor_id"):
            _text(name, getattr(self, name))
        if type(self.order_date) is not date:
            raise TypeError("order_date must be a date")
        for name in (
            "net_amount",
            "vat_amount",
            "gross_amount",
            "quantity",
            "approved_price_variance",
        ):
            _money(name, getattr(self, name))
        _refs(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class GoodsReceiptRecord:
    record_id: str
    receipt_reference: str
    vendor_id: str
    receipt_date: date
    net_amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    vat_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    invoice_reference: str | None = None
    purchase_order_reference: str | None = None
    quantity: Decimal | None = None
    classification: PurchaseClassification = PurchaseClassification.GOODS
    status: ReceiptStatus = ReceiptStatus.ACCEPTED
    approved_price_variance: Decimal = ZERO
    reusable: bool = False

    def __post_init__(self) -> None:
        for name in ("record_id", "receipt_reference", "vendor_id"):
            _text(name, getattr(self, name))
        if type(self.receipt_date) is not date:
            raise TypeError("receipt_date must be a date")
        for name in (
            "net_amount",
            "vat_amount",
            "gross_amount",
            "quantity",
            "approved_price_variance",
        ):
            _money(name, getattr(self, name))
        if not isinstance(self.classification, PurchaseClassification):
            raise TypeError("classification must be PurchaseClassification")
        if not isinstance(self.status, ReceiptStatus):
            raise TypeError("status must be ReceiptStatus")
        _refs(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class PurchaseAdjustmentRecord:
    record_id: str
    kind: MatchAdjustmentKind
    vendor_id: str
    effective_date: date
    net_amount: Decimal
    vat_amount: Decimal
    gross_amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    invoice_reference: str | None = None
    purchase_order_reference: str | None = None
    goods_receipt_reference: str | None = None
    quantity: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("record_id", "vendor_id"):
            _text(name, getattr(self, name))
        if not isinstance(self.kind, MatchAdjustmentKind):
            raise TypeError("kind must be MatchAdjustmentKind")
        if type(self.effective_date) is not date:
            raise TypeError("effective_date must be a date")
        for name in ("net_amount", "vat_amount", "gross_amount", "quantity"):
            _money(name, getattr(self, name))
        _refs(self.evidence_refs)


ThreeWayMatchRecord = (
    PurchaseInvoiceRecord | PurchaseOrderRecord | GoodsReceiptRecord | PurchaseAdjustmentRecord
)


@dataclass(frozen=True, slots=True)
class ThreeWayMatchOutcome(ControlOutcome):
    finding: MatchFinding
    confidence: MatchConfidence
    subject_record_id: str
    matched_record_ids: tuple[str, ...]
    invoice_net: Decimal
    invoice_vat: Decimal
    invoice_gross: Decimal
    matched_net: Decimal
    matched_vat: Decimal
    matched_gross: Decimal
    net_difference: Decimal
    vat_difference: Decimal
    gross_difference: Decimal
    quantity_difference: Decimal | None


T = TypeVar("T")


def _dedupe(records: tuple[T, ...]) -> tuple[T, ...]:
    by_source: dict[tuple[type[object], str], T] = {}
    for record in records:
        key = (type(record), record.record_id)  # type: ignore[attr-defined]
        prior = by_source.get(key)
        if prior is not None and prior != record:
            raise ValueError(f"conflicting duplicate source record: {record.record_id}")  # type: ignore[attr-defined]
        by_source[key] = record

    deduplicated: dict[tuple[object, ...], T] = {}
    passthrough: list[T] = []
    for record in sorted(
        by_source.values(),
        key=lambda item: (type(item).__name__, item.record_id),  # type: ignore[attr-defined]
    ):
        business_key = _business_key(record)
        if business_key is None:
            passthrough.append(record)
            continue
        prior = deduplicated.get(business_key)
        if prior is None:
            deduplicated[business_key] = record
            continue
        if _semantic_key(prior) == _semantic_key(record):
            chosen = min((prior, record), key=lambda item: item.record_id)  # type: ignore[attr-defined]
            merged = _merge_refs(prior.evidence_refs, record.evidence_refs)  # type: ignore[attr-defined]
            deduplicated[business_key] = replace(chosen, evidence_refs=merged)
        else:
            # Repeated business references can be legitimate document lines. Only
            # semantically identical representations are collapsed.
            passthrough.append(record)
    result = [*deduplicated.values(), *passthrough]
    return tuple(sorted(result, key=lambda item: (type(item).__name__, item.record_id)))  # type: ignore[attr-defined]


def _business_key(record: object) -> tuple[object, ...] | None:
    if isinstance(record, PurchaseInvoiceRecord):
        return (type(record), _norm(record.vendor_id), _norm(record.invoice_reference))
    if isinstance(record, PurchaseOrderRecord):
        return (type(record), _norm(record.vendor_id), _norm(record.order_reference))
    if isinstance(record, GoodsReceiptRecord):
        return (type(record), _norm(record.vendor_id), _norm(record.receipt_reference))
    if isinstance(record, PurchaseAdjustmentRecord):
        return (type(record), _semantic_key(record))
    return None


def _semantic_key(record: object) -> tuple[object, ...]:
    return tuple(
        getattr(record, item.name)
        for item in fields(record)
        if item.name not in {"record_id", "evidence_refs"}
    )


def _merge_refs(*groups: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    found: dict[str, EvidenceRef] = {}
    for group in groups:
        for ref in group:
            found[ref.model_dump_json()] = ref
    return tuple(found[key] for key in sorted(found))


def _sum(values: list[Decimal]) -> Decimal:
    return sum(values, start=ZERO)


def _positive_difference(left: Decimal, right: Decimal, tolerance: Decimal) -> Decimal:
    difference = left - right
    return ZERO if difference <= tolerance else difference


@dataclass(slots=True)
class _Available:
    net: Decimal
    vat: Decimal | None
    gross: Decimal | None
    quantity: Decimal | None


@dataclass(frozen=True, slots=True)
class _Candidate:
    rank: int
    confidence: MatchConfidence
    receipt: GoodsReceiptRecord
    date_distance: int
    amount_distance: Decimal


class ThreeWayMatchControl:
    """Deterministically match normalized purchasing records without case verdicts."""

    control_id = "three_way_match"
    version = "1.0.0"

    def evaluate(
        self,
        context: ControlContext[ThreeWayMatchRecord, ThreeWayMatchParameters],
    ) -> tuple[ThreeWayMatchOutcome, ...]:
        parameters = context.parameters
        if parameters is None:
            raise ValueError("ThreeWayMatchParameters are required")
        records = _dedupe(context.records)
        invoices = tuple(item for item in records if isinstance(item, PurchaseInvoiceRecord))
        orders = tuple(item for item in records if isinstance(item, PurchaseOrderRecord))
        receipts = tuple(item for item in records if isinstance(item, GoodsReceiptRecord))
        adjustments = tuple(item for item in records if isinstance(item, PurchaseAdjustmentRecord))

        available = {
            item.record_id: _Available(
                item.net_amount if item.status == ReceiptStatus.ACCEPTED else ZERO,
                item.vat_amount if item.status == ReceiptStatus.ACCEPTED else ZERO,
                item.gross_amount if item.status == ReceiptStatus.ACCEPTED else ZERO,
                item.quantity if item.status == ReceiptStatus.ACCEPTED else ZERO,
            )
            for item in receipts
        }
        order_available = {
            item.record_id: _Available(
                ZERO if item.cancelled else item.net_amount,
                ZERO if item.cancelled else item.vat_amount,
                ZERO if item.cancelled else item.gross_amount,
                ZERO if item.cancelled else item.quantity,
            )
            for item in orders
        }
        adjustment_available = {
            item.record_id: _Available(
                item.net_amount, item.vat_amount, item.gross_amount, item.quantity
            )
            for item in adjustments
        }
        duplicate_ids = self._duplicate_invoice_ids(invoices)
        outcomes: list[ThreeWayMatchOutcome] = []
        for invoice in invoices:
            outcome, _consumed = self._evaluate_invoice(
                invoice,
                invoices,
                orders,
                receipts,
                adjustments,
                available,
                order_available,
                adjustment_available,
                duplicate_ids,
                parameters,
            )
            outcomes.append(outcome)

        for receipt in receipts:
            remainder = available[receipt.record_id]
            if (
                receipt.status == ReceiptStatus.ACCEPTED
                and remainder.net > parameters.amount_tolerance
            ):
                outcomes.append(self._unmatched_receipt(receipt, remainder, parameters))

        return tuple(
            sorted(outcomes, key=lambda item: (item.subject_record_id, item.finding.value))
        )

    @staticmethod
    def _duplicate_invoice_ids(invoices: tuple[PurchaseInvoiceRecord, ...]) -> set[str]:
        grouped: dict[tuple[str, str], list[PurchaseInvoiceRecord]] = {}
        for invoice in invoices:
            grouped.setdefault(
                (_norm(invoice.vendor_id), _norm(invoice.invoice_reference)), []
            ).append(invoice)
        duplicate_ids: set[str] = set()
        for group in grouped.values():
            if len(group) > 1:
                ordered = sorted(group, key=lambda item: item.record_id)
                duplicate_ids.update(item.record_id for item in ordered[1:])
        return duplicate_ids

    def _evaluate_invoice(
        self,
        invoice: PurchaseInvoiceRecord,
        invoices: tuple[PurchaseInvoiceRecord, ...],
        orders: tuple[PurchaseOrderRecord, ...],
        receipts: tuple[GoodsReceiptRecord, ...],
        adjustments: tuple[PurchaseAdjustmentRecord, ...],
        available: dict[str, _Available],
        order_available: dict[str, _Available],
        adjustment_available: dict[str, _Available],
        duplicate_ids: set[str],
        parameters: ThreeWayMatchParameters,
    ) -> tuple[ThreeWayMatchOutcome, set[str]]:
        adjustment_candidates = sorted(
            (
                item
                for item in adjustments
                if _norm(item.vendor_id) == _norm(invoice.vendor_id)
                and (
                    _norm(item.invoice_reference) == _norm(invoice.invoice_reference)
                    or (
                        invoice.purchase_order_reference
                        and _norm(item.purchase_order_reference)
                        == _norm(invoice.purchase_order_reference)
                    )
                    or (
                        invoice.goods_receipt_reference
                        and _norm(item.goods_receipt_reference)
                        == _norm(invoice.goods_receipt_reference)
                    )
                )
            ),
            key=lambda item: (
                0 if _norm(item.invoice_reference) == _norm(invoice.invoice_reference) else 1,
                item.effective_date,
                item.record_id,
            ),
        )
        related_nonaccepted = tuple(
            item
            for item in receipts
            if item.status != ReceiptStatus.ACCEPTED
            and _norm(item.vendor_id) == _norm(invoice.vendor_id)
            and (
                (
                    item.invoice_reference
                    and _norm(item.invoice_reference) == _norm(invoice.invoice_reference)
                )
                or (
                    invoice.goods_receipt_reference
                    and _norm(item.receipt_reference) == _norm(invoice.goods_receipt_reference)
                )
                or (
                    invoice.purchase_order_reference
                    and _norm(item.purchase_order_reference)
                    == _norm(invoice.purchase_order_reference)
                )
            )
        )
        linked_adjustments: list[PurchaseAdjustmentRecord] = []
        credit_net = credit_vat = credit_gross = ZERO
        for item in adjustment_candidates:
            pool = adjustment_available[item.record_id]
            take_net = min(invoice.net_amount - credit_net, pool.net)
            take_vat = min(invoice.vat_amount - credit_vat, pool.vat or ZERO)
            take_gross = min(invoice.gross_amount - credit_gross, pool.gross or ZERO)
            if take_net == ZERO and take_vat == ZERO and take_gross == ZERO:
                continue
            linked_adjustments.append(item)
            credit_net += take_net
            credit_vat += take_vat
            credit_gross += take_gross
            pool.net -= take_net
            if pool.vat is not None:
                pool.vat -= take_vat
            if pool.gross is not None:
                pool.gross -= take_gross
        cancelled = (
            invoice.cancelled
            or any(
                item.kind in {MatchAdjustmentKind.CANCELLATION, MatchAdjustmentKind.REVERSAL}
                for item in linked_adjustments
            )
            and credit_gross + parameters.amount_tolerance >= invoice.gross_amount
        )
        target_net = ZERO if cancelled else max(ZERO, invoice.net_amount - credit_net)
        target_vat = ZERO if cancelled else max(ZERO, invoice.vat_amount - credit_vat)
        target_gross = ZERO if cancelled else max(ZERO, invoice.gross_amount - credit_gross)

        candidates = self._receipt_candidates(
            invoice,
            invoices=invoices,
            receipts=receipts,
            available=available,
            parameters=parameters,
        )
        matched: list[GoodsReceiptRecord] = []
        confidences: list[MatchConfidence] = []
        net_parts: list[Decimal] = []
        vat_parts: list[Decimal] = []
        gross_parts: list[Decimal] = []
        quantity_parts: list[Decimal] = []
        remaining_net, remaining_vat, remaining_gross = target_net, target_vat, target_gross
        remaining_quantity = invoice.quantity

        for candidate in candidates:
            pool = available[candidate.receipt.record_id]
            if pool.net <= parameters.amount_tolerance and not candidate.receipt.reusable:
                continue
            take_net = min(remaining_net, pool.net)
            take_vat = min(remaining_vat, pool.vat) if pool.vat is not None else ZERO
            take_gross = min(remaining_gross, pool.gross) if pool.gross is not None else ZERO
            take_quantity = (
                min(remaining_quantity, pool.quantity)
                if remaining_quantity is not None and pool.quantity is not None
                else ZERO
            )
            if take_net == ZERO and target_net != ZERO:
                continue
            matched.append(candidate.receipt)
            confidences.append(candidate.confidence)
            net_parts.append(take_net)
            vat_parts.append(take_vat)
            gross_parts.append(take_gross)
            quantity_parts.append(take_quantity)
            remaining_net -= take_net
            remaining_vat -= take_vat
            remaining_gross -= take_gross
            if remaining_quantity is not None:
                remaining_quantity -= take_quantity
            if not candidate.receipt.reusable:
                pool.net -= take_net
                if pool.vat is not None:
                    pool.vat -= take_vat
                if pool.gross is not None:
                    pool.gross -= take_gross
                if pool.quantity is not None:
                    pool.quantity -= take_quantity
            if remaining_net <= parameters.amount_tolerance:
                break

        linked_orders = self._linked_orders(invoice, orders)
        allocated_orders: list[PurchaseOrderRecord] = []
        order_covered = order_vat_covered = order_gross_covered = ZERO
        order_quantity_covered = ZERO
        for order in linked_orders:
            pool = order_available[order.record_id]
            take_net = min(max(ZERO, target_net - order_covered), pool.net)
            take_vat = min(max(ZERO, target_vat - order_vat_covered), pool.vat or ZERO)
            take_gross = min(max(ZERO, target_gross - order_gross_covered), pool.gross or ZERO)
            take_quantity = (
                min(max(ZERO, invoice.quantity - order_quantity_covered), pool.quantity)
                if invoice.quantity is not None and pool.quantity is not None
                else ZERO
            )
            if any(value > ZERO for value in (take_net, take_vat, take_gross, take_quantity)):
                allocated_orders.append(order)
                order_covered += take_net
                order_vat_covered += take_vat
                order_gross_covered += take_gross
                order_quantity_covered += take_quantity
                if not order.reusable:
                    pool.net -= take_net
                    if pool.vat is not None:
                        pool.vat -= take_vat
                    if pool.gross is not None:
                        pool.gross -= take_gross
                    if pool.quantity is not None:
                        pool.quantity -= take_quantity

        matched_net = _sum(net_parts)
        matched_vat = _sum(vat_parts)
        matched_gross = _sum(gross_parts)
        approved_variance = _sum(
            [item.approved_price_variance for item in allocated_orders]
            + [item.approved_price_variance for item in matched]
        )
        tolerance = parameters.amount_tolerance + approved_variance
        receipt_net_difference = _positive_difference(target_net, matched_net, tolerance)
        order_net_difference = (
            _positive_difference(target_net, order_covered, tolerance) if linked_orders else ZERO
        )
        net_difference = max(receipt_net_difference, order_net_difference)
        # VAT and gross are only covered by those same dimensions; net is never substituted.
        receipt_vat_difference = _positive_difference(
            target_vat, matched_vat, parameters.amount_tolerance
        )
        order_vat_difference = (
            _positive_difference(target_vat, order_vat_covered, parameters.amount_tolerance)
            if linked_orders
            else ZERO
        )
        vat_difference = max(receipt_vat_difference, order_vat_difference)
        receipt_gross_difference = _positive_difference(target_gross, matched_gross, tolerance)
        order_gross_difference = (
            _positive_difference(target_gross, order_gross_covered, tolerance)
            if linked_orders
            else ZERO
        )
        gross_difference = max(receipt_gross_difference, order_gross_difference)
        quantity_difference = (
            _positive_difference(
                invoice.quantity,
                _sum(quantity_parts),
                parameters.quantity_tolerance,
            )
            if invoice.quantity is not None and any(item.quantity is not None for item in matched)
            else None
        )
        if invoice.quantity is not None and linked_orders:
            order_quantity_difference = _positive_difference(
                invoice.quantity, order_quantity_covered, parameters.quantity_tolerance
            )
            quantity_difference = max(quantity_difference or ZERO, order_quantity_difference)
        order_shortfall = any(
            value > ZERO
            for value in (order_net_difference, order_vat_difference, order_gross_difference)
        )
        finding, status, uncertainty = self._classify(
            invoice,
            bool(matched),
            confidences,
            net_difference,
            vat_difference,
            gross_difference,
            quantity_difference,
            cancelled,
            invoice.record_id in duplicate_ids,
            order_shortfall,
            parameters,
        )
        confidence = (
            max(confidences, key=self._confidence_rank) if confidences else MatchConfidence.NONE
        )
        evidence = _merge_refs(
            invoice.evidence_refs,
            *(item.evidence_refs for item in allocated_orders),
            *(item.evidence_refs for item in matched),
            *(item.evidence_refs for item in related_nonaccepted),
            *(item.evidence_refs for item in linked_adjustments),
        )
        matched_ids = tuple(
            sorted(
                {item.record_id for item in allocated_orders}
                | {item.record_id for item in matched}
                | {item.record_id for item in linked_adjustments}
            )
        )
        exposure = net_difference
        if finding == MatchFinding.DUPLICATE_INVOICE:
            exposure = target_gross
        counter_tests = self._counter_tests(
            invoice,
            [*matched, *related_nonaccepted],
            tuple(allocated_orders),
            tuple(linked_adjustments),
            approved_variance,
            parameters,
        )
        calculation = CalculationStep(
            sequence=1,
            label="like-for-like three-way comparison",
            expression=(
                "invoice net/VAT/gross - credits - matched receipt net/VAT/gross; "
                "approved variance and tolerance applied"
            ),
            result=(
                f"net={net_difference};vat={vat_difference};gross={gross_difference};"
                f"exposure={exposure}"
            ),
            evidence_refs=evidence,
        )
        supporting = SupportingEvidence(
            role="purchase-match",
            description=f"{finding.value} ({confidence.value} confidence)",
            evidence_refs=evidence,
        )
        return (
            ThreeWayMatchOutcome(
                control_id=self.control_id,
                control_version=self.version,
                status=status,
                group_key=(("invoice_reference", invoice.invoice_reference),),
                rule_parameters=parameters.as_items(),
                exposure_amount=exposure,
                supporting_evidence=(supporting,),
                counter_tests=counter_tests,
                uncertainty=uncertainty,
                calculation_steps=(calculation,),
                evidence_refs=evidence,
                finding=finding,
                confidence=confidence,
                subject_record_id=invoice.record_id,
                matched_record_ids=matched_ids,
                invoice_net=invoice.net_amount,
                invoice_vat=invoice.vat_amount,
                invoice_gross=invoice.gross_amount,
                matched_net=matched_net,
                matched_vat=matched_vat,
                matched_gross=matched_gross,
                net_difference=net_difference,
                vat_difference=vat_difference,
                gross_difference=gross_difference,
                quantity_difference=quantity_difference,
            ),
            {item.record_id for item in matched},
        )

    @staticmethod
    def _confidence_rank(value: MatchConfidence) -> int:
        return {
            MatchConfidence.EXACT: 0,
            MatchConfidence.HIGH: 1,
            MatchConfidence.LOW: 2,
            MatchConfidence.NONE: 3,
        }[value]

    def _receipt_candidates(
        self,
        invoice: PurchaseInvoiceRecord,
        invoices: tuple[PurchaseInvoiceRecord, ...],
        receipts: tuple[GoodsReceiptRecord, ...],
        available: dict[str, _Available],
        parameters: ThreeWayMatchParameters,
    ) -> tuple[_Candidate, ...]:
        result: list[_Candidate] = []
        for receipt in receipts:
            if receipt.status != ReceiptStatus.ACCEPTED:
                continue
            if _norm(receipt.vendor_id) != _norm(invoice.vendor_id):
                continue
            exact = (
                bool(receipt.invoice_reference)
                and _norm(receipt.invoice_reference) == _norm(invoice.invoice_reference)
            ) or (
                bool(invoice.goods_receipt_reference)
                and _norm(invoice.goods_receipt_reference) == _norm(receipt.receipt_reference)
            )
            po_link = bool(invoice.purchase_order_reference) and (
                _norm(invoice.purchase_order_reference) == _norm(receipt.purchase_order_reference)
            )
            receipt_link = bool(invoice.goods_receipt_reference) and (
                _norm(invoice.goods_receipt_reference) == _norm(receipt.receipt_reference)
            )
            claimed_by_other = bool(receipt.invoice_reference) and not (
                _norm(receipt.invoice_reference) == _norm(invoice.invoice_reference)
            )
            claimed_by_other = claimed_by_other or any(
                other.record_id != invoice.record_id
                and _norm(other.vendor_id) == _norm(invoice.vendor_id)
                and bool(other.goods_receipt_reference)
                and _norm(other.goods_receipt_reference) == _norm(receipt.receipt_reference)
                for other in invoices
            )
            if claimed_by_other and not exact:
                continue
            distance = abs((invoice.invoice_date - receipt.receipt_date).days)
            amount_distance = abs(invoice.net_amount - available[receipt.record_id].net)
            fallback = (
                not receipt.invoice_reference
                and not receipt.purchase_order_reference
                and distance <= parameters.date_window_days
                and amount_distance <= parameters.amount_tolerance
            )
            if exact:
                result.append(
                    _Candidate(1, MatchConfidence.EXACT, receipt, distance, amount_distance)
                )
            elif po_link:
                result.append(
                    _Candidate(2, MatchConfidence.HIGH, receipt, distance, amount_distance)
                )
            elif receipt_link:
                result.append(
                    _Candidate(3, MatchConfidence.HIGH, receipt, distance, amount_distance)
                )
            elif fallback:
                result.append(
                    _Candidate(4, MatchConfidence.LOW, receipt, distance, amount_distance)
                )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.rank,
                    item.date_distance,
                    item.amount_distance,
                    item.receipt.record_id,
                ),
            )
        )

    @staticmethod
    def _linked_orders(
        invoice: PurchaseInvoiceRecord, orders: tuple[PurchaseOrderRecord, ...]
    ) -> tuple[PurchaseOrderRecord, ...]:
        result = [
            order
            for order in orders
            if not order.cancelled
            and _norm(order.vendor_id) == _norm(invoice.vendor_id)
            and (
                (
                    bool(order.invoice_reference)
                    and _norm(order.invoice_reference) == _norm(invoice.invoice_reference)
                )
                or (
                    bool(invoice.purchase_order_reference)
                    and _norm(invoice.purchase_order_reference) == _norm(order.order_reference)
                )
            )
        ]
        return tuple(sorted(result, key=lambda item: item.record_id))

    @staticmethod
    def _classify(
        invoice: PurchaseInvoiceRecord,
        has_receipt: bool,
        confidences: list[MatchConfidence],
        net_difference: Decimal,
        vat_difference: Decimal,
        gross_difference: Decimal,
        quantity_difference: Decimal | None,
        cancelled: bool,
        duplicate: bool,
        order_shortfall: bool,
        parameters: ThreeWayMatchParameters,
    ) -> tuple[MatchFinding, OutcomeStatus, tuple[str, ...]]:
        if duplicate:
            return (
                MatchFinding.DUPLICATE_INVOICE,
                OutcomeStatus.REVIEW_NEEDED,
                ("same vendor and invoice reference occurs in multiple source records",),
            )
        if cancelled:
            return MatchFinding.CANCELLED_OR_REVERSED, OutcomeStatus.DISMISSED, ()
        if invoice.gross_amount > ZERO and gross_difference == ZERO and not has_receipt:
            # A fully linked credit/return can extinguish the invoice without a receipt.
            return MatchFinding.CANCELLED_OR_REVERSED, OutcomeStatus.DISMISSED, ()
        if invoice.classification in {None, PurchaseClassification.UNKNOWN}:
            return (
                MatchFinding.REVIEW_CLASSIFICATION,
                OutcomeStatus.REVIEW_NEEDED,
                ("invoice purchase classification is unknown",),
            )
        if not has_receipt and invoice.classification == PurchaseClassification.SERVICE:
            return MatchFinding.SERVICE_WITHOUT_RECEIPT, OutcomeStatus.DISMISSED, ()
        if not has_receipt:
            return (
                MatchFinding.UNMATCHED_INVOICE,
                OutcomeStatus.REVIEW_NEEDED,
                ("no accepted goods receipt or service acceptance matched",),
            )
        if order_shortfall:
            return (
                MatchFinding.OVER_INVOICED,
                OutcomeStatus.REVIEW_NEEDED,
                ("invoice exceeds allocated order coverage",),
            )
        if quantity_difference is not None and quantity_difference > parameters.quantity_tolerance:
            return (
                MatchFinding.PARTIAL_DELIVERY,
                OutcomeStatus.REVIEW_NEEDED,
                ("invoiced quantity exceeds matched accepted quantity",),
            )
        if net_difference > ZERO or vat_difference > ZERO or gross_difference > ZERO:
            return (
                MatchFinding.AMOUNT_DIFFERENCE,
                OutcomeStatus.REVIEW_NEEDED,
                ("like-for-like amount dimensions differ beyond tolerance",),
            )
        if MatchConfidence.LOW in confidences:
            return (
                MatchFinding.FALLBACK_MATCH,
                OutcomeStatus.REVIEW_NEEDED,
                ("matched only by vendor, amount, and date window",),
            )
        return MatchFinding.MATCHED, OutcomeStatus.DISMISSED, ()

    @staticmethod
    def _counter_tests(
        invoice: PurchaseInvoiceRecord,
        receipts: list[GoodsReceiptRecord],
        orders: tuple[PurchaseOrderRecord, ...],
        adjustments: tuple[PurchaseAdjustmentRecord, ...],
        approved_variance: Decimal,
        parameters: ThreeWayMatchParameters,
    ) -> tuple[CounterTestResult, ...]:
        def item(
            name: str, present: bool, description: str, refs: tuple[EvidenceRef, ...] = ()
        ) -> CounterTestResult:
            return CounterTestResult(
                name=name,
                status=CounterTestStatus.ACCOUNTED_FOR if present else CounterTestStatus.NOT_FOUND,
                description=description,
                evidence_refs=refs,
            )

        receipt_refs = (
            _merge_refs(*(record.evidence_refs for record in receipts)) if receipts else ()
        )
        adjustment_refs = (
            _merge_refs(*(record.evidence_refs for record in adjustments)) if adjustments else ()
        )
        return (
            item(
                "valid service invoice",
                invoice.classification == PurchaseClassification.SERVICE,
                "service classification considered",
            ),
            item(
                "service acceptance",
                any(r.classification == PurchaseClassification.SERVICE for r in receipts),
                "explicit service acceptance considered",
                receipt_refs,
            ),
            item(
                "partial delivery or backorder",
                bool(receipts) and sum((r.net_amount for r in receipts), ZERO) < invoice.net_amount,
                "partial accepted coverage retained rather than treated as duplicate",
                receipt_refs,
            ),
            item(
                "legitimate timing difference",
                any(
                    abs((invoice.invoice_date - r.receipt_date).days) <= parameters.date_window_days
                    for r in receipts
                ),
                "configured date window considered",
                receipt_refs,
            ),
            item(
                "approved price variance",
                approved_variance > ZERO,
                "approved variance applied to net difference",
                _merge_refs(*(o.evidence_refs for o in orders)) if orders else (),
            ),
            item(
                "return or rejection",
                any(r.status in {ReceiptStatus.RETURNED, ReceiptStatus.REJECTED} for r in receipts),
                "returned and rejected quantities excluded",
                receipt_refs,
            ),
            item(
                "credit note",
                any(a.kind == MatchAdjustmentKind.CREDIT_NOTE for a in adjustments),
                "credit notes reduce the linked invoice",
                adjustment_refs,
            ),
            item(
                "cancellation or reversal",
                invoice.cancelled
                or any(
                    a.kind in {MatchAdjustmentKind.CANCELLATION, MatchAdjustmentKind.REVERSAL}
                    for a in adjustments
                ),
                "cancellation and reversal considered",
                adjustment_refs,
            ),
            item(
                "explicit reference already matched",
                bool(receipts),
                "single-use allocation prevents a second match",
                receipt_refs,
            ),
        )

    def _unmatched_receipt(
        self,
        receipt: GoodsReceiptRecord,
        remainder: _Available,
        parameters: ThreeWayMatchParameters,
    ) -> ThreeWayMatchOutcome:
        evidence = receipt.evidence_refs
        return ThreeWayMatchOutcome(
            control_id=self.control_id,
            control_version=self.version,
            status=OutcomeStatus.REVIEW_NEEDED,
            group_key=(("receipt_reference", receipt.receipt_reference),),
            rule_parameters=parameters.as_items(),
            exposure_amount=remainder.net,
            supporting_evidence=(
                SupportingEvidence(
                    role="unmatched-receipt",
                    description="accepted receipt has no allocated invoice",
                    evidence_refs=evidence,
                ),
            ),
            counter_tests=(),
            uncertainty=("no invoice matched this accepted receipt",),
            calculation_steps=(
                CalculationStep(
                    sequence=1,
                    label="unmatched receipt net",
                    expression="accepted receipt net - allocated invoice net",
                    result=str(remainder.net),
                    evidence_refs=evidence,
                ),
            ),
            evidence_refs=evidence,
            finding=MatchFinding.UNMATCHED_RECEIPT,
            confidence=MatchConfidence.NONE,
            subject_record_id=receipt.record_id,
            matched_record_ids=(),
            invoice_net=ZERO,
            invoice_vat=ZERO,
            invoice_gross=ZERO,
            matched_net=ZERO,
            matched_vat=ZERO,
            matched_gross=ZERO,
            net_difference=remainder.net,
            vat_difference=ZERO,
            gross_difference=ZERO,
            quantity_difference=remainder.quantity,
        )
