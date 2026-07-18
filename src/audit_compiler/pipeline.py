"""End-to-end engagement compile: parse -> controls -> counter-evidence -> admission -> bundle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from audit_compiler.admission import admit
from audit_compiler.casebuilder import case_dict
from audit_compiler.compiler import compile_runtime
from audit_compiler.controls.base import ControlContext
from audit_compiler.controls.registry import METHODOLOGY_VERSION, default_controls
from audit_compiler.ir.roles import using_locale
from audit_compiler.models import DataLocale


def compile_engagement(
    directory: Path,
    *,
    name: str | None = None,
    params: dict | None = None,
    database: Path | None = None,
    locale: DataLocale | str = DataLocale.DE,
    engagement_id: UUID | None = None,
) -> dict:
    """Compile a dossier into the ``cases.json`` replay bundle described in docs/CASES_SCHEMA.md."""

    root = Path(directory).expanduser().resolve()
    runtime = compile_runtime(
        root,
        database=database,
        name=name,
        locale=locale,
        engagement_id=engagement_id,
    )
    dossier = runtime.dossier
    manifest_files = runtime.report.discovered_files

    warned = {path for path, _ in dossier.warnings}
    rows_by_path: dict[str, int] = {}
    for table in dossier.tables:
        rows_by_path[table.source_path] = rows_by_path.get(table.source_path, 0) + len(table.rows)

    source_files = []
    for source in manifest_files:
        if source.file_type in {"xml", "unknown"} or source.path.endswith(".dtd"):
            status = "skipped"
        elif source.path in warned:
            status = "warning"
        elif source.path in rows_by_path:
            status = "parsed"
        else:
            status = "skipped"
        parsed_rows = rows_by_path.get(source.path, 0)
        source_files.append({
            "path": source.path,
            "type": source.file_type,
            "bytes": source.byte_size,
            "sha256": source.sha256,
            "status": status,
            "source_rows": parsed_rows,
            "parsed_rows": parsed_rows,
            "warnings": [m for p, m in dossier.warnings if p == source.path],
        })

    cases = []
    with using_locale(dossier.locale.value):
        ctx = ControlContext(dossier=dossier, params=params or {})
        for control in default_controls():
            for finding in control.run(ctx):
                cases.append(case_dict(finding, admit(finding)))

    verdicts = [c["verdict"] for c in cases]
    evidence_records = sum(
        len(s["evidence"]) for c in cases for s in c["evidence_chain"]
    ) + sum(len(c["calculation"]["evidence"]) for c in cases)

    return {
        "engagement": {
            "engagement_id": str(runtime.report.engagement_id),
            "run_id": str(runtime.report.run_id),
            "name": name or root.name,
            "dossier_root": root.name,
            "locale": dossier.locale.value,
            "compiled_at": datetime.now(UTC).isoformat(),
            "methodology_version": METHODOLOGY_VERSION,
            "counts": {
                "source_files": len(source_files),
                "evidence_records": evidence_records,
                "entities": len({t.name for t in dossier.tables}),
                "events": sum(len(table.rows) for table in dossier.tables),
                "canonical_events": len(runtime.events),
                "confirmed": verdicts.count("CONFIRMED"),
                "human_review": verdicts.count("HUMAN_REVIEW"),
                "dismissed": verdicts.count("DISMISSED"),
                "rejected": verdicts.count("REJECTED"),
            },
            "source_files": source_files,
        },
        "cases": cases,
    }
