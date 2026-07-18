"""Vendor integrity and segregation-of-duties control.

Trigger: a newly created vendor master record. The control then searches for innocent
explanations (independent approval, real goods receipts, prior-year history). It hard-codes
no vendor id or amount: creation events, the creator/approver identity, and delivery
evidence are all read from whichever columns the dossier actually provides.
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

_CREATION_WORDS = ("neuanlage", "anlage", "angelegt", "creation", "create", "new")
_VENDOR_WORDS = ("kreditor", "vendor", "supplier", "lieferant")
_PAYMENT_WORDS = ("zahlung", "payment", "ausgang", "settle")
_CARRYFORWARD_WORDS = ("saldenvortrag", "vortrag", "opening", "carry")
_RIGHT_CREATE = ("anlegen", "stammdaten", "create", "master")
_RIGHT_POST = ("buchen", "post", "journal")
_RIGHT_PAY = ("zahlungslauf", "zahlung", "payment", "pay")


class VendorSoDControl:
    id = "vendor_sod"
    version = "0.1.0"

    def run(self, ctx: ControlContext) -> list[Finding]:
        dossier = ctx.dossier
        masters = find_tables(dossier, {"change_type", "account", "changed_by", "approved_by"})
        if not masters:
            return []
        master = masters[0]
        ct = resolve_column(master, "change_type")
        acc = resolve_column(master, "account")
        cb = resolve_column(master, "changed_by")
        ab = resolve_column(master, "approved_by")
        fld = resolve_column(master, "field_changed")
        dt = resolve_column(master, "posting_date")

        findings: list[Finding] = []
        for index, row in enumerate(master.rows):
            kind = f"{row.get(ct, '')} {row.get(fld, '')}".lower()
            if not any(w in kind for w in _VENDOR_WORDS):
                continue
            if not any(w in kind for w in _CREATION_WORDS):
                continue
            vendor = row[acc]
            creator, approver = row[cb], row[ab]
            finding = self._build(ctx, master, index, vendor, creator, approver, dt)
            if finding is not None:
                findings.append(finding)
        return findings

    def _build(self, ctx, master, index, vendor, creator, approver, dt):  # noqa: ANN001
        dossier = ctx.dossier
        creation_ev = master.evidence(index, master.columns[0])
        four_eyes = creator != approver

        # Exposure: total charged to this vendor (invoice legs = negative postings), via DuckDB.
        posting_table, invoice_inputs, exposure, sql = self._vendor_exposure(dossier, vendor)

        chain = [
            EvidenceStep(
                step=(
                    f"Vendor master created and self-approved by the same user ({creator})"
                    if not four_eyes
                    else f"Vendor master created ({creator}) and approved ({approver})"
                ),
                evidence=(
                    master.evidence(index, master.columns[0]),
                    creation_ev,
                ),
            )
        ]
        rights_step = self._toxic_rights_step(dossier, creator)
        if rights_step is not None:
            chain.append(rights_step)
        if invoice_inputs:
            chain.append(
                EvidenceStep(
                    step="Invoices and payments booked against the vendor",
                    evidence=tuple(i.evidence for i in invoice_inputs[:6]),
                )
            )

        goods = self._goods_receipts(dossier, vendor)
        history = self._prior_history(dossier, posting_table, vendor)

        counter = [
            CounterTest(
                name="independent_approval",
                outcome="present" if four_eyes else "absent",
                detail=(
                    "Creator and approver differ (four-eyes principle operated)."
                    if four_eyes
                    else "Creator and approver are the same user; no independent approval."
                ),
                evidence=(master.evidence(index, master.columns[0]),),
            ),
            CounterTest(
                name="goods_receipt",
                outcome="present" if goods else "absent",
                detail=(
                    f"{len(goods)} goods-receipt record(s) matched the vendor."
                    if goods
                    else "Vendor does not appear in any goods-receipt list."
                ),
                evidence=tuple(goods[:3]),
            ),
            CounterTest(
                name="prior_year_history",
                outcome="present" if history else "absent",
                detail=(
                    "Vendor has prior-period activity / opening balance."
                    if history
                    else "No opening balance or prior-period activity for the vendor."
                ),
                evidence=tuple(history[:1]),
            ),
        ]

        return Finding(
            control_id=self.id,
            control_version=self.version,
            title="Vendor control override and unsupported spend",
            assertion="Occurrence / segregation of duties",
            severity="high",
            narrative=(
                "A newly created vendor was approved without independent review and paid "
                "with no supporting delivery evidence."
                if not four_eyes
                else "A newly created vendor; segregation of duties is being verified."
            ),
            exposure=exposure,
            exposure_label="gross",
            evidence_chain=tuple(chain),
            calculation=Calculation(
                expression=" + ".join(str(i.value) for i in invoice_inputs) or "0",
                inputs=tuple(invoice_inputs),
                result=exposure,
                sql=sql,
            ),
            counter_tests=tuple(counter),
            recommended_action=(
                "Obtain the framework contract, independent approval, and service/receipt "
                "evidence before sign-off."
            ),
            uncertainty=(
                "Service invoices do not always carry goods receipts; absence alone is not "
                "proof and must be weighed with the other evidence."
            ),
            subject=vendor,
        )

    def _vendor_exposure(self, dossier, vendor):  # noqa: ANN001
        candidates = [
            t for t in find_tables(dossier, {"amount", "posting_text"})
            if resolve_column(t, "account") and any(
                r[resolve_column(t, "account")] == vendor for r in t.rows
            )
        ]
        if not candidates:
            return None, [], Decimal("0.00"), "SELECT 0"
        table = candidates[0]
        acc = resolve_column(table, "account")
        amt = resolve_column(table, "amount")
        txt = resolve_column(table, "posting_text")
        rows, inputs = [], []
        for i, r in enumerate(table.rows):
            if r[acc] != vendor:
                continue
            value = money(r[amt])
            text = r.get(txt, "").lower()
            if value is None or any(w in text for w in _CARRYFORWARD_WORDS):
                continue
            rows.append((r[acc], value, text))
            if value < 0:  # invoice / charge leg
                ev = table.evidence(i, amt, normalized=str(abs(value)))
                inputs.append(CalcInput(label=r.get(txt, "")[:40], value=abs(value), evidence=ev))
        sql = (
            "SELECT SUM(ABS(amount)) FROM t "
            "WHERE account = ? AND amount < 0 "
            "AND lower(text) NOT LIKE '%saldenvortrag%'"
        )
        result = compute(
            [("account", "VARCHAR"), ("amount", "DECIMAL(18,2)"), ("text", "VARCHAR")],
            rows, sql, params=[vendor],
        )
        exposure = result[0][0] if result and result[0][0] is not None else Decimal("0.00")
        return table, inputs, Decimal(exposure).quantize(Decimal("0.01")), sql

    def _goods_receipts(self, dossier, vendor):  # noqa: ANN001
        out = []
        for table in find_tables(dossier, {"vendor", "goods_receipt_no"}):
            vcol = resolve_column(table, "vendor")
            for i, r in enumerate(table.rows):
                if r[vcol] == vendor:
                    out.append(table.evidence(i, vcol))
        return out

    def _prior_history(self, dossier, table, vendor):  # noqa: ANN001
        if table is None:
            return []
        acc = resolve_column(table, "account")
        txt = resolve_column(table, "posting_text")
        out = []
        for i, r in enumerate(table.rows):
            if r[acc] == vendor and txt and any(
                w in r[txt].lower() for w in _CARRYFORWARD_WORDS
            ):
                out.append(table.evidence(i, txt))
        return out

    def _toxic_rights_step(self, dossier, user):  # noqa: ANN001
        for table in dossier.tables:
            ucol = resolve_column(table, "permission_user")
            if ucol is None or len(table.columns) < 4:
                continue
            right_cols = {"create": None, "post": None, "pay": None}
            for col in table.columns:
                low = col.lower()
                if right_cols["create"] is None and any(w in low for w in _RIGHT_CREATE):
                    right_cols["create"] = col
                elif right_cols["post"] is None and any(w in low for w in _RIGHT_POST):
                    right_cols["post"] = col
                elif right_cols["pay"] is None and any(w in low for w in _RIGHT_PAY):
                    right_cols["pay"] = col
            if not all(right_cols.values()):
                continue
            for i, r in enumerate(table.rows):
                if r[ucol] != user:
                    continue
                if all(r[c].strip() for c in right_cols.values()):
                    return EvidenceStep(
                        step=f"User {user} holds create-vendor, post, and payment rights",
                        evidence=tuple(
                            table.evidence(i, c) for c in right_cols.values()
                        ),
                    )
        return None
