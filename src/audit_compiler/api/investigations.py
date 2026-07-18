"""Investigation-agent API: start/step/inspect investigations over a compiled engagement.

Mirrors the style of ``audit_compiler.api.app``: thin request/response models, the store
(``audit_compiler.agent.store``) as the only state, and every operation that touches a
best-effort partner (the graph memory) degrading to an empty/actionable response instead of
raising. The heavy lifting -- hypothesis generation, tool selection, execution -- lives in
``audit_compiler.agent.loop``; this module only wires HTTP onto it.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from audit_compiler.agent import tool_registry
from audit_compiler.agent.answers import build_answer
from audit_compiler.agent.loop import (
    _VERDICT_TO_STATUS,
    InvestigationLimits,
    _category_control_id,
    _event,
    run_next_step,
    start_investigation,
)
from audit_compiler.agent.models import HypothesisStatus, Investigation, VerdictRecommendation
from audit_compiler.agent.planner import get_planner
from audit_compiler.agent.store import get_store

router = APIRouter()


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartInvestigationRequest(_Body):
    engagement_id: str
    objective: str


class MessageRequest(_Body):
    message: str


class ChallengeRequest(_Body):
    note: str | None = None


def _get_investigation(investigation_id: str) -> Investigation:
    inv = get_store().get(investigation_id)
    if inv is None:
        raise HTTPException(404, "investigation not found")
    return inv


def _get_hypothesis(inv: Investigation, hypothesis_id: str):
    hyp = inv.hypothesis(hypothesis_id)
    if hyp is None:
        raise HTTPException(404, "hypothesis not found")
    return hyp


def _dump(inv: Investigation) -> dict:
    return inv.model_dump(mode="json")


@router.get("/agent-status")
def agent_status() -> dict:
    """Report which live capabilities back the agent right now, so the UI can show
    whether it is running with OpenAI planning, Cognee memory, or in deterministic
    fallback. Never performs a network call; reflects configured capability only."""

    openai_active = bool(os.environ.get("OPENAI_API_KEY"))
    cognee_active = False
    try:
        from audit_compiler.agent.cognee_memory import get_memory

        cognee_active = bool(get_memory().available)
    except Exception:  # noqa: BLE001 - status must never raise
        cognee_active = False

    if openai_active and cognee_active:
        mode = "live"
    elif openai_active or cognee_active:
        mode = "partial"
    else:
        mode = "fallback"

    return {
        "mode": mode,
        "planner": get_planner().name,
        "openai": {
            "active": openai_active,
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini") if openai_active else None,
        },
        "cognee": {"active": cognee_active},
    }


@router.post("/investigations")
def create_investigation(request: StartInvestigationRequest) -> dict:
    ctx = get_store().get_context(request.engagement_id)
    if ctx is None:
        raise HTTPException(404, "unknown engagement_id; upload/compile it first")
    inv = start_investigation(
        ctx, engagement_id=request.engagement_id, objective=request.objective,
        planner=get_planner(),
    )
    get_store().save(inv)
    return _dump(inv)


@router.get("/investigations")
def list_investigations() -> dict:
    investigations = get_store().list()
    return {
        "investigations": [
            {
                "investigation_id": str(inv.investigation_id),
                "engagement_id": inv.engagement_id,
                "objective": inv.objective,
                "status": inv.status.value,
                "hypotheses": len(inv.hypotheses),
                "created_at": inv.created_at.isoformat(),
                "updated_at": inv.updated_at.isoformat(),
            }
            for inv in investigations
        ]
    }


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str) -> dict:
    return _dump(_get_investigation(investigation_id))


@router.post("/investigations/{investigation_id}/run-next")
def run_next(investigation_id: str) -> dict:
    inv = _get_investigation(investigation_id)
    ctx = get_store().get_context(inv.engagement_id)
    if ctx is None:
        raise HTTPException(404, "engagement context no longer available")
    run_next_step(inv, ctx, planner=get_planner())
    get_store().save(inv)
    return _dump(inv)


@router.post("/investigations/{investigation_id}/run")
def run_to_completion(investigation_id: str) -> dict:
    inv = _get_investigation(investigation_id)
    ctx = get_store().get_context(inv.engagement_id)
    if ctx is None:
        raise HTTPException(404, "engagement context no longer available")
    planner = get_planner()
    limits = InvestigationLimits()
    started_at = time.monotonic()
    terminal = {
        "submitted", "dismissed", "stopped", "completed",
    }
    for _ in range(limits.max_steps):
        if inv.status.value in terminal:
            break
        run_next_step(inv, ctx, planner=planner, limits=limits, started_at=started_at)
    get_store().save(inv)
    return _dump(inv)


@router.get("/investigations/{investigation_id}/timeline")
def get_timeline(investigation_id: str) -> dict:
    inv = _get_investigation(investigation_id)
    return {"timeline": inv.timeline}


def _human_source(resolved: dict) -> str:
    """Render an evidence pointer as a human-readable source string (file/sheet/row/cell/…)."""

    path = resolved.get("source_path") or "(unknown source)"
    locator = resolved.get("locator") or {}
    parts = [path]
    if locator.get("sheet"):
        parts.append(f"sheet {locator['sheet']!r}")
    if locator.get("row") is not None:
        parts.append(f"row {locator['row']}")
    if locator.get("cell"):
        parts.append(f"cell {locator['cell']}")
    if locator.get("page") is not None:
        parts.append(f"page {locator['page']}")
    if locator.get("passage"):
        parts.append(f"passage {locator['passage']}")
    return " · ".join(parts)


@router.get("/investigations/{investigation_id}/evidence/{evidence_id}")
def get_investigation_evidence(investigation_id: str, evidence_id: str) -> dict:
    """Resolve one of the investigation's ``ev_...`` evidence ids to its exact source.

    Resolution goes through the engagement's evidence registry (the same one the tools cite
    into), so the pointer and snippet are the real source coordinates and raw value — never a
    fixture. 404 if the investigation, its engagement context, or the id is unknown.
    """

    inv = _get_investigation(investigation_id)
    ctx = get_store().get_context(inv.engagement_id)
    if ctx is None:
        raise HTTPException(404, "engagement context no longer available")
    resolved = ctx.registry.resolve(evidence_id)
    if resolved is None:
        raise HTTPException(404, "evidence not found for this investigation")
    return {
        "evidence_id": evidence_id,
        "kind": resolved.get("source_type"),
        "source": _human_source(resolved),
        "snippet": resolved.get("raw_value"),
    }


@router.get("/investigations/{investigation_id}/graph")
def get_graph(investigation_id: str) -> dict:
    inv = _get_investigation(investigation_id)
    try:
        from audit_compiler.agent.cognee_memory import get_memory

        memory = get_memory()
        memory.remember_investigation(inv)
        context = memory.open_hypothesis_context(str(inv.investigation_id))
        return {
            "nodes": context.get("nodes", []),
            "edges": context.get("edges", []),
            "available": context.get("available", False),
        }
    except Exception:  # noqa: BLE001 - the graph is a best-effort aid, never a hard failure
        return {"nodes": [], "edges": [], "available": False}


@router.post("/investigations/{investigation_id}/hypotheses/{hypothesis_id}/dismiss")
def dismiss_hypothesis(investigation_id: str, hypothesis_id: str) -> dict:
    inv = _get_investigation(investigation_id)
    hyp = _get_hypothesis(inv, hypothesis_id)
    hyp.status = HypothesisStatus.DISMISSED
    hyp.verdict_recommendation = VerdictRecommendation.DISMISS
    _event(inv, "hypothesis_dismissed", hypothesis_id=str(hyp.hypothesis_id))
    get_store().save(inv)
    return _dump(inv)


@router.post("/investigations/{investigation_id}/hypotheses/{hypothesis_id}/submit")
def submit_hypothesis(investigation_id: str, hypothesis_id: str) -> dict:
    inv = _get_investigation(investigation_id)
    hyp = _get_hypothesis(inv, hypothesis_id)
    ctx = get_store().get_context(inv.engagement_id)
    if ctx is None:
        raise HTTPException(404, "engagement context no longer available")

    args = {"subject": hyp.subject, "category": _category_control_id(hyp.category)}
    result = tool_registry.run_tool(ctx, "submit_case_to_admission", args)
    if result.ok:
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
        hyp.status = HypothesisStatus.SUBMITTED
        hyp.verdict_recommendation = VerdictRecommendation.CONFIRM
        _event(inv, "hypothesis_resolved", hypothesis_id=str(hyp.hypothesis_id),
               verdict="SUBMITTED", reason="; ".join(result.errors))
    get_store().save(inv)
    return _dump(inv)


@router.post("/investigations/{investigation_id}/hypotheses/{hypothesis_id}/continue")
def continue_hypothesis(investigation_id: str, hypothesis_id: str) -> dict:
    inv = _get_investigation(investigation_id)
    hyp = _get_hypothesis(inv, hypothesis_id)
    hyp.status = HypothesisStatus.ACTIVE
    _event(inv, "hypothesis_continued", hypothesis_id=str(hyp.hypothesis_id))
    get_store().save(inv)
    return _dump(inv)


@router.post("/investigations/{investigation_id}/hypotheses/{hypothesis_id}/challenge")
def challenge_hypothesis(
    investigation_id: str, hypothesis_id: str, request: ChallengeRequest
) -> dict:
    inv = _get_investigation(investigation_id)
    hyp = _get_hypothesis(inv, hypothesis_id)
    note = request.note or "auditor challenged this hypothesis; more evidence requested"
    hyp.missing_evidence = [*hyp.missing_evidence, note]
    inv.questions_for_auditor = [*inv.questions_for_auditor, note]
    hyp.status = HypothesisStatus.AWAITING_AUDITOR
    _event(inv, "hypothesis_challenged", hypothesis_id=str(hyp.hypothesis_id), note=note)
    get_store().save(inv)
    return _dump(inv)


@router.post("/investigations/{investigation_id}/messages")
def add_message(investigation_id: str, request: MessageRequest) -> dict:
    """Record an auditor question and answer it, grounded strictly in the investigation.

    The answer is derived from the investigation's real hypotheses, tool observations,
    evidence ids, and verdicts — it never invents a number, evidence id, or verdict. When an
    OpenAI planner is configured it phrases the answer; otherwise a deterministic,
    state-derived answer is produced. Any evidence id cited that is not already in the
    investigation is stripped. Never raises to the client: any failure degrades to the
    deterministic answer.
    """

    inv = _get_investigation(investigation_id)
    question = request.message
    inv.questions_for_auditor = [*inv.questions_for_auditor, question]
    _event(inv, "auditor_message", detail=question)

    try:
        answer, evidence_ids = build_answer(inv, question, get_planner())
    except Exception:  # noqa: BLE001 - answering must never break the endpoint
        answer, evidence_ids = "", []
    if not answer:
        # build_answer already degrades internally, but guarantee a non-empty reply.
        answer = (
            f"The investigation into \"{inv.objective}\" is currently {inv.status.value}; "
            "no further grounded detail is available yet."
        )
        evidence_ids = []

    _event(inv, "assistant_reply", detail=answer, evidence_ids=evidence_ids)
    get_store().save(inv)
    return _dump(inv)
