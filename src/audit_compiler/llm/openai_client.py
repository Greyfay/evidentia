"""OpenAI-backed `LLMInterpreter` using Structured Outputs.

Every public method wraps its API call in a broad exception handler: a missing
key, an auth failure, a network error, a rate limit, or a schema-validation
failure from the API all degrade to `available=False` results rather than
raising into the compiler pipeline. Nothing here performs arithmetic or issues
verdicts; the model only normalizes terms, classifies text, drafts prose
explanations bound to an evidence allow-set, and proposes hypotheses.
"""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from audit_compiler.llm.interface import (
    Classification,
    Explanation,
    TermNormalization,
    split_evidence_citations,
)

DEFAULT_MODEL = "gpt-4o-mini"

_SYSTEM_PREAMBLE = (
    "You are an advisory assistant embedded in a forensic audit compiler. You never "
    "invent facts, never perform arithmetic, never assert equality between values, "
    "and never issue a verdict on a case or control. You only help with wording, "
    "terminology, classification, and non-authoritative hypotheses. All authoritative "
    "numbers and decisions come from deterministic code, not from you."
)


class _NormalizedTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str


class _TermNormalizationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_terms: list[_NormalizedTerm]


class _ClassificationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class _ExplanationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    cited_evidence_ids: list[str]


class _CounterHypothesesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypotheses: list[str]


class OpenAIInterpreter:
    """`LLMInterpreter` implementation backed by the OpenAI Structured Outputs API."""

    provider = "openai"

    def __init__(self, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        self._model = model
        self._last_error: str | None = None
        if client is not None:
            self._client = client
            return
        # Deferred import: a missing/broken `openai` install must not break
        # module import elsewhere in the pipeline.
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        timeout = min(max(float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "20")), 1.0), 120.0)
        self._client = OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=1,
        )

    def _parse(self, *, system: str, user: str, schema: type[BaseModel]) -> BaseModel | None:
        try:
            completion = self._client.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
            )
            choice = completion.choices[0]
            parsed = choice.message.parsed
            if parsed is None:
                self._last_error = "model returned no parsed structured output"
                return None
            return parsed
        except Exception as exc:  # noqa: BLE001 - any failure must degrade, never raise
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None

    def normalize_terms(self, terms: list[str], target_language: str) -> TermNormalization:
        system = (
            f"{_SYSTEM_PREAMBLE} Normalize German/English audit and accounting "
            f"terminology into {target_language}. Do not translate proper nouns or "
            "amounts; return only terminology mappings."
        )
        user = json.dumps({"terms": terms, "target_language": target_language})
        payload = self._parse(system=system, user=user, schema=_TermNormalizationPayload)
        if payload is None:
            return TermNormalization(
                available=False, provider=self.provider, error=self._last_error
            )
        assert isinstance(payload, _TermNormalizationPayload)
        return TermNormalization(
            available=True,
            provider=self.provider,
            normalized_terms={
                term.source: term.target for term in payload.normalized_terms
            },
        )

    def classify_description(self, text: str, labels: list[str]) -> Classification:
        system = (
            f"{_SYSTEM_PREAMBLE} Classify the narrative description into exactly one of "
            "the provided labels. This is a suggestion for a human reviewer, not a "
            "finding or a verdict."
        )
        user = json.dumps({"text": text, "labels": labels})
        payload = self._parse(system=system, user=user, schema=_ClassificationPayload)
        if payload is None:
            return Classification(available=False, provider=self.provider, error=self._last_error)
        assert isinstance(payload, _ClassificationPayload)
        if payload.label not in labels:
            return Classification(
                available=False,
                provider=self.provider,
                error=f"model returned an out-of-set label: {payload.label!r}",
            )
        return Classification(
            available=True,
            provider=self.provider,
            label=payload.label,
            confidence=payload.confidence,
            rationale=payload.rationale,
        )

    def explain_case(self, context: dict[str, Any], allowed_evidence_ids: set[str]) -> Explanation:
        system = (
            f"{_SYSTEM_PREAMBLE} Write a concise auditor-language explanation of the "
            "case described in the context. You may cite evidence ids ONLY from the "
            "provided allow-list; never cite or invent any other id, and never state "
            "amounts that are not already present verbatim in the context."
        )
        user = json.dumps(
            {"context": context, "allowed_evidence_ids": sorted(allowed_evidence_ids)},
            default=str,
        )
        payload = self._parse(system=system, user=user, schema=_ExplanationPayload)
        if payload is None:
            return Explanation(available=False, provider=self.provider, error=self._last_error)
        assert isinstance(payload, _ExplanationPayload)
        cited, rejected = split_evidence_citations(payload.cited_evidence_ids, allowed_evidence_ids)
        return Explanation(
            available=True,
            provider=self.provider,
            text=payload.text,
            cited_evidence_ids=cited,
            rejected_evidence_ids=rejected,
        )

    def generate_counter_hypotheses(self, context: dict[str, Any]) -> list[str]:
        system = (
            f"{_SYSTEM_PREAMBLE} Propose alternative, non-authoritative hypotheses that "
            "could explain the case, for a human reviewer to investigate further."
        )
        user = json.dumps({"context": context}, default=str)
        payload = self._parse(system=system, user=user, schema=_CounterHypothesesPayload)
        if payload is None:
            return []
        assert isinstance(payload, _CounterHypothesesPayload)
        return list(payload.hypotheses)
