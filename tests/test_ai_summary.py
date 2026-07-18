from types import SimpleNamespace

import pytest

from audit_compiler.ai import (
    CalculationInput,
    CasePayload,
    CaseSummary,
    CitedText,
    EvidenceInput,
    SummarizationError,
    SummaryStatus,
    summarize_case,
)
from audit_compiler.ai.openai import OpenAISummaryProvider, SYSTEM_PROMPT


def payload() -> CasePayload:
    return CasePayload(
        case_id="CASE-1",
        evidence=(EvidenceInput(evidence_id="E-1", content="Invoice date is 2026-01-10"),),
        calculations=(
            CalculationInput(
                calculation_id="C-1",
                explanation="Deterministic rule output: supplied exposure is EUR 50.00.",
            ),
        ),
        facts=(
            CitedText(
                text="The deterministic control flagged the supplied exposure.",
                evidence_ids=("E-1",),
                calculation_ids=("C-1",),
            ),
        ),
    )


def valid_summary(*, status: SummaryStatus = SummaryStatus.COMPLETED) -> CaseSummary:
    citation = {"evidence_ids": ("E-1",), "calculation_ids": ("C-1",)}
    return CaseSummary(
        status=status,
        title=CitedText(text="Invoice requires review", **citation),
        plain_language_explanation=CitedText(
            text="The supplied rule output identifies EUR 50.00 for review.", **citation
        ),
        evidence_ids_used=("E-1",),
        calculation_explanation=(
            CalculationInput(
                calculation_id="C-1",
                explanation="Deterministic rule output: supplied exposure is EUR 50.00.",
            ),
        ),
        innocent_explanations_considered=(
            CitedText(
                text="The date may reflect an ordinary posting delay.",
                evidence_ids=("E-1",),
            ),
        ),
        missing_evidence=(
            CitedText(text="Approval evidence was not supplied.", evidence_ids=("E-1",)),
        ),
        recommended_review_action=CitedText(
            text="A reviewer should request the approval record.", evidence_ids=("E-1",)
        ),
    )


class MockProvider:
    def __init__(self, response: CaseSummary) -> None:
        self.response = response
        self.received: CasePayload | None = None

    def summarize(self, case_payload: CasePayload) -> CaseSummary:
        self.received = case_payload
        return self.response


def test_returns_grounded_structured_summary_from_mock_provider() -> None:
    case_payload = payload()
    provider = MockProvider(valid_summary())

    result = summarize_case(case_payload, provider)

    assert result.status == SummaryStatus.COMPLETED
    assert result.evidence_ids_used == ("E-1",)
    assert provider.received is case_payload


def test_rejects_invented_evidence_id() -> None:
    data = valid_summary().model_dump()
    data["title"]["evidence_ids"] = ("E-INVENTED",)
    data["evidence_ids_used"] = ("E-1", "E-INVENTED")

    with pytest.raises(SummarizationError, match="unknown evidence"):
        summarize_case(payload(), MockProvider(CaseSummary.model_validate(data)))


def test_rejects_changed_deterministic_calculation_explanation() -> None:
    data = valid_summary().model_dump()
    data["calculation_explanation"][0]["explanation"] = "The model recalculated EUR 75.00."

    with pytest.raises(SummarizationError, match="copied verbatim"):
        summarize_case(payload(), MockProvider(CaseSummary.model_validate(data)))


def test_allows_provider_to_abstain_when_evidence_is_insufficient() -> None:
    result = summarize_case(payload(), MockProvider(valid_summary(status=SummaryStatus.ABSTAINED)))
    assert result.status == SummaryStatus.ABSTAINED


def test_openai_adapter_uses_structured_output_with_injected_mock() -> None:
    expected = valid_summary()

    class Responses:
        def __init__(self) -> None:
            self.kwargs = None

        def parse(self, **kwargs):  # noqa: ANN003, ANN201 - SDK-shaped test double
            self.kwargs = kwargs
            return SimpleNamespace(output_parsed=expected)

    responses = Responses()
    client = SimpleNamespace(responses=responses)

    result = OpenAISummaryProvider(client=client, model="test-model").summarize(payload())

    assert result is expected
    assert responses.kwargs["instructions"] == SYSTEM_PROMPT
    assert responses.kwargs["text_format"] is CaseSummary
    assert responses.kwargs["model"] == "test-model"
