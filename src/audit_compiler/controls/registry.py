"""The methodology's ordered control library."""

from __future__ import annotations

from audit_compiler.controls.base import Control
from audit_compiler.controls.capitalisation import CapitalisationControl
from audit_compiler.controls.cutoff import CutoffControl
from audit_compiler.controls.split_payment import SplitPaymentControl
from audit_compiler.controls.vendor_sod import VendorSoDControl

METHODOLOGY_VERSION = "generic-controls@0.1.0"


def default_controls() -> list[Control]:
    """Return the four generic controls in methodology order."""

    return [
        VendorSoDControl(),
        SplitPaymentControl(),
        CapitalisationControl(),
        CutoffControl(),
    ]
