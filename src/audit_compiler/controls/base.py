"""Control framework: findings, counter-tests, and the deterministic contract.

A control produces :class:`Finding` objects. It performs NO verdict logic itself beyond
running its declared counter-tests; the admission gate turns findings into published
verdicts. Every number a finding reports must be carried by an :class:`EvidenceRef`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol

from audit_compiler.ir.dossier import LoadedDossier
from audit_compiler.models import EvidenceRef

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
    """A refuter: an innocent explanation the control actively searched for.

    ``outcome == "present"`` means the innocent explanation was FOUND (evidence clears the
    case). ``"absent"`` means it was searched for and not found. ``"not_applicable"`` means
    the test could not be run and the case must not be auto-confirmed on it.
    """

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
    subject: str = ""  # opaque grouping key (e.g. a vendor account); never shown as truth

    @property
    def cleared_by(self) -> CounterTest | None:
        return next((c for c in self.counter_tests if c.outcome == "present"), None)


@dataclass(frozen=True)
class ControlContext:
    dossier: LoadedDossier
    params: dict[str, object] = field(default_factory=dict)


class Control(Protocol):
    id: str
    version: str

    def run(self, ctx: ControlContext) -> list[Finding]: ...
