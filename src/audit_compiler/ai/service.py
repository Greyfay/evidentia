"""Post-generation guardrails for evidence-grounded summaries."""

from __future__ import annotations

from audit_compiler.ai.models import CasePayload, CaseSummary, CitedText, SummaryStatus
from audit_compiler.ai.provider import SummaryProvider


class SummarizationError(ValueError):
    """The provider returned an ungrounded or otherwise unsafe summary."""


def _narrative_fields(summary: CaseSummary) -> tuple[CitedText, ...]:
    return (
        summary.title,
        summary.plain_language_explanation,
        *summary.innocent_explanations_considered,
        *summary.missing_evidence,
        summary.recommended_review_action,
    )


def summarize_case(payload: CasePayload, provider: SummaryProvider) -> CaseSummary:
    """Generate and validate a summary; never calculate or access persistence."""

    summary = provider.summarize(payload)
    known_evidence = {item.evidence_id for item in payload.evidence}
    known_calculations = {item.calculation_id for item in payload.calculations}

    for narrative in _narrative_fields(summary):
        if not set(narrative.evidence_ids) <= known_evidence:
            raise SummarizationError("summary invented or referenced unknown evidence")
        if not set(narrative.calculation_ids) <= known_calculations:
            raise SummarizationError("summary referenced an unknown calculation")

    cited_evidence = {
        evidence_id
        for narrative in _narrative_fields(summary)
        for evidence_id in narrative.evidence_ids
    }
    if set(summary.evidence_ids_used) != cited_evidence:
        raise SummarizationError("evidence_ids_used must exactly match narrative citations")

    supplied_calculations = {item.calculation_id: item for item in payload.calculations}
    for explanation in summary.calculation_explanation:
        if supplied_calculations.get(explanation.calculation_id) != explanation:
            raise SummarizationError("calculation explanations must be copied verbatim from input")

    cited_calculation_ids = {
        calculation_id
        for narrative in _narrative_fields(summary)
        for calculation_id in narrative.calculation_ids
    }
    if {item.calculation_id for item in summary.calculation_explanation} != cited_calculation_ids:
        raise SummarizationError(
            "calculation explanations must exactly match cited calculations"
        )

    if summary.status == SummaryStatus.COMPLETED and not cited_evidence:
        raise SummarizationError("a completed summary requires cited evidence")
    return summary
