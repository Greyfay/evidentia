"""End-to-end engagement compile: parse -> controls -> counter-evidence -> admission -> bundle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from audit_compiler.admission import admit
from audit_compiler.casebuilder import case_dict
from audit_compiler.controls.base import ControlContext
from audit_compiler.controls.registry import METHODOLOGY_VERSION, default_controls
from audit_compiler.inventory import inventory_dossier
from audit_compiler.ir.dossier import load_dossier


def compile_engagement(directory: Path, *, name: str | None = None,
                       params: dict | None = None) -> dict:
    """Compile a dossier into the ``cases.json`` replay bundle described in docs/CASES_SCHEMA.md."""

    root = Path(directory).expanduser().resolve()
    dossier = load_dossier(root)
    manifest = inventory_dossier(root)

    warned = {path for path, _ in dossier.warnings}
    rows_by_path: dict[str, int] = {}
    for table in dossier.tables:
        rows_by_path[table.source_path] = rows_by_path.get(table.source_path, 0) + len(table.rows)

    source_files = []
    for source in manifest.files:
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

    ctx = ControlContext(dossier=dossier, params=params or {})
    cases = []
    for control in default_controls():
        for finding in control.run(ctx):
            cases.append(case_dict(finding, admit(finding)))

    verdicts = [c["verdict"] for c in cases]
    evidence_records = sum(
        len(s["evidence"]) for c in cases for s in c["evidence_chain"]
    ) + sum(len(c["calculation"]["evidence"]) for c in cases)

    return {
        "engagement": {
            "name": name or root.name,
            "dossier_root": root.name,
            "compiled_at": datetime.now(UTC).isoformat(),
            "methodology_version": METHODOLOGY_VERSION,
            "counts": {
                "source_files": len(source_files),
                "evidence_records": evidence_records,
                "entities": len({t.name for t in dossier.tables}),
                "events": sum(len(t.rows) for t in dossier.tables),
                "confirmed": verdicts.count("CONFIRMED"),
                "human_review": verdicts.count("HUMAN_REVIEW"),
                "dismissed": verdicts.count("DISMISSED"),
                "rejected": verdicts.count("REJECTED"),
            },
            "source_files": source_files,
        },
        "cases": cases,
    }
