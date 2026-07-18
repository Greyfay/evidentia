"""The planner: what to investigate and which tool to run next.

Two interchangeable implementations behind one Protocol:

* ``OpenAIPlanner`` uses Structured Outputs so every response is schema-valid. It proposes
  hypotheses, picks the next single tool, and recommends a decision — but it only ever
  emits tool names and entity ids that the loop then validates against the allow-list and
  the entity catalog. It never computes a total or declares a final verdict.
* ``DeterministicPlanner`` is a genuine, LLM-free code path (used offline and in tests): it
  derives hypotheses from the available controls and drives a real per-category tool
  sequence. It selects real tools that run on real data — it is not a scripted animation.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from audit_compiler.agent.models import HypothesisCategory, VerdictRecommendation


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HypothesisDraft(_Schema):
    claim: str
    category: HypothesisCategory
    target_entity_id: str | None = None
    priority: int = Field(ge=0, le=100)
    potential_impact: str
    evidence_availability: str
    false_positive_risk: str
    rationale: str


class HypothesesResponse(_Schema):
    hypotheses: list[HypothesisDraft]


class NextActionDraft(_Schema):
    tool_name: str
    arguments_json: str = "{}"
    reason: str
    expected_evidence: str


class DecisionDraft(_Schema):
    decision: str  # continue | ask_auditor | dismiss | submit | stop
    rationale: str
    verdict_recommendation: VerdictRecommendation = VerdictRecommendation.UNDECIDED
    question: str | None = None


class Planner(Protocol):
    name: str

    def propose_hypotheses(self, summary: dict) -> list[HypothesisDraft]: ...
    def next_action(self, objective: str, hypothesis: dict, completed_tools: list[str],
                    available_tools: list[str], summary: dict) -> NextActionDraft: ...
    def decide(self, hypothesis: dict, observations: list[dict]) -> DecisionDraft: ...


_CATEGORY_HINT = {
    "vendor_sod": HypothesisCategory.VENDOR_INTEGRITY,
    "split_payment": HypothesisCategory.SPLIT_PAYMENT,
    "capitalisation": HypothesisCategory.CAPITALISATION,
    "cutoff": HypothesisCategory.CUTOFF,
}

# Genuine per-category investigation plans: real tools, run in order, incl. required refuters.
_PLAN = {
    HypothesisCategory.VENDOR_INTEGRITY: [
        "check_vendor_creation_and_approval",
        "check_user_permissions",
        "reconcile_vendor_invoices_and_payments",
        "find_contract_or_service_evidence",
        "find_independent_approval",
        "compare_peer_vendors",
        "submit_case_to_admission",
    ],
    HypothesisCategory.SPLIT_PAYMENT: [
        "cluster_payments", "find_reversal", "find_independent_approval",
        "submit_case_to_admission",
    ],
    HypothesisCategory.CAPITALISATION: [
        "inspect_asset_additions", "submit_case_to_admission",
    ],
    HypothesisCategory.CUTOFF: [
        "test_period_cutoff", "submit_case_to_admission",
    ],
}


class DeterministicPlanner:
    name = "deterministic"

    def propose_hypotheses(self, summary: dict) -> list[HypothesisDraft]:
        drafts: list[HypothesisDraft] = []
        priorities = {"vendor_sod": 90, "cutoff": 80, "capitalisation": 70, "split_payment": 60}
        for control_id in summary.get("available_controls", []):
            category = _CATEGORY_HINT.get(control_id, HypothesisCategory.OTHER)
            drafts.append(HypothesisDraft(
                claim=f"A {category.value.replace('_', ' ')} risk may be present in the dossier.",
                category=category,
                priority=priorities.get(control_id, 50),
                potential_impact="unknown until deterministic tools quantify it",
                evidence_availability="controls and structured sources are available",
                false_positive_risk="medium; requires counter-evidence before confirming",
                rationale=f"The {control_id} control is available and maps to this risk.",
            ))
        return sorted(drafts, key=lambda d: d.priority, reverse=True)[:5]

    def next_action(self, objective, hypothesis, completed_tools, available_tools, summary):  # noqa: ANN001
        category = HypothesisCategory(hypothesis["category"])
        full_plan = _PLAN.get(category, ["submit_case_to_admission"])
        plan = [t for t in full_plan if t in available_tools]
        remaining = [t for t in plan if t not in completed_tools]
        tool = remaining[0] if remaining else "submit_case_to_admission"
        args: dict = {}
        target = hypothesis.get("target_entity_id")
        if target and tool != "submit_case_to_admission":
            args["vendor_id"] = target
        if tool == "submit_case_to_admission":
            args = {"subject": target or hypothesis.get("subject", ""), "category": category.value}
        return NextActionDraft(
            tool_name=tool, arguments_json=json.dumps(args),
            reason=f"Next step in the {category.value} plan.",
            expected_evidence="cited source records or a deterministic calculation",
        )

    def decide(self, hypothesis, observations):  # noqa: ANN001
        cleared = any(o.get("cleared") for o in observations)
        if cleared:
            return DecisionDraft(
                decision="dismiss",
                rationale="A supported innocent explanation was found.",
                verdict_recommendation=VerdictRecommendation.DISMISS,
            )
        submitted = any(o.get("tool_name") == "submit_case_to_admission" for o in observations)
        if submitted:
            return DecisionDraft(decision="stop", rationale="Case submitted to the admission gate.",
                                 verdict_recommendation=VerdictRecommendation.CONFIRM)
        return DecisionDraft(decision="continue", rationale="More counter-evidence checks remain.")


_SYSTEM = (
    "You are the planning brain of a forensic audit agent. You NEVER compute totals, perform "
    "equality checks, or declare a final verdict — deterministic tools and an admission gate do "
    "that. You may only reference tool names from the provided allow-list and entity ids that "
    "appear in the provided summary. Prefer precision: require counter-evidence before confirming."
)


class OpenAIPlanner:
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import OpenAI

        timeout = min(max(float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "20")), 1.0), 120.0)
        self._client = OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=1,
        )
        self._model = model

    def _parse(self, instruction: str, payload: dict, schema: type[_Schema]):
        context = json.dumps(payload)[:12000]
        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"{instruction}\n\nCONTEXT:\n{context}"},
            ],
            response_format=schema,
        )
        return completion.choices[0].message.parsed

    def propose_hypotheses(self, summary: dict) -> list[HypothesisDraft]:
        result = self._parse(
            "Propose 3-5 ranked fraud hypotheses for this engagement.", summary, HypothesesResponse
        )
        return list(result.hypotheses)[:5]

    def next_action(self, objective, hypothesis, completed_tools, available_tools, summary):  # noqa: ANN001
        payload = {
            "objective": objective, "hypothesis": hypothesis,
            "completed_tools": completed_tools, "available_tools": available_tools,
            "entities": {"vendor_ids_sample": summary.get("vendor_ids_sample", []),
                         "user_ids": summary.get("user_ids", [])},
        }
        return self._parse(
            "Choose the single next tool to run. Use only an allow-listed tool name and known ids.",
            payload, NextActionDraft,
        )

    def decide(self, hypothesis, observations):  # noqa: ANN001
        payload = {"hypothesis": hypothesis, "observations": observations}
        return self._parse(
            "Decide: continue, ask_auditor, dismiss, submit, or stop. Do not invent numbers.",
            payload, DecisionDraft,
        )


class HybridPlanner:
    """OpenAI decides *what* to investigate; deterministic plans decide *how*.

    Hypotheses (the interpretive, judgement-heavy step) come from OpenAI and are then
    guaranteed to cover every available control category. Tool selection and decisions use
    the deterministic per-category plan, so execution is reliable and every arithmetic step
    still runs in a deterministic tool. This is the "OpenAI plans, code verifies" split.
    """

    name = "hybrid"

    def __init__(self, openai_planner: OpenAIPlanner) -> None:
        self._openai = openai_planner
        self._deterministic = DeterministicPlanner()

    def propose_hypotheses(self, summary: dict) -> list[HypothesisDraft]:
        try:
            llm_drafts = self._openai.propose_hypotheses(summary)
        except Exception:  # noqa: BLE001 - fall back to deterministic hypotheses on any error
            llm_drafts = []
        by_category: dict[HypothesisCategory, HypothesisDraft] = {}
        for draft in llm_drafts:
            if draft.category is not HypothesisCategory.OTHER:
                by_category.setdefault(draft.category, draft)
        for draft in self._deterministic.propose_hypotheses(summary):
            by_category.setdefault(draft.category, draft)
        return sorted(by_category.values(), key=lambda d: d.priority, reverse=True)[:5]

    def next_action(self, objective, hypothesis, completed_tools, available_tools, summary):  # noqa: ANN001
        return self._deterministic.next_action(
            objective, hypothesis, completed_tools, available_tools, summary)

    def decide(self, hypothesis, observations):  # noqa: ANN001
        return self._deterministic.decide(hypothesis, observations)


def get_planner(*, model: str | None = None) -> Planner:
    """Return the hybrid planner when an OpenAI key is configured, else deterministic.

    Hybrid keeps OpenAI genuinely in the investigation path (hypothesis generation and
    ranking) while deterministic tools stay authoritative for execution and arithmetic.
    """

    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            openai_planner = OpenAIPlanner(
                api_key=api_key, model=model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
            return HybridPlanner(openai_planner)
        except Exception:  # noqa: BLE001 - never let planner init break the pipeline
            return DeterministicPlanner()
    return DeterministicPlanner()
