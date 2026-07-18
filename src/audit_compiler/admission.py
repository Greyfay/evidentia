"""The admission gate: turn a control finding into a published verdict.

A model may recommend; it cannot bypass this gate. The gate is pure, deterministic, and
based only on evidence, control support, and the outcomes of required counter-tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from audit_compiler.controls.base import Finding

Verdict = Literal["CONFIRMED", "HUMAN_REVIEW", "DISMISSED", "REJECTED"]


@dataclass(frozen=True)
class Admission:
    verdict: Verdict
    reason: str


def admit(finding: Finding) -> Admission:
    """Apply the publication gate to a single finding."""

    if not finding.evidence_chain:
        return Admission("REJECTED", "No evidence chain.")
    if finding.exposure and finding.exposure != 0 and not finding.calculation.inputs:
        return Admission("REJECTED", "Reported exposure has no cited calculation inputs.")
    if not finding.control_id:
        return Admission("REJECTED", "No deterministic control supports the finding.")

    required = [c for c in finding.counter_tests if c.required]
    cleared = next((c for c in required if c.outcome == "present"), None)
    if cleared is not None:
        return Admission("DISMISSED", f"Innocent explanation supported: {cleared.name}.")
    incomplete = next((c for c in required if c.outcome == "not_applicable"), None)
    if incomplete is not None:
        return Admission("HUMAN_REVIEW", f"Required counter-test not run: {incomplete.name}.")
    return Admission("CONFIRMED", "Evidence and controls support the finding; refuters searched.")
