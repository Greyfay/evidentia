"""Synthetic tests for the generic anomaly-discovery control.

All inputs are in-memory synthetic dossiers; no sample-specific data is used. The tests
assert that anomalies are found, ordering is stable and input-order-independent, money is
Decimal, findings are review-needed leads (never confirmed/dismissed), thresholds are
configurable, and clean data yields no false positives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from hashlib import sha256

import pytest

from audit_compiler.admission import admit
from audit_compiler.controls import AnomalyDiscoveryControl, AnomalyParameters, ControlContext
from audit_compiler.models import EvidenceRef, SourceType

# --- Synthetic in-memory dossier -------------------------------------------------------

@dataclass(frozen=True)
class FakeTable:
    """A minimal stand-in for SourceTable that yields real EvidenceRefs."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    source_path: str = "synthetic/ledger.csv"

    def evidence(self, index: int, column: str, *, normalized: str | None = None) -> EvidenceRef:
        raw = self.rows[index].get(column, "")
        return EvidenceRef(
            source_path=self.source_path,
            source_type=SourceType.CSV_ROW,
            file_sha256="a" * 64,
            raw_value=raw,
            raw_value_sha256=sha256(raw.encode()).hexdigest(),
            normalized_value=normalized,
            row=index + 2,
        )


@dataclass(frozen=True)
class FakeDossier:
    tables: tuple[FakeTable, ...] = field(default_factory=tuple)


def ledger(rows: list[dict[str, str]], *, name: str = "ledger") -> FakeTable:
    columns = ("BELEGNUMMER", "BUCHUNGSBETRAG", "SACHKONTONUMMER", "BUCHUNGSTEXT")
    return FakeTable(
        name=name,
        columns=columns,
        rows=tuple(
            {
                "BELEGNUMMER": row.get("doc", ""),
                "BUCHUNGSBETRAG": row["amount"],
                "SACHKONTONUMMER": row.get("account", "A-1"),
                "BUCHUNGSTEXT": row.get("text", ""),
            }
            for row in rows
        ),
    )


def run(rows, *, params=None, name="ledger"):
    dossier = FakeDossier(tables=(ledger(rows, name=name),))
    ctx = ControlContext(dossier=dossier, params=params or {})
    return AnomalyDiscoveryControl().run(ctx)


def by_subject(findings):
    return {f.subject: f for f in findings}


# A Benford-conforming clean population (per-digit counts match log10(1+1/d) at N=1000)
# with distinct references and non-round amounts, so no default threshold is tripped.
_BENFORD_COUNTS = {1: 301, 2: 176, 3: 125, 4: 97, 5: 79, 6: 67, 7: 58, 8: 51, 9: 46}


def _clean_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for digit, count in _BENFORD_COUNTS.items():
        for k in range(count):
            cents = (k * 7) % 99 + 1  # always 1..99: never a whole multiple of 1000
            rows.append(
                {
                    "amount": f"{digit}{k}.{cents:02d}",  # leading significant digit == digit
                    "doc": f"C-{digit}-{k}",
                    "account": "A-1",
                }
            )
    return rows


# --- Round-number, large postings ------------------------------------------------------

def test_round_large_postings_are_flagged() -> None:
    rows = _clean_rows() + [
        {"amount": "5000.00", "doc": "R-1"},
        {"amount": "12000.00", "doc": "R-2"},
    ]
    finding = by_subject(run(rows))["anomaly:round-number-postings"]
    assert finding.control_id == "anomaly_discovery"
    assert finding.exposure == Decimal("17000.00")
    assert isinstance(finding.exposure, Decimal)
    assert all(isinstance(i.value, Decimal) for i in finding.calculation.inputs)
    assert finding.calculation.inputs  # cited exposure


def test_round_threshold_is_configurable() -> None:
    rows = _clean_rows() + [{"amount": "5000.00", "doc": "R-1"}]
    # 5000 is a multiple of 1000 (default) but not of 4000.
    assert "anomaly:round-number-postings" in by_subject(run(rows))
    tuned = run(rows, params={"anomaly_round_multiple": "4000"})
    assert "anomaly:round-number-postings" not in by_subject(tuned)


def test_round_magnitude_floor_is_configurable() -> None:
    rows = _clean_rows() + [{"amount": "2000.00", "doc": "R-1"}]
    high_floor = run(rows, params={"anomaly_round_min_magnitude": "5000"})
    assert "anomaly:round-number-postings" not in by_subject(high_floor)


# --- Duplicate document references -----------------------------------------------------

def test_duplicate_reference_and_amount_is_flagged() -> None:
    rows = _clean_rows() + [
        {"amount": "250.00", "doc": "DUP-1"},
        {"amount": "250.00", "doc": "DUP-1"},
        {"amount": "250.00", "doc": "DUP-1"},
    ]
    dup = [f for f in run(rows) if f.title == "Duplicated document reference and amount"]
    assert len(dup) == 1
    # (3 - 1) * 250 potential double-booking exposure.
    assert dup[0].exposure == Decimal("500.00")
    assert dup[0].subject == "anomaly:duplicate-reference:DUP-1:250.00"


def test_distinct_amounts_under_same_reference_are_not_duplicates() -> None:
    rows = _clean_rows() + [
        {"amount": "250.00", "doc": "REF-1"},
        {"amount": "999.00", "doc": "REF-1"},
    ]
    assert not [f for f in run(rows) if f.title == "Duplicated document reference and amount"]


def test_duplicate_min_count_is_configurable() -> None:
    rows = _clean_rows() + [
        {"amount": "250.00", "doc": "DUP-1"},
        {"amount": "250.00", "doc": "DUP-1"},
    ]
    assert [f for f in run(rows) if f.title == "Duplicated document reference and amount"]
    stricter = run(rows, params={"anomaly_duplicate_min_count": "3"})
    assert not [f for f in stricter if f.title == "Duplicated document reference and amount"]


# --- Benford first-digit deviation -----------------------------------------------------

def test_benford_deviation_is_flagged_on_skewed_population() -> None:
    # A population dominated by leading digit 9 grossly violates Benford's law.
    rows = [{"amount": "900.00", "doc": f"B-{i}", "account": "A-1"} for i in range(300)]
    benford = [f for f in run(rows) if f.title == "First-digit (Benford) deviation"]
    assert len(benford) == 1
    assert benford[0].exposure == Decimal("0.00")  # population-level lead, not a money amount
    assert benford[0].calculation.inputs  # still cites sampled evidence


def test_benford_requires_minimum_sample() -> None:
    rows = [{"amount": "900.00", "doc": f"B-{i}"} for i in range(50)]
    assert not [f for f in run(rows) if f.title == "First-digit (Benford) deviation"]
    # Lowering the sample floor lets the same skew surface.
    tuned = run(rows, params={"anomaly_benford_min_sample": "10"})
    assert [f for f in tuned if f.title == "First-digit (Benford) deviation"]


def test_benford_tolerance_is_configurable() -> None:
    rows = [{"amount": "900.00", "doc": f"B-{i}"} for i in range(300)]
    lenient = run(rows, params={"anomaly_benford_max_abs_deviation": "1"})
    assert not [f for f in lenient if f.title == "First-digit (Benford) deviation"]


# --- Review-needed, never a verdict ----------------------------------------------------

def test_every_finding_is_routed_to_human_review() -> None:
    rows = _clean_rows() + [
        {"amount": "5000.00", "doc": "R-1"},
        {"amount": "250.00", "doc": "DUP-1"},
        {"amount": "250.00", "doc": "DUP-1"},
    ]
    findings = run(rows)
    assert findings
    for finding in findings:
        verdict = admit(finding).verdict
        assert verdict == "HUMAN_REVIEW", (finding.subject, verdict)
        # A generic anomaly never confirms nor dismisses.
        assert verdict not in {"CONFIRMED", "DISMISSED"}
        # Every review-needed lead carries an evidence chain and a cited calculation.
        assert finding.evidence_chain
        assert finding.calculation.inputs


def test_required_counter_test_is_unrunnable_gate() -> None:
    rows = _clean_rows() + [{"amount": "5000.00", "doc": "R-1"}]
    finding = by_subject(run(rows))["anomaly:round-number-postings"]
    required = [c for c in finding.counter_tests if c.required]
    assert required and all(c.outcome == "not_applicable" for c in required)


# --- Determinism -----------------------------------------------------------------------

def test_ordering_is_stable_and_independent_of_input_order() -> None:
    rows = _clean_rows() + [
        {"amount": "5000.00", "doc": "R-1"},
        {"amount": "250.00", "doc": "DUP-1"},
        {"amount": "250.00", "doc": "DUP-1"},
        {"amount": "8000.00", "doc": "R-2"},
    ]
    forward = [f.subject for f in run(rows)]
    reversed_rows = list(reversed(rows))
    backward = [f.subject for f in run(reversed_rows)]
    assert forward == backward
    assert forward == sorted(forward)


def test_repeated_runs_are_identical() -> None:
    rows = _clean_rows() + [{"amount": "5000.00", "doc": "R-1"}]
    first = run(rows)
    second = run(rows)
    assert [f.subject for f in first] == [f.subject for f in second]
    assert [str(f.exposure) for f in first] == [str(f.exposure) for f in second]


# --- No false positives on clean data --------------------------------------------------

def test_clean_population_produces_no_findings() -> None:
    assert run(_clean_rows()) == []


def test_no_amount_table_yields_no_findings() -> None:
    empty = FakeTable(name="notes", columns=("BEMERKUNG",), rows=({"BEMERKUNG": "x"},))
    ctx = ControlContext(dossier=FakeDossier(tables=(empty,)), params={})
    assert AnomalyDiscoveryControl().run(ctx) == []


# --- Parameter validation --------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        {"anomaly_round_multiple": "0"},
        {"anomaly_duplicate_min_count": "1"},
        {"anomaly_benford_max_abs_deviation": "2"},
        {"anomaly_evidence_sample_size": "0"},
    ],
)
def test_invalid_parameters_are_rejected(params: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        AnomalyParameters.from_params(params)


def test_garbage_parameter_values_fall_back_to_defaults() -> None:
    parameters = AnomalyParameters.from_params(
        {"anomaly_round_multiple": "not-a-number", "anomaly_duplicate_min_count": "oops"}
    )
    assert parameters.round_multiple == AnomalyParameters().round_multiple
    assert parameters.duplicate_min_count == AnomalyParameters().duplicate_min_count
