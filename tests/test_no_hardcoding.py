"""Prove the product logic contains no sample-specific constants.

This guard scans the shipped source (excluding tests) for the organizer's sample vendor
ids, document numbers, and expected amounts. It must pass on every fresh clone.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "audit_compiler"

# Values that appear ONLY in the private oracle / sample answers — never legitimate in code.
_FORBIDDEN = [
    "209101", "209112", "200007", "MV-U05", "SAMMEL-200007",
    "248000", "295120", "150800", "192000", "39040", "2599841", "2257041",
    "IA-2025-04", "Ratio Consulting", "ER901421",
]


def test_source_contains_no_sample_constants():
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in _FORBIDDEN:
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert not offenders, f"sample-specific constants leaked into product logic: {offenders}"


def test_no_repair_account_numbers_hardcoded():
    """Capitalisation must classify accounts by master-data type, not literal numbers."""

    capex = (_SRC / "controls" / "capitalisation.py").read_text(encoding="utf-8")
    # Bare six-digit account literals would indicate a hard-coded chart of accounts.
    assert not re.search(r"\b0[24]0000\b|\b060000\b|\b670000\b", capex)
