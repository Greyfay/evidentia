"""Shared contracts for record-oriented and dossier-oriented controls.

The package contains two compatible deterministic execution styles:

* record controls evaluate normalized records and return local ``ControlOutcome`` values;
* dossier controls inspect a ``LoadedDossier`` and return admission-gated ``Finding`` values.

Both styles share provenance-first evidence models and Decimal-only calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

from audit_compiler.ir.dossier import LoadedDossier
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
    """Execution context for either normalized records or a loaded dossier."""

    records: tuple[RecordT, ...] = ()
    parameters: ParametersT | None = None
    dossier: LoadedDossier | None = None
    params: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        record_mode = self.parameters is not None
        dossier_mode = self.dossier is not None
        if record_mode == dossier_mode:
            raise ValueError(
                "ControlContext requires either records/parameters or dossier/params"
            )
        if dossier_mode and self.records:
            raise ValueError("dossier control context cannot also contain normalized records")


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
    """A deterministic control over normalized records."""

    control_id: str
    version: str

    def evaluate(
        self, context: ControlContext[RecordT, ParametersT]
    ) -> tuple[ControlOutcome, ...]: ...


Outcome = Literal["absent", "present", "not_applicable"]


@dataclass(frozen=True)
class EvidenceStep:
    step: str
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class CalcInput:
    label: str
    value: Decimal
    evidence: EvidenceRef


@dataclass(frozen=True)
class Calculation:
    expression: str
    inputs: tuple[CalcInput, ...]
    result: Decimal
    sql: str


@dataclass(frozen=True)
class CounterTest:
    """An innocent explanation that a dossier control actively searched for."""

    name: str
    outcome: Outcome
    detail: str
    required: bool = True
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class Finding:
    control_id: str
    control_version: str
    title: str
    assertion: str
    severity: Literal["high", "medium", "low", "control"]
    narrative: str
    exposure: Decimal
    exposure_label: Literal["net", "gross", "control"]
    evidence_chain: tuple[EvidenceStep, ...]
    calculation: Calculation
    counter_tests: tuple[CounterTest, ...]
    recommended_action: str
    uncertainty: str | None = None
    subject: str = ""

    @property
    def cleared_by(self) -> CounterTest | None:
        return next(
            (counter for counter in self.counter_tests if counter.outcome == "present"),
            None,
        )


@runtime_checkable
class DossierControl(Protocol):
    """A deterministic control over a fully loaded dossier."""

    id: str
    version: str

    def run(self, ctx: ControlContext[object, object]) -> list[Finding]: ...
