"""Grounded answers to auditor questions.

An answer is assembled strictly from an investigation's real state — its hypotheses, tool
observations, evidence ids, and admission verdicts. It never invents a number, an evidence
id, or a verdict: the deterministic path only restates figures already present in the
investigation, and the LLM path is fed exactly those same facts, then has any evidence id it
cites that is not already in the investigation stripped out before the answer is returned.

The planner (OpenAI/Hybrid) merely *phrases* the answer more fluently; the facts, the money,
and the verdicts still come from the deterministic investigation state.
"""

from __future__ import annotations

import re
from decimal import Decimal

from audit_compiler.agent.loop import _compact
from audit_compiler.agent.models import Hypothesis, Investigation
from audit_compiler.agent.planner import Planner

# The registry mints ids as ``ev_`` + 16 hex chars (see EvidenceRegistry._key).
_EVIDENCE_ID_RE = re.compile(r"ev_[0-9a-f]{16}")


def allowed_evidence_ids(inv: Investigation) -> list[str]:
    """Every evidence id the investigation has actually gathered, order-preserving."""

    ids: list[str] = list(inv.evidence_ids)
    for hyp in inv.hypotheses:
        for evidence_id in (*hyp.supporting_evidence_ids, *hyp.contradicting_evidence_ids):
            if evidence_id not in ids:
                ids.append(evidence_id)
    for obs in inv.completed_actions:
        for evidence_id in obs.evidence_ids:
            if evidence_id not in ids:
                ids.append(evidence_id)
    return ids


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def build_answer(
    inv: Investigation, question: str, planner: Planner
) -> tuple[str, list[str]]:
    """Return a grounded ``(answer_text, cited_evidence_ids)`` for ``question``.

    Uses the planner's LLM to phrase the answer when one is configured, constrained to the
    investigation facts and allow-listed evidence ids; degrades to a deterministic,
    state-derived answer on any LLM error or empty response. Never raises.
    """

    allowed = set(allowed_evidence_ids(inv))
    phrase = getattr(planner, "phrase_grounded_answer", None)
    if phrase is not None:
        try:
            text = phrase(question, _facts(inv))
        except Exception:  # noqa: BLE001 - LLM is best-effort; degrade to deterministic
            text = ""
        if text and text.strip():
            clean_text, cited = _sanitize(text, allowed)
            if clean_text.strip():
                return clean_text, cited
    return _deterministic_answer(inv)


def _facts(inv: Investigation) -> dict:
    """A JSON-serialisable, decimal-safe snapshot of the investigation for the LLM.

    Money is rendered as strings so no float ever reaches the model, and the model is only
    shown the evidence ids the investigation truly holds.
    """

    hypotheses = [
        {
            "claim": hyp.claim,
            "category": hyp.category.value,
            "status": hyp.status.value,
            "verdict_recommendation": hyp.verdict_recommendation.value,
            "candidate_exposure": _money(hyp.candidate_exposure),
            "supporting_evidence_ids": list(hyp.supporting_evidence_ids),
            "contradicting_evidence_ids": list(hyp.contradicting_evidence_ids),
            "missing_evidence": list(hyp.missing_evidence),
        }
        for hyp in inv.hypotheses
    ]
    observations = [
        {
            "tool_name": obs.tool_name,
            "result": _compact(obs.structured_result),
            "evidence_ids": list(obs.evidence_ids),
            "calculation_result": _money(obs.calculation.result) if obs.calculation else None,
            "errors": list(obs.errors),
        }
        for obs in inv.completed_actions[-5:]
    ]
    return {
        "objective": inv.objective,
        "status": inv.status.value,
        "hypotheses": hypotheses,
        "recent_observations": observations,
        "allowed_evidence_ids": allowed_evidence_ids(inv),
    }


def _sanitize(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Strip any evidence id the LLM cited that the investigation does not hold.

    Returns the cleaned text plus the ordered, de-duplicated list of the *allowed* ids it
    cited. A hallucinated id is removed from the prose so it cannot be presented as sourced.
    """

    cited: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        evidence_id = match.group(0)
        if evidence_id in allowed:
            if evidence_id not in cited:
                cited.append(evidence_id)
            return evidence_id
        return "[unverified evidence id removed]"

    clean = _EVIDENCE_ID_RE.sub(_replace, text)
    return clean, cited


def _leading_hypothesis(inv: Investigation) -> Hypothesis | None:
    if not inv.hypotheses:
        return None
    return max(inv.hypotheses, key=lambda h: h.priority)


def _deterministic_answer(inv: Investigation) -> tuple[str, list[str]]:
    """A grounded answer assembled purely from investigation state — never a canned string."""

    hyp = _leading_hypothesis(inv)
    if hyp is None:
        text = (
            f"The investigation into \"{inv.objective}\" is currently {inv.status.value} and no "
            "hypotheses have been formed yet, so there is no evidence or finding to report."
        )
        return text, []

    cited: list[str] = []
    for evidence_id in (*hyp.supporting_evidence_ids, *hyp.contradicting_evidence_ids):
        if evidence_id not in cited:
            cited.append(evidence_id)

    parts = [
        f"The investigation into \"{inv.objective}\" is currently {inv.status.value}.",
        f"The leading hypothesis ({hyp.category.value}, status {hyp.status.value}) is: "
        f"{hyp.claim}",
    ]

    support = len(hyp.supporting_evidence_ids)
    contra = len(hyp.contradicting_evidence_ids)
    if support or contra:
        support_ref = f" [{', '.join(hyp.supporting_evidence_ids)}]" if support else ""
        parts.append(
            f"It has {support} supporting{support_ref} and {contra} contradicting evidence "
            f"item(s) gathered so far."
        )
    else:
        parts.append("No evidence has been gathered against it yet.")

    if hyp.candidate_exposure is not None:
        parts.append(
            f"A candidate exposure of {hyp.candidate_exposure} was quantified by the "
            "deterministic control/admission gate."
        )

    if hyp.verdict_recommendation.value != "undecided":
        parts.append(
            f"The admission gate's recommendation is '{hyp.verdict_recommendation.value}'."
        )

    if hyp.missing_evidence:
        parts.append("Outstanding evidence: " + "; ".join(hyp.missing_evidence) + ".")

    if inv.completed_actions:
        last = inv.completed_actions[-1]
        compact = _compact(last.structured_result)
        detail = f" reporting {compact}" if compact else ""
        parts.append(f"The most recent tool run was '{last.tool_name}'{detail}.")

    return " ".join(parts), cited
