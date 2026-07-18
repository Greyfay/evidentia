"""LLM interpretation interface for the partner integration layer.

The LLM is used **only** for bilingual (German/English) terminology normalization,
classifying ambiguous narrative descriptions, schema-constrained extraction from
ambiguous passages, candidate relationship suggestions, counter-hypothesis
generation, and concise auditor-language explanations.

The LLM must never produce authoritative numbers, perform arithmetic, assert
equality, or issue a verdict on a case or control. Every method degrades to a
deterministic, typed fallback on a missing API key, a missing library, or a
network error; none of them may raise into the compiler pipeline.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class LLMResult(BaseModel):
    """Base type for LLM-derived results. All results are advisory, never authoritative."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    provider: str
    error: str | None = None


class TermNormalization(LLMResult):
    """Bilingual terminology normalization suggestions, keyed by the input term."""

    normalized_terms: dict[str, str] = Field(default_factory=dict)


class Classification(LLMResult):
    """A candidate label for an ambiguous narrative description."""

    label: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = None


class Explanation(LLMResult):
    """An auditor-facing prose explanation that may cite only allowed evidence ids."""

    text: str = ""
    cited_evidence_ids: tuple[str, ...] = ()
    rejected_evidence_ids: tuple[str, ...] = ()


@runtime_checkable
class LLMInterpreter(Protocol):
    """Advisory-only LLM interpretation surface. No implementation may raise."""

    def normalize_terms(self, terms: list[str], target_language: str) -> TermNormalization:
        """Suggest normalized German/English terminology for the given terms."""
        ...

    def classify_description(self, text: str, labels: list[str]) -> Classification:
        """Classify an ambiguous narrative description into one of `labels`."""
        ...

    def explain_case(self, context: dict[str, Any], allowed_evidence_ids: set[str]) -> Explanation:
        """Produce auditor-language prose that may cite only `allowed_evidence_ids`."""
        ...

    def generate_counter_hypotheses(self, context: dict[str, Any]) -> list[str]:
        """Generate alternative, non-authoritative hypotheses for a case."""
        ...


def validate_evidence_citations(candidate_ids: set[str], allowed_ids: set[str]) -> None:
    """Raise ``ValueError`` if any candidate evidence id is outside the allow-set.

    This is the enforcement point for the rule that model output referencing
    evidence ids must be validated against a caller-supplied allow-set. Callers
    that must never raise (e.g. an `LLMInterpreter.explain_case` implementation)
    should catch this and degrade by dropping the offending ids instead of
    propagating the exception into the pipeline.
    """

    unknown = candidate_ids - allowed_ids
    if unknown:
        raise ValueError(f"unknown evidence ids referenced: {sorted(unknown)}")


def split_evidence_citations(
    candidate_ids: list[str], allowed_ids: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split candidate evidence ids into (allowed, rejected) tuples, preserving order."""

    seen: set[str] = set()
    cited: list[str] = []
    rejected: list[str] = []
    for candidate in candidate_ids:
        if candidate in seen:
            continue
        seen.add(candidate)
        (cited if candidate in allowed_ids else rejected).append(candidate)
    return tuple(cited), tuple(rejected)


class NullInterpreter:
    """Deterministic fallback used with no API key, a missing library, or a network error."""

    provider = "null"

    def normalize_terms(self, terms: list[str], target_language: str) -> TermNormalization:
        return TermNormalization(available=False, provider=self.provider)

    def classify_description(self, text: str, labels: list[str]) -> Classification:
        return Classification(available=False, provider=self.provider)

    def explain_case(self, context: dict[str, Any], allowed_evidence_ids: set[str]) -> Explanation:
        return Explanation(available=False, provider=self.provider)

    def generate_counter_hypotheses(self, context: dict[str, Any]) -> list[str]:
        return []


def get_interpreter() -> LLMInterpreter:
    """Return an `OpenAIInterpreter` if `OPENAI_API_KEY` is set, else `NullInterpreter`.

    Import of the OpenAI client is deferred so that a missing/broken `openai`
    installation, or client construction failure, degrades to the null fallback
    instead of raising.
    """

    if not os.environ.get("OPENAI_API_KEY"):
        return NullInterpreter()
    try:
        from audit_compiler.llm.openai_client import OpenAIInterpreter

        return OpenAIInterpreter()
    except Exception:
        return NullInterpreter()
