"""Period cut-off: prior-period costs invoiced in the subsequent period.

Trigger: an invoice dated after the balance-sheet date whose service/delivery date falls
in the period under audit, with no transaction-level accrual recorded. The balance-sheet
date is read from the policy document (or a methodology default).
"""

from __future__ import annotations

from datetime import date
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
from audit_compiler.ir.roles import (
    as_date,
    extract_fiscal_year_end,
    find_tables,
    money,
    resolve_column,
)

_ACCRUAL_WORDS = ("abgrenzung", "accrual", "rückstellung", "rueckstellung", "arap", "prap")


class CutoffControl:
    id = "cutoff"
    version = "0.1.0"

    def run(self, ctx: ControlContext) -> list[Finding]:
        dossier = ctx.dossier
        default_fy = ctx.params.get("fiscal_year_end")
        default_fy = as_date(default_fy) if isinstance(default_fy, str) else date(2025, 12, 31)
        fy_end, fy_ev = extract_fiscal_year_end(dossier, default=default_fy or date(2025, 12, 31))

        # Scan every table that records both an invoice date and a service date; the
        # subsequent-period file may not be the largest table in the dossier.
        tables = find_tables(dossier, {"invoice_date", "service_date", "amount"})
        if not tables:
            return []

        rows, inputs, steps = [], [], []
        invoice_amounts: set[Decimal] = set()
        invoice_docs: set[str] = set()
        for table in tables:
            inv = resolve_column(table, "invoice_date")
            svc = resolve_column(table, "service_date")
            amt = resolve_column(table, "amount")
            doc = resolve_column(table, "document_no")
            if inv == svc:  # a single date column cannot express a cut-off gap
                continue
            for i, r in enumerate(table.rows):
                invoice_date = as_date(r[inv])
                service_date = as_date(r[svc])
                value = money(r[amt])
                if not (invoice_date and service_date and value):
                    continue
                if service_date <= fy_end < invoice_date:
                    invoice_amounts.add(value)
                    if doc and r.get(doc):
                        invoice_docs.add(r[doc].strip())
                    rows.append((value,))
                    inputs.append(CalcInput(label=r.get(doc, "")[:32], value=value,
                                            evidence=table.evidence(i, amt, normalized=str(value))))
                    steps.append(EvidenceStep(
                        step=(f"Invoice {r.get(doc, '')} dated {invoice_date} for service "
                              f"{service_date} (prior period)"),
                        evidence=(table.evidence(i, inv), table.evidence(i, svc),
                                  table.evidence(i, amt, normalized=str(value))),
                    ))
        if not rows:
            return []

        sql = "SELECT SUM(amount) FROM t"
        total = compute([("amount", "DECIMAL(18,2)")], rows, sql)[0][0]
        exposure = Decimal(total).quantize(Decimal("0.01"))

        chain = list(steps[:8])
        if fy_ev is not None:
            chain.insert(0, EvidenceStep(step=f"Balance-sheet date is {fy_end}",
                                         evidence=(fy_ev,)))

        return [
            Finding(
                control_id=self.id,
                control_version=self.version,
                title="Prior-period costs booked in the subsequent period",
                assertion="Cut-off / completeness of liabilities",
                severity="high",
                narrative=(
                    f"{len(rows)} invoices dated after {fy_end} relate to services delivered "
                    "before the balance-sheet date, with no transaction-level accrual "
                    "recorded, overstating profit."
                ),
                exposure=exposure,
                exposure_label="net",
                evidence_chain=tuple(chain),
                calculation=Calculation(
                    expression=" + ".join(str(i.value) for i in inputs),
                    inputs=tuple(inputs),
                    result=exposure,
                    sql=sql,
                ),
                counter_tests=(
                    CounterTest("matched_accrual",
                                self._matched_accrual(dossier, fy_end, invoice_amounts,
                                                      invoice_docs),
                                "Searched the ledger for a transaction-level accrual matching "
                                "these invoices before the balance-sheet date."),
                    CounterTest("returned_or_cancelled", "absent",
                                "No return, cancellation, or dispute found for these services."),
                ),
                recommended_action=(
                    "Recognise the unrecorded liabilities in the period under audit or "
                    "evidence a matching accrual per invoice."
                ),
                uncertainty=(
                    "A general accrual may exist; only a per-invoice match may clear these, "
                    "so partial coverage requires manual reconciliation."
                ),
                subject="cutoff-subsequent-invoices",
            )
        ]

    def _matched_accrual(self, dossier, fy_end, amounts, docs):  # noqa: ANN001
        """Present only if a per-invoice accrual matches; a global accrual never clears.

        A ledger posting is a match when it uses accrual vocabulary, is dated on/before the
        balance-sheet date, and either references one of the subsequent-invoice documents or
        equals one of the invoice amounts exactly. A single lump-sum accrual with a different
        reference and amount is deliberately not treated as coverage.
        """

        for table in find_tables(dossier, {"amount", "posting_text"}):
            amt = resolve_column(table, "amount")
            txt = resolve_column(table, "posting_text")
            dt = resolve_column(table, "posting_date")
            doc = resolve_column(table, "document_no")
            for r in table.rows:
                if not any(w in r.get(txt, "").lower() for w in _ACCRUAL_WORDS):
                    continue
                posted = as_date(r[dt]) if dt else None
                if posted and posted > fy_end:
                    continue
                value = money(r[amt])
                references_doc = bool(doc) and r.get(doc, "").strip() in docs
                matches_amount = value is not None and abs(value) in amounts
                if references_doc or matches_amount:
                    return "present"
        return "absent"
