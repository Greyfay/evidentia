"""LEGACY STRONG CONTROL: available behind the controls API, not production-integrated."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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


@dataclass(frozen=True, slots=True)
class SplitPaymentParameters:
    threshold: Decimal
    minimum_payment_count: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.threshold, Decimal):
            raise TypeError("split-payment threshold must be Decimal")
        if not self.threshold.is_finite():
            raise ValueError("split-payment threshold must be finite")
        if self.threshold <= 0:
            raise ValueError("split-payment threshold must be positive")
        if isinstance(self.minimum_payment_count, bool) or not isinstance(
            self.minimum_payment_count, int
        ):
            raise TypeError("minimum_payment_count must be an integer")
        if self.minimum_payment_count < 2:
            raise ValueError("minimum_payment_count must be at least two")

    def as_items(self) -> tuple[tuple[str, str], ...]:
        return (
            ("threshold", str(self.threshold)),
            ("minimum_payment_count", str(self.minimum_payment_count)),
        )


@dataclass(frozen=True, slots=True)
class PaymentRecord:
    payment_id: str
    payee: str
    payment_date: date
    payment_reference: str
    amount: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    reversal_of: str | None = None
    obligation_id: str | None = None
    installment_plan_id: str | None = None
    second_approval_evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.payment_id, self.payee, self.payment_reference)
        ):
            raise ValueError("payment identifiers, payee, and reference are required")
        if type(self.payment_date) is not date:
            raise TypeError("payment_date must be a date")
        if not isinstance(self.amount, Decimal):
            raise TypeError("payment amount must be Decimal")
        if not self.amount.is_finite():
            raise ValueError("payment amount must be finite")
        if not self.evidence_refs:
            raise ValueError("payment requires at least one EvidenceRef")
        if not all(isinstance(evidence, EvidenceRef) for evidence in self.evidence_refs):
            raise TypeError("payment evidence must contain only EvidenceRefs")
        if not all(
            isinstance(evidence, EvidenceRef)
            for evidence in self.second_approval_evidence_refs
        ):
            raise TypeError("second-approval evidence must contain only EvidenceRefs")
        if self.reversal_of is not None and self.amount >= 0:
            raise ValueError("an explicit reversal must have a negative amount")
        for name, value in (
            ("reversal_of", self.reversal_of),
            ("obligation_id", self.obligation_id),
            ("installment_plan_id", self.installment_plan_id),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when supplied")


@dataclass(frozen=True, slots=True)
class _NormalizedPayment:
    record: PaymentRecord
    payee: str
    reference: str


@dataclass(frozen=True, slots=True)
class _ReversalResolution:
    reversal: _NormalizedPayment
    target: _NormalizedPayment | None
    reason: str


def _evidence(records: tuple[_NormalizedPayment, ...]) -> tuple[EvidenceRef, ...]:
    result: list[EvidenceRef] = []
    seen = set()
    for payment in records:
        for evidence in payment.record.evidence_refs:
            if evidence.evidence_id in seen:
                continue
            seen.add(evidence.evidence_id)
            result.append(evidence)
    return tuple(result)


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


def _sum(records: tuple[_NormalizedPayment, ...]) -> Decimal:
    return sum((payment.record.amount for payment in records), start=Decimal("0"))


def _sum_expression(records: tuple[_NormalizedPayment, ...], result: Decimal) -> str:
    operands = " + ".join(str(payment.record.amount) for payment in records) or "0"
    return f"{operands} = {result}"


def _qualifies(
    records: tuple[_NormalizedPayment, ...], parameters: SplitPaymentParameters
) -> bool:
    return (
        len(records) >= parameters.minimum_payment_count
        and all(Decimal("0") < payment.record.amount < parameters.threshold for payment in records)
        and _sum(records) >= parameters.threshold
    )


class SplitPaymentControl:
    control_id = "split_payment_below_threshold"
    version = "1.0.0"

    def evaluate(
        self,
        context: ControlContext[PaymentRecord, SplitPaymentParameters],
    ) -> tuple[ControlOutcome, ...]:
        parameters = context.parameters
        if not isinstance(parameters, SplitPaymentParameters):
            raise TypeError("SplitPaymentControl requires SplitPaymentParameters")
        if not all(isinstance(record, PaymentRecord) for record in context.records):
            raise TypeError("SplitPaymentControl requires PaymentRecord inputs")

        normalized = tuple(
            _NormalizedPayment(
                record=record,
                payee=normalize_identifier(record.payee),
                reference=normalize_identifier(record.payment_reference),
            )
            for record in context.records
        )
        by_id: dict[str, _NormalizedPayment] = {}
        for payment in normalized:
            if payment.record.payment_id in by_id:
                raise ValueError(f"duplicate payment_id: {payment.record.payment_id}")
            by_id[payment.record.payment_id] = payment

        cancelled_ids: set[str] = set()
        resolutions: list[_ReversalResolution] = []
        reversals = tuple(
            sorted(
                (payment for payment in normalized if payment.record.amount < 0),
                key=lambda payment: (
                    payment.record.payment_date,
                    payment.record.payment_id,
                ),
            )
        )
        positives = tuple(payment for payment in normalized if payment.record.amount > 0)

        for reversal in reversals:
            target: _NormalizedPayment | None = None
            reason: str
            if reversal.record.reversal_of is not None:
                candidate = by_id.get(reversal.record.reversal_of)
                compatible = (
                    candidate is not None
                    and candidate.record.amount > 0
                    and candidate.record.payment_id not in cancelled_ids
                    and candidate.record.amount == abs(reversal.record.amount)
                    and candidate.payee == reversal.payee
                )
                if compatible and candidate.record.payment_date <= reversal.record.payment_date:
                    target = candidate
                    reason = "explicit reversal matched its referenced payment"
                elif compatible:
                    reason = "explicit reversal predates its referenced payment"
                else:
                    reason = (
                        "explicit reversal target is missing, incompatible, "
                        "or already reversed"
                    )
            else:
                candidates = tuple(
                    payment
                    for payment in positives
                    if payment.record.payment_id not in cancelled_ids
                    and payment.payee == reversal.payee
                    and payment.reference == reversal.reference
                    and payment.record.amount == abs(reversal.record.amount)
                    and payment.record.payment_date <= reversal.record.payment_date
                )
                if len(candidates) == 1:
                    target = candidates[0]
                    reason = "unique equal-and-opposite payment matched by payee and reference"
                elif not candidates:
                    reason = "no equal-and-opposite payment matched the reversal"
                else:
                    reason = "multiple payments could match the reversal"
            if target is not None:
                cancelled_ids.add(target.record.payment_id)
                cancelled_ids.add(reversal.record.payment_id)
            resolutions.append(
                _ReversalResolution(reversal=reversal, target=target, reason=reason)
            )

        raw_groups: dict[tuple[str, date, str], list[_NormalizedPayment]] = defaultdict(list)
        for payment in positives:
            raw_groups[(payment.payee, payment.record.payment_date, payment.reference)].append(
                payment
            )

        outcomes: list[ControlOutcome] = []
        for group_key in sorted(raw_groups, key=lambda key: (key[0], key[1].isoformat(), key[2])):
            raw_group = tuple(
                sorted(raw_groups[group_key], key=lambda payment: payment.record.payment_id)
            )
            if not _qualifies(raw_group, parameters):
                continue
            active_group = tuple(
                payment
                for payment in raw_group
                if payment.record.payment_id not in cancelled_ids
            )
            group_ids = {payment.record.payment_id for payment in raw_group}
            resolved = tuple(
                resolution
                for resolution in resolutions
                if resolution.target is not None
                and resolution.target.record.payment_id in group_ids
            )
            unresolved = tuple(
                resolution
                for resolution in resolutions
                if resolution.target is None
                and resolution.reversal.payee == group_key[0]
                and (
                    resolution.reversal.record.reversal_of in group_ids
                    or (
                        resolution.reversal.reference == group_key[2]
                        and resolution.reversal.record.payment_date >= group_key[1]
                    )
                )
            )

            if unresolved:
                status = OutcomeStatus.REVIEW_NEEDED
            elif _qualifies(active_group, parameters):
                status = OutcomeStatus.CONFIRMED_CANDIDATE
            else:
                status = OutcomeStatus.DISMISSED

            reversal_records = tuple(
                resolution.reversal for resolution in (*resolved, *unresolved)
            )
            all_records = (*raw_group, *reversal_records)
            raw_evidence = _evidence(raw_group)
            active_evidence = _evidence(active_group) if active_group else raw_evidence
            approval_evidence = _merge_evidence(
                *(payment.record.second_approval_evidence_refs for payment in raw_group)
            )
            all_evidence = _merge_evidence(_evidence(all_records), approval_evidence)
            raw_total = _sum(raw_group)
            active_total = _sum(active_group)
            uncertainty: list[str] = []

            if unresolved:
                counter_test = CounterTestResult(
                    name="reversal_search",
                    status=CounterTestStatus.UNRESOLVED,
                    description="; ".join(resolution.reason for resolution in unresolved),
                    evidence_refs=_evidence(reversal_records),
                )
            elif resolved:
                counter_test = CounterTestResult(
                    name="reversal_search",
                    status=CounterTestStatus.ACCOUNTED_FOR,
                    description="; ".join(resolution.reason for resolution in resolved),
                    evidence_refs=_evidence(reversal_records),
                )
            else:
                counter_test = CounterTestResult(
                    name="reversal_search",
                    status=CounterTestStatus.NOT_FOUND,
                    description="no matching explicit or equal-and-opposite reversal was found",
                )

            if unresolved:
                uncertainty.extend(resolution.reason for resolution in unresolved)

            obligation_ids = tuple(
                normalize_identifier(payment.record.obligation_id)
                if payment.record.obligation_id is not None
                else None
                for payment in raw_group
            )
            if all(obligation_ids) and len(set(obligation_ids)) == len(obligation_ids):
                obligation_test = CounterTestResult(
                    name="distinct_contractual_obligations",
                    status=CounterTestStatus.ACCOUNTED_FOR,
                    description="every payment maps to a distinct contractual obligation",
                    evidence_refs=raw_evidence,
                )
            elif any(obligation_ids):
                message = "contractual-obligation identifiers are incomplete or duplicated"
                uncertainty.append(message)
                obligation_test = CounterTestResult(
                    name="distinct_contractual_obligations",
                    status=CounterTestStatus.UNRESOLVED,
                    description=message,
                    evidence_refs=raw_evidence,
                )
            else:
                obligation_test = CounterTestResult(
                    name="distinct_contractual_obligations",
                    status=CounterTestStatus.NOT_FOUND,
                    description="no distinct contractual-obligation evidence was supplied",
                )

            plan_ids = tuple(
                normalize_identifier(payment.record.installment_plan_id)
                if payment.record.installment_plan_id is not None
                else None
                for payment in raw_group
            )
            if all(plan_ids) and len(set(plan_ids)) == 1:
                installment_test = CounterTestResult(
                    name="valid_installment_plan",
                    status=CounterTestStatus.ACCOUNTED_FOR,
                    description="all payments belong to the same documented installment plan",
                    evidence_refs=raw_evidence,
                )
            elif any(plan_ids):
                message = "installment-plan identifiers are incomplete or inconsistent"
                uncertainty.append(message)
                installment_test = CounterTestResult(
                    name="valid_installment_plan",
                    status=CounterTestStatus.UNRESOLVED,
                    description=message,
                    evidence_refs=raw_evidence,
                )
            else:
                installment_test = CounterTestResult(
                    name="valid_installment_plan",
                    status=CounterTestStatus.NOT_FOUND,
                    description="no valid installment-plan evidence was supplied",
                )

            approval_test = CounterTestResult(
                name="second_approval",
                status=(
                    CounterTestStatus.ACCOUNTED_FOR
                    if approval_evidence
                    else CounterTestStatus.NOT_FOUND
                ),
                description=(
                    "documented second approval was supplied"
                    if approval_evidence
                    else "no documented second approval was supplied"
                ),
                evidence_refs=approval_evidence,
            )

            innocent_explanation_supported = any(
                test.status == CounterTestStatus.ACCOUNTED_FOR
                for test in (obligation_test, installment_test, approval_test)
            )
            if uncertainty:
                status = OutcomeStatus.REVIEW_NEEDED
            elif innocent_explanation_supported:
                status = OutcomeStatus.DISMISSED

            maximum = max(payment.record.amount for payment in raw_group)
            calculations = (
                CalculationStep(
                    sequence=1,
                    label="candidate aggregate",
                    expression=_sum_expression(raw_group, raw_total),
                    result=str(raw_total),
                    evidence_refs=raw_evidence,
                ),
                CalculationStep(
                    sequence=2,
                    label="individual threshold test",
                    expression=f"max({maximum}) < {parameters.threshold}",
                    result=str(maximum < parameters.threshold).lower(),
                    evidence_refs=raw_evidence,
                ),
                CalculationStep(
                    sequence=3,
                    label="reversal-adjusted aggregate",
                    expression=_sum_expression(active_group, active_total),
                    result=str(active_total),
                    evidence_refs=active_evidence,
                ),
                CalculationStep(
                    sequence=4,
                    label="aggregate threshold test",
                    expression=f"{active_total} >= {parameters.threshold}",
                    result=str(active_total >= parameters.threshold).lower(),
                    evidence_refs=active_evidence,
                ),
            )
            supporting = (
                SupportingEvidence(
                    role="grouping",
                    description="payments share normalized payee, date, and reference",
                    evidence_refs=raw_evidence,
                ),
                SupportingEvidence(
                    role="threshold",
                    description="candidate payments are individually below the threshold",
                    evidence_refs=raw_evidence,
                ),
                SupportingEvidence(
                    role="aggregate",
                    description="candidate aggregate meets or exceeds the threshold",
                    evidence_refs=raw_evidence,
                ),
            )
            outcomes.append(
                ControlOutcome(
                    control_id=self.control_id,
                    control_version=self.version,
                    status=status,
                    group_key=(
                        ("payee", group_key[0]),
                        ("date", group_key[1].isoformat()),
                        ("payment_reference", group_key[2]),
                    ),
                    rule_parameters=parameters.as_items(),
                    exposure_amount=active_total,
                    supporting_evidence=supporting,
                    counter_tests=(
                        counter_test,
                        obligation_test,
                        installment_test,
                        approval_test,
                    ),
                    uncertainty=tuple(uncertainty),
                    calculation_steps=calculations,
                    evidence_refs=all_evidence,
                )
            )
        return tuple(outcomes)
