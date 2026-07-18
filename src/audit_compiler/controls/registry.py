"""The methodology's ordered control library."""

from __future__ import annotations

from dataclasses import dataclass

from audit_compiler.controls.anomaly_discovery import AnomalyDiscoveryControl
from audit_compiler.controls.base import ControlContext, DossierControl, Finding
from audit_compiler.controls.capitalisation import CapitalisationControl
from audit_compiler.controls.cutoff import CutoffControl
from audit_compiler.controls.split_payment import SplitPaymentControl
from audit_compiler.controls.vendor_sod import VendorSoDControl

METHODOLOGY_VERSION = "generic-controls@0.1.0"


def default_controls() -> list[DossierControl]:
    """Return the methodology controls in order.

    The four targeted controls run first, then the generic anomaly-discovery scanner. The
    latter only ever emits admission ``HUMAN_REVIEW`` leads (each finding carries a required,
    unrunnable counter-test), so it never changes the confirmed/dismissed verdicts of the
    four targeted controls -- it only surfaces additional leads for the auditor.
    """

    return [
        VendorSoDControl(),
        SplitPaymentControl(),
        CapitalisationControl(),
        CutoffControl(),
        AnomalyDiscoveryControl(),
    ]


def select_controls(
    control_ids: tuple[str, ...] | None,
) -> tuple[list[DossierControl], tuple[str, ...]]:
    """Resolve an explicit allowlist against the complete deterministic registry."""

    registry = default_controls()
    if control_ids is None:
        return registry, ()
    requested = set(control_ids)
    known = {control.id for control in registry}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"unknown control ID(s): {', '.join(unknown)}")
    selected = [control for control in registry if control.id in requested]
    skipped = tuple(control.id for control in registry if control.id not in requested)
    return selected, skipped


@dataclass(frozen=True, slots=True)
class ControlRun:
    findings: tuple[Finding, ...]
    selected: tuple[str, ...]
    executed: tuple[str, ...]
    failed: tuple[str, ...]
    skipped: tuple[str, ...]


class ControlEngine:
    """Stable production interface over the active deterministic methodology."""

    def __init__(self, control_ids: tuple[str, ...] | None = None) -> None:
        self._controls, self._skipped = select_controls(control_ids)

    def run(self, context: ControlContext) -> ControlRun:
        findings: list[Finding] = []
        executed: list[str] = []
        failed: list[str] = []
        for control in self._controls:
            executed.append(control.id)
            try:
                findings.extend(control.run(context))
            except Exception:  # control isolation is reported in compilation metadata
                failed.append(control.id)
        return ControlRun(
            findings=tuple(findings),
            selected=tuple(control.id for control in self._controls),
            executed=tuple(executed),
            failed=tuple(failed),
            skipped=self._skipped,
        )
