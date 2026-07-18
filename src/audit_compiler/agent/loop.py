"""The bounded investigation loop.

observe -> hypothesise -> rank -> plan -> run ONE tool -> observe -> challenge -> decide.

The planner (OpenAI or deterministic) chooses hypotheses and the next single tool; the loop
validates every tool name against the allow-list and every argument against its schema, runs
the deterministic tool, records the observation on a replayable timeline, and updates the
hypothesis. Verdicts come only from ``submit_case_to_admission`` -> the existing admission
gate — never from the LLM. Hard limits (steps, tool calls, wall-clock, repeat detection)
guarantee termination.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from audit_compiler.agent import tool_registry
from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.models import (
    ActionStatus,
    Hypothesis,
    HypothesisCategory,
    HypothesisStatus,
    Investigation,
    InvestigationStatus,
    PlannedAction,
    ToolObservation,
    VerdictRecommendation,
)
from audit_compiler.agent.planner import Planner, get_planner
from audit_compiler.agent.summary import build_dossier_summary
from audit_compiler.controls.registry import default_controls

_TERMINAL_HYP = {
    HypothesisStatus.SUBMITTED,
    HypothesisStatus.DISMISSED,
    HypothesisStatus.REFUTED,
    HypothesisStatus.INSUFFICIENT_EVIDENCE,
    HypothesisStatus.AWAITING_AUDITOR,
}
_TERMINAL_INV = {
    InvestigationStatus.COMPLETED,
    InvestigationStatus.STOPPED,
    InvestigationStatus.DISMISSED,
    InvestigationStatus.SUBMITTED,
}
_VERDICT_TO_STATUS = {
    "CONFIRMED": (HypothesisStatus.SUBMITTED, VerdictRecommendation.CONFIRM),
    "DISMISSED": (HypothesisStatus.DISMISSED, VerdictRecommendation.DISMISS),
    "HUMAN_REVIEW": (HypothesisStatus.AWAITING_AUDITOR, VerdictRecommendation.HUMAN_REVIEW),
    "REJECTED": (HypothesisStatus.INSUFFICIENT_EVIDENCE, VerdictRecommendation.REJECT),
}


@dataclass
class InvestigationLimits:
    max_hypotheses: int = 5
    max_steps: int = 16
    max_tool_calls: int = 28
    max_seconds: float = 120.0


def _now() -> datetime:
    return datetime.now(UTC)


def _event(inv: Investigation, kind: str, **data: object) -> None:
    inv.timeline = [*inv.timeline, {"kind": kind, "at": _now().isoformat(), **data}]


def start_investigation(
    ctx: AgentContext,
    *,
    engagement_id: str,
    objective: str,
    planner: Planner | None = None,
    limits: InvestigationLimits | None = None,
) -> Investigation:
    """Observe the dossier and propose ranked, validated hypotheses."""

    planner = planner or get_planner()
    limits = limits or InvestigationLimits()
    control_ids = [c.id for c in default_controls()]
    summary = build_dossier_summary(ctx, control_ids=control_ids)

    drafts = planner.propose_hypotheses(summary)
    hypotheses: list[Hypothesis] = [
        Hypothesis(claim=draft.claim, category=draft.category, priority=draft.priority)
        for draft in drafts[: limits.max_hypotheses]
    ]
    hypotheses.sort(key=lambda h: h.priority, reverse=True)

    now = _now()
    inv = Investigation(
        engagement_id=engagement_id,
        objective=objective,
        status=InvestigationStatus.ACTIVE if hypotheses else InvestigationStatus.STOPPED,
        hypotheses=hypotheses,
        created_at=now,
        updated_at=now,
    )
    _event(inv, "investigation_started", objective=objective, planner=planner.name,
           hypotheses=len(hypotheses))
    for hyp in hypotheses:
        _event(inv, "hypothesis_created", hypothesis_id=str(hyp.hypothesis_id),
               category=hyp.category.value, priority=hyp.priority, claim=hyp.claim)
    return inv


def _active_hypothesis(inv: Investigation) -> Hypothesis | None:
    candidates = [h for h in inv.hypotheses if h.status not in _TERMINAL_HYP]
    if not candidates:
        return None
    return max(candidates, key=lambda h: h.priority)


def _completed_tools(inv: Investigation, hyp: Hypothesis) -> list[str]:
    return [
        e["tool_name"]
        for e in inv.timeline
        if e.get("kind") == "tool_result" and e.get("hypothesis_id") == str(hyp.hypothesis_id)
    ]


def run_next_step(
    inv: Investigation,
    ctx: AgentContext,
    *,
    planner: Planner | None = None,
    limits: InvestigationLimits | None = None,
    started_at: float | None = None,
) -> Investigation:
    """Advance the active hypothesis by exactly one validated, executed tool call."""

    planner = planner or get_planner()
    limits = limits or InvestigationLimits()
    if inv.status in _TERMINAL_INV:
        return inv

    tool_events = [e for e in inv.timeline if e.get("kind") == "tool_result"]
    if len(tool_events) >= limits.max_tool_calls:
        inv.status = InvestigationStatus.STOPPED
        _event(inv, "stopped", reason="tool-call limit reached")
        return inv
    if started_at is not None and (time.monotonic() - started_at) > limits.max_seconds:
        inv.status = InvestigationStatus.STOPPED
        _event(inv, "stopped", reason="time budget exceeded")
        return inv

    hyp = _active_hypothesis(inv)
    if hyp is None:
        inv.status = InvestigationStatus.COMPLETED
        _event(inv, "completed", reason="all hypotheses resolved")
        return inv
    hyp.status = HypothesisStatus.ACTIVE

    available = [t["name"] for t in tool_registry.list_tools()]
    completed = _completed_tools(inv, hyp)
    draft = planner.next_action(inv.objective, hyp.model_dump(mode="json"), completed,
                                available, build_dossier_summary(ctx, control_ids=available))

    tool_name = draft.tool_name
    try:
        args = json.loads(draft.arguments_json) if draft.arguments_json else {}
        if not isinstance(args, dict):
            args = {}
    except json.JSONDecodeError:
        args = {}
    args = _normalise_args(tool_name, args)
    # Only target a subject the loop actually discovered (or an auditor pre-seeded); never a
    # model guess. Vendor discovery runs generically until a real subject is captured.
    if hyp.subject and "vendor_id" not in args and tool_name != "submit_case_to_admission":
        args["vendor_id"] = hyp.subject
    if tool_name == "submit_case_to_admission":
        args["subject"] = hyp.subject
        # The tool keys on the deterministic control id, not the hypothesis category label.
        args["category"] = _category_control_id(hyp.category)

    _event(inv, "tool_selected", hypothesis_id=str(hyp.hypothesis_id), tool_name=tool_name,
           reason=draft.reason, arguments=args)

    if tool_name not in available:
        _event(inv, "tool_rejected", hypothesis_id=str(hyp.hypothesis_id), tool_name=tool_name,
               reason="not in allow-list")
        hyp.status = HypothesisStatus.INSUFFICIENT_EVIDENCE
        return _touch(inv)

    # Repeat detection: the same tool already ran for this hypothesis -> force closure.
    if tool_name in completed and tool_name != "submit_case_to_admission":
        tool_name, args = "submit_case_to_admission", {
            "subject": hyp.subject, "category": _category_control_id(hyp.category)}
        if tool_name not in available:
            hyp.status = HypothesisStatus.INSUFFICIENT_EVIDENCE
            _event(inv, "stopped", hypothesis_id=str(hyp.hypothesis_id), reason="repeat detected")
            return _touch(inv)

    action = PlannedAction(tool_name=tool_name, reason=draft.reason, arguments=args,
                           status=ActionStatus.RUNNING)
    result = tool_registry.run_tool(ctx, tool_name, args)
    action.status = ActionStatus.COMPLETED if result.ok else ActionStatus.FAILED

    observation = ToolObservation(
        action_id=action.action_id, tool_name=tool_name,
        structured_result=result.structured_result, evidence_ids=result.evidence_ids,
        calculation=result.calculation, errors=result.errors, timestamp=_now())
    inv.completed_actions = [*inv.completed_actions, observation]
    for evidence_id in result.evidence_ids:
        if evidence_id not in inv.evidence_ids:
            inv.evidence_ids.append(evidence_id)
        if evidence_id not in hyp.supporting_evidence_ids:
            hyp.supporting_evidence_ids.append(evidence_id)
    # Capture the entity this tool centred on so later steps (esp. submit) can target it.
    if not hyp.subject:
        hyp.subject = _extract_subject(result.structured_result)

    _event(inv, "tool_result", hypothesis_id=str(hyp.hypothesis_id), tool_name=tool_name,
           ok=result.ok, evidence_count=len(result.evidence_ids),
           result=_compact(result.structured_result), errors=list(result.errors))

    if tool_name in _REFUTER_TOOLS:
        _event(inv, "counter_evidence", hypothesis_id=str(hyp.hypothesis_id),
               tool_name=tool_name, outcome=_compact(result.structured_result))

    if tool_name == "submit_case_to_admission":
        verdict = str(result.structured_result.get("verdict", "REJECTED"))
        status, recommendation = _VERDICT_TO_STATUS.get(
            verdict, (HypothesisStatus.INSUFFICIENT_EVIDENCE, VerdictRecommendation.REJECT))
        hyp.status = status
        hyp.verdict_recommendation = recommendation
        if result.calculation is not None:
            hyp.candidate_exposure = result.calculation.result
        _event(inv, "hypothesis_resolved", hypothesis_id=str(hyp.hypothesis_id),
               verdict=verdict, reason=str(result.structured_result.get("reason", "")))
    else:
        _event(inv, "hypothesis_updated", hypothesis_id=str(hyp.hypothesis_id),
               supporting=len(hyp.supporting_evidence_ids))

    return _touch(inv)


def run_investigation(
    ctx: AgentContext,
    *,
    engagement_id: str,
    objective: str,
    planner: Planner | None = None,
    limits: InvestigationLimits | None = None,
) -> Investigation:
    """Run start + repeated steps until every hypothesis resolves or a limit is hit."""

    planner = planner or get_planner()
    limits = limits or InvestigationLimits()
    inv = start_investigation(ctx, engagement_id=engagement_id, objective=objective,
                              planner=planner, limits=limits)
    started_at = time.monotonic()
    for _ in range(limits.max_steps):
        if inv.status in _TERMINAL_INV:
            break
        run_next_step(inv, ctx, planner=planner, limits=limits, started_at=started_at)
    if inv.status not in _TERMINAL_INV:
        inv.status = InvestigationStatus.COMPLETED
        _event(inv, "completed", reason="step budget reached")
    return inv


_REFUTER_TOOLS = {
    "find_reversal", "find_credit_note", "find_independent_approval",
    "find_contract_or_service_evidence", "compare_peer_vendors",
}
_CATEGORY_CONTROL = {
    HypothesisCategory.VENDOR_INTEGRITY: "vendor_sod",
    HypothesisCategory.SPLIT_PAYMENT: "split_payment",
    HypothesisCategory.CAPITALISATION: "capitalisation",
    HypothesisCategory.CUTOFF: "cutoff",
}


def _category_control_id(category: HypothesisCategory) -> str:
    return _CATEGORY_CONTROL.get(category, "vendor_sod")


def _normalise_args(tool_name: str, args: dict) -> dict:
    """Repair common LLM argument mistakes and drop keys the tool does not accept.

    The tool schemas forbid extra keys, so a hallucinated argument would fail validation.
    We map the frequent ``vendor_ids: [...]`` mistake to a single ``vendor_id`` and then keep
    only the keys the tool actually declares, so a well-intentioned but sloppy tool call still
    runs on its valid arguments instead of being rejected wholesale.
    """

    if "vendor_ids" in args and "vendor_id" not in args:
        values = args.pop("vendor_ids")
        if isinstance(values, list) and values and isinstance(values[0], str):
            args["vendor_id"] = values[0]
    try:
        allowed = set(tool_registry.get_tool(tool_name).input_model.model_fields)
    except Exception:  # noqa: BLE001 - unknown tool handled by the allow-list check
        return args
    return {key: value for key, value in args.items() if key in allowed}


_SUBJECT_KEYS = ("subject", "vendor_id", "account", "reference")
_SUBJECT_CONTAINERS = ("vendors", "groups", "candidates", "assets", "items", "results")


def _extract_subject(structured: dict) -> str:
    """Find the opaque subject id a tool centred on, top-level or in its first list item."""

    for key in _SUBJECT_KEYS:
        value = structured.get(key)
        if isinstance(value, str) and value:
            return value
    for container in _SUBJECT_CONTAINERS:
        items = structured.get(container)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            for key in _SUBJECT_KEYS:
                value = items[0].get(key)
                if isinstance(value, str) and value:
                    return value
    return ""


def _compact(structured: dict) -> dict:
    """Trim a tool result to a small, timeline-friendly view."""

    out: dict = {}
    for key in ("verdict", "reason", "outcome", "count", "exposure", "found", "present",
                "vendor_id", "creator", "approver", "self_approved", "threshold"):
        if key in structured:
            out[key] = structured[key]
    return out or {k: structured[k] for k in list(structured)[:4]}


def _touch(inv: Investigation) -> Investigation:
    inv.updated_at = _now()
    return inv
