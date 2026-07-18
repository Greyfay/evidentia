"""Legacy compatibility facade for the canonical compiler service.

Production entry points import :class:`audit_compiler.compiler.CompilerService` directly.
This module remains only for callers covered by the pre-migration public API.
"""

from __future__ import annotations

from pathlib import Path

from audit_compiler.compiler import CompileRequest, CompilerService
from audit_compiler.models import DataLocale


def compile_engagement(
    directory: Path,
    *,
    name: str | None = None,
    params: dict | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
    database: Path | None = None,
    locale: DataLocale | str = DataLocale.DE,
    control_ids: tuple[str, ...] | None = None,
) -> dict:
    """Deprecated dict-returning wrapper over :class:`CompilerService`."""

    bundle = CompilerService().compile(
        CompileRequest(
            dossier=directory,
            name=name,
            params=params or {},
            engagement_id=engagement_id,
            run_id=run_id,
            database=database,
            locale=DataLocale(locale),
            control_ids=control_ids,
        )
    )
    return bundle.model_dump(mode="json")
