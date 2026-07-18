"""Models local to the optional AI summarization boundary.

These deliberately do not extend or modify the compiler's shared domain models.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceInput(AIModel):
    """Evidence already selected by deterministic application code."""

    evidence_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class CalculationInput(AIModel):
    """A deterministic calculation and its human-readable explanation."""

    calculation_id: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class CitedText(AIModel):
    """Generated prose whose support is explicit and machine-checkable."""

    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    calculation_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def has_citation(self) -> CitedText:
        if not self.evidence_ids and not self.calculation_ids:
            raise ValueError("generated text must cite evidence or a calculation")
        return self


class CasePayload(AIModel):
    """Already-calculated, read-only input accepted by the summarizer."""

    case_id: str = Field(min_length=1)
    facts: tuple[CitedText, ...] = Field(min_length=1)
    evidence: tuple[EvidenceInput, ...] = Field(min_length=1)
    calculations: tuple[CalculationInput, ...] = ()

    @model_validator(mode="after")
    def ids_are_unique_and_facts_are_grounded(self) -> CasePayload:
        evidence_ids = [item.evidence_id for item in self.evidence]
        calculation_ids = [item.calculation_id for item in self.calculations]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        if len(calculation_ids) != len(set(calculation_ids)):
            raise ValueError("calculation IDs must be unique")
        known_evidence = set(evidence_ids)
        known_calculations = set(calculation_ids)
        for fact in self.facts:
            if not set(fact.evidence_ids) <= known_evidence:
                raise ValueError("fact references unknown evidence")
            if not set(fact.calculation_ids) <= known_calculations:
                raise ValueError("fact references unknown calculation")
        return self


class SummaryStatus(StrEnum):
    COMPLETED = "completed"
    ABSTAINED = "abstained"


class CaseSummary(AIModel):
    """A structured narrative; every generated field carries citations."""

    status: SummaryStatus
    title: CitedText
    plain_language_explanation: CitedText
    evidence_ids_used: tuple[str, ...]
    calculation_explanation: tuple[CalculationInput, ...]
    innocent_explanations_considered: tuple[CitedText, ...]
    missing_evidence: tuple[CitedText, ...]
    recommended_review_action: CitedText

