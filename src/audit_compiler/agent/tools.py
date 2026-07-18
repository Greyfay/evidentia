"""Deterministic, allow-listed agent tools for the interactive audit investigation agent.

Every tool is a plain function ``(ctx: AgentContext, args: <pydantic model>) -> ToolResult``.
Tools never invent evidence: every id returned in ``ToolResult.evidence_ids`` or inside a
``ToolCalculation`` comes from ``ctx.cite(ref)``, which records the pointer in the shared
``EvidenceRegistry`` first. Tools never hard-code a filename, vendor id, or column name —
concepts are resolved through ``audit_compiler.ir.roles`` against whatever dossier is loaded.
All monetary arithmetic is either delegated to a control's DuckDB ``compute`` or done with
``Decimal`` directly; floats are rejected at the input boundary.

Detection logic (self-approved vendors, split payments, capitalised repairs, cut-off) is not
reimplemented here: tools call into the four generic controls in ``audit_compiler.controls``
and translate their ``Finding``/``Calculation`` objects into cited ``ToolResult`` payloads.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from audit_compiler.admission import admit
from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.models import ToolCalculation, ToolCalculationInput, ToolResult
from audit_compiler.controls._engine import compute
from audit_compiler.controls.base import Calculation, ControlContext, Finding
from audit_compiler.controls.registry import default_controls
from audit_compiler.controls.vendor_sod import VendorSoDControl
from audit_compiler.ir.dossier import LoadedDossier, SourceTable
from audit_compiler.ir.roles import as_date, find_tables, money, resolve_column
from audit_compiler.models import EvidenceRef, SourceType

_CONTROLS_BY_ID = {c.id: c for c in default_controls()}
_VENDOR_SOD = _CONTROLS_BY_ID["vendor_sod"]
assert isinstance(_VENDOR_SOD, VendorSoDControl)

_SEARCH_LIMIT = 50
_PEER_SCAN_LIMIT = 200

_REVERSAL_WORDS = ("storno", "reversal", "rückbuchung", "rueckbuchung", "cancel", "cancellation")
_CREDIT_NOTE_WORDS = ("gutschrift", "credit note", "credit memo", "erstattung")
_CONTRACT_WORDS = (
    "vertrag", "rahmenvertrag", "dienstleistungsvertrag", "werkvertrag",
    "contract", "service agreement", "framework agreement",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("monetary values must be Decimal/int/str, never float")
    return value


# --------------------------------------------------------------------------------------
# Shared helpers: citing evidence and converting control-layer objects into agent-layer
# (cited) ones. Nothing here invents an evidence id; every id passes through ctx.cite.
# --------------------------------------------------------------------------------------


def _cite_all(ctx: AgentContext, refs: tuple[EvidenceRef, ...]) -> tuple[str, ...]:
    return tuple(ctx.cite(ref) for ref in refs)


def _dedupe(ids: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))


def _convert_calculation(ctx: AgentContext, calc: Calculation) -> ToolCalculation:
    inputs = tuple(
        ToolCalculationInput(label=i.label, value=i.value, evidence_id=ctx.cite(i.evidence))
        for i in calc.inputs
    )
    return ToolCalculation(
        expression=calc.expression, inputs=inputs, result=calc.result, sql=calc.sql
    )


def _finding_evidence_ids(ctx: AgentContext, finding: Finding) -> tuple[str, ...]:
    ids: list[str] = []
    for step in finding.evidence_chain:
        ids.extend(ctx.cite(e) for e in step.evidence)
    for counter_test in finding.counter_tests:
        ids.extend(ctx.cite(e) for e in counter_test.evidence)
    ids.extend(ctx.cite(i.evidence) for i in finding.calculation.inputs)
    return _dedupe(ids)


def _finding_summary(finding: Finding, admission=None) -> dict:  # noqa: ANN001
    summary = {
        "control_id": finding.control_id,
        "control_version": finding.control_version,
        "subject": finding.subject,
        "title": finding.title,
        "assertion": finding.assertion,
        "severity": finding.severity,
        "narrative": finding.narrative,
        "exposure": str(finding.exposure),
        "exposure_label": finding.exposure_label,
        "counter_tests": [
            {"name": c.name, "outcome": c.outcome, "detail": c.detail, "required": c.required}
            for c in finding.counter_tests
        ],
        "recommended_action": finding.recommended_action,
        "uncertainty": finding.uncertainty,
    }
    if admission is not None:
        summary["verdict"] = admission.verdict
        summary["verdict_reason"] = admission.reason
    return summary


def _run_control(control, dossier: LoadedDossier, params: dict) -> list[Finding]:  # noqa: ANN001
    return control.run(ControlContext(dossier=dossier, params=params))


# --------------------------------------------------------------------------------------
# inventory_dossier
# --------------------------------------------------------------------------------------


class InventoryDossierArgs(_StrictModel):
    pass


def tool_inventory_dossier(ctx: AgentContext, args: InventoryDossierArgs) -> ToolResult:
    tables = [
        {
            "name": table.name,
            "source_path": table.source_path,
            "source_type": table.source_type.value,
            "sheet": table.sheet,
            "columns": list(table.columns),
            "row_count": len(table.rows),
        }
        for table in ctx.dossier.tables
    ]
    warnings = [{"source_path": path, "message": message} for path, message in ctx.dossier.warnings]
    return ToolResult(
        tool_name="inventory_dossier",
        structured_result={"root": str(ctx.dossier.root), "tables": tables, "warnings": warnings},
    )


# --------------------------------------------------------------------------------------
# search_evidence
# --------------------------------------------------------------------------------------


class SearchEvidenceArgs(_StrictModel):
    query: str = Field(min_length=1)
    source_type: str | None = None


def tool_search_evidence(ctx: AgentContext, args: SearchEvidenceArgs) -> ToolResult:
    source_type_filter = None
    if args.source_type is not None:
        valid = {s.value for s in SourceType}
        if args.source_type not in valid:
            return ToolResult(
                tool_name="search_evidence",
                ok=False,
                errors=(f"unknown source_type {args.source_type!r}; valid: {sorted(valid)}",),
            )
        source_type_filter = args.source_type

    query_lower = args.query.lower()
    matches: list[dict] = []
    evidence_ids: list[str] = []
    truncated = False
    for table in ctx.dossier.tables:
        if source_type_filter and table.source_type.value != source_type_filter:
            continue
        for index, row in enumerate(table.rows):
            for column, value in row.items():
                if query_lower not in value.lower():
                    continue
                if len(matches) >= _SEARCH_LIMIT:
                    truncated = True
                    break
                ref = table.evidence(index, column)
                evidence_id = ctx.cite(ref)
                evidence_ids.append(evidence_id)
                matches.append(
                    {
                        "evidence_id": evidence_id,
                        "source_path": table.source_path,
                        "column": column,
                        "row": table.row_numbers[index],
                        "raw_value": value[:200],
                    }
                )
            if truncated:
                break
        if truncated:
            break

    return ToolResult(
        tool_name="search_evidence",
        structured_result={"query": args.query, "matches": matches, "truncated": truncated},
        evidence_ids=_dedupe(evidence_ids),
    )


# --------------------------------------------------------------------------------------
# open_evidence
# --------------------------------------------------------------------------------------


class OpenEvidenceArgs(_StrictModel):
    evidence_id: str = Field(min_length=1)


def tool_open_evidence(ctx: AgentContext, args: OpenEvidenceArgs) -> ToolResult:
    resolved = ctx.registry.resolve(args.evidence_id)
    if resolved is None:
        return ToolResult(
            tool_name="open_evidence",
            ok=False,
            errors=(
                f"unknown evidence id (not recorded by any prior tool call): {args.evidence_id}",
            ),
        )
    return ToolResult(
        tool_name="open_evidence",
        structured_result=resolved,
        evidence_ids=(args.evidence_id,),
    )


# --------------------------------------------------------------------------------------
# get_vendor_history
# --------------------------------------------------------------------------------------


class GetVendorHistoryArgs(_StrictModel):
    vendor_id: str = Field(min_length=1)


def _vendor_posting_table(dossier: LoadedDossier, vendor_id: str) -> SourceTable | None:
    for table in find_tables(dossier, {"account", "amount"}):
        acc = resolve_column(table, "account")
        if any(r[acc] == vendor_id for r in table.rows):
            return table
    return None


def tool_get_vendor_history(ctx: AgentContext, args: GetVendorHistoryArgs) -> ToolResult:
    table = _vendor_posting_table(ctx.dossier, args.vendor_id)
    if table is None:
        return ToolResult(
            tool_name="get_vendor_history",
            ok=False,
            errors=(f"vendor {args.vendor_id!r} not found in any posting table",),
        )
    acc = resolve_column(table, "account")
    amt = resolve_column(table, "amount")
    txt = resolve_column(table, "posting_text")
    dt = resolve_column(table, "posting_date")

    rows: list[tuple[str, Decimal, str]] = []
    postings: list[dict] = []
    for index, row in enumerate(table.rows):
        if row[acc] != args.vendor_id:
            continue
        value = money(row[amt])
        if value is None:
            continue
        rows.append((row[acc], value, row.get(txt, "")))
        evidence_id = ctx.cite(table.evidence(index, amt, normalized=str(value)))
        postings.append(
            {
                "date": row.get(dt, ""),
                "amount": str(value),
                "text": row.get(txt, ""),
                "evidence_id": evidence_id,
            }
        )

    sql = "SELECT SUM(amount) FROM t WHERE account = ?"
    result = compute(
        [("account", "VARCHAR"), ("amount", "DECIMAL(18,2)"), ("text", "VARCHAR")],
        rows, sql, params=[args.vendor_id],
    )
    net_total = result[0][0] if result and result[0][0] is not None else Decimal("0.00")
    net_total = Decimal(net_total).quantize(Decimal("0.01"))

    calc_inputs = tuple(
        ToolCalculationInput(
            label=p["text"][:48], value=Decimal(p["amount"]), evidence_id=p["evidence_id"]
        )
        for p in postings
    )
    return ToolResult(
        tool_name="get_vendor_history",
        structured_result={
            "vendor_id": args.vendor_id, "postings": postings, "net_total": str(net_total)
        },
        evidence_ids=_dedupe([p["evidence_id"] for p in postings]),
        calculation=ToolCalculation(
            expression="SUM(amount) WHERE account = vendor_id",
            inputs=calc_inputs,
            result=net_total,
            sql=sql,
        ),
    )


# --------------------------------------------------------------------------------------
# check_vendor_creation_and_approval
# --------------------------------------------------------------------------------------


class CheckVendorCreationAndApprovalArgs(_StrictModel):
    vendor_id: str | None = None


def tool_check_vendor_creation_and_approval(
    ctx: AgentContext, args: CheckVendorCreationAndApprovalArgs
) -> ToolResult:
    findings = _run_control(_VENDOR_SOD, ctx.dossier, ctx.params)
    if not findings:
        return ToolResult(
            tool_name="check_vendor_creation_and_approval",
            ok=False,
            errors=("no vendor-creation events found in the master-change table",),
        )
    if args.vendor_id is not None:
        findings = [f for f in findings if f.subject == args.vendor_id]
        if not findings:
            return ToolResult(
                tool_name="check_vendor_creation_and_approval",
                ok=False,
                errors=(f"no vendor-creation event found for vendor {args.vendor_id!r}",),
            )

    evidence_ids: list[str] = []
    vendors = []
    for finding in findings:
        evidence_ids.extend(_finding_evidence_ids(ctx, finding))
        independent = next(
            (c for c in finding.counter_tests if c.name == "independent_approval"), None
        )
        vendors.append(
            {
                "vendor_id": finding.subject,
                "self_approved": independent is not None and independent.outcome == "absent",
                "detail": independent.detail if independent else "",
                **_finding_summary(finding),
            }
        )
    return ToolResult(
        tool_name="check_vendor_creation_and_approval",
        structured_result={"vendors": vendors},
        evidence_ids=_dedupe(evidence_ids),
    )


# --------------------------------------------------------------------------------------
# check_user_permissions
# --------------------------------------------------------------------------------------


class CheckUserPermissionsArgs(_StrictModel):
    user_id: str = Field(min_length=1)


def _has_permission_table(dossier: LoadedDossier) -> bool:
    for table in dossier.tables:
        user_col = resolve_column(table, "permission_user")
        if user_col is not None and len(table.columns) >= 4:
            return True
    return False


def tool_check_user_permissions(ctx: AgentContext, args: CheckUserPermissionsArgs) -> ToolResult:
    if not _has_permission_table(ctx.dossier):
        return ToolResult(
            tool_name="check_user_permissions",
            ok=False,
            errors=("no user-permissions sheet found in the dossier",),
        )
    step = _VENDOR_SOD._toxic_rights_step(ctx.dossier, args.user_id)  # noqa: SLF001
    evidence_ids = _cite_all(ctx, step.evidence) if step is not None else ()
    return ToolResult(
        tool_name="check_user_permissions",
        structured_result={
            "user_id": args.user_id,
            "toxic_combination": step is not None,
            "detail": step.step if step is not None
            else f"No create+post+pay rights combination found for user {args.user_id!r}.",
        },
        evidence_ids=evidence_ids,
    )


# --------------------------------------------------------------------------------------
# reconcile_vendor_invoices_and_payments
# --------------------------------------------------------------------------------------


class ReconcileVendorInvoicesAndPaymentsArgs(_StrictModel):
    vendor_id: str = Field(min_length=1)


def tool_reconcile_vendor_invoices_and_payments(
    ctx: AgentContext, args: ReconcileVendorInvoicesAndPaymentsArgs
) -> ToolResult:
    table = _vendor_posting_table(ctx.dossier, args.vendor_id)
    if table is None:
        return ToolResult(
            tool_name="reconcile_vendor_invoices_and_payments",
            ok=False,
            errors=(f"vendor {args.vendor_id!r} not found in any posting table",),
        )
    acc = resolve_column(table, "account")
    amt = resolve_column(table, "amount")
    txt = resolve_column(table, "posting_text")

    rows: list[tuple[str, Decimal]] = []
    calc_inputs: list[ToolCalculationInput] = []
    for index, row in enumerate(table.rows):
        if row[acc] != args.vendor_id:
            continue
        value = money(row[amt])
        if value is None:
            continue
        rows.append((row[acc], value))
        evidence_id = ctx.cite(table.evidence(index, amt, normalized=str(value)))
        calc_inputs.append(
            ToolCalculationInput(label=row.get(txt, "")[:48], value=value, evidence_id=evidence_id)
        )

    sql = (
        "SELECT SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS invoices, "
        "SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS payments FROM t WHERE account = ?"
    )
    result = compute(
        [("account", "VARCHAR"), ("amount", "DECIMAL(18,2)")], rows, sql, params=[args.vendor_id]
    )
    invoices_total, payments_total = result[0] if result else (None, None)
    invoices_total = (
        Decimal(invoices_total).quantize(Decimal("0.01"))
        if invoices_total is not None else Decimal("0.00")
    )
    payments_total = (
        Decimal(payments_total).quantize(Decimal("0.01"))
        if payments_total is not None else Decimal("0.00")
    )
    unreconciled = (invoices_total - payments_total).quantize(Decimal("0.01"))

    return ToolResult(
        tool_name="reconcile_vendor_invoices_and_payments",
        structured_result={
            "vendor_id": args.vendor_id,
            "invoices_total": str(invoices_total),
            "payments_total": str(payments_total),
            "unreconciled": str(unreconciled),
        },
        evidence_ids=_dedupe([i.evidence_id for i in calc_inputs]),
        calculation=ToolCalculation(
            expression="SUM(invoice legs) - SUM(payment legs)",
            inputs=tuple(calc_inputs),
            result=unreconciled,
            sql=sql,
        ),
    )


# --------------------------------------------------------------------------------------
# match_invoice_order_receipt
# --------------------------------------------------------------------------------------


class MatchInvoiceOrderReceiptArgs(_StrictModel):
    vendor_id: str | None = None


def tool_match_invoice_order_receipt(
    ctx: AgentContext, args: MatchInvoiceOrderReceiptArgs
) -> ToolResult:
    capable_tables = find_tables(ctx.dossier, {"vendor", "goods_receipt_no"})
    if not capable_tables:
        return ToolResult(
            tool_name="match_invoice_order_receipt",
            ok=False,
            errors=("no goods-receipt table found in the dossier",),
        )

    if args.vendor_id is not None:
        refs = _VENDOR_SOD._goods_receipts(ctx.dossier, args.vendor_id)  # noqa: SLF001
        evidence_ids = _cite_all(ctx, tuple(refs))
        return ToolResult(
            tool_name="match_invoice_order_receipt",
            structured_result={
                "vendor_id": args.vendor_id,
                "matched": bool(refs),
                "match_count": len(refs),
            },
            evidence_ids=evidence_ids,
        )

    evidence_ids: list[str] = []
    total = 0
    for table in capable_tables:
        vendor_col = resolve_column(table, "vendor")
        for index, row in enumerate(table.rows):
            if not row.get(vendor_col):
                continue
            total += 1
            if len(evidence_ids) < _SEARCH_LIMIT:
                evidence_ids.append(ctx.cite(table.evidence(index, vendor_col)))
    return ToolResult(
        tool_name="match_invoice_order_receipt",
        structured_result={"vendor_id": None, "matched": total > 0, "match_count": total},
        evidence_ids=_dedupe(evidence_ids),
    )


# --------------------------------------------------------------------------------------
# cluster_payments
# --------------------------------------------------------------------------------------


class ClusterPaymentsArgs(_StrictModel):
    threshold: Decimal | None = None

    _no_float = field_validator("threshold", mode="before")(_reject_float)


def tool_cluster_payments(ctx: AgentContext, args: ClusterPaymentsArgs) -> ToolResult:
    control = _CONTROLS_BY_ID["split_payment"]
    required = {"amount", "document_no", "posting_date", "posting_kind"}
    if not find_tables(ctx.dossier, required):
        return ToolResult(
            tool_name="cluster_payments",
            ok=False,
            errors=("no payment table found with amount/document/date/posting-kind columns",),
        )

    params = dict(ctx.params)
    if args.threshold is not None:
        params["approval_threshold"] = str(args.threshold)
    findings = _run_control(control, ctx.dossier, params)

    evidence_ids: list[str] = []
    groups = []
    calc_inputs: list[ToolCalculationInput] = []
    for finding in findings:
        evidence_ids.extend(_finding_evidence_ids(ctx, finding))
        groups.append(_finding_summary(finding))
        if finding.calculation.inputs:
            first = finding.calculation.inputs[0]
            calc_inputs.append(
                ToolCalculationInput(
                    label=finding.subject,
                    value=finding.exposure,
                    evidence_id=ctx.cite(first.evidence),
                )
            )

    total = sum((c.value for c in calc_inputs), Decimal("0.00"))
    return ToolResult(
        tool_name="cluster_payments",
        structured_result={"threshold": str(args.threshold) if args.threshold is not None else None,
                            "groups": groups},
        evidence_ids=_dedupe(evidence_ids),
        calculation=ToolCalculation(
            expression="SUM(group exposure)",
            inputs=tuple(calc_inputs),
            result=total.quantize(Decimal("0.01")),
        ),
    )


# --------------------------------------------------------------------------------------
# inspect_asset_additions
# --------------------------------------------------------------------------------------


class InspectAssetAdditionsArgs(_StrictModel):
    pass


def tool_inspect_asset_additions(ctx: AgentContext, args: InspectAssetAdditionsArgs) -> ToolResult:
    control = _CONTROLS_BY_ID["capitalisation"]
    required = {"asset_no", "amount", "posting_kind", "asset_group"}
    if not find_tables(ctx.dossier, required):
        return ToolResult(
            tool_name="inspect_asset_additions",
            ok=False,
            errors=("no asset-additions table found with asset/amount/posting-kind/group columns",),
        )
    findings = _run_control(control, ctx.dossier, ctx.params)
    if not findings:
        return ToolResult(tool_name="inspect_asset_additions", structured_result={"findings": []})

    finding = findings[0]
    return ToolResult(
        tool_name="inspect_asset_additions",
        structured_result=_finding_summary(finding),
        evidence_ids=_finding_evidence_ids(ctx, finding),
        calculation=_convert_calculation(ctx, finding.calculation),
    )


# --------------------------------------------------------------------------------------
# test_period_cutoff
# --------------------------------------------------------------------------------------


class TestPeriodCutoffArgs(_StrictModel):
    fiscal_year_end: str | None = None


def tool_test_period_cutoff(ctx: AgentContext, args: TestPeriodCutoffArgs) -> ToolResult:
    control = _CONTROLS_BY_ID["cutoff"]
    if args.fiscal_year_end is not None and as_date(args.fiscal_year_end) is None:
        return ToolResult(
            tool_name="test_period_cutoff",
            ok=False,
            errors=(f"fiscal_year_end {args.fiscal_year_end!r} is not a parseable date",),
        )
    required = {"invoice_date", "service_date", "amount"}
    if not find_tables(ctx.dossier, required):
        return ToolResult(
            tool_name="test_period_cutoff",
            ok=False,
            errors=("no table found with distinct invoice/service dates and amounts",),
        )
    params = dict(ctx.params)
    if args.fiscal_year_end is not None:
        params["fiscal_year_end"] = args.fiscal_year_end
    findings = _run_control(control, ctx.dossier, params)
    if not findings:
        return ToolResult(tool_name="test_period_cutoff", structured_result={"findings": []})

    finding = findings[0]
    return ToolResult(
        tool_name="test_period_cutoff",
        structured_result=_finding_summary(finding),
        evidence_ids=_finding_evidence_ids(ctx, finding),
        calculation=_convert_calculation(ctx, finding.calculation),
    )


# --------------------------------------------------------------------------------------
# find_reversal / find_credit_note
# --------------------------------------------------------------------------------------


class FindReversalArgs(_StrictModel):
    reference: str | None = None


def _search_posting_text(
    ctx: AgentContext, words: tuple[str, ...], reference: str | None
) -> tuple[bool, list[dict], list[str]] | None:
    tables = find_tables(ctx.dossier, {"posting_text"})
    if not tables:
        return None
    matches: list[dict] = []
    evidence_ids: list[str] = []
    for table in tables:
        txt = resolve_column(table, "posting_text")
        doc = resolve_column(table, "document_no")
        ref = resolve_column(table, "payment_reference")
        for index, row in enumerate(table.rows):
            text = row.get(txt, "").lower()
            if not any(w in text for w in words):
                continue
            if reference is not None:
                doc_value = row.get(doc, "") if doc else ""
                ref_value = row.get(ref, "") if ref else ""
                if reference not in (doc_value, ref_value) and reference.lower() not in text:
                    continue
            evidence_id = ctx.cite(table.evidence(index, txt))
            evidence_ids.append(evidence_id)
            matches.append(
                {
                    "source_path": table.source_path,
                    "row": table.row_numbers[index],
                    "document_no": row.get(doc, "") if doc else "",
                    "text": row.get(txt, ""),
                    "evidence_id": evidence_id,
                }
            )
    return bool(matches), matches, evidence_ids


def tool_find_reversal(ctx: AgentContext, args: FindReversalArgs) -> ToolResult:
    result = _search_posting_text(ctx, _REVERSAL_WORDS, args.reference)
    if result is None:
        return ToolResult(
            tool_name="find_reversal", ok=False,
            errors=("no table with a posting-text column found in the dossier",),
        )
    found, matches, evidence_ids = result
    return ToolResult(
        tool_name="find_reversal",
        structured_result={"reference": args.reference, "found": found, "matches": matches},
        evidence_ids=_dedupe(evidence_ids),
    )


class FindCreditNoteArgs(_StrictModel):
    reference: str | None = None


def tool_find_credit_note(ctx: AgentContext, args: FindCreditNoteArgs) -> ToolResult:
    result = _search_posting_text(ctx, _CREDIT_NOTE_WORDS, args.reference)
    if result is None:
        return ToolResult(
            tool_name="find_credit_note", ok=False,
            errors=("no table with a posting-text column found in the dossier",),
        )
    found, matches, evidence_ids = result
    return ToolResult(
        tool_name="find_credit_note",
        structured_result={"reference": args.reference, "found": found, "matches": matches},
        evidence_ids=_dedupe(evidence_ids),
    )


# --------------------------------------------------------------------------------------
# find_independent_approval
# --------------------------------------------------------------------------------------


class FindIndependentApprovalArgs(_StrictModel):
    vendor_id: str = Field(min_length=1)


def tool_find_independent_approval(
    ctx: AgentContext, args: FindIndependentApprovalArgs
) -> ToolResult:
    all_findings = _run_control(_VENDOR_SOD, ctx.dossier, ctx.params)
    findings = [f for f in all_findings if f.subject == args.vendor_id]
    if not findings:
        return ToolResult(
            tool_name="find_independent_approval",
            ok=False,
            errors=(f"no vendor-creation event found for vendor {args.vendor_id!r}",),
        )
    finding = findings[0]
    counter_test = next(
        (c for c in finding.counter_tests if c.name == "independent_approval"), None
    )
    evidence_ids = _cite_all(ctx, counter_test.evidence) if counter_test else ()
    return ToolResult(
        tool_name="find_independent_approval",
        structured_result={
            "vendor_id": args.vendor_id,
            "independent_approval": bool(counter_test and counter_test.outcome == "present"),
            "detail": counter_test.detail if counter_test else "",
        },
        evidence_ids=evidence_ids,
    )


# --------------------------------------------------------------------------------------
# find_contract_or_service_evidence
# --------------------------------------------------------------------------------------


class FindContractOrServiceEvidenceArgs(_StrictModel):
    vendor_id: str = Field(min_length=1)


def tool_find_contract_or_service_evidence(
    ctx: AgentContext, args: FindContractOrServiceEvidenceArgs
) -> ToolResult:
    goods_receipt_tables = find_tables(ctx.dossier, {"vendor", "goods_receipt_no"})
    narrative_tables = [
        t for t in ctx.dossier.tables if "paragraph" in t.columns or "text" in t.columns
    ]
    if not goods_receipt_tables and not narrative_tables:
        return ToolResult(
            tool_name="find_contract_or_service_evidence",
            ok=False,
            errors=("dossier has neither a goods-receipt table nor any narrative document",),
        )

    evidence_ids: list[str] = []
    goods_refs = _VENDOR_SOD._goods_receipts(ctx.dossier, args.vendor_id)  # noqa: SLF001
    evidence_ids.extend(_cite_all(ctx, tuple(goods_refs)))

    contract_hits: list[dict] = []
    vendor_lower = args.vendor_id.lower()
    for table in narrative_tables:
        text_col = "paragraph" if "paragraph" in table.columns else "text"
        for index, row in enumerate(table.rows):
            text = row[text_col].lower()
            if vendor_lower in text and any(w in text for w in _CONTRACT_WORDS):
                evidence_id = ctx.cite(table.evidence(index, text_col))
                evidence_ids.append(evidence_id)
                contract_hits.append({"source_path": table.source_path, "evidence_id": evidence_id})

    return ToolResult(
        tool_name="find_contract_or_service_evidence",
        structured_result={
            "vendor_id": args.vendor_id,
            "goods_receipt_count": len(goods_refs),
            "contract_mentions": contract_hits,
            "found": bool(goods_refs) or bool(contract_hits),
        },
        evidence_ids=_dedupe(evidence_ids),
    )


# --------------------------------------------------------------------------------------
# compare_peer_vendors
# --------------------------------------------------------------------------------------


class ComparePeerVendorsArgs(_StrictModel):
    vendor_id: str = Field(min_length=1)


def tool_compare_peer_vendors(ctx: AgentContext, args: ComparePeerVendorsArgs) -> ToolResult:
    table, invoice_inputs, exposure, sql = _VENDOR_SOD._vendor_exposure(ctx.dossier, args.vendor_id)  # noqa: SLF001
    if table is None:
        return ToolResult(
            tool_name="compare_peer_vendors",
            ok=False,
            errors=(f"vendor {args.vendor_id!r} not found in any posting table",),
        )
    acc = resolve_column(table, "account")
    peer_ids = sorted({r[acc] for r in table.rows if r[acc] != args.vendor_id})[:_PEER_SCAN_LIMIT]

    peer_exposures: list[Decimal] = []
    for peer_id in peer_ids:
        _, _, peer_exposure, _ = _VENDOR_SOD._vendor_exposure(ctx.dossier, peer_id)  # noqa: SLF001
        if peer_exposure > 0:
            peer_exposures.append(peer_exposure)

    peer_exposures.sort()
    peer_count = len(peer_exposures)
    if peer_count:
        mid = peer_count // 2
        median = (
            peer_exposures[mid]
            if peer_count % 2 == 1
            else (peer_exposures[mid - 1] + peer_exposures[mid]) / 2
        )
    else:
        median = Decimal("0.00")
    rank = 1 + sum(1 for e in peer_exposures if e > exposure)

    evidence_ids = tuple(ctx.cite(i.evidence) for i in invoice_inputs)
    calc_inputs = tuple(
        ToolCalculationInput(label=i.label, value=i.value, evidence_id=eid)
        for i, eid in zip(invoice_inputs, evidence_ids, strict=True)
    )
    return ToolResult(
        tool_name="compare_peer_vendors",
        structured_result={
            "vendor_id": args.vendor_id,
            "vendor_exposure": str(exposure),
            "peer_count": peer_count,
            "peer_median_exposure": str(median),
            "rank": rank,
        },
        evidence_ids=_dedupe(list(evidence_ids)),
        calculation=ToolCalculation(
            expression="SUM(ABS(amount)) WHERE account = vendor_id AND amount < 0",
            inputs=calc_inputs,
            result=exposure,
            sql=sql,
        ),
    )


# --------------------------------------------------------------------------------------
# trace_amount_to_sources
# --------------------------------------------------------------------------------------


class TraceAmountToSourcesArgs(_StrictModel):
    amount: Decimal

    _no_float = field_validator("amount", mode="before")(_reject_float)


def tool_trace_amount_to_sources(ctx: AgentContext, args: TraceAmountToSourcesArgs) -> ToolResult:
    target = args.amount.quantize(Decimal("0.01"))
    amount_tables = [t for t in ctx.dossier.tables if resolve_column(t, "amount") is not None]
    if not amount_tables:
        return ToolResult(
            tool_name="trace_amount_to_sources",
            ok=False,
            errors=("no table in the dossier resolves an amount column",),
        )

    matches: list[dict] = []
    evidence_ids: list[str] = []
    for table in amount_tables:
        amt = resolve_column(table, "amount")
        txt = resolve_column(table, "posting_text")
        for index, row in enumerate(table.rows):
            value = money(row[amt])
            if value is None or value.quantize(Decimal("0.01")) != target:
                continue
            evidence_id = ctx.cite(table.evidence(index, amt, normalized=str(value)))
            evidence_ids.append(evidence_id)
            matches.append(
                {
                    "source_path": table.source_path,
                    "row": table.row_numbers[index],
                    "text": row.get(txt, "") if txt else "",
                    "evidence_id": evidence_id,
                }
            )
    return ToolResult(
        tool_name="trace_amount_to_sources",
        structured_result={"amount": str(target), "matches": matches},
        evidence_ids=_dedupe(evidence_ids),
    )


# --------------------------------------------------------------------------------------
# submit_case_to_admission
# --------------------------------------------------------------------------------------


_CATEGORY_CHOICES = tuple(_CONTROLS_BY_ID)


class SubmitCaseToAdmissionArgs(_StrictModel):
    subject: str = Field(min_length=1)
    category: str

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in _CATEGORY_CHOICES:
            raise ValueError(f"category must be one of {_CATEGORY_CHOICES}")
        return value


def tool_submit_case_to_admission(ctx: AgentContext, args: SubmitCaseToAdmissionArgs) -> ToolResult:
    control = _CONTROLS_BY_ID[args.category]
    findings = _run_control(control, ctx.dossier, ctx.params)
    finding = next((f for f in findings if f.subject == args.subject), None)
    if finding is None:
        return ToolResult(
            tool_name="submit_case_to_admission",
            ok=False,
            errors=(
                f"no {args.category} finding produced for subject {args.subject!r}; "
                "run the matching investigation tool first",
            ),
        )
    admission = admit(finding)
    return ToolResult(
        tool_name="submit_case_to_admission",
        structured_result=_finding_summary(finding, admission),
        evidence_ids=_finding_evidence_ids(ctx, finding),
        calculation=_convert_calculation(ctx, finding.calculation),
    )


__all__ = [
    "tool_inventory_dossier",
    "tool_search_evidence",
    "tool_open_evidence",
    "tool_get_vendor_history",
    "tool_check_vendor_creation_and_approval",
    "tool_check_user_permissions",
    "tool_reconcile_vendor_invoices_and_payments",
    "tool_match_invoice_order_receipt",
    "tool_cluster_payments",
    "tool_inspect_asset_additions",
    "tool_test_period_cutoff",
    "tool_find_reversal",
    "tool_find_credit_note",
    "tool_find_independent_approval",
    "tool_find_contract_or_service_evidence",
    "tool_compare_peer_vendors",
    "tool_trace_amount_to_sources",
    "tool_submit_case_to_admission",
]
