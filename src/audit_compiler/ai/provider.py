"""Provider-neutral model interface."""

from __future__ import annotations

from typing import Protocol

from audit_compiler.ai.models import CasePayload, CaseSummary


class SummaryProvider(Protocol):
    """A provider that only transforms supplied content into a summary."""

    def summarize(self, payload: CasePayload) -> CaseSummary:
        """Return a structured candidate summary without side effects."""
        ...

