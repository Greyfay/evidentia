"""Serialise findings + verdicts into the ``cases.json`` replay bundle.

See ``docs/CASES_SCHEMA.md`` for the emitted structure.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from audit_compiler.admission import Admission
from audit_compiler.controls.base import EvidenceStep, Finding
from audit_compiler.models import EvidenceRef

_NS = uuid5(NAMESPACE_URL, "evidentia/case")


def _evidence(ref: EvidenceRef) -> dict:
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


def _step(step: EvidenceStep) -> dict:
    return {"step": step.step, "evidence": [_evidence(e) for e in step.evidence]}


def case_dict(finding: Finding, admission: Admission) -> dict:
    return {
        "case_id": str(uuid5(_NS, f"{finding.control_id}:{finding.subject}")),
        "title": finding.title,
        "control_id": finding.control_id,
        "control_version": finding.control_version,
        "verdict": admission.verdict,
        "verdict_reason": admission.reason,
        "severity": finding.severity,
        "assertion": finding.assertion,
        "narrative": finding.narrative,
        "financial_exposure": {
            "amount": str(finding.exposure),
            "currency": "EUR",
            "label": finding.exposure_label,
        },
        "evidence_chain": [_step(s) for s in finding.evidence_chain],
        "calculation": {
            "expression": finding.calculation.expression,
            "inputs": [
                {
                    "label": i.label,
                    "value": str(i.value),
                    "evidence_id": str(i.evidence.evidence_id),
                }
                for i in finding.calculation.inputs
            ],
            "result": str(finding.calculation.result),
            "sql": finding.calculation.sql,
            "evidence": [_evidence(i.evidence) for i in finding.calculation.inputs],
        },
        "counter_tests": [
            {
                "name": c.name,
                "outcome": c.outcome,
                "detail": c.detail,
                "required": c.required,
                "evidence": [_evidence(e) for e in c.evidence],
            }
            for c in finding.counter_tests
        ],
        "uncertainty": finding.uncertainty,
        "recommended_action": finding.recommended_action,
        "reviewer_decision": None,
    }
