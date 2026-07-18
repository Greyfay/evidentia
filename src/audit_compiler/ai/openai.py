"""Optional OpenAI adapter. The OpenAI SDK is intentionally not a project dependency yet."""

from __future__ import annotations

from typing import Any

from audit_compiler.ai.models import CasePayload, CaseSummary


SYSTEM_PROMPT = """You summarize an already-calculated audit case.
Do not calculate amounts, infer missing numbers, query tools or databases, or invent evidence.
Use only supplied evidence_id and calculation_id values. Every narrative field must cite its
support. Copy calculation explanations exactly. Consider plausible innocent explanations and
identify missing evidence. If the evidence cannot support a useful summary, set status to
'abstained' and recommend human evidence collection or review. Return only the requested schema.
"""


class OpenAISummaryProvider:
    """Structured-output adapter using an injected OpenAI-compatible client."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def summarize(self, payload: CasePayload) -> CaseSummary:
        response = self._client.responses.parse(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            input=payload.model_dump_json(),
            text_format=CaseSummary,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI response did not contain a structured summary")
        return parsed if isinstance(parsed, CaseSummary) else CaseSummary.model_validate(parsed)
