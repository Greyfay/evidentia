"""The allow-list enforcement boundary between the LLM planner and the deterministic tools.

The planner never calls a Python function directly. It names a tool and supplies raw
arguments; ``run_tool`` is the only path in, and it (a) rejects any name not in ``TOOLS``,
(b) validates the raw arguments against that tool's strict pydantic schema, and (c) only
then invokes the underlying function. Both rejection paths return an ``ok=False``
``ToolResult`` rather than raising, so a malformed or hallucinated tool call can never crash
the agent loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from audit_compiler.agent import cognee_tools, tools
from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.models import ToolResult


class _CogneeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindRelatedEntitiesArgs(_CogneeArgs):
    entity_id: str
    hops: int = 2


class FindOtherVendorsConnectedToUserArgs(_CogneeArgs):
    user_id: str
    hops: int = 3


def _cognee_adapter(
    fn: Callable[[AgentContext, dict], ToolResult],
) -> Callable[[AgentContext, BaseModel], ToolResult]:
    """Bridge a Cognee tool's ``(ctx, dict)`` shape onto the allow-list's ``(ctx, model)``
    contract: validate via the pydantic model, then hand the tool a plain dict."""

    def _run(ctx: AgentContext, args: BaseModel) -> ToolResult:
        return fn(ctx, args.model_dump())

    return _run


@dataclass(frozen=True)
class ToolSpec:
    name: str
    func: Callable[[AgentContext, BaseModel], ToolResult]
    input_model: type[BaseModel]
    description: str


TOOLS: dict[str, ToolSpec] = {
    "inventory_dossier": ToolSpec(
        name="inventory_dossier",
        func=tools.tool_inventory_dossier,
        input_model=tools.InventoryDossierArgs,
        description="List every parsed source table in the dossier with its columns and row count.",
    ),
    "search_evidence": ToolSpec(
        name="search_evidence",
        func=tools.tool_search_evidence,
        input_model=tools.SearchEvidenceArgs,
        description="Full-text search across every cell/paragraph/passage in the dossier, "
                    "optionally filtered by source type.",
    ),
    "open_evidence": ToolSpec(
        name="open_evidence",
        func=tools.tool_open_evidence,
        input_model=tools.OpenEvidenceArgs,
        description="Resolve a previously cited evidence id back to its full source pointer.",
    ),
    "get_vendor_history": ToolSpec(
        name="get_vendor_history",
        func=tools.tool_get_vendor_history,
        input_model=tools.GetVendorHistoryArgs,
        description="List every posting booked against a vendor account, with a net total.",
    ),
    "check_vendor_creation_and_approval": ToolSpec(
        name="check_vendor_creation_and_approval",
        func=tools.tool_check_vendor_creation_and_approval,
        input_model=tools.CheckVendorCreationAndApprovalArgs,
        description="Check whether a newly created vendor's master record was self-approved "
                    "(creator == approver) using the vendor-SoD control.",
    ),
    "check_user_permissions": ToolSpec(
        name="check_user_permissions",
        func=tools.tool_check_user_permissions,
        input_model=tools.CheckUserPermissionsArgs,
        description="Check whether a user holds a toxic create+post+pay rights combination.",
    ),
    "reconcile_vendor_invoices_and_payments": ToolSpec(
        name="reconcile_vendor_invoices_and_payments",
        func=tools.tool_reconcile_vendor_invoices_and_payments,
        input_model=tools.ReconcileVendorInvoicesAndPaymentsArgs,
        description="Sum a vendor's invoice legs and payment legs separately and report the "
                    "unreconciled difference.",
    ),
    "match_invoice_order_receipt": ToolSpec(
        name="match_invoice_order_receipt",
        func=tools.tool_match_invoice_order_receipt,
        input_model=tools.MatchInvoiceOrderReceiptArgs,
        description="Match goods-receipt records to a vendor (or count matches dossier-wide).",
    ),
    "cluster_payments": ToolSpec(
        name="cluster_payments",
        func=tools.tool_cluster_payments,
        input_model=tools.ClusterPaymentsArgs,
        description="Find same-day, same-reference payments that individually fall below the "
                    "approval threshold but aggregate above it, using the split-payment control.",
    ),
    "inspect_asset_additions": ToolSpec(
        name="inspect_asset_additions",
        func=tools.tool_inspect_asset_additions,
        input_model=tools.InspectAssetAdditionsArgs,
        description="Find asset additions with repair/maintenance vocabulary capitalised onto "
                    "balance-sheet accounts, using the capitalisation control.",
    ),
    "test_period_cutoff": ToolSpec(
        name="test_period_cutoff",
        func=tools.tool_test_period_cutoff,
        input_model=tools.TestPeriodCutoffArgs,
        description="Find invoices dated after the balance-sheet date for services delivered "
                    "before it, using the cut-off control.",
    ),
    "find_reversal": ToolSpec(
        name="find_reversal",
        func=tools.tool_find_reversal,
        input_model=tools.FindReversalArgs,
        description="Search posting text for a reversal/storno entry, optionally tied to a "
                    "specific document or payment reference.",
    ),
    "find_credit_note": ToolSpec(
        name="find_credit_note",
        func=tools.tool_find_credit_note,
        input_model=tools.FindCreditNoteArgs,
        description="Search posting text for a credit note / Gutschrift, optionally tied to a "
                    "specific document or payment reference.",
    ),
    "find_independent_approval": ToolSpec(
        name="find_independent_approval",
        func=tools.tool_find_independent_approval,
        input_model=tools.FindIndependentApprovalArgs,
        description="Check whether a vendor's creation event carries an independent (four-eyes) "
                    "approval.",
    ),
    "find_contract_or_service_evidence": ToolSpec(
        name="find_contract_or_service_evidence",
        func=tools.tool_find_contract_or_service_evidence,
        input_model=tools.FindContractOrServiceEvidenceArgs,
        description="Search for goods-receipt records and narrative contract/service mentions "
                    "for a vendor.",
    ),
    "compare_peer_vendors": ToolSpec(
        name="compare_peer_vendors",
        func=tools.tool_compare_peer_vendors,
        input_model=tools.ComparePeerVendorsArgs,
        description="Compare a vendor's exposure against the median and rank of its peers in "
                    "the same posting table.",
    ),
    "trace_amount_to_sources": ToolSpec(
        name="trace_amount_to_sources",
        func=tools.tool_trace_amount_to_sources,
        input_model=tools.TraceAmountToSourcesArgs,
        description="Find every cell across the dossier whose amount matches the given value.",
    ),
    "submit_case_to_admission": ToolSpec(
        name="submit_case_to_admission",
        func=tools.tool_submit_case_to_admission,
        input_model=tools.SubmitCaseToAdmissionArgs,
        description="Run the matching control for a subject/category, then pass its finding "
                    "through the admission gate and return the published verdict.",
    ),
    "find_related_entities": ToolSpec(
        name="find_related_entities",
        func=_cognee_adapter(cognee_tools.find_related_entities),
        input_model=FindRelatedEntitiesArgs,
        description="Explore the Cognee-backed investigation memory graph: return the "
                    "entities, events and evidence related to an entity id, multi-hop. "
                    "Relationship context only — never a monetary assertion.",
    ),
    "find_other_vendors_connected_to_user": ToolSpec(
        name="find_other_vendors_connected_to_user",
        func=_cognee_adapter(cognee_tools.find_other_vendors_connected_to_user),
        input_model=FindOtherVendorsConnectedToUserArgs,
        description="Explore the Cognee-backed investigation memory graph: return other "
                    "vendor entities reachable from a user id, multi-hop.",
    ),
}


def get_tool(name: str) -> ToolSpec:
    """Return the allow-listed tool spec for ``name``, or raise ``KeyError``."""

    try:
        return TOOLS[name]
    except KeyError:
        raise KeyError(f"unknown tool: {name!r}; allow-listed tools: {sorted(TOOLS)}") from None


def list_tools() -> list[dict[str, Any]]:
    """Return the allow-list as planner-facing metadata: name, description, JSON schema."""

    return [
        {
            "name": spec.name,
            "description": spec.description,
            "schema": spec.input_model.model_json_schema(),
        }
        for spec in TOOLS.values()
    ]


def run_tool(ctx: AgentContext, name: str, raw_args: dict[str, Any] | None = None) -> ToolResult:
    """Validate ``name`` against the allow-list and ``raw_args`` against its schema, then run it.

    Never raises: an unknown tool name or a schema violation produces an ``ok=False``
    ``ToolResult`` instead of propagating an exception to the planner loop.
    """

    raw_args = raw_args or {}
    try:
        spec = get_tool(name)
    except KeyError as exc:
        return ToolResult(tool_name=name, ok=False, errors=(str(exc),))

    try:
        args = spec.input_model.model_validate(raw_args)
    except ValidationError as exc:
        return ToolResult(tool_name=name, ok=False, errors=(f"invalid arguments: {exc}",))

    try:
        return spec.func(ctx, args)
    except Exception as exc:  # noqa: BLE001 - the allow-list boundary must never raise outward
        return ToolResult(tool_name=name, ok=False, errors=(f"{type(exc).__name__}: {exc}",))
