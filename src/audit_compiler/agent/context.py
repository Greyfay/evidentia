"""Shared execution context passed to every deterministic agent tool.

Holds the compiled dossier, the evidence registry (stable citeable ids), and methodology
parameters. Tools read from this context; they never reach outside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from audit_compiler.agent.evidence_registry import EvidenceRegistry
from audit_compiler.ir.dossier import LoadedDossier, load_dossier
from audit_compiler.models import EvidenceRef


@dataclass
class AgentContext:
    dossier: LoadedDossier
    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    params: dict = field(default_factory=dict)

    @classmethod
    def from_dossier_path(cls, path: str | Path, *, params: dict | None = None) -> AgentContext:
        return cls(dossier=load_dossier(Path(path)), params=params or {})

    def cite(self, ref: EvidenceRef) -> str:
        """Record an evidence pointer and return its citeable id."""

        return self.registry.record(ref)
