"""Tests for the deterministic, allow-listed agent tool layer.

Structural tests (allow-list enforcement, schema validation, no-fabrication, determinism)
run unconditionally. The behavioural tests at the bottom exercise the tools against the
sample dossier and are skipped (via the shared ``sample_dossier`` fixture) unless
``EVIDENTIA_SAMPLE_DOSSIER`` is set.
"""

from __future__ import annotations

from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.tool_registry import get_tool, list_tools, run_tool


def _ctx(sample_dossier) -> AgentContext:  # noqa: ANN001
    return AgentContext.from_dossier_path(sample_dossier)


# --------------------------------------------------------------------------------------
# Allow-list enforcement
# --------------------------------------------------------------------------------------


def test_get_tool_rejects_unknown_name():
    try:
        get_tool("delete_all_files")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for an unknown tool name")


def test_run_tool_rejects_unlisted_tool_name(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(ctx, "not_a_real_tool", {})
    assert result.ok is False
    assert result.errors
    assert "unknown tool" in result.errors[0]


def test_run_tool_rejects_malformed_args_without_raising(sample_dossier):
    ctx = _ctx(sample_dossier)
    # search_evidence requires a non-empty "query" string; give it an extra unknown field
    # and a missing required field so schema validation must fail (not raise).
    result = run_tool(ctx, "search_evidence", {"not_a_field": 1})
    assert result.ok is False
    assert result.errors
    assert result.tool_name == "search_evidence"


def test_run_tool_rejects_extra_fields(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(ctx, "open_evidence", {"evidence_id": "ev_x", "surprise": True})
    assert result.ok is False


def test_run_tool_rejects_float_money_args(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(ctx, "trace_amount_to_sources", {"amount": 123.45})
    assert result.ok is False


def test_list_tools_covers_the_full_allow_list():
    names = {t["name"] for t in list_tools()}
    expected = {
        "inventory_dossier", "search_evidence", "open_evidence", "get_vendor_history",
        "check_vendor_creation_and_approval", "check_user_permissions",
        "reconcile_vendor_invoices_and_payments", "match_invoice_order_receipt",
        "cluster_payments", "inspect_asset_additions", "test_period_cutoff",
        "find_reversal", "find_credit_note", "find_independent_approval",
        "find_contract_or_service_evidence", "compare_peer_vendors",
        "trace_amount_to_sources", "submit_case_to_admission",
    }
    assert expected <= names


# --------------------------------------------------------------------------------------
# No fabrication
# --------------------------------------------------------------------------------------


def test_open_evidence_rejects_unknown_id(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(ctx, "open_evidence", {"evidence_id": "ev_0000000000000000"})
    assert result.ok is False
    assert "unknown evidence id" in result.errors[0]


def test_inventory_dossier_never_fails_and_cites_nothing_fabricated(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(ctx, "inventory_dossier", {})
    assert result.ok is True
    assert result.structured_result["tables"]
    for evidence_id in result.evidence_ids:
        assert ctx.registry.contains(evidence_id)


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------


def test_search_evidence_is_deterministic_across_calls(sample_dossier):
    ctx = _ctx(sample_dossier)
    first = run_tool(ctx, "search_evidence", {"query": "a"})
    second = run_tool(ctx, "search_evidence", {"query": "a"})
    assert first.structured_result == second.structured_result
    assert first.evidence_ids == second.evidence_ids
    for evidence_id in first.evidence_ids:
        assert ctx.registry.contains(evidence_id)


def test_inventory_dossier_is_deterministic_on_fresh_contexts(sample_dossier):
    first = run_tool(_ctx(sample_dossier), "inventory_dossier", {})
    second = run_tool(_ctx(sample_dossier), "inventory_dossier", {})
    assert first.structured_result == second.structured_result


# --------------------------------------------------------------------------------------
# Sample-dossier behavioural tests
# --------------------------------------------------------------------------------------


def test_check_vendor_creation_and_approval_finds_self_approved_vendor(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(ctx, "check_vendor_creation_and_approval", {})
    assert result.ok is True
    vendors = result.structured_result["vendors"]
    self_approved = [v for v in vendors if v["self_approved"]]
    assert self_approved, "expected at least one self-approved vendor in the sample dossier"
    assert result.evidence_ids
    for evidence_id in result.evidence_ids:
        assert ctx.registry.contains(evidence_id)


def test_cluster_payments_finds_the_split_group(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(ctx, "cluster_payments", {})
    assert result.ok is True
    groups = result.structured_result["groups"]
    assert groups, "expected the split-payment control to surface at least one group"
    for evidence_id in result.evidence_ids:
        assert ctx.registry.contains(evidence_id)


def test_submit_case_to_admission_confirms_a_supported_vendor_subject(sample_dossier):
    ctx = _ctx(sample_dossier)
    detection = run_tool(ctx, "check_vendor_creation_and_approval", {})
    self_approved = [v for v in detection.structured_result["vendors"] if v["self_approved"]]
    assert self_approved
    vendor_id = self_approved[0]["vendor_id"]

    result = run_tool(
        ctx, "submit_case_to_admission", {"subject": vendor_id, "category": "vendor_sod"}
    )
    assert result.ok is True
    assert result.structured_result["verdict"] == "CONFIRMED"
    assert result.evidence_ids
    for evidence_id in result.evidence_ids:
        assert ctx.registry.contains(evidence_id)


def test_submit_case_to_admission_rejects_unsupported_category(sample_dossier):
    ctx = _ctx(sample_dossier)
    result = run_tool(
        ctx, "submit_case_to_admission", {"subject": "x", "category": "not_a_control"}
    )
    assert result.ok is False
