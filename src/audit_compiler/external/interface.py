"""External verification interface for the partner integration layer.

`ExternalVerifier` cross-checks an entity name against the open web (e.g. "does
a company by this name plausibly exist"). It is advisory only, is never forced
on for the compiler's offline fictional dossiers, and only ever runs when both
`TAVILY_API_KEY` is set AND the caller explicitly enables it. Every method
degrades to `available=False` on a missing key, missing library, or network
error rather than raising.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ExternalCheck(BaseModel):
    """The (advisory) result of an external verification lookup."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    provider: str
    query: str
    verified: bool | None = None
    summary: str | None = None
    sources: tuple[str, ...] = Field(default_factory=tuple)
    error: str | None = None


@runtime_checkable
class ExternalVerifier(Protocol):
    """Opt-in external corroboration surface. No implementation may raise."""

    def verify_entity(self, name: str, context: str) -> ExternalCheck:
        """Best-effort external corroboration for `name`. Never authoritative."""
        ...


class NullVerifier:
    """Fallback used when external verification is disabled, unkeyed, or unavailable."""

    provider = "null"

    def verify_entity(self, name: str, context: str) -> ExternalCheck:
        return ExternalCheck(available=False, provider=self.provider, query=name)


def get_verifier(*, enabled: bool = False) -> ExternalVerifier:
    """Return a `TavilyVerifier` only if explicitly `enabled` AND `TAVILY_API_KEY` is set.

    External verification is opt-in by design: it must never run implicitly
    against an offline fictional dossier. Callers must pass `enabled=True`
    explicitly, in addition to having the API key configured.
    """

    if not enabled or not os.environ.get("TAVILY_API_KEY"):
        return NullVerifier()
    try:
        from audit_compiler.external.tavily_client import TavilyVerifier

        return TavilyVerifier()
    except Exception:
        return NullVerifier()
