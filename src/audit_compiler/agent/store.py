"""Process-wide in-memory store for compiled engagements and their investigations.

This is deliberately the simplest thing that works for the POC: dicts keyed by
generated ids, no persistence, no locking. `AgentContext` (the compiled dossier +
evidence registry) is kept per engagement so tools can run against it repeatedly
across investigation steps; `Investigation` objects are mutable pydantic models
that the loop updates in place and the API re-serializes on every response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.models import Investigation


@dataclass
class _Engagement:
    context: AgentContext
    bundle: dict


@dataclass
class InvestigationStore:
    """Holds every compiled engagement and every investigation opened against one."""

    _engagements: dict[str, _Engagement] = field(default_factory=dict)
    _investigations: dict[str, Investigation] = field(default_factory=dict)

    def add_engagement(self, engagement_id: str | None, ctx: AgentContext, bundle: dict) -> str:
        """Register a compiled engagement and return its id (generating one if not given)."""

        engagement_id = engagement_id or f"eng_{uuid4().hex[:12]}"
        self._engagements[engagement_id] = _Engagement(context=ctx, bundle=bundle)
        return engagement_id

    def get_engagement(self, engagement_id: str) -> _Engagement | None:
        return self._engagements.get(engagement_id)

    def get_context(self, engagement_id: str) -> AgentContext | None:
        engagement = self._engagements.get(engagement_id)
        return engagement.context if engagement else None

    def get_bundle(self, engagement_id: str) -> dict | None:
        engagement = self._engagements.get(engagement_id)
        return engagement.bundle if engagement else None

    def save(self, inv: Investigation) -> Investigation:
        self._investigations[str(inv.investigation_id)] = inv
        return inv

    def get(self, investigation_id: str) -> Investigation | None:
        return self._investigations.get(str(investigation_id))

    def list(self) -> list[Investigation]:
        return list(self._investigations.values())


_store: InvestigationStore | None = None


def get_store() -> InvestigationStore:
    """Return the process-wide `InvestigationStore` singleton."""

    global _store
    if _store is None:
        _store = InvestigationStore()
    return _store


def reset_store() -> None:
    """Test-only helper: drop the singleton so each test starts from a clean store."""

    global _store
    _store = None
