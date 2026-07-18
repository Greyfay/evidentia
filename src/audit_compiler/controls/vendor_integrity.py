"""Deterministic vendor-integrity and segregation-of-duties control."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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


class VendorEventKind(StrEnum):
    CREATED = "created"
    APPROVED = "approved"


class PermissionKind(StrEnum):
    CREATE_VENDOR = "create_vendor"
    POST_SUPPLIER_INVOICE = "post_supplier_invoice"
    EXECUTE_PAYMENT = "execute_payment"


class PurchaseKind(StrEnum):
    GOODS = "goods"
    SERVICE = "service"
    UNKNOWN = "unknown"


class SupportingEvidenceKind(StrEnum):
    CONTRACT = "contract"
    DELIVERABLE = "deliverable"
    SERVICE_ACCEPTANCE = "service_acceptance"
    GOODS_RECEIPT = "goods_receipt"
    LEGITIMATE_FOUR_EYES = "legitimate_four_eyes"


class VendorSignalType(StrEnum):
    MISSING_VENDOR_CREATION_EVENT = "missing_vendor_creation_event"
    NEW_VENDOR = "new_vendor"
    CREATOR_EQUALS_APPROVER = "creator_equals_approver"
    CREATE_AND_PAY_PERMISSION = "create_and_pay_permission"
    SAME_USER_CREATES_POSTS_PAYS = "same_user_creates_posts_pays"
    RAPID_FIRST_INVOICE = "rapid_first_invoice"
    RAPID_FIRST_PAYMENT = "rapid_first_payment"
    INVOICE_PAID_UNUSUALLY_QUICKLY = "invoice_paid_unusually_quickly"
    MISSING_INDEPENDENT_APPROVAL = "missing_independent_approval"
    MISSING_APPROVAL_LOG = "missing_approval_log"
    NO_PRIOR_VENDOR_HISTORY = "no_prior_vendor_history"
    MISSING_SERVICE_OR_DELIVERY_EVIDENCE = "missing_service_or_delivery_evidence"


_DEFAULT_WEIGHTS = tuple((signal, Decimal("1")) for signal in VendorSignalType)


def _validate_identifier(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_evidence(evidence_refs: tuple[EvidenceRef, ...]) -> None:
    if not evidence_refs:
        raise ValueError("each normalized input requires at least one EvidenceRef")
    if not all(isinstance(evidence, EvidenceRef) for evidence in evidence_refs):
        raise TypeError("evidence_refs must contain only EvidenceRefs")


def _validate_date(name: str, value: object) -> None:
    if type(value) is not date:
        raise TypeError(f"{name} must be a date")


def _validate_decimal(name: str, value: object, *, allow_negative: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if not allow_negative and value < 0:
        raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class VendorLifecycleEvent:
    record_id: str
    vendor_id: str
    kind: VendorEventKind
    user_id: str
    event_date: date
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("vendor_id", self.vendor_id),
            ("user_id", self.user_id),
        ):
            _validate_identifier(name, value)
        _validate_date("event_date", self.event_date)
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class UserPermissionRecord:
    record_id: str
    user_id: str
    permission: PermissionKind
    active: bool
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_identifier("record_id", self.record_id)
        _validate_identifier("user_id", self.user_id)
        if not isinstance(self.active, bool):
            raise TypeError("active must be boolean")
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class SupplierInvoiceRecord:
    record_id: str
    vendor_id: str
    invoice_id: str
    posting_user_id: str
    posting_date: date
    purchase_kind: PurchaseKind
    net_amount: Decimal | None
    tax_amount: Decimal | None
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("vendor_id", self.vendor_id),
            ("invoice_id", self.invoice_id),
            ("posting_user_id", self.posting_user_id),
        ):
            _validate_identifier(name, value)
        _validate_date("posting_date", self.posting_date)
        if self.net_amount is not None:
            _validate_decimal("net_amount", self.net_amount)
        if self.tax_amount is not None:
            _validate_decimal("tax_amount", self.tax_amount)
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class OutgoingPaymentRecord:
    record_id: str
    vendor_id: str
    payment_id: str
    invoice_id: str | None
    execution_user_id: str
    payment_date: date
    gross_amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    reversal_of: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("vendor_id", self.vendor_id),
            ("payment_id", self.payment_id),
            ("execution_user_id", self.execution_user_id),
        ):
            _validate_identifier(name, value)
        if self.invoice_id is not None:
            _validate_identifier("invoice_id", self.invoice_id)
        if self.reversal_of is not None:
            _validate_identifier("reversal_of", self.reversal_of)
        _validate_date("payment_date", self.payment_date)
        _validate_decimal("gross_amount", self.gross_amount, allow_negative=True)
        if self.reversal_of is not None and self.gross_amount >= 0:
            raise ValueError("an explicit reversal must have a negative gross amount")
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class ApprovalLogRecord:
    record_id: str
    vendor_id: str
    approver_user_id: str
    approval_date: date
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("vendor_id", self.vendor_id),
            ("approver_user_id", self.approver_user_id),
        ):
            _validate_identifier(name, value)
        _validate_date("approval_date", self.approval_date)
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class PriorVendorHistoryRecord:
    record_id: str
    vendor_id: str
    activity_count: int
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_identifier("record_id", self.record_id)
        _validate_identifier("vendor_id", self.vendor_id)
        if isinstance(self.activity_count, bool) or not isinstance(self.activity_count, int):
            raise TypeError("activity_count must be an integer")
        if self.activity_count < 0:
            raise ValueError("activity_count must not be negative")
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class VendorSupportingEvidenceRecord:
    record_id: str
    vendor_id: str
    kind: SupportingEvidenceKind
    present: bool
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_identifier("record_id", self.record_id)
        _validate_identifier("vendor_id", self.vendor_id)
        if not isinstance(self.present, bool):
            raise TypeError("present must be boolean")
        _validate_evidence(self.evidence_refs)


VendorIntegrityRecord = (
    VendorLifecycleEvent
    | UserPermissionRecord
    | SupplierInvoiceRecord
    | OutgoingPaymentRecord
    | ApprovalLogRecord
    | PriorVendorHistoryRecord
    | VendorSupportingEvidenceRecord
)


@dataclass(frozen=True, slots=True)
class VendorIntegrityParameters:
    analysis_date: date
    new_vendor_window_days: int = 365
    rapid_first_invoice_days: int = 7
    rapid_first_payment_days: int = 14
    rapid_invoice_payment_days: int = 3
    review_score_threshold: Decimal = Decimal("1")
    severity_weights: tuple[tuple[VendorSignalType, Decimal], ...] = _DEFAULT_WEIGHTS

    def __post_init__(self) -> None:
        _validate_date("analysis_date", self.analysis_date)
        for name, value in (
            ("new_vendor_window_days", self.new_vendor_window_days),
            ("rapid_first_invoice_days", self.rapid_first_invoice_days),
            ("rapid_first_payment_days", self.rapid_first_payment_days),
            ("rapid_invoice_payment_days", self.rapid_invoice_payment_days),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        _validate_decimal("review_score_threshold", self.review_score_threshold)
        supplied = [signal for signal, _ in self.severity_weights]
        if len(supplied) != len(set(supplied)) or set(supplied) != set(VendorSignalType):
            raise ValueError("severity_weights must configure every signal exactly once")
        for signal, weight in self.severity_weights:
            if not isinstance(signal, VendorSignalType):
                raise TypeError("severity-weight keys must be VendorSignalType values")
            _validate_decimal(f"severity weight {signal.value}", weight)

    def weight_for(self, signal: VendorSignalType) -> Decimal:
        return dict(self.severity_weights)[signal]

    def as_items(self) -> tuple[tuple[str, str], ...]:
        values = (
            ("analysis_date", self.analysis_date.isoformat()),
            ("new_vendor_window_days", str(self.new_vendor_window_days)),
            ("rapid_first_invoice_days", str(self.rapid_first_invoice_days)),
            ("rapid_first_payment_days", str(self.rapid_first_payment_days)),
            ("rapid_invoice_payment_days", str(self.rapid_invoice_payment_days)),
            ("review_score_threshold", str(self.review_score_threshold)),
        )
        weights = tuple(
            (f"weight.{signal.value}", str(weight))
            for signal, weight in sorted(
                self.severity_weights, key=lambda item: item[0].value
            )
        )
        return (*values, *weights)


@dataclass(frozen=True, slots=True)
class VendorSignal:
    signal_type: VendorSignalType
    weight: Decimal
    description: str
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_decimal("signal weight", self.weight)
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class VendorIntegrityOutcome(ControlOutcome):
    vendor_id: str
    severity_score: Decimal
    signals: tuple[VendorSignal, ...]
    gross_cash_paid: Decimal
    invoice_net_amount: Decimal | None
    invoice_tax_amount: Decimal | None


RecordT = TypeVar("RecordT")


def _deduplicate(records: tuple[RecordT, ...]) -> tuple[RecordT, ...]:
    by_id: dict[tuple[type, str], RecordT] = {}
    for record in records:
        record_id = record.record_id
        key = (type(record), record_id)
        existing = by_id.get(key)
        if existing is not None and existing != record:
            raise ValueError(f"conflicting duplicate record_id: {record_id}")
        by_id[key] = record
    return tuple(by_id[key] for key in sorted(by_id, key=lambda item: (item[0].__name__, item[1])))


def _merge_evidence(*groups: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    result: list[EvidenceRef] = []
    seen = set()
    for group in groups:
        for evidence in group:
            if evidence.evidence_id in seen:
                continue
            seen.add(evidence.evidence_id)
            result.append(evidence)
    return tuple(result)


def _record_evidence(records: tuple[object, ...]) -> tuple[EvidenceRef, ...]:
    return _merge_evidence(*(record.evidence_refs for record in records))


def _validate_unique_invoice_ids(invoices: tuple[SupplierInvoiceRecord, ...]) -> None:
    seen: set[str] = set()
    for invoice in invoices:
        invoice_id = normalize_identifier(invoice.invoice_id)
        if invoice_id in seen:
            raise ValueError(f"duplicate invoice_id: {invoice.invoice_id}")
        seen.add(invoice_id)


def _validate_unique_payment_ids(payments: tuple[OutgoingPaymentRecord, ...]) -> None:
    seen: set[str] = set()
    for payment in payments:
        payment_id = normalize_identifier(payment.payment_id)
        if payment_id in seen:
            raise ValueError(f"duplicate payment_id: {payment.payment_id}")
        seen.add(payment_id)


def _sum_optional_amounts(
    invoices: tuple[SupplierInvoiceRecord, ...], attribute: str
) -> Decimal | None:
    values = [getattr(invoice, attribute) for invoice in invoices]
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present, start=Decimal("0"))


def _support_counter_test(
    name: str,
    records: tuple[VendorSupportingEvidenceRecord, ...],
    kind: SupportingEvidenceKind,
) -> CounterTestResult:
    relevant = tuple(record for record in records if record.kind == kind)
    evidence = _record_evidence(relevant)
    if any(record.present for record in relevant):
        status = CounterTestStatus.ACCOUNTED_FOR
        description = f"{kind.value} evidence is present"
    elif relevant:
        status = CounterTestStatus.NOT_FOUND
        description = f"a documented search found no {kind.value} evidence"
    else:
        status = CounterTestStatus.UNRESOLVED
        description = f"no {kind.value} evidence or documented search was supplied"
    return CounterTestResult(
        name=name,
        status=status,
        description=description,
        evidence_refs=evidence,
    )


def _resolve_payment_reversals(
    vendor_id: str,
    payments: tuple[OutgoingPaymentRecord, ...],
) -> tuple[
    tuple[OutgoingPaymentRecord, ...],
    tuple[OutgoingPaymentRecord, ...],
    tuple[OutgoingPaymentRecord, ...],
]:
    by_payment_id = {
        normalize_identifier(payment.payment_id): payment for payment in payments
    }
    cancelled_ids: set[str] = set()
    resolved: list[OutgoingPaymentRecord] = []
    unresolved: list[OutgoingPaymentRecord] = []
    for reversal in (payment for payment in payments if payment.gross_amount < 0):
        target = (
            by_payment_id.get(normalize_identifier(reversal.reversal_of))
            if reversal.reversal_of is not None
            else None
        )
        if (
            target is not None
            and target.gross_amount == abs(reversal.gross_amount)
            and target.payment_date <= reversal.payment_date
            and normalize_identifier(target.vendor_id) == vendor_id
            and normalize_identifier(target.payment_id) not in cancelled_ids
        ):
            cancelled_ids.add(normalize_identifier(target.payment_id))
            cancelled_ids.add(normalize_identifier(reversal.payment_id))
            resolved.extend((target, reversal))
        else:
            unresolved.append(reversal)
    active = tuple(
        payment
        for payment in payments
        if payment.gross_amount > 0
        and normalize_identifier(payment.payment_id) not in cancelled_ids
    )
    return active, tuple(resolved), tuple(unresolved)


def _reversal_counter_test(
    resolved: tuple[OutgoingPaymentRecord, ...],
    unresolved: tuple[OutgoingPaymentRecord, ...],
) -> CounterTestResult:
    return CounterTestResult(
        name="reversal",
        status=(
            CounterTestStatus.UNRESOLVED
            if unresolved
            else CounterTestStatus.ACCOUNTED_FOR
            if resolved
            else CounterTestStatus.NOT_FOUND
        ),
        description=(
            "one or more reversal records could not be matched deterministically"
            if unresolved
            else "matched payment reversals were removed from cash exposure"
            if resolved
            else "no payment reversal was found"
        ),
        evidence_refs=_merge_evidence(
            _record_evidence(resolved),
            _record_evidence(unresolved),
        ),
    )


class VendorIntegrityControl:
    control_id = "vendor_integrity_and_segregation_of_duties"
    version = "1.0.0"

    def evaluate(
        self,
        context: ControlContext[VendorIntegrityRecord, VendorIntegrityParameters],
    ) -> tuple[VendorIntegrityOutcome, ...]:
        if not isinstance(context.parameters, VendorIntegrityParameters):
            raise TypeError("VendorIntegrityControl requires VendorIntegrityParameters")
        allowed = (
            VendorLifecycleEvent,
            UserPermissionRecord,
            SupplierInvoiceRecord,
            OutgoingPaymentRecord,
            ApprovalLogRecord,
            PriorVendorHistoryRecord,
            VendorSupportingEvidenceRecord,
        )
        if not all(isinstance(record, allowed) for record in context.records):
            raise TypeError("VendorIntegrityControl received an unsupported input record")

        records = _deduplicate(context.records)
        lifecycle = _deduplicate(
            tuple(record for record in records if isinstance(record, VendorLifecycleEvent))
        )
        permissions = _deduplicate(
            tuple(record for record in records if isinstance(record, UserPermissionRecord))
        )
        invoices = _deduplicate(
            tuple(record for record in records if isinstance(record, SupplierInvoiceRecord))
        )
        payments = _deduplicate(
            tuple(record for record in records if isinstance(record, OutgoingPaymentRecord))
        )
        _validate_unique_invoice_ids(invoices)
        _validate_unique_payment_ids(payments)
        approvals = _deduplicate(
            tuple(record for record in records if isinstance(record, ApprovalLogRecord))
        )
        histories = _deduplicate(
            tuple(record for record in records if isinstance(record, PriorVendorHistoryRecord))
        )
        supporting = _deduplicate(
            tuple(
                record
                for record in records
                if isinstance(record, VendorSupportingEvidenceRecord)
            )
        )

        vendor_ids = sorted(
            {
                normalize_identifier(record.vendor_id)
                for record in (
                    *lifecycle,
                    *invoices,
                    *payments,
                    *approvals,
                    *histories,
                    *supporting,
                )
            }
        )
        outcomes: list[VendorIntegrityOutcome] = []
        for vendor_id in vendor_ids:
            outcome = self._evaluate_vendor(
                vendor_id=vendor_id,
                parameters=context.parameters,
                lifecycle=lifecycle,
                permissions=permissions,
                invoices=invoices,
                payments=payments,
                approvals=approvals,
                histories=histories,
                supporting=supporting,
            )
            if outcome is not None:
                outcomes.append(outcome)
        return tuple(outcomes)

    def _missing_creation_outcome(
        self,
        *,
        vendor_id: str,
        parameters: VendorIntegrityParameters,
        invoices: tuple[SupplierInvoiceRecord, ...],
        payments: tuple[OutgoingPaymentRecord, ...],
        approvals: tuple[ApprovalLogRecord, ...],
        histories: tuple[PriorVendorHistoryRecord, ...],
        supporting: tuple[VendorSupportingEvidenceRecord, ...],
    ) -> VendorIntegrityOutcome:
        active_payments, resolved_reversals, unresolved_reversals = (
            _resolve_payment_reversals(vendor_id, payments)
        )
        source_evidence = _merge_evidence(
            _record_evidence(invoices),
            _record_evidence(payments),
            _record_evidence(approvals),
            _record_evidence(histories),
            _record_evidence(supporting),
        )
        signal = VendorSignal(
            signal_type=VendorSignalType.MISSING_VENDOR_CREATION_EVENT,
            weight=parameters.weight_for(VendorSignalType.MISSING_VENDOR_CREATION_EVENT),
            description="vendor activity exists but no vendor-creation event was supplied",
            evidence_refs=source_evidence,
        )
        contract_test = _support_counter_test(
            "contract", supporting, SupportingEvidenceKind.CONTRACT
        )
        deliverable_test = _support_counter_test(
            "deliverables", supporting, SupportingEvidenceKind.DELIVERABLE
        )
        acceptance_test = _support_counter_test(
            "service_acceptance", supporting, SupportingEvidenceKind.SERVICE_ACCEPTANCE
        )
        goods_receipt_test = _support_counter_test(
            "goods_receipt", supporting, SupportingEvidenceKind.GOODS_RECEIPT
        )
        prior_count = sum(history.activity_count for history in histories)
        prior_test = CounterTestResult(
            name="prior_activity",
            status=(
                CounterTestStatus.ACCOUNTED_FOR
                if prior_count > 0
                else CounterTestStatus.NOT_FOUND
                if histories
                else CounterTestStatus.UNRESOLVED
            ),
            description=(
                "prior vendor activity is documented"
                if prior_count > 0
                else "documented history contains no prior activity"
                if histories
                else "no prior-history evidence was supplied"
            ),
            evidence_refs=_record_evidence(histories),
        )
        reversal_test = _reversal_counter_test(
            resolved_reversals, unresolved_reversals
        )
        approval_evidence = _record_evidence(approvals)
        independent_test = CounterTestResult(
            name="independent_approval",
            status=CounterTestStatus.UNRESOLVED,
            description="independence cannot be assessed without the vendor creator",
            evidence_refs=approval_evidence,
        )
        four_eyes_test = CounterTestResult(
            name="legitimate_four_eyes_setup",
            status=CounterTestStatus.UNRESOLVED,
            description="four-eyes setup cannot be assessed without the vendor creator",
            evidence_refs=approval_evidence,
        )
        invoice_net = _sum_optional_amounts(invoices, "net_amount")
        invoice_tax = _sum_optional_amounts(invoices, "tax_amount")
        gross_cash = sum(
            (payment.gross_amount for payment in active_payments), start=Decimal("0")
        )
        counter_tests = (
            independent_test,
            contract_test,
            deliverable_test,
            acceptance_test,
            prior_test,
            goods_receipt_test,
            reversal_test,
            four_eyes_test,
        )
        calculations = (
            CalculationStep(
                sequence=1,
                label="invoice net total",
                expression=" + ".join(
                    str(invoice.net_amount)
                    for invoice in invoices
                    if invoice.net_amount is not None
                )
                or "not available",
                result=str(invoice_net) if invoice_net is not None else "not_available",
                evidence_refs=source_evidence,
            ),
            CalculationStep(
                sequence=2,
                label="invoice tax total",
                expression=" + ".join(
                    str(invoice.tax_amount)
                    for invoice in invoices
                    if invoice.tax_amount is not None
                )
                or "not available",
                result=str(invoice_tax) if invoice_tax is not None else "not_available",
                evidence_refs=source_evidence,
            ),
            CalculationStep(
                sequence=3,
                label="reversal-adjusted gross cash paid",
                expression=" + ".join(
                    str(payment.gross_amount) for payment in active_payments
                )
                or "0",
                result=str(gross_cash),
                evidence_refs=source_evidence,
            ),
            CalculationStep(
                sequence=4,
                label="severity score",
                expression=str(signal.weight),
                result=str(signal.weight),
                evidence_refs=source_evidence,
            ),
        )
        uncertainty = (
            "vendor creation evidence is missing; creator and approval segregation "
            "cannot be assessed",
        )
        all_evidence = _merge_evidence(
            source_evidence,
            *(counter_test.evidence_refs for counter_test in counter_tests),
        )
        return VendorIntegrityOutcome(
            control_id=self.control_id,
            control_version=self.version,
            status=OutcomeStatus.REVIEW_NEEDED,
            group_key=(("vendor_id", vendor_id),),
            rule_parameters=parameters.as_items(),
            exposure_amount=gross_cash,
            supporting_evidence=(
                SupportingEvidence(
                    role=signal.signal_type.value,
                    description=signal.description,
                    evidence_refs=signal.evidence_refs,
                ),
            ),
            counter_tests=counter_tests,
            uncertainty=uncertainty,
            calculation_steps=calculations,
            evidence_refs=all_evidence,
            vendor_id=vendor_id,
            severity_score=signal.weight,
            signals=(signal,),
            gross_cash_paid=gross_cash,
            invoice_net_amount=invoice_net,
            invoice_tax_amount=invoice_tax,
        )

    def _evaluate_vendor(
        self,
        *,
        vendor_id: str,
        parameters: VendorIntegrityParameters,
        lifecycle: tuple[VendorLifecycleEvent, ...],
        permissions: tuple[UserPermissionRecord, ...],
        invoices: tuple[SupplierInvoiceRecord, ...],
        payments: tuple[OutgoingPaymentRecord, ...],
        approvals: tuple[ApprovalLogRecord, ...],
        histories: tuple[PriorVendorHistoryRecord, ...],
        supporting: tuple[VendorSupportingEvidenceRecord, ...],
    ) -> VendorIntegrityOutcome | None:
        vendor_lifecycle = tuple(
            record for record in lifecycle if normalize_identifier(record.vendor_id) == vendor_id
        )
        vendor_invoices = tuple(
            record for record in invoices if normalize_identifier(record.vendor_id) == vendor_id
        )
        vendor_payments = tuple(
            record for record in payments if normalize_identifier(record.vendor_id) == vendor_id
        )
        vendor_approvals = tuple(
            record for record in approvals if normalize_identifier(record.vendor_id) == vendor_id
        )
        vendor_histories = tuple(
            record for record in histories if normalize_identifier(record.vendor_id) == vendor_id
        )
        vendor_support = tuple(
            record for record in supporting if normalize_identifier(record.vendor_id) == vendor_id
        )
        creation_events = tuple(
            sorted(
                (record for record in vendor_lifecycle if record.kind == VendorEventKind.CREATED),
                key=lambda record: (record.event_date, record.record_id),
            )
        )
        vendor_invoices = tuple(
            sorted(vendor_invoices, key=lambda record: (record.posting_date, record.invoice_id))
        )
        vendor_payments = tuple(
            sorted(vendor_payments, key=lambda record: (record.payment_date, record.payment_id))
        )
        if not creation_events:
            return self._missing_creation_outcome(
                vendor_id=vendor_id,
                parameters=parameters,
                invoices=vendor_invoices,
                payments=vendor_payments,
                approvals=vendor_approvals,
                histories=vendor_histories,
                supporting=vendor_support,
            )
        creation = creation_events[0]
        creator = normalize_identifier(creation.user_id)
        approval_events = tuple(
            sorted(
                (record for record in vendor_lifecycle if record.kind == VendorEventKind.APPROVED),
                key=lambda record: (record.event_date, record.record_id),
            )
        )
        active_payments, resolved_reversals, unresolved_reversals = (
            _resolve_payment_reversals(vendor_id, vendor_payments)
        )

        signals: list[VendorSignal] = []

        def add_signal(
            signal_type: VendorSignalType,
            description: str,
            evidence_refs: tuple[EvidenceRef, ...],
        ) -> None:
            signals.append(
                VendorSignal(
                    signal_type=signal_type,
                    weight=parameters.weight_for(signal_type),
                    description=description,
                    evidence_refs=evidence_refs,
                )
            )

        age = (parameters.analysis_date - creation.event_date).days
        if 0 <= age <= parameters.new_vendor_window_days:
            add_signal(
                VendorSignalType.NEW_VENDOR,
                f"vendor was created {age} days before the analysis date",
                creation.evidence_refs,
            )

        creator_approvals = tuple(
            approval
            for approval in approval_events
            if normalize_identifier(approval.user_id) == creator
        )
        creator_log_approvals = tuple(
            approval
            for approval in vendor_approvals
            if normalize_identifier(approval.approver_user_id) == creator
        )
        if creator_approvals or creator_log_approvals:
            add_signal(
                VendorSignalType.CREATOR_EQUALS_APPROVER,
                "the vendor creator also approved the vendor",
                _merge_evidence(
                    creation.evidence_refs,
                    _record_evidence(creator_approvals),
                    _record_evidence(creator_log_approvals),
                ),
            )

        posting_users = {
            normalize_identifier(invoice.posting_user_id) for invoice in vendor_invoices
        }
        paying_users = {
            normalize_identifier(payment.execution_user_id) for payment in active_payments
        }
        involved_users = {creator, *posting_users, *paying_users}
        active_permissions: dict[str, dict[PermissionKind, list[UserPermissionRecord]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        for permission in permissions:
            if permission.active:
                active_permissions[normalize_identifier(permission.user_id)][
                    permission.permission
                ].append(permission)
        conflicting_users = sorted(
            user_id
            for user_id, user_permissions in active_permissions.items()
            if user_id in involved_users
            if PermissionKind.CREATE_VENDOR in user_permissions
            and PermissionKind.EXECUTE_PAYMENT in user_permissions
        )
        if conflicting_users:
            relevant_permissions = tuple(
                permission
                for permission in permissions
                if normalize_identifier(permission.user_id) in conflicting_users
                and permission.permission
                in {PermissionKind.CREATE_VENDOR, PermissionKind.EXECUTE_PAYMENT}
                and permission.active
            )
            add_signal(
                VendorSignalType.CREATE_AND_PAY_PERMISSION,
                "user(s) can both create vendors and execute payments: "
                + ", ".join(conflicting_users),
                _record_evidence(relevant_permissions),
            )

        if creator in posting_users and creator in paying_users:
            creator_invoices = tuple(
                invoice
                for invoice in vendor_invoices
                if normalize_identifier(invoice.posting_user_id) == creator
            )
            creator_payments = tuple(
                payment
                for payment in active_payments
                if normalize_identifier(payment.execution_user_id) == creator
            )
            add_signal(
                VendorSignalType.SAME_USER_CREATES_POSTS_PAYS,
                "the same user created the vendor, posted invoices, and executed payments",
                _merge_evidence(
                    creation.evidence_refs,
                    _record_evidence(creator_invoices),
                    _record_evidence(creator_payments),
                ),
            )

        if vendor_invoices:
            first_invoice = vendor_invoices[0]
            days = (first_invoice.posting_date - creation.event_date).days
            if 0 <= days <= parameters.rapid_first_invoice_days:
                add_signal(
                    VendorSignalType.RAPID_FIRST_INVOICE,
                    f"first invoice was posted {days} days after vendor creation",
                    _merge_evidence(creation.evidence_refs, first_invoice.evidence_refs),
                )
        if active_payments:
            first_payment = active_payments[0]
            days = (first_payment.payment_date - creation.event_date).days
            if 0 <= days <= parameters.rapid_first_payment_days:
                add_signal(
                    VendorSignalType.RAPID_FIRST_PAYMENT,
                    f"first active payment was executed {days} days after vendor creation",
                    _merge_evidence(creation.evidence_refs, first_payment.evidence_refs),
                )

        invoices_by_id = {
            normalize_identifier(invoice.invoice_id): invoice for invoice in vendor_invoices
        }
        quickly_paid_pairs = []
        for payment in active_payments:
            invoice = (
                invoices_by_id.get(normalize_identifier(payment.invoice_id))
                if payment.invoice_id is not None
                else None
            )
            if invoice is None:
                continue
            days = (payment.payment_date - invoice.posting_date).days
            if 0 <= days <= parameters.rapid_invoice_payment_days:
                quickly_paid_pairs.append((invoice, payment, days))
        if quickly_paid_pairs:
            add_signal(
                VendorSignalType.INVOICE_PAID_UNUSUALLY_QUICKLY,
                "invoice-to-payment timing met the configured rapid-payment window",
                _merge_evidence(
                    *(
                        _merge_evidence(invoice.evidence_refs, payment.evidence_refs)
                        for invoice, payment, _ in quickly_paid_pairs
                    )
                ),
            )

        independent_approval_events = tuple(
            approval
            for approval in approval_events
            if normalize_identifier(approval.user_id) != creator
        )
        independent_log_records = tuple(
            approval
            for approval in vendor_approvals
            if normalize_identifier(approval.approver_user_id) != creator
        )
        independent_evidence = _merge_evidence(
            _record_evidence(independent_approval_events),
            _record_evidence(independent_log_records),
        )
        if not independent_evidence:
            add_signal(
                VendorSignalType.MISSING_INDEPENDENT_APPROVAL,
                "no independent vendor approval was supplied",
                _merge_evidence(creation.evidence_refs, _record_evidence(approval_events)),
            )
        if not vendor_approvals:
            add_signal(
                VendorSignalType.MISSING_APPROVAL_LOG,
                "no approval-log record was supplied for the vendor",
                _merge_evidence(creation.evidence_refs, _record_evidence(approval_events)),
            )

        prior_count = sum(history.activity_count for history in vendor_histories)
        if vendor_histories and prior_count == 0:
            add_signal(
                VendorSignalType.NO_PRIOR_VENDOR_HISTORY,
                "the supplied prior-history records contain no prior activity",
                _record_evidence(vendor_histories),
            )

        contract_test = _support_counter_test(
            "contract", vendor_support, SupportingEvidenceKind.CONTRACT
        )
        deliverable_test = _support_counter_test(
            "deliverables", vendor_support, SupportingEvidenceKind.DELIVERABLE
        )
        acceptance_test = _support_counter_test(
            "service_acceptance", vendor_support, SupportingEvidenceKind.SERVICE_ACCEPTANCE
        )
        goods_receipt_test = _support_counter_test(
            "goods_receipt", vendor_support, SupportingEvidenceKind.GOODS_RECEIPT
        )
        four_eyes_supplied = _support_counter_test(
            "legitimate_four_eyes_setup",
            vendor_support,
            SupportingEvidenceKind.LEGITIMATE_FOUR_EYES,
        )
        has_independent_setup = bool(independent_evidence and vendor_approvals)
        four_eyes_test = (
            CounterTestResult(
                name="legitimate_four_eyes_setup",
                status=CounterTestStatus.ACCOUNTED_FOR,
                description="creation and documented approval were performed by different users",
                evidence_refs=_merge_evidence(creation.evidence_refs, independent_evidence),
            )
            if has_independent_setup
            else four_eyes_supplied
        )
        independent_test = CounterTestResult(
            name="independent_approval",
            status=(
                CounterTestStatus.ACCOUNTED_FOR
                if independent_evidence
                else CounterTestStatus.NOT_FOUND
                if approval_events or vendor_approvals
                else CounterTestStatus.UNRESOLVED
            ),
            description=(
                "independent approval evidence is present"
                if independent_evidence
                else "approval evidence is present but not independent"
                if approval_events or vendor_approvals
                else "no approval evidence was supplied"
            ),
            evidence_refs=_merge_evidence(
                independent_evidence,
                _record_evidence(approval_events),
                _record_evidence(vendor_approvals),
            ),
        )
        prior_test = CounterTestResult(
            name="prior_activity",
            status=(
                CounterTestStatus.ACCOUNTED_FOR
                if prior_count > 0
                else CounterTestStatus.NOT_FOUND
                if vendor_histories
                else CounterTestStatus.UNRESOLVED
            ),
            description=(
                "prior vendor activity is documented"
                if prior_count > 0
                else "documented history contains no prior activity"
                if vendor_histories
                else "no prior-history evidence was supplied"
            ),
            evidence_refs=_record_evidence(vendor_histories),
        )
        reversal_test = _reversal_counter_test(
            resolved_reversals, unresolved_reversals
        )

        purchase_kinds = {invoice.purchase_kind for invoice in vendor_invoices}
        service_required = PurchaseKind.SERVICE in purchase_kinds
        goods_required = PurchaseKind.GOODS in purchase_kinds
        unknown_required = PurchaseKind.UNKNOWN in purchase_kinds
        service_supported = any(
            test.status == CounterTestStatus.ACCOUNTED_FOR
            for test in (deliverable_test, acceptance_test)
        )
        goods_supported = goods_receipt_test.status == CounterTestStatus.ACCOUNTED_FOR
        unknown_supported = service_supported or goods_supported
        missing_performance_evidence = (
            (service_required and not service_supported)
            or (goods_required and not goods_supported)
            or (unknown_required and not unknown_supported)
        )
        if vendor_invoices and missing_performance_evidence:
            relevant_negative_evidence = _merge_evidence(
                deliverable_test.evidence_refs,
                acceptance_test.evidence_refs,
                goods_receipt_test.evidence_refs,
            )
            add_signal(
                VendorSignalType.MISSING_SERVICE_OR_DELIVERY_EVIDENCE,
                "required service-performance or goods-delivery evidence was not supplied",
                relevant_negative_evidence or _record_evidence(vendor_invoices),
            )

        if not signals:
            return None
        signals_tuple = tuple(
            sorted(signals, key=lambda signal: (signal.signal_type.value, signal.description))
        )
        severity_score = sum(
            (signal.weight for signal in signals_tuple), start=Decimal("0")
        )
        invoice_net = _sum_optional_amounts(vendor_invoices, "net_amount")
        invoice_tax = _sum_optional_amounts(vendor_invoices, "tax_amount")
        gross_cash = sum(
            (payment.gross_amount for payment in active_payments), start=Decimal("0")
        )

        material_uncertainty: list[str] = []
        if reversal_test.status == CounterTestStatus.UNRESOLVED:
            material_uncertainty.append(reversal_test.description)
        if prior_test.status == CounterTestStatus.UNRESOLVED:
            material_uncertainty.append(prior_test.description)
        if independent_test.status == CounterTestStatus.UNRESOLVED:
            material_uncertainty.append(independent_test.description)
        if four_eyes_test.status == CounterTestStatus.UNRESOLVED:
            material_uncertainty.append(four_eyes_test.description)
        if service_required:
            if contract_test.status == CounterTestStatus.UNRESOLVED:
                material_uncertainty.append(contract_test.description)
            if not service_supported and all(
                test.status == CounterTestStatus.UNRESOLVED
                for test in (deliverable_test, acceptance_test)
            ):
                material_uncertainty.append(
                    "no service deliverable or acceptance evidence/search was supplied"
                )
        if goods_required and goods_receipt_test.status == CounterTestStatus.UNRESOLVED:
            material_uncertainty.append(goods_receipt_test.description)
        if unknown_required and not unknown_supported:
            material_uncertainty.append(
                "purchase type is unknown and no performance or delivery evidence was supplied"
            )

        legitimate_setup = (
            independent_test.status == CounterTestStatus.ACCOUNTED_FOR
            and four_eyes_test.status == CounterTestStatus.ACCOUNTED_FOR
            and (not service_required or service_supported)
            and (not goods_required or goods_supported)
            and (not unknown_required or unknown_supported)
        )
        core_sod_conflicts = {
            VendorSignalType.CREATOR_EQUALS_APPROVER,
            VendorSignalType.CREATE_AND_PAY_PERMISSION,
            VendorSignalType.SAME_USER_CREATES_POSTS_PAYS,
        } & {signal.signal_type for signal in signals_tuple}
        if legitimate_setup and core_sod_conflicts:
            material_uncertainty.append(
                "legitimate approval or delivery evidence mitigates but does not resolve "
                "direct segregation-of-duties conflicts"
            )
        missing_performance_evidence_only = {
            signal.signal_type for signal in signals_tuple
        } == {VendorSignalType.MISSING_SERVICE_OR_DELIVERY_EVIDENCE}
        if missing_performance_evidence_only:
            material_uncertainty.append(
                "missing service or delivery evidence alone is not proof of misconduct"
            )
        if legitimate_setup and not core_sod_conflicts:
            status = OutcomeStatus.DISMISSED
        elif material_uncertainty:
            status = OutcomeStatus.REVIEW_NEEDED
        elif severity_score < parameters.review_score_threshold:
            status = OutcomeStatus.DISMISSED
        else:
            status = OutcomeStatus.CONFIRMED_CANDIDATE

        signal_evidence = _merge_evidence(
            *(signal.evidence_refs for signal in signals_tuple)
        )
        invoice_evidence = _record_evidence(vendor_invoices)
        payment_evidence = _record_evidence(active_payments)
        calculation_evidence = signal_evidence
        calculations = (
            CalculationStep(
                sequence=1,
                label="invoice net total",
                expression=" + ".join(
                    str(invoice.net_amount)
                    for invoice in vendor_invoices
                    if invoice.net_amount is not None
                )
                or "not available",
                result=str(invoice_net) if invoice_net is not None else "not_available",
                evidence_refs=invoice_evidence or calculation_evidence,
            ),
            CalculationStep(
                sequence=2,
                label="invoice tax total",
                expression=" + ".join(
                    str(invoice.tax_amount)
                    for invoice in vendor_invoices
                    if invoice.tax_amount is not None
                )
                or "not available",
                result=str(invoice_tax) if invoice_tax is not None else "not_available",
                evidence_refs=invoice_evidence or calculation_evidence,
            ),
            CalculationStep(
                sequence=3,
                label="reversal-adjusted gross cash paid",
                expression=" + ".join(str(payment.gross_amount) for payment in active_payments)
                or "0",
                result=str(gross_cash),
                evidence_refs=payment_evidence or calculation_evidence,
            ),
            CalculationStep(
                sequence=4,
                label="severity score",
                expression=" + ".join(str(signal.weight) for signal in signals_tuple),
                result=str(severity_score),
                evidence_refs=signal_evidence,
            ),
        )
        counter_tests = (
            independent_test,
            contract_test,
            deliverable_test,
            acceptance_test,
            prior_test,
            goods_receipt_test,
            reversal_test,
            four_eyes_test,
        )
        supporting_outputs = tuple(
            SupportingEvidence(
                role=signal.signal_type.value,
                description=signal.description,
                evidence_refs=signal.evidence_refs,
            )
            for signal in signals_tuple
        )
        all_evidence = _merge_evidence(
            signal_evidence,
            *(counter_test.evidence_refs for counter_test in counter_tests),
        )
        return VendorIntegrityOutcome(
            control_id=self.control_id,
            control_version=self.version,
            status=status,
            group_key=(("vendor_id", vendor_id),),
            rule_parameters=parameters.as_items(),
            exposure_amount=gross_cash,
            supporting_evidence=supporting_outputs,
            counter_tests=counter_tests,
            uncertainty=tuple(sorted(set(material_uncertainty))),
            calculation_steps=calculations,
            evidence_refs=all_evidence,
            vendor_id=vendor_id,
            severity_score=severity_score,
            signals=signals_tuple,
            gross_cash_paid=gross_cash,
            invoice_net_amount=invoice_net,
            invoice_tax_amount=invoice_tax,
        )
