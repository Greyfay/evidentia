"""The methodology's ordered control library."""

from __future__ import annotations

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


class ControlEngine:
    """Stable production interface over the active deterministic methodology."""

    def __init__(self, controls: list[DossierControl] | None = None) -> None:
        self._controls = controls or default_controls()

    def run(self, context: ControlContext) -> tuple[Finding, ...]:
        return tuple(finding for control in self._controls for finding in control.run(context))
