"""Executable boundaries for the canonical modular architecture."""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

from audit_compiler.compiler import CompileRequest, CompilerService
from audit_compiler.duckdb_store import DuckDBAuditStore
from audit_compiler.models import CanonicalPayment, EvidenceRef, SourceType


def _dossier(root: Path) -> Path:
    (root / "payments.csv").write_text(
        "vendor,payment_date,amount\nV-1,2026-01-01,12.30\n", encoding="utf-8"
    )
    return root


def _evidence() -> EvidenceRef:
    return EvidenceRef.canonical(
        source_path="payments.csv",
        source_type=SourceType.CSV_ROW,
        file_sha256="a" * 64,
        raw_value="12.30",
        row=2,
    )


def test_sources_are_parsed_once(monkeypatch, tmp_path: Path) -> None:
    import audit_compiler.ir.dossier as dossier_module

    calls = 0
    original = dossier_module.load_dossier

    def counted(path: Path, **kwargs):
        nonlocal calls
        calls += 1
        return original(path, **kwargs)

    monkeypatch.setattr(dossier_module, "load_dossier", counted)
    CompilerService().compile(CompileRequest(dossier=_dossier(tmp_path)))
    assert calls == 1


def test_cli_imports_the_canonical_compiler() -> None:
    source = Path("src/audit_compiler/cli.py").read_text(encoding="utf-8")
    assert "from audit_compiler.compiler import CompileRequest, CompilerService" in source
    assert "audit_compiler.pipeline" not in source


def test_records_are_scoped_by_engagement_and_run(tmp_path: Path) -> None:
    root = _dossier(tmp_path)
    database = tmp_path / "runs.duckdb"
    service = CompilerService()
    service.compile(CompileRequest(
        dossier=root, database=database, engagement_id="eng-1", run_id="run-1"
    ))
    service.compile(CompileRequest(
        dossier=root, database=database, engagement_id="eng-1", run_id="run-2"
    ))
    store = DuckDBAuditStore(database)
    assert store.load_dossier("eng-1", "run-1").tables
    assert store.load_dossier("eng-1", "run-2").tables


def test_canonical_contracts_serialize_deterministically() -> None:
    payment = CanonicalPayment(
        payment_id="P-1", engagement_id="eng", run_id="run", vendor_id="V-1",
        payment_date="2026-01-01", amount=Decimal("12.30"), evidence_refs=(_evidence(),),
    )
    first = payment.deterministic_json()
    assert first == payment.deterministic_json()
    assert json.loads(first)["amount"] == "12.30"


def test_controls_cannot_assign_final_verdicts() -> None:
    controls = Path("src/audit_compiler/controls")
    for path in controls.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigned = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert "verdict" not in assigned, path


def test_production_entry_points_do_not_import_legacy_paths() -> None:
    for relative in ("src/audit_compiler/cli.py", "src/audit_compiler/api/app.py"):
        source = Path(relative).read_text(encoding="utf-8")
        assert "audit_compiler.pipeline" not in source
        assert "controls._engine" not in source
        assert "ir.dossier import load_dossier" not in source


def test_canonical_layer_imports_are_acyclic() -> None:
    # Public layer direction: models -> IR/store -> controls -> admission -> compiler -> API/CLI.
    forbidden = {
        "models.py": ("audit_compiler.controls", "audit_compiler.compiler"),
        "ir/dossier.py": ("audit_compiler.controls", "audit_compiler.compiler"),
        "admission.py": ("audit_compiler.compiler", "audit_compiler.api"),
        "compiler.py": ("audit_compiler.api", "audit_compiler.cli"),
    }
    base = Path("src/audit_compiler")
    for relative, imports in forbidden.items():
        source = (base / relative).read_text(encoding="utf-8")
        for imported in imports:
            assert imported not in source
