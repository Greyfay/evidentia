"""Generic deterministic control contracts and local outcome types."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from audit_compiler.models import EvidenceRef

RecordT = TypeVar("RecordT")
ParametersT = TypeVar("ParametersT", covariant=True)


class OutcomeStatus(StrEnum):
    CONFIRMED_CANDIDATE = "confirmed_candidate"
    REVIEW_NEEDED = "review_needed"
    DISMISSED = "dismissed"


class CounterTestStatus(StrEnum):
    NOT_FOUND = "not_found"
    ACCOUNTED_FOR = "accounted_for"
    UNRESOLVED = "unresolved"


@runtime_checkable
class RuleParameters(Protocol):
    """Serializable configuration carried into every replayable outcome."""

    def as_items(self) -> tuple[tuple[str, str], ...]: ...


@dataclass(frozen=True, slots=True)
class ControlContext(Generic[RecordT, ParametersT]):
    records: tuple[RecordT, ...]
    parameters: ParametersT


@dataclass(frozen=True, slots=True)
class SupportingEvidence:
    role: str
    description: str
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.role or not self.description:
            raise ValueError("supporting evidence requires a role and description")
        if not self.evidence_refs:
            raise ValueError("supporting evidence requires at least one EvidenceRef")


@dataclass(frozen=True, slots=True)
class CounterTestResult:
    name: str
    status: CounterTestStatus
    description: str
    evidence_refs: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class CalculationStep:
    sequence: int
    label: str
    expression: str
    result: str
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("calculation sequence must be one-based")
        if not self.label or not self.expression:
            raise ValueError("calculation step requires a label and expression")


@dataclass(frozen=True, slots=True)
class ControlOutcome:
    control_id: str
    control_version: str
    status: OutcomeStatus
    group_key: tuple[tuple[str, str], ...]
    rule_parameters: tuple[tuple[str, str], ...]
    exposure_amount: Decimal
    supporting_evidence: tuple[SupportingEvidence, ...]
    counter_tests: tuple[CounterTestResult, ...]
    uncertainty: tuple[str, ...]
    calculation_steps: tuple[CalculationStep, ...]
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.exposure_amount, Decimal):
            raise TypeError("control exposure must be Decimal")
        if not self.supporting_evidence or not self.calculation_steps:
            raise ValueError("control outcomes require evidence and calculation steps")
        if not self.evidence_refs:
            raise ValueError("control outcomes require at least one EvidenceRef")
        if self.status == OutcomeStatus.REVIEW_NEEDED and not self.uncertainty:
            raise ValueError("review-needed outcomes require explicit uncertainty")


@runtime_checkable
class Control(Protocol[RecordT, ParametersT]):
    control_id: str
    version: str

    def evaluate(
        self, context: ControlContext[RecordT, ParametersT]
    ) -> tuple[ControlOutcome, ...]: ...
