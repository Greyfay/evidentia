"""Shared execution context passed to every deterministic agent tool.

Holds the compiled dossier, the evidence registry (stable citeable ids), and methodology
parameters. Tools read from this context; they never reach outside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from audit_compiler.agent.evidence_registry import EvidenceRegistry
from audit_compiler.ir.dossier import LoadedDossier
from audit_compiler.models import EvidenceRef


@dataclass
class AgentContext:
    dossier: LoadedDossier
    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    params: dict = field(default_factory=dict)
    control_ids: tuple[str, ...] | None = None

    @classmethod
    def from_dossier_path(
        cls,
        path: str | Path,
        *,
        params: dict | None = None,
        control_ids: tuple[str, ...] | None = None,
    ) -> AgentContext:
        from audit_compiler.compiler import CompileRequest, CompilerService

        root = Path(path).expanduser().resolve()
        bundle = CompilerService().compile(
            CompileRequest(dossier=root, params=params or {}, control_ids=control_ids)
        )
        return cls.from_compiled_run(
            root / ".admissible" / "audit.duckdb",
            bundle.engagement.engagement_id,
            bundle.engagement.run_id,
            params=params,
            control_ids=control_ids,
        )

    @classmethod
    def from_compiled_run(
        cls,
        database: str | Path,
        engagement_id: str,
        run_id: str,
        *,
        params: dict | None = None,
        control_ids: tuple[str, ...] | None = None,
    ) -> AgentContext:
        from audit_compiler.duckdb_store import DuckDBAuditStore

        dossier = DuckDBAuditStore(database).load_dossier(engagement_id, run_id)
        return cls(dossier=dossier, params=params or {}, control_ids=control_ids)

    def cite(self, ref: EvidenceRef) -> str:
        """Record an evidence pointer and return its citeable id."""

        return self.registry.record(ref)
