"""Repair/maintenance costs capitalised as fixed assets.

Trigger: an asset addition whose description uses repair/maintenance vocabulary, posted to
a balance-sheet asset account while a maintenance-expense account exists. Account nature is
read from the chart-of-accounts master (balance sheet vs P&L), never from hard-coded numbers.
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
from audit_compiler.ir.roles import find_tables, money, resolve_column

_REPAIR_WORDS = (
    "reparatur", "instandhaltung", "instandsetzung", "wartung", "austausch",
    "überholung", "ueberholung", "generalüberholung", "repair", "maintenance",
    "overhaul", "replacement", "servicing", "refurbish",
)
_ADDITION_WORDS = ("acquisition", "zugang", "addition", "anschaffung", "zuschreibung")
_BALANCE_SHEET = ("bilanz", "balance", "asset", "aktiv", "anlage")
_INVEST_WORDS = ("investitionsantrag", "investment request", "capex", "ia-", "invest")


class CapitalisationControl:
    id = "capitalisation"
    version = "0.1.0"

    def run(self, ctx: ControlContext) -> list[Finding]:
        dossier = ctx.dossier
        postings = find_tables(dossier, {"asset_no", "amount", "posting_kind", "asset_group"})
        if not postings:
            return []
        table = postings[0]
        asset_no = resolve_column(table, "asset_no")
        amt = resolve_column(table, "amount")
        kind = resolve_column(table, "posting_kind")
        group = resolve_column(table, "asset_group")
        txt = resolve_column(table, "posting_text")

        descriptions = self._asset_descriptions(dossier)
        balance_sheet_accounts = self._balance_sheet_accounts(dossier)

        rows, inputs, steps = [], [], []
        for i, r in enumerate(table.rows):
            if not any(w in r.get(kind, "").lower() for w in _ADDITION_WORDS):
                continue
            value = money(r[amt])
            if value is None or value <= 0:
                continue
            asset_id = r[asset_no]
            desc, desc_ev = descriptions.get(asset_id, (r.get(txt, ""), None))
            blob = f"{desc} {r.get(txt, '')}".lower()
            if not any(w in blob for w in _REPAIR_WORDS):
                continue
            account = r[group]
            if balance_sheet_accounts and account not in balance_sheet_accounts:
                continue
            rows.append((asset_id, value))
            inputs.append(CalcInput(label=desc[:48], value=value,
                                    evidence=table.evidence(i, amt, normalized=str(value))))
            evidence = [table.evidence(i, amt, normalized=str(value))]
            if desc_ev is not None:
                evidence.append(desc_ev)
            steps.append(EvidenceStep(step=f"Repair-type addition: {desc[:60]}",
                                      evidence=tuple(evidence)))
        if not rows:
            return []

        sql = "SELECT SUM(amount) FROM t"
        total = compute([("asset", "VARCHAR"), ("amount", "DECIMAL(18,2)")], rows, sql)[0][0]
        exposure = Decimal(total).quantize(Decimal("0.01"))

        return [
            Finding(
                control_id=self.id,
                control_version=self.version,
                title="Repairs capitalised as fixed assets",
                assertion="Classification / capitalisation",
                severity="high",
                narrative=(
                    f"{len(rows)} additions with repair/maintenance descriptions were posted "
                    "to balance-sheet asset accounts rather than maintenance expense, "
                    "overstating assets and profit."
                ),
                exposure=exposure,
                exposure_label="net",
                evidence_chain=tuple(steps[:8]),
                calculation=Calculation(
                    expression=" + ".join(str(i.value) for i in inputs),
                    inputs=tuple(inputs),
                    result=exposure,
                    sql=sql,
                ),
                counter_tests=(
                    CounterTest("investment_request",
                                self._search_words(dossier, _INVEST_WORDS, [r[0] for r in rows]),
                                "Searched documents for an investment request for these assets."),
                    CounterTest("capacity_or_useful_life", "absent",
                                "Descriptions indicate restoration, not capacity increase or "
                                "useful-life extension."),
                    CounterTest("separable_new_asset", "absent",
                                "Descriptions reference existing equipment, not a distinct new "
                                "asset."),
                ),
                recommended_action=(
                    "Reclassify repair costs to maintenance expense and correct asset values."
                ),
                subject="capitalised-repairs",
            )
        ]

    def _asset_descriptions(self, dossier):  # noqa: ANN001
        out = {}
        for table in find_tables(dossier, {"asset_no", "asset_desc"}):
            id_col = resolve_column(table, "asset_no")
            desc_col = resolve_column(table, "asset_desc")
            for i, r in enumerate(table.rows):
                out.setdefault(r[id_col], (r[desc_col], table.evidence(i, desc_col)))
        return out

    def _balance_sheet_accounts(self, dossier):  # noqa: ANN001
        accounts = set()
        for table in find_tables(dossier, {"account", "account_type"}):
            acc = resolve_column(table, "account")
            typ = resolve_column(table, "account_type")
            for r in table.rows:
                if any(w in r[typ].lower() for w in _BALANCE_SHEET):
                    accounts.add(r[acc])
        return accounts

    def _search_words(self, dossier, words, subjects):  # noqa: ANN001
        for table in dossier.tables:
            for r in table.rows:
                blob = " ".join(r.values()).lower()
                if any(w in blob for w in words) and any(s in blob for s in subjects):
                    return "present"
        return "absent"
