"""Deterministic year-end cut-off and unrecorded-liability control.

The record-oriented :class:`YearEndCutoffControl` is deliberately not production wired.
Adapters can later translate canonical events into the local immutable input records below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from audit_compiler.controls.base import (
    CalcInput,
    Calculation,
    CalculationStep,
    ControlContext,
    ControlOutcome,
    CounterTest,
    CounterTestResult,
    CounterTestStatus,
    EvidenceStep,
    Finding,
    OutcomeStatus,
    SupportingEvidence,
)
from audit_compiler.models import EvidenceRef
from audit_compiler.normalization import normalize_identifier


def _decimal(name: str, value: Decimal, *, nonnegative: bool = True) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or (nonnegative and value < 0):
        raise ValueError(f"{name} must be finite and non-negative")


def _text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _refs(refs: tuple[EvidenceRef, ...]) -> None:
    if not refs or not all(isinstance(ref, EvidenceRef) for ref in refs):
        raise ValueError("each record requires exact EvidenceRefs")


class MatchField(StrEnum):
    INVOICE_ID = "invoice_id"
    DOCUMENT_ID = "document_id"
    RECEIPT_ID = "receipt_id"
    VENDOR_AMOUNT = "vendor_amount"


class ReceiptStatus(StrEnum):
    ACCEPTED = "accepted"
    RETURNED = "returned"
    REJECTED = "rejected"
    DISPUTED = "disputed"


class AdjustmentKind(StrEnum):
    CREDIT_NOTE = "credit_note"
    REVERSAL = "reversal"
    CANCELLATION = "cancellation"


class ClosingRecordKind(StrEnum):
    LIABILITY = "liability"
    ACCRUAL = "accrual"
    PROVISION = "provision"


@dataclass(frozen=True, slots=True)
class CutoffParameters:
    fiscal_period_start: date
    fiscal_period_end: date
    amount_tolerance: Decimal = Decimal("0.00")
    matching_hierarchy: tuple[MatchField, ...] = (
        MatchField.INVOICE_ID,
        MatchField.DOCUMENT_ID,
        MatchField.RECEIPT_ID,
        MatchField.VENDOR_AMOUNT,
    )

    def __post_init__(self) -> None:
        if type(self.fiscal_period_start) is not date or type(self.fiscal_period_end) is not date:
            raise TypeError("fiscal period boundaries must be dates")
        if self.fiscal_period_start > self.fiscal_period_end:
            raise ValueError("fiscal period start must not follow its end")
        _decimal("amount_tolerance", self.amount_tolerance)
        if not self.matching_hierarchy or len(set(self.matching_hierarchy)) != len(
            self.matching_hierarchy
        ):
            raise ValueError("matching hierarchy must contain unique fields")
        if not all(isinstance(field, MatchField) for field in self.matching_hierarchy):
            raise TypeError("matching hierarchy must contain MatchField values")

    def as_items(self) -> tuple[tuple[str, str], ...]:
        return (
            ("fiscal_period_start", self.fiscal_period_start.isoformat()),
            ("fiscal_period_end", self.fiscal_period_end.isoformat()),
            ("amount_tolerance", str(self.amount_tolerance)),
            ("matching_hierarchy", "|".join(field.value for field in self.matching_hierarchy)),
        )


@dataclass(frozen=True, slots=True)
class CutoffInvoiceRecord:
    record_id: str
    invoice_id: str
    vendor_id: str
    document_id: str
    invoice_date: date
    posting_date: date | None
    net_amount: Decimal
    vat_amount: Decimal
    gross_amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    receipt_id: str | None = None
    description: str = ""
    accounting_period_known: bool = True

    def __post_init__(self) -> None:
        for name in ("record_id", "invoice_id", "vendor_id", "document_id"):
            _text(name, getattr(self, name))
        if type(self.invoice_date) is not date:
            raise TypeError("invoice_date must be a date")
        if self.posting_date is not None and type(self.posting_date) is not date:
            raise TypeError("posting_date must be a date when supplied")
        for name in ("net_amount", "vat_amount", "gross_amount"):
            _decimal(name, getattr(self, name))
        _refs(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class ServiceReceiptRecord:
    record_id: str
    occurrence_date: date | None
    evidence_refs: tuple[EvidenceRef, ...]
    invoice_id: str | None = None
    vendor_id: str | None = None
    document_id: str | None = None
    receipt_id: str | None = None
    net_amount: Decimal | None = None
    status: ReceiptStatus = ReceiptStatus.ACCEPTED
    description: str = ""

    def __post_init__(self) -> None:
        _text("record_id", self.record_id)
        if self.occurrence_date is not None and type(self.occurrence_date) is not date:
            raise TypeError("occurrence_date must be a date when supplied")
        if self.net_amount is not None:
            _decimal("net_amount", self.net_amount)
        _refs(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class ClosingBalanceRecord:
    record_id: str
    kind: ClosingRecordKind
    posting_date: date | None
    net_amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    invoice_id: str | None = None
    vendor_id: str | None = None
    document_id: str | None = None
    receipt_id: str | None = None
    service_date: date | None = None
    generic: bool = False
    accounting_period_known: bool = True

    def __post_init__(self) -> None:
        _text("record_id", self.record_id)
        if not isinstance(self.kind, ClosingRecordKind):
            raise TypeError("kind must be ClosingRecordKind")
        if self.posting_date is not None and type(self.posting_date) is not date:
            raise TypeError("posting_date must be a date when supplied")
        _decimal("net_amount", self.net_amount)
        _refs(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class CutoffAdjustmentRecord:
    record_id: str
    kind: AdjustmentKind
    effective_date: date
    net_amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    invoice_id: str | None = None
    vendor_id: str | None = None
    document_id: str | None = None

    def __post_init__(self) -> None:
        _text("record_id", self.record_id)
        if not isinstance(self.kind, AdjustmentKind):
            raise TypeError("kind must be AdjustmentKind")
        if type(self.effective_date) is not date:
            raise TypeError("effective_date must be a date")
        _decimal("net_amount", self.net_amount)
        _refs(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class CutoffPolicyExceptionRecord:
    record_id: str
    reason: str
    evidence_refs: tuple[EvidenceRef, ...]
    invoice_id: str | None = None
    document_id: str | None = None

    def __post_init__(self) -> None:
        _text("record_id", self.record_id)
        _text("reason", self.reason)
        _refs(self.evidence_refs)


CutoffRecord = (
    CutoffInvoiceRecord
    | ServiceReceiptRecord
    | ClosingBalanceRecord
    | CutoffAdjustmentRecord
    | CutoffPolicyExceptionRecord
)


@dataclass(frozen=True, slots=True)
class CutoffOutcome(ControlOutcome):
    invoice_id: str
    potentially_unrecorded_net: Decimal
    invoice_vat_amount: Decimal
    invoice_gross_amount: Decimal
    closing_coverage_net: Decimal
    adjustment_net: Decimal


T = TypeVar("T")


def _dedupe(records: tuple[T, ...]) -> tuple[T, ...]:
    found: dict[tuple[object, ...], T] = {}
    for record in records:
        if isinstance(record, CutoffInvoiceRecord):
            key = (type(record), _norm(record.vendor_id), _norm(record.invoice_id))
        elif isinstance(record, ServiceReceiptRecord):
            identity = _norm(record.receipt_id) or _norm(record.invoice_id)
            key = (type(record), identity, record.occurrence_date, record.status)
        else:
            key = (type(record), record.record_id)
        previous = found.get(key)
        if previous is None:
            found[key] = record
        elif previous != record:
            if (
                isinstance(previous, CutoffInvoiceRecord)
                and isinstance(record, CutoffInvoiceRecord)
                and (
                    previous.net_amount,
                    previous.vat_amount,
                    previous.gross_amount,
                    previous.invoice_date,
                )
                != (
                    record.net_amount,
                    record.vat_amount,
                    record.gross_amount,
                    record.invoice_date,
                )
            ):
                raise ValueError(f"conflicting duplicate invoice: {record.invoice_id}")
            found[key] = min((previous, record), key=lambda item: item.record_id)
    return tuple(sorted(found.values(), key=lambda item: (type(item).__name__, item.record_id)))


def _norm(value: str | None) -> str:
    return normalize_identifier(value) if value else ""


def _exact_link(invoice: CutoffInvoiceRecord, candidate: object, field: MatchField) -> bool:
    if field == MatchField.INVOICE_ID:
        return bool(_norm(invoice.invoice_id)) and _norm(invoice.invoice_id) == _norm(
            getattr(candidate, "invoice_id", None)
        )
    if field == MatchField.DOCUMENT_ID:
        return bool(_norm(invoice.document_id)) and _norm(invoice.document_id) == _norm(
            getattr(candidate, "document_id", None)
        )
    if field == MatchField.RECEIPT_ID:
        return bool(_norm(invoice.receipt_id)) and _norm(invoice.receipt_id) == _norm(
            getattr(candidate, "receipt_id", None)
        )
    return False


def _match_rank(
    invoice: CutoffInvoiceRecord,
    candidate: object,
    parameters: CutoffParameters,
    amount: Decimal | None = None,
) -> int | None:
    for rank, field in enumerate(parameters.matching_hierarchy):
        if _exact_link(invoice, candidate, field):
            return rank
        if field == MatchField.VENDOR_AMOUNT:
            candidate_amount = getattr(candidate, "net_amount", None)
            if (
                _norm(invoice.vendor_id)
                and _norm(invoice.vendor_id) == _norm(getattr(candidate, "vendor_id", None))
                and candidate_amount is not None
                and abs(candidate_amount - (amount if amount is not None else invoice.net_amount))
                <= parameters.amount_tolerance
            ):
                return rank
    return None


def _merge_refs(*groups: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    refs: dict[str, EvidenceRef] = {}
    for group in groups:
        for ref in group:
            refs[str(ref.evidence_id)] = ref
    return tuple(refs[key] for key in sorted(refs))


class YearEndCutoffControl:
    """Evaluate each subsequent-period invoice without assigning a case verdict."""

    control_id = "year_end_cutoff_unrecorded_liability"
    version = "1.0.0"

    def evaluate(
        self, context: ControlContext[CutoffRecord, CutoffParameters]
    ) -> tuple[CutoffOutcome, ...]:
        if not isinstance(context.parameters, CutoffParameters):
            raise TypeError("YearEndCutoffControl requires CutoffParameters")
        parameters = context.parameters
        records = _dedupe(context.records)
        allowed = (
            CutoffInvoiceRecord,
            ServiceReceiptRecord,
            ClosingBalanceRecord,
            CutoffAdjustmentRecord,
            CutoffPolicyExceptionRecord,
        )
        if not all(isinstance(record, allowed) for record in records):
            raise TypeError("unsupported cut-off record type")

        invoices = sorted(
            (record for record in records if isinstance(record, CutoffInvoiceRecord)),
            key=lambda item: (
                item.invoice_date,
                _norm(item.vendor_id),
                _norm(item.invoice_id),
                item.record_id,
            ),
        )
        receipts = tuple(record for record in records if isinstance(record, ServiceReceiptRecord))
        closing = tuple(record for record in records if isinstance(record, ClosingBalanceRecord))
        adjustments = tuple(
            record for record in records if isinstance(record, CutoffAdjustmentRecord)
        )
        exceptions = tuple(
            record for record in records if isinstance(record, CutoffPolicyExceptionRecord)
        )
        used_receipts: set[str] = set()
        used_closing: set[str] = set()
        used_adjustments: set[str] = set()
        outcomes: list[CutoffOutcome] = []

        for invoice in invoices:
            # An invoice/posting wholly inside the closing period is already recorded.
            posting = invoice.posting_date or invoice.invoice_date
            if (
                invoice.invoice_date <= parameters.fiscal_period_end
                or posting <= parameters.fiscal_period_end
            ):
                continue

            receipt_candidates = [
                (rank, receipt)
                for receipt in receipts
                if receipt.record_id not in used_receipts
                and (rank := _match_rank(invoice, receipt, parameters)) is not None
            ]
            receipt_candidates.sort(key=lambda item: (item[0], item[1].record_id))
            receipt = receipt_candidates[0][1] if receipt_candidates else None
            if receipt is not None:
                used_receipts.add(receipt.record_id)

            uncertainty: list[str] = []
            refuters: list[tuple[EvidenceRef, ...]] = []
            if not invoice.accounting_period_known:
                uncertainty.append("invoice accounting period is uncertain")
            if receipt is None or receipt.occurrence_date is None:
                uncertainty.append("service, delivery, or receipt date is missing")
            elif receipt.occurrence_date > parameters.fiscal_period_end:
                continue
            elif receipt.occurrence_date < parameters.fiscal_period_start:
                uncertainty.append("occurrence predates the configured fiscal period")

            if receipt is not None and receipt.status != ReceiptStatus.ACCEPTED:
                refuters.append(receipt.evidence_refs)

            policy = sorted(
                (item for item in exceptions if _match_rank(invoice, item, parameters) is not None),
                key=lambda item: item.record_id,
            )
            refuters.extend(item.evidence_refs for item in policy)

            available_closing = []
            generic = []
            for item in closing:
                if item.record_id in used_closing:
                    continue
                rank = _match_rank(invoice, item, parameters)
                if item.generic:
                    if rank is not None or _norm(item.vendor_id) == _norm(invoice.vendor_id):
                        generic.append(item)
                    continue
                if rank is None:
                    continue
                if not item.accounting_period_known or item.posting_date is None:
                    uncertainty.append(
                        f"closing record {item.record_id} has uncertain accounting period"
                    )
                    refuters.append(item.evidence_refs)
                    continue
                if (
                    parameters.fiscal_period_start
                    <= item.posting_date
                    <= parameters.fiscal_period_end
                ):
                    available_closing.append((rank, item))
            available_closing.sort(key=lambda value: (value[0], value[1].record_id))

            remaining = invoice.net_amount
            matched_closing: list[ClosingBalanceRecord] = []
            for _, item in available_closing:
                if remaining <= parameters.amount_tolerance:
                    break
                matched_closing.append(item)
                used_closing.add(item.record_id)
                remaining = max(Decimal("0"), remaining - item.net_amount)

            matched_adjustments: list[CutoffAdjustmentRecord] = []
            for item in sorted(adjustments, key=lambda value: value.record_id):
                if item.record_id in used_adjustments:
                    continue
                if _match_rank(invoice, item, parameters) is not None:
                    matched_adjustments.append(item)
                    used_adjustments.add(item.record_id)
            adjustment_net = min(
                invoice.net_amount,
                sum((item.net_amount for item in matched_adjustments), Decimal("0")),
            )
            coverage = min(
                invoice.net_amount - adjustment_net,
                sum((item.net_amount for item in matched_closing), Decimal("0")),
            )
            exposure = max(Decimal("0"), invoice.net_amount - adjustment_net - coverage)
            if exposure <= parameters.amount_tolerance:
                exposure = Decimal("0")

            if generic:
                uncertainty.append("generic accrual lacks a defensible transaction link")
                refuters.extend(item.evidence_refs for item in generic)

            dismissed = bool(
                (receipt is not None and receipt.status != ReceiptStatus.ACCEPTED)
                or policy
                or adjustment_net >= invoice.net_amount - parameters.amount_tolerance
                or exposure == 0
            )
            if uncertainty:
                status = OutcomeStatus.REVIEW_NEEDED
            elif dismissed:
                status = OutcomeStatus.DISMISSED
            else:
                status = OutcomeStatus.CONFIRMED_CANDIDATE

            receipt_refs = receipt.evidence_refs if receipt is not None else invoice.evidence_refs
            closing_refs = _merge_refs(*(item.evidence_refs for item in matched_closing))
            adjustment_refs = _merge_refs(*(item.evidence_refs for item in matched_adjustments))
            refuter_refs = _merge_refs(*refuters)
            all_refs = _merge_refs(
                invoice.evidence_refs, receipt_refs, closing_refs, adjustment_refs, refuter_refs
            )
            support = [
                SupportingEvidence(
                    "invoice", "subsequent-period supplier invoice", invoice.evidence_refs
                ),
                SupportingEvidence(
                    "service_or_receipt",
                    "linked service, delivery, or acceptance evidence",
                    receipt_refs,
                ),
            ]
            if closing_refs:
                support.append(
                    SupportingEvidence("closing_coverage", "matched closing records", closing_refs)
                )
            if refuter_refs:
                support.append(
                    SupportingEvidence(
                        "refuter", "counter-evidence requiring evaluation", refuter_refs
                    )
                )

            counter_tests = (
                CounterTestResult(
                    "closing_liability_or_accrual",
                    CounterTestStatus.ACCOUNTED_FOR
                    if exposure == 0 and coverage
                    else (CounterTestStatus.UNRESOLVED if generic else CounterTestStatus.NOT_FOUND),
                    "transaction-linked closing coverage was allocated once"
                    if matched_closing
                    else "no transaction-linked closing coverage was found",
                    closing_refs or _merge_refs(*(item.evidence_refs for item in generic)),
                ),
                CounterTestResult(
                    "reversal_credit_or_cancellation",
                    CounterTestStatus.ACCOUNTED_FOR
                    if matched_adjustments
                    else CounterTestStatus.NOT_FOUND,
                    "linked adjustment reduces the invoice net amount"
                    if matched_adjustments
                    else "no linked adjustment was found",
                    adjustment_refs,
                ),
                CounterTestResult(
                    "return_dispute_or_policy_exception",
                    CounterTestStatus.ACCOUNTED_FOR
                    if dismissed and refuter_refs
                    else CounterTestStatus.NOT_FOUND,
                    "linked counter-evidence was found"
                    if refuter_refs
                    else "no linked counter-evidence was found",
                    refuter_refs,
                ),
            )
            calculations = (
                CalculationStep(
                    1,
                    "invoice net",
                    str(invoice.net_amount),
                    str(invoice.net_amount),
                    invoice.evidence_refs,
                ),
                CalculationStep(
                    2,
                    "transaction-linked closing coverage",
                    " + ".join(str(item.net_amount) for item in matched_closing) or "0",
                    str(coverage),
                    closing_refs or invoice.evidence_refs,
                ),
                CalculationStep(
                    3,
                    "linked adjustments",
                    " + ".join(str(item.net_amount) for item in matched_adjustments) or "0",
                    str(adjustment_net),
                    adjustment_refs or invoice.evidence_refs,
                ),
                CalculationStep(
                    4,
                    "potentially unrecorded net",
                    f"max(0, {invoice.net_amount} - {coverage} - {adjustment_net})",
                    str(exposure),
                    all_refs,
                ),
            )
            outcomes.append(
                CutoffOutcome(
                    control_id=self.control_id,
                    control_version=self.version,
                    status=status,
                    group_key=(("invoice_id", invoice.invoice_id),),
                    rule_parameters=parameters.as_items(),
                    exposure_amount=exposure,
                    supporting_evidence=tuple(support),
                    counter_tests=counter_tests,
                    uncertainty=tuple(dict.fromkeys(uncertainty)),
                    calculation_steps=calculations,
                    evidence_refs=all_refs,
                    invoice_id=invoice.invoice_id,
                    potentially_unrecorded_net=exposure,
                    invoice_vat_amount=invoice.vat_amount,
                    invoice_gross_amount=invoice.gross_amount,
                    closing_coverage_net=coverage,
                    adjustment_net=adjustment_net,
                )
            )
        return tuple(outcomes)


class CutoffControl:
    """Legacy dossier adapter retained for existing production wiring.

    New integrations should adapt canonical events into ``YearEndCutoffControl`` records.
    Unlike the former implementation, this adapter has no hard-coded fiscal year.
    """

    id = "cutoff"
    version = "0.2.0"

    def run(self, ctx: ControlContext) -> list[Finding]:
        from audit_compiler.ir.roles import as_date, find_tables, money, resolve_column

        configured = ctx.params.get("fiscal_year_end")
        period_end = as_date(configured) if isinstance(configured, str) else None
        if period_end is None:
            # Policy extraction is intentionally local to this compatibility adapter.
            from audit_compiler.ir.roles import extract_fiscal_year_end

            period_end, evidence = extract_fiscal_year_end(ctx.dossier, default=date.max)
            if period_end == date.max:
                return []
        else:
            evidence = None
        candidates: list[tuple[Decimal, EvidenceRef, tuple[EvidenceRef, ...], str]] = []
        for table in find_tables(ctx.dossier, {"invoice_date", "service_date", "amount"}):
            inv = resolve_column(table, "invoice_date")
            service = resolve_column(table, "service_date")
            amount = resolve_column(table, "amount")
            document = resolve_column(table, "document_no")
            if inv == service:
                continue
            for row_number, row in enumerate(table.rows):
                invoice_date = as_date(row[inv])
                service_date = as_date(row[service])
                value = money(row[amount])
                if (
                    invoice_date
                    and service_date
                    and value
                    and service_date <= period_end < invoice_date
                ):
                    amount_ref = table.evidence(row_number, amount, normalized=str(value))
                    refs = (
                        table.evidence(row_number, inv),
                        table.evidence(row_number, service),
                        amount_ref,
                    )
                    candidates.append(
                        (value, amount_ref, refs, row.get(document, "") if document else "")
                    )
        if not candidates:
            return []
        candidates.sort(key=lambda item: (item[3], str(item[1].evidence_id)))
        exposure = sum((item[0] for item in candidates), Decimal("0"))
        chain = [
            EvidenceStep("subsequent invoice and prior-period service", item[2])
            for item in candidates[:8]
        ]
        if evidence is not None:
            chain.insert(0, EvidenceStep(f"Balance-sheet date is {period_end}", (evidence,)))
        inputs = tuple(CalcInput(item[3], item[0], item[1]) for item in candidates)
        return [
            Finding(
                control_id=self.id,
                control_version=self.version,
                title="Prior-period costs booked in the subsequent period",
                assertion="Cut-off / completeness of liabilities",
                severity="high",
                narrative=(
                    f"{len(candidates)} subsequent-period invoices relate to prior-period service."
                ),
                exposure=exposure,
                exposure_label="net",
                evidence_chain=tuple(chain),
                calculation=Calculation(
                    " + ".join(str(item.value) for item in inputs),
                    inputs,
                    exposure,
                    "legacy adapter",
                ),
                counter_tests=(
                    CounterTest(
                        "strong_record_reconciliation",
                        "absent",
                        "Use the isolated strong control for transaction-level reconciliation.",
                    ),
                ),
                recommended_action="Reconcile each invoice through the strong cut-off control.",
                uncertainty=(
                    "The compatibility adapter does not clear accruals; admission must review it."
                ),
                subject="cutoff-subsequent-invoices",
            )
        ]
