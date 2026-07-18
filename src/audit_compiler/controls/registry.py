"""The methodology's ordered control library."""

from __future__ import annotations

from audit_compiler.controls.base import ControlContext, DossierControl, Finding
from audit_compiler.controls.capitalisation import CapitalisationControl
from audit_compiler.controls.cutoff import CutoffControl
from audit_compiler.controls.split_payment import SplitPaymentControl
from audit_compiler.controls.vendor_sod import VendorSoDControl

METHODOLOGY_VERSION = "generic-controls@0.1.0"


def default_controls() -> list[DossierControl]:
    """Return the four generic controls in methodology order."""

    return [
        VendorSoDControl(),
        SplitPaymentControl(),
        CapitalisationControl(),
        CutoffControl(),
    ]


class ControlEngine:
    """Stable production interface over the active deterministic methodology."""

    def __init__(self, controls: list[DossierControl] | None = None) -> None:
        self._controls = controls or default_controls()

    def run(self, context: ControlContext) -> tuple[Finding, ...]:
        return tuple(finding for control in self._controls for finding in control.run(context))
