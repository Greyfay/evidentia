"""Generic statistical / structural anomaly-discovery control.

Unlike the four targeted controls (vendor SoD, split payments, capitalisation, cut-off),
this control assumes nothing about *what* the irregularity is. It scans whichever ledger
the dossier actually provides for a small set of robust, explainable, deterministic
signals and raises each as a LEAD for the auditor -- never a verdict.

Signals implemented:

* round-number, large postings (per-row outliers against a configurable magnitude/round
  grid: a classic estimate/manual-entry red flag);
* duplicated document references (the same reference *and* amount booked more than once:
  a structural double-booking red flag);
* first-digit (Benford) deviation on the amount column (a population-level statistical
  red flag).

Every finding carries a *required* counter-test that only a human substantive procedure
can satisfy (outcome ``not_applicable``), so the admission gate always routes these
findings to human review and this control can never, on its own, confirm or dismiss a
case. Thresholds are methodology parameters read from ``ctx.params``; no sample-specific
vendor, amount, document id, filename, or year is hard-coded. Arithmetic runs in DuckDB
via :func:`audit_compiler.controls._engine.compute` to stay consistent with the other
controls, and Decimal is used throughout for money.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from audit_compiler.controls._engine import compute
from audit_compiler.controls.base import (
    CalcInput,
    Calculation,
    ControlContext,
    CounterTest,
    EvidenceStep,
    Finding,
)
from audit_compiler.ir.roles import find_tables, money, resolve_column

# Benford's law expected first-significant-digit frequencies, log10(1 + 1/d).
# These are mathematical constants of the distribution -- never sample data.
_BENFORD_EXPECTED: dict[int, Decimal] = {
    1: Decimal("0.301030"),
    2: Decimal("0.176091"),
    3: Decimal("0.124939"),
    4: Decimal("0.096910"),
    5: Decimal("0.079181"),
    6: Decimal("0.066947"),
    7: Decimal("0.057992"),
    8: Decimal("0.051153"),
    9: Decimal("0.045757"),
}

_TWO_DP = Decimal("0.01")
_SIX_DP = Decimal("0.000001")

_SCHEMA: list[tuple[str, str]] = [
    ("i", "INTEGER"),
    ("amount", "DECIMAL(18,2)"),
    ("doc", "VARCHAR"),
    ("account", "VARCHAR"),
]

# Amount rows -> first significant digit, without floating point (leading 1-9 char).
_BENFORD_DIGIT_SQL = (
    "SELECT CAST(substr(regexp_replace(CAST(ABS(amount) AS VARCHAR), '[^1-9]', '', 'g'), 1, 1) "
    "AS INTEGER) AS d, COUNT(*) AS n FROM t WHERE ABS(amount) > 0 GROUP BY d ORDER BY d"
)
_ROUND_SELECT_SQL = (
    "SELECT i, amount FROM t WHERE ABS(amount) >= ? AND mod(ABS(amount), ?) = 0 "
    "ORDER BY ABS(amount) DESC, i"
)
_ROUND_SUM_SQL = (
    "SELECT COALESCE(SUM(ABS(amount)), 0) FROM t WHERE ABS(amount) >= ? AND mod(ABS(amount), ?) = 0"
)
_DUPLICATE_SQL = (
    "SELECT doc, amount, COUNT(*) AS n, (COUNT(*) - 1) * ABS(amount) AS exposure "
    "FROM t WHERE doc <> '' GROUP BY doc, amount HAVING COUNT(*) >= ? "
    "ORDER BY exposure DESC, doc, amount"
)


def _as_decimal(value: Any, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    return result if result.is_finite() else default


def _as_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _leading_digit(amount: Decimal) -> int | None:
    """Return the first significant digit of ``amount`` (sign- and scale-independent)."""

    for char in str(abs(amount)):
        if char in "123456789":
            return int(char)
    return None


@dataclass(frozen=True, slots=True)
class AnomalyParameters:
    """Deterministic, replayable thresholds. Defaults are methodology parameters."""

    round_multiple: Decimal = Decimal("1000")
    round_min_magnitude: Decimal = Decimal("1000")
    duplicate_min_count: int = 2
    benford_min_sample: int = 200
    benford_max_abs_deviation: Decimal = Decimal("0.05")
    max_findings_per_signal: int = 25
    evidence_sample_size: int = 8

    def __post_init__(self) -> None:
        if not (self.round_multiple.is_finite() and self.round_multiple > 0):
            raise ValueError("round_multiple must be a positive Decimal")
        if not (self.round_min_magnitude.is_finite() and self.round_min_magnitude >= 0):
            raise ValueError("round_min_magnitude must be a non-negative Decimal")
        if self.duplicate_min_count < 2:
            raise ValueError("duplicate_min_count must be at least 2")
        if self.benford_min_sample < 1:
            raise ValueError("benford_min_sample must be positive")
        if not (Decimal("0") <= self.benford_max_abs_deviation <= Decimal("1")):
            raise ValueError("benford_max_abs_deviation must lie within [0, 1]")
        if self.max_findings_per_signal < 1:
            raise ValueError("max_findings_per_signal must be positive")
        if self.evidence_sample_size < 1:
            raise ValueError("evidence_sample_size must be positive")

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> AnomalyParameters:
        defaults = cls()
        return cls(
            round_multiple=_as_decimal(
                params.get("anomaly_round_multiple"), defaults.round_multiple
            ),
            round_min_magnitude=_as_decimal(
                params.get("anomaly_round_min_magnitude"), defaults.round_min_magnitude
            ),
            duplicate_min_count=_as_int(
                params.get("anomaly_duplicate_min_count"), defaults.duplicate_min_count
            ),
            benford_min_sample=_as_int(
                params.get("anomaly_benford_min_sample"), defaults.benford_min_sample
            ),
            benford_max_abs_deviation=_as_decimal(
                params.get("anomaly_benford_max_abs_deviation"),
                defaults.benford_max_abs_deviation,
            ),
            max_findings_per_signal=_as_int(
                params.get("anomaly_max_findings_per_signal"), defaults.max_findings_per_signal
            ),
            evidence_sample_size=_as_int(
                params.get("anomaly_evidence_sample_size"), defaults.evidence_sample_size
            ),
        )


class AnomalyDiscoveryControl:
    """Deterministic generic-anomaly scanner. Emits review-needed LEADS only."""

    id = "anomaly_discovery"
    version = "0.1.0"

    # A generic anomaly is a lead, never a verdict. This required, unrunnable counter-test
    # forces the admission gate to route every finding to HUMAN_REVIEW.
    _REVIEW_GATE = CounterTest(
        name="auditor_substantive_procedure",
        outcome="not_applicable",
        detail=(
            "A generic anomaly is a lead, not a verdict. A substantive procedure by the "
            "auditor is required before any conclusion; this control never confirms or clears."
        ),
        required=True,
    )

    def run(self, ctx: ControlContext) -> list[Finding]:
        dossier = ctx.dossier
        if dossier is None:
            return []
        parameters = AnomalyParameters.from_params(ctx.params)

        tables = find_tables(dossier, {"amount"})
        if not tables:
            return []
        table = tables[0]  # largest amount-bearing ledger; deterministic for a given dossier.
        amt = resolve_column(table, "amount")
        doc = resolve_column(table, "document_no")
        acc = resolve_column(table, "account")

        rows: list[tuple[int, Decimal, str, str]] = []
        for index, row in enumerate(table.rows):
            value = money(row[amt])
            if value is None or not value.is_finite():
                continue
            rows.append(
                (
                    index,
                    value.quantize(_TWO_DP),
                    (row.get(doc) or "").strip() if doc else "",
                    (row.get(acc) or "").strip() if acc else "",
                )
            )
        if not rows:
            return []

        findings: list[Finding] = []
        findings += self._round_number_signal(table, amt, rows, parameters)
        findings += self._duplicate_reference_signal(table, amt, doc, rows, parameters)
        findings += self._benford_signal(table, amt, rows, parameters)

        # Stable, input-order-independent ordering keyed only on emitted content.
        findings.sort(key=lambda finding: (finding.subject, finding.title))
        return findings

    def _round_number_signal(
        self,
        table: Any,  # noqa: ANN401 - SourceTable, kept loose to mirror the other controls
        amt: str,
        rows: list[tuple[int, Decimal, str, str]],
        parameters: AnomalyParameters,
    ) -> list[Finding]:
        flagged = compute(
            _SCHEMA,
            rows,
            _ROUND_SELECT_SQL,
            params=[parameters.round_min_magnitude, parameters.round_multiple],
        )
        if not flagged:
            return []
        total = compute(
            _SCHEMA,
            rows,
            _ROUND_SUM_SQL,
            params=[parameters.round_min_magnitude, parameters.round_multiple],
        )[0][0]
        exposure = Decimal(total).quantize(_TWO_DP)

        inputs = [
            CalcInput(
                label=f"round posting {abs(Decimal(amount))}",
                value=abs(Decimal(amount)),
                evidence=table.evidence(int(index), amt, normalized=str(abs(Decimal(amount)))),
            )
            for index, amount in flagged
        ]
        sample = inputs[: parameters.evidence_sample_size]
        chain = (
            EvidenceStep(
                step=(
                    f"{len(flagged)} posting(s) are exact multiples of "
                    f"{parameters.round_multiple} and at least "
                    f"{parameters.round_min_magnitude} in magnitude"
                ),
                evidence=tuple(item.evidence for item in sample),
            ),
        )
        return [
            Finding(
                control_id=self.id,
                control_version=self.version,
                title="Unusually round, large postings",
                assertion="Accuracy / existence (generic anomaly lead)",
                severity="low",
                narrative=(
                    f"{len(flagged)} posting(s) are exact multiples of "
                    f"{parameters.round_multiple} and at least "
                    f"{parameters.round_min_magnitude}. Round, large amounts frequently signal "
                    "estimates, accruals, or manual entries and are a lead for substantive review."
                ),
                exposure=exposure,
                exposure_label="control",
                evidence_chain=chain,
                calculation=Calculation(
                    expression=" + ".join(str(item.value) for item in inputs),
                    inputs=tuple(inputs),
                    result=exposure,
                    sql=_ROUND_SELECT_SQL,
                ),
                counter_tests=(
                    self._REVIEW_GATE,
                    CounterTest(
                        name="documented_estimate_or_contract_sum",
                        outcome="not_applicable",
                        detail=(
                            "Round values can be legitimate contract sums, budgets, or estimates; "
                            "the underlying source context was not evaluated by this control."
                        ),
                        required=False,
                    ),
                ),
                recommended_action=(
                    "Trace a sample of the round postings to source documents and confirm the "
                    "amount is contractual rather than an estimate or manual adjustment."
                ),
                uncertainty=(
                    "Rounding alone is not an error; this is a generic lead requiring review."
                ),
                subject="anomaly:round-number-postings",
            )
        ]

    def _duplicate_reference_signal(
        self,
        table: Any,  # noqa: ANN401 - SourceTable
        amt: str,
        doc: str | None,
        rows: list[tuple[int, Decimal, str, str]],
        parameters: AnomalyParameters,
    ) -> list[Finding]:
        if doc is None:
            return []
        groups = compute(
            _SCHEMA,
            rows,
            _DUPLICATE_SQL,
            params=[parameters.duplicate_min_count],
        )
        findings: list[Finding] = []
        for reference, amount, count, exposure_raw in groups[: parameters.max_findings_per_signal]:
            amount = Decimal(amount)
            exposure = Decimal(exposure_raw).quantize(_TWO_DP)
            members = sorted(
                (row for row in rows if row[2] == reference and row[1] == amount),
                key=lambda row: row[0],
            )
            inputs = [
                CalcInput(
                    label=f"reference {reference}",
                    value=abs(amount),
                    evidence=table.evidence(row[0], amt, normalized=str(abs(amount))),
                )
                for row in members
            ]
            chain = (
                EvidenceStep(
                    step=(
                        f"Reference {reference} carries {count} postings of {abs(amount)} each"
                    ),
                    evidence=tuple(
                        table.evidence(row[0], doc)
                        for row in members[: parameters.evidence_sample_size]
                    ),
                ),
            )
            findings.append(
                Finding(
                    control_id=self.id,
                    control_version=self.version,
                    title="Duplicated document reference and amount",
                    assertion="Existence / accuracy (generic anomaly lead)",
                    severity="medium",
                    narrative=(
                        f"Document reference {reference} appears {count} times with an identical "
                        f"amount of {abs(amount)}, a structural indicator of a possible "
                        "double-booking; the excess is a lead for review."
                    ),
                    exposure=exposure,
                    exposure_label="control",
                    evidence_chain=chain,
                    calculation=Calculation(
                        expression=f"({count} - 1) * {abs(amount)}",
                        inputs=tuple(inputs),
                        result=exposure,
                        sql=_DUPLICATE_SQL,
                    ),
                    counter_tests=(
                        self._REVIEW_GATE,
                        CounterTest(
                            name="distinct_underlying_transactions",
                            outcome="not_applicable",
                            detail=(
                                "A repeated reference may legitimately settle distinct legs "
                                "(instalments, partial deliveries); the underlying documents "
                                "were not inspected by this control."
                            ),
                            required=False,
                        ),
                        CounterTest(
                            name="reversal_or_correction",
                            outcome="not_applicable",
                            detail=(
                                "One leg may be a reversal or correction of another; the postings "
                                "were not reconciled against reversal entries."
                            ),
                            required=False,
                        ),
                    ),
                    recommended_action=(
                        "Reconcile the repeated postings against their source documents and any "
                        "reversal entries to confirm whether a duplicate booking occurred."
                    ),
                    uncertainty=(
                        "A repeated reference is not necessarily a duplicate; this is a lead."
                    ),
                    subject=f"anomaly:duplicate-reference:{reference}:{abs(amount)}",
                )
            )
        return findings

    def _benford_signal(
        self,
        table: Any,  # noqa: ANN401 - SourceTable
        amt: str,
        rows: list[tuple[int, Decimal, str, str]],
        parameters: AnomalyParameters,
    ) -> list[Finding]:
        counts = compute(_SCHEMA, rows, _BENFORD_DIGIT_SQL)
        observed = {int(digit): int(count) for digit, count in counts if digit is not None}
        total = sum(observed.values())
        if total < parameters.benford_min_sample:
            return []

        deviations: list[tuple[int, Decimal, Decimal]] = []
        for digit in range(1, 10):
            proportion = (Decimal(observed.get(digit, 0)) / Decimal(total)).quantize(_SIX_DP)
            deviation = abs(proportion - _BENFORD_EXPECTED[digit])
            if deviation > parameters.benford_max_abs_deviation:
                deviations.append((digit, proportion, deviation))
        if not deviations:
            return []
        deviations.sort(key=lambda item: (-item[2], item[0]))
        worst_digit, worst_proportion, worst_deviation = deviations[0]

        sample = [
            row
            for row in sorted(rows, key=lambda row: row[0])
            if _leading_digit(row[1]) == worst_digit
        ][: parameters.evidence_sample_size]
        if not sample:  # defensive: the digit necessarily originates from the population
            return []

        inputs = [
            CalcInput(
                label=f"amount with leading digit {worst_digit}",
                value=abs(row[1]),
                evidence=table.evidence(row[0], amt, normalized=str(abs(row[1]))),
            )
            for row in sample
        ]
        flagged_digits = ", ".join(str(item[0]) for item in sorted(deviations))
        chain = (
            EvidenceStep(
                step=(
                    f"First-digit distribution over {total} postings deviates from Benford's law "
                    f"for digit(s) {flagged_digits}"
                ),
                evidence=tuple(item.evidence for item in inputs),
            ),
        )
        return [
            Finding(
                control_id=self.id,
                control_version=self.version,
                title="First-digit (Benford) deviation",
                assertion="Completeness / accuracy (generic anomaly lead)",
                severity="low",
                # Benford is a population-level indicator, not a quantified misstatement.
                exposure=Decimal("0.00"),
                exposure_label="control",
                narrative=(
                    f"The leading-digit distribution of {total} amounts deviates from Benford's "
                    f"law for digit(s) {flagged_digits} (largest deviation {worst_deviation} for "
                    f"digit {worst_digit}, above the {parameters.benford_max_abs_deviation} "
                    "threshold). This is a population-level lead for review."
                ),
                evidence_chain=chain,
                calculation=Calculation(
                    expression=(
                        f"|observed({worst_proportion}) - benford("
                        f"{_BENFORD_EXPECTED[worst_digit]})| = {worst_deviation} "
                        f"> {parameters.benford_max_abs_deviation}"
                    ),
                    inputs=tuple(inputs),
                    result=Decimal("0.00"),
                    sql=_BENFORD_DIGIT_SQL,
                ),
                counter_tests=(
                    self._REVIEW_GATE,
                    CounterTest(
                        name="naturally_bounded_population",
                        outcome="not_applicable",
                        detail=(
                            "Populations bound by price lists, fixed fees, or a narrow range need "
                            "not follow Benford's law; the population composition was not assessed."
                        ),
                        required=False,
                    ),
                ),
                recommended_action=(
                    "Stratify the population by account and review the over-represented "
                    "first-digit band for manual or fabricated entries."
                ),
                uncertainty=(
                    "Benford deviation is expected for some legitimate populations; this is a lead."
                ),
                subject="anomaly:benford-first-digit",
            )
        ]
