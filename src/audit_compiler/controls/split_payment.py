"""Payment-splitting below an approval threshold.

Same-reference, same-day payments that each fall below the second-approval threshold but
aggregate above it. The threshold is read from the engagement's policy document (or a
methodology default). Grouping and summation run in DuckDB.
"""

from __future__ import annotations

from decimal import Decimal

from audit_compiler.controls._engine import compute
from audit_compiler.controls.base import (
    CalcInput,
    Calculation,
    ControlContext,
    CounterTest,
    EvidenceStep,
    Finding,
)
from audit_compiler.ir.roles import extract_threshold, find_tables, money, resolve_column

# A payment leg is a vendor *disbursement*. Identify it by posting type, and exclude
# customer receipts (incoming) and invoice lines so the control never groups an invoice
# with its own settlement.
_PAYMENT_KIND = ("zahlung", "payment", "auszahlung", "disbursement", "zahlungslauf")
_EXCLUDE = ("eingang", "incoming", "gutschrift", "erstattung", "ausgangsrechnung", "receipt")
_INSTALMENT_WORDS = ("rate", "raten", "instal", "abschlag")
_REVERSAL_WORDS = ("storno", "reversal", "rückbuchung", "cancel")


class SplitPaymentControl:
    id = "split_payment"
    version = "0.1.0"

    def run(self, ctx: ControlContext) -> list[Finding]:
        dossier = ctx.dossier
        default = Decimal(str(ctx.params.get("approval_threshold", "10000")))
        threshold, threshold_ev = extract_threshold(dossier, default=default)

        tables = find_tables(dossier, {"amount", "document_no", "posting_date", "posting_kind"})
        if not tables:
            return []
        table = tables[0]
        amt = resolve_column(table, "amount")
        # Group on the shared batch/payment reference (e.g. a collective-payment document),
        # not the per-line document number: reusing one reference across legs is the signal.
        ref_col = resolve_column(table, "payment_reference") or resolve_column(table, "document_no")
        doc = resolve_column(table, "document_no")
        dt = resolve_column(table, "posting_date")
        kind = resolve_column(table, "posting_kind")
        txt = resolve_column(table, "posting_text")

        rows = []
        index_by_key: dict[tuple[str, str], list[int]] = {}
        for i, r in enumerate(table.rows):
            kind_text = r.get(kind, "").lower()
            blob = f"{kind_text} {r.get(txt, '').lower()}"
            if not any(w in kind_text for w in _PAYMENT_KIND):
                continue
            if any(x in blob for x in _EXCLUDE):
                continue
            value = money(r[amt])
            if value is None or value <= 0:  # count each payment once (debit leg)
                continue
            reference = r[ref_col].strip()
            if not reference:
                continue
            rows.append((reference, r[dt], value, i))
            index_by_key.setdefault((reference, r[dt]), []).append(i)

        # Deterministic grouping + threshold logic in DuckDB.
        sql = (
            "SELECT reference, day, COUNT(*) AS n, SUM(amount) AS total, MAX(amount) AS biggest "
            "FROM t GROUP BY reference, day "
            "HAVING COUNT(*) >= 2 AND SUM(amount) >= ? AND MAX(amount) < ?"
        )
        groups = compute(
            [("reference", "VARCHAR"), ("day", "VARCHAR"), ("amount", "DECIMAL(18,2)"),
             ("i", "INTEGER")],
            rows, sql, params=[threshold, threshold],
        )

        findings: list[Finding] = []
        for reference, day, n, total, _biggest in groups:
            member_indices = index_by_key[(reference, day)]
            inputs = [
                CalcInput(
                    label=table.rows[i][doc],
                    value=money(table.rows[i][amt]),
                    evidence=table.evidence(i, amt, normalized=str(money(table.rows[i][amt]))),
                )
                for i in member_indices
            ]
            chain = [
                EvidenceStep(
                    step=f"{n} same-day payments share reference {reference}",
                    evidence=tuple(table.evidence(i, doc) for i in member_indices),
                )
            ]
            if threshold_ev is not None:
                chain.insert(
                    0,
                    EvidenceStep(
                        step=f"Second-approval threshold is {threshold} EUR (policy document)",
                        evidence=(threshold_ev,),
                    ),
                )
            findings.append(
                Finding(
                    control_id=self.id,
                    control_version=self.version,
                    title="Approval-limit payment splitting",
                    assertion="Authorisation / approval limits",
                    severity="control",
                    narrative=(
                        f"{n} payments on {day} share one reference and each fall below the "
                        f"{threshold} EUR approval limit, but aggregate to {Decimal(total)}."
                    ),
                    exposure=Decimal(total).quantize(Decimal("0.01")),
                    exposure_label="control",
                    evidence_chain=tuple(chain),
                    calculation=Calculation(
                        expression=" + ".join(str(i.value) for i in inputs),
                        inputs=tuple(inputs),
                        result=Decimal(total).quantize(Decimal("0.01")),
                        sql=sql,
                    ),
                    counter_tests=(
                        CounterTest(
                            "separate_invoices",
                            "present" if len({table.rows[i][doc] for i in member_indices}) > 1
                            else "absent",
                            "Whether the legs settle distinct underlying invoices/documents.",
                        ),
                        CounterTest("instalment_plan",
                                    self._search(table, txt, _INSTALMENT_WORDS, member_indices),
                                    "Searched payment texts for an instalment agreement."),
                        CounterTest("reversal_present",
                                    self._search(table, txt, _REVERSAL_WORDS, member_indices),
                                    "Searched for a reversing/storno entry."),
                        CounterTest("second_approval", "absent",
                                    "No second approval recorded above the threshold."),
                    ),
                    recommended_action=(
                        "Review the approval-limit control and confirm whether the payments "
                        "should have required a second approval."
                    ),
                    subject=reference,
                )
            )
        return findings

    def _search(self, table, txt, words, indices):  # noqa: ANN001
        if txt is None:
            return "not_applicable"
        for i in indices:
            if any(w in table.rows[i].get(txt, "").lower() for w in words):
                return "present"
        return "absent"
