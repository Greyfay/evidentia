from pathlib import Path
from uuid import uuid4

import pytest

from audit_compiler.compiler import compile_runtime
from audit_compiler.duckdb_store import connect, engagement_run
from audit_compiler.models import DataLocale, EngagementIdentity


def _write_dossier(root: Path, amount: str, posting_date: str) -> None:
    (root / "ledger.csv").write_text(
        "Belegnummer;Buchungsdatum;Betrag;Konto\n"
        f"INV-1;{posting_date};{amount};4400\n",
        encoding="utf-8",
    )


def test_engagement_run_rolls_back_every_write_on_failure() -> None:
    connection = connect()
    identity = EngagementIdentity(
        engagement_id=uuid4(),
        name="rollback",
        dossier_root="rollback",
        locale=DataLocale.DE,
    )

    with pytest.raises(RuntimeError, match="injected"):
        with engagement_run(connection, identity) as run_id:
            connection.execute(
                "INSERT INTO run_source_files VALUES (?, 'ledger.csv', 'csv', 1, ?)",
                [run_id, "a" * 64],
            )
            raise RuntimeError("injected failure")

    assert connection.execute("SELECT count(*) FROM engagements").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM compilation_runs").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM run_source_files").fetchone()[0] == 0
    connection.close()


def test_repeated_compiles_are_run_isolated_and_provenance_exact(tmp_path: Path) -> None:
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    database = tmp_path / "runtime.duckdb"
    _write_dossier(dossier, "1.234,50", "18.07.2026")

    first = compile_runtime(dossier, database=database, locale="de")
    second = compile_runtime(dossier, database=database, locale="de")

    assert first.report.engagement_id == second.report.engagement_id
    assert first.report.run_id != second.report.run_id
    assert first.report.canonical_event_count == 1
    assert len(first.events) == len(second.events) == 1
    assert first.events[0].event_id == second.events[0].event_id
    assert first.events[0].net_amount == second.events[0].net_amount

    connection = connect(database)
    runs = connection.execute(
        "SELECT run_id, status FROM compilation_runs ORDER BY started_at"
    ).fetchall()
    assert runs == [
        (first.report.run_id, "completed"),
        (second.report.run_id, "completed"),
    ]
    rows = connection.execute(
        """
        SELECT run_id, raw_value, normalized_value, row_number
        FROM canonical_event_evidence
        WHERE raw_value = '1.234,50'
        ORDER BY run_id
        """
    ).fetchall()
    assert {row[0] for row in rows} == {first.report.run_id, second.report.run_id}
    assert all(row[1:] == ("1.234,50", "1234.50", 2) for row in rows)
    connection.close()


def test_locale_is_explicit_and_changes_ambiguous_mapping(tmp_path: Path) -> None:
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    _write_dossier(dossier, "1,234", "07/18/2026")

    english = compile_runtime(
        dossier,
        database=tmp_path / "english.duckdb",
        locale="en",
    )
    german = compile_runtime(
        dossier,
        database=tmp_path / "german.duckdb",
        locale="de",
    )

    assert english.report.locale is DataLocale.EN
    assert english.events[0].net_amount == 1234
    assert german.events == ()
