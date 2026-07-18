from pathlib import Path

import duckdb
import pytest

from audit_compiler.compiler import CompileRequest, CompilerService
from audit_compiler.duckdb_store import DuckDBAuditStore, connect
from audit_compiler.ir.canonical import map_canonical_events
from audit_compiler.ir.dossier import load_dossier
from audit_compiler.models import DataLocale


def _write_dossier(root: Path, amount: str, posting_date: str) -> None:
    (root / "ledger.csv").write_text(
        "Belegnummer;Buchungsdatum;Betrag;Konto\n"
        f"INV-1;{posting_date};{amount};4400\n",
        encoding="utf-8",
    )


def test_atomic_store_rolls_back_run_tables_and_events(tmp_path: Path) -> None:
    dossier_path = tmp_path / "dossier"
    dossier_path.mkdir()
    _write_dossier(dossier_path, "1.234,50", "18.07.2026")
    dossier = load_dossier(dossier_path, locale="de")
    event = map_canonical_events(
        dossier, engagement_id="eng-rollback", run_id="run-rollback"
    )[0]
    database = tmp_path / "rollback.duckdb"
    store = DuckDBAuditStore(database)

    with pytest.raises(duckdb.ConstraintException):
        store.persist_dossier(
            "eng-rollback",
            "run-rollback",
            dossier,
            events=(event, event),
        )

    connection = connect(database)
    assert connection.execute("SELECT count(*) FROM audit_runs").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM audit_ir_tables").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM audit_ir_events").fetchone()[0] == 0
    connection.close()


def test_repeated_compiles_are_run_isolated_and_provenance_exact(tmp_path: Path) -> None:
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    database = tmp_path / "runtime.duckdb"
    _write_dossier(dossier, "1.234,50", "18.07.2026")
    service = CompilerService()

    first = service.compile(
        CompileRequest(
            dossier=dossier,
            database=database,
            engagement_id="eng-1",
            run_id="run-1",
            locale="de",
        )
    )
    second = service.compile(
        CompileRequest(
            dossier=dossier,
            database=database,
            engagement_id="eng-1",
            run_id="run-2",
            locale="de",
        )
    )

    assert first.engagement.locale is second.engagement.locale is DataLocale.DE
    assert first.engagement.counts["canonical_events"] == 1
    store = DuckDBAuditStore(database)
    first_event = store.load_events("eng-1", "run-1")[0]
    second_event = store.load_events("eng-1", "run-2")[0]
    assert first_event.event_id == second_event.event_id
    assert first_event.net_amount == second_event.net_amount
    amount_evidence = next(
        evidence
        for evidence in first_event.evidence_refs
        if evidence.raw_value == "1.234,50"
    )
    assert amount_evidence.normalized_value == "1234.50"
    assert amount_evidence.row == 2


def test_locale_is_explicit_and_changes_ambiguous_mapping(tmp_path: Path) -> None:
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    _write_dossier(dossier, "1,234", "07/18/2026")
    service = CompilerService()

    english = service.compile(
        CompileRequest(
            dossier=dossier,
            database=tmp_path / "english.duckdb",
            locale="en",
        )
    )
    german = service.compile(
        CompileRequest(
            dossier=dossier,
            database=tmp_path / "german.duckdb",
            locale="de",
        )
    )

    assert english.engagement.locale is DataLocale.EN
    assert english.engagement.counts["canonical_events"] == 1
    assert german.engagement.counts["canonical_events"] == 0
