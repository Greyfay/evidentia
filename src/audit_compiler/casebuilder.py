"""Deterministic serialization of admission-gated cases."""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from audit_compiler.admission import Admission
from audit_compiler.controls.base import EvidenceStep, Finding
from audit_compiler.models import ControlOutcome, CounterTest, EvidenceRef

_NS = uuid5(NAMESPACE_URL, "evidentia/case")


def _evidence_key(ref: EvidenceRef) -> tuple[str, str, str]:
    return str(ref.evidence_id), ref.source_path, ref.raw_value_sha256


def _evidence(ref: EvidenceRef) -> dict[str, Any]:
    return {
        "evidence_id": str(ref.evidence_id),
        "source_path": ref.source_path,
        "source_type": ref.source_type.value,
        "locator": {
            "row": ref.row,
            "sheet": ref.sheet,
            "cell": ref.cell,
            "page": ref.page,
            "passage": ref.passage,
        },
        "raw_value": ref.raw_value,
        "file_sha256": ref.file_sha256,
    }


def _evidence_list(refs: tuple[EvidenceRef, ...]) -> list[dict[str, Any]]:
    return [_evidence(ref) for ref in sorted(refs, key=_evidence_key)]


def _step(step: EvidenceStep) -> dict[str, Any]:
    return {"step": step.step, "evidence": _evidence_list(step.evidence)}


def _canonical_counter(counter: CounterTest) -> dict[str, Any]:
    return {
        "name": counter.name,
        "outcome": counter.outcome.value,
        "detail": counter.detail,
        "required": counter.required,
        "evidence": _evidence_list(counter.evidence),
        "search": counter.search.model_dump(mode="json") if counter.search else None,
    }


def _common(
    *,
    control_id: str,
    control_version: str,
    subject: str,
    title: str,
    engagement_id: str,
    run_id: str,
    admission: Admission,
) -> dict[str, Any]:
    return {
        "case_id": str(uuid5(_NS, f"{engagement_id}:{run_id}:{control_id}:{subject}")),
        "engagement_id": engagement_id,
        "run_id": run_id,
        "title": title,
        "control_id": control_id,
        "control_version": control_version,
        "verdict": admission.verdict,
        "verdict_reason": admission.reason,
        "admission_reasons": [
            reason.model_dump(mode="json") for reason in admission.reasons
        ],
    }


def _legacy_case(
    finding: Finding,
    admission: Admission,
    engagement_id: str,
    run_id: str,
) -> dict[str, Any]:
    result = _common(
        control_id=finding.control_id,
        control_version=finding.control_version,
        subject=finding.subject,
        title=finding.title,
        engagement_id=engagement_id,
        run_id=run_id,
        admission=admission,
    )
    result.update(
        {
            "severity": finding.severity,
            "assertion": finding.assertion,
            "narrative": finding.narrative,
            "financial_exposure": {
                "amount": str(finding.exposure),
                "currency": "EUR",
                "label": finding.exposure_label,
            },
            "evidence_chain": [
                _step(step)
                for step in sorted(
                    finding.evidence_chain,
                    key=lambda item: (
                        item.step,
                        tuple(str(ref.evidence_id) for ref in item.evidence),
                    ),
                )
            ],
            "calculation": {
                "expression": finding.calculation.expression,
                "inputs": [
                    {
                        "label": item.label,
                        "value": str(item.value),
                        "evidence_id": str(item.evidence.evidence_id),
                    }
                    for item in sorted(
                        finding.calculation.inputs,
                        key=lambda item: (item.label, str(item.evidence.evidence_id)),
                    )
                ],
                "result": str(finding.calculation.result),
                "sql": finding.calculation.sql,
                "evidence": _evidence_list(
                    tuple(item.evidence for item in finding.calculation.inputs)
                ),
            },
            "counter_tests": [
                {
                    "name": counter.name,
                    "outcome": counter.outcome,
                    "detail": counter.detail,
                    "required": counter.required,
                    "evidence": _evidence_list(counter.evidence),
                    "search": None,
                }
                for counter in sorted(
                    finding.counter_tests,
                    key=lambda item: (item.name, item.outcome, item.detail),
                )
            ],
            "uncertainty": finding.uncertainty,
            "recommended_action": finding.recommended_action,
            "replay": None,
            "reviewer_decision": None,
        }
    )
    return result


def _canonical_case(outcome: ControlOutcome, admission: Admission) -> dict[str, Any]:
    result = _common(
        control_id=outcome.control_id,
        control_version=outcome.control_version,
        subject=outcome.subject,
        title=f"{outcome.control_id}: {outcome.subject}",
        engagement_id=outcome.engagement_id,
        run_id=outcome.run_id,
        admission=admission,
    )
    evidence = tuple(outcome.evidence_refs)
    evidence_by_id = {ref.evidence_id: ref for ref in evidence}
    result.update(
        {
            "severity": None,
            "assertion": outcome.subject,
            "narrative": None,
            "financial_exposure": {
                "amount": str(outcome.exposure_amount),
                "currency": "EUR",
                "label": "control",
            },
            "evidence_chain": [
                {"step": "deterministic control evidence", "evidence": _evidence_list(evidence)}
            ],
            "calculation": {
                "expression": outcome.calculation.expression,
                "inputs": [
                    item.model_dump(mode="json")
                    for item in sorted(
                        outcome.calculation.inputs,
                        key=lambda item: (item.label, str(item.evidence_id)),
                    )
                ],
                "result": str(outcome.calculation.result),
                "sql": outcome.calculation.sql,
                "evidence": _evidence_list(
                    tuple(
                        evidence_by_id[item.evidence_id]
                        for item in outcome.calculation.inputs
                        if item.evidence_id in evidence_by_id
                    )
                ),
            },
            "counter_tests": [
                _canonical_counter(counter)
                for counter in sorted(
                    outcome.counter_tests,
                    key=lambda item: (item.name, item.outcome.value, item.detail),
                )
            ],
            "uncertainty": outcome.uncertainty,
            "recommended_action": None,
            "replay": outcome.replay.model_dump(mode="json") if outcome.replay else None,
            "reviewer_decision": None,
        }
    )
    return result


def case_dict(
    candidate: ControlOutcome | Finding,
    admission: Admission,
    *,
    engagement_id: str = "legacy",
    run_id: str = "legacy",
) -> dict[str, Any]:
    """Build a case from an already-computed admission decision.

    No candidate status, recommendation, or supplied verdict is consulted here.
    """

    if isinstance(candidate, ControlOutcome):
        return _canonical_case(candidate, admission)
    return _legacy_case(candidate, admission, engagement_id, run_id)
