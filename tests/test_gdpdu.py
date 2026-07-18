import codecs
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from audit_compiler.adapters.gdpdu import compile_gdpdu_dossier, parse_gdpdu_index
from audit_compiler.cli import main
from audit_compiler.compiler import ParsingStatus, compile_dossier
from audit_compiler.duckdb_store import connect, store_parsed_table
from audit_compiler.normalization import parse_decimal


def _write_gdpdu_fixture(
    dossier: Path, *, include_encoding: bool = True, encoding: str = "windows-1252"
) -> Path:
    encoding_attribute = f' encoding="{encoding}"' if include_encoding else ""
    index = dossier / "index.xml"
    index.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<GDPdU>
  <DataSet name="Bookings" file="exports/bookings.txt"{encoding_attribute} delimiter=";">
    <Fields>
      <Field name="Belegnummer" />
      <Field name="Beschreibung" />
      <Field name="Betrag" />
    </Fields>
  </DataSet>
</GDPdU>
""",
        encoding="utf-8",
    )
    export = dossier / "exports" / "bookings.txt"
    export.parent.mkdir()
    export.write_bytes("A-1;Änderung;1.234,50\r\nA-2;Rückgabe;12,00\r\n".encode("cp1252"))
    return index


def test_gdpdu_maps_metadata_to_windows_1252_rows_with_exact_provenance(tmp_path: Path) -> None:
    index = _write_gdpdu_fixture(tmp_path)

    definitions = parse_gdpdu_index(index, dossier_root=tmp_path)
    compilation = compile_gdpdu_dossier(index, dossier_root=tmp_path)

    assert [column.name for column in definitions[0].columns] == [
        "Belegnummer",
        "Beschreibung",
        "Betrag",
    ]
    table = compilation.tables[0]
    assert table.detected_encoding == "cp1252"
    assert table.source_row_count == table.parsed_row_count == 2
    assert table.records[0].fields[1].raw_value == "Änderung"
    assert table.records[0].named_values["Beschreibung"] == "Änderung"
    assert table.records[0].raw_row == "A-1;Änderung;1.234,50\r\n"
    assert table.records[0].evidence_ref.raw_value == table.records[0].raw_row
    assert table.records[0].raw_row_sha256 == hashlib.sha256(
        table.records[0].raw_row.encode("utf-8")
    ).hexdigest()
    assert (
        table.records[0].evidence_ref.raw_value_sha256
        == table.records[0].raw_row_sha256
    )
    assert table.records[1].fields[2].evidence_ref.row == 2
    assert table.records[1].fields[2].evidence_ref.source_path == "exports/bookings.txt"
    assert parse_decimal(table.records[0].fields[2].raw_value, locale="de") == Decimal("1234.50")


def test_gdpdu_standard_nested_table_schema_is_mapped_once(tmp_path: Path) -> None:
    index = tmp_path / "metadata.xml"
    index.write_text(
        """<DataSet>
  <Media>
    <Table>
      <URL>records.csv</URL>
      <Name>Records</Name>
      <VariableLength><ColumnDelimiter>;</ColumnDelimiter></VariableLength>
      <Column><Name>Record</Name></Column>
      <Column><Name>Value</Name></Column>
    </Table>
  </Media>
</DataSet>
""",
        encoding="utf-8",
    )
    (tmp_path / "records.csv").write_text("R-1;raw\n", encoding="utf-8")

    definitions = parse_gdpdu_index(index, dossier_root=tmp_path)
    compilation = compile_gdpdu_dossier(index, dossier_root=tmp_path)

    assert len(definitions) == len(compilation.tables) == 1
    assert definitions[0].source_path == "records.csv"
    assert [column.name for column in definitions[0].columns] == ["Record", "Value"]


def test_gdpdu_detects_windows_1252_without_metadata(tmp_path: Path) -> None:
    index = _write_gdpdu_fixture(tmp_path, include_encoding=False)

    table = compile_gdpdu_dossier(index, dossier_root=tmp_path).tables[0]

    assert table.definition.encoding is None
    assert table.detected_encoding == "cp1252"


def test_gdpdu_supports_utf8_bom_and_preserves_missing_values(tmp_path: Path) -> None:
    index = _write_gdpdu_fixture(tmp_path, encoding="utf-8")
    export = tmp_path / "exports" / "bookings.txt"
    export.write_bytes(codecs.BOM_UTF8 + "B-1;Größe;\r\n".encode())

    table = compile_gdpdu_dossier(index, dossier_root=tmp_path).tables[0]

    assert table.detected_encoding == "utf-8-sig"
    assert table.records[0].named_values == {
        "Belegnummer": "B-1",
        "Beschreibung": "Größe",
        "Betrag": "",
    }
    assert table.records[0].fields[2].evidence_ref.raw_value == ""


def test_parsed_gdpdu_rows_and_raw_values_are_persisted_and_reconciled(tmp_path: Path) -> None:
    index = _write_gdpdu_fixture(tmp_path)
    table = compile_gdpdu_dossier(index, dossier_root=tmp_path).tables[0]
    connection = connect()

    assert store_parsed_table(connection, table) == 2
    rows = connection.execute(
        "SELECT row_number, raw_values_json FROM parsed_records ORDER BY row_number"
    ).fetchall()
    fields = connection.execute(
        "SELECT parsed_fields.raw_value, row_number "
        "FROM parsed_fields JOIN evidence_refs USING (evidence_id) "
        "WHERE column_name = 'Betrag' ORDER BY row_number"
    ).fetchall()
    assert rows == [(1, '["A-1", "Änderung", "1.234,50"]'), (2, '["A-2", "Rückgabe", "12,00"]')]
    assert fields == [("1.234,50", 1), ("12,00", 2)]
    connection.close()


def test_compile_report_persists_row_count_mismatch_with_provenance(tmp_path: Path) -> None:
    _write_gdpdu_fixture(tmp_path)
    export = tmp_path / "exports" / "bookings.txt"
    export.write_bytes("A-1;Text;1,00\r\nA-2;missing-field\r\n".encode("cp1252"))
    database = tmp_path / "result.duckdb"

    report = compile_dossier(tmp_path, database=database)

    assert report.parsing_status == ParsingStatus.FAILED
    assert report.source_row_count == 2
    assert report.parsed_row_count == 1
    assert report.errors[0].source_path == "exports/bookings.txt"
    assert report.errors[0].row_number == 2
    assert report.errors[0].raw_row == "A-2;missing-field\r\n"
    assert report.errors[0].raw_row_sha256 is not None

    connection = connect(database)
    reconciliation = connection.execute(
        """
        SELECT status, source_row_count, parsed_row_count, errors_json
        FROM parse_reconciliations
        """
    ).fetchone()
    assert reconciliation[:3] == ("failed", 2, 1)
    assert "row 2" in reconciliation[3]
    assert connection.execute("SELECT count(*) FROM parsed_records").fetchone()[0] == 0
    connection.close()


def test_cli_compile_emits_json_report_and_persists_success(tmp_path: Path) -> None:
    _write_gdpdu_fixture(tmp_path)
    database = tmp_path / "compiled.duckdb"
    output = tmp_path / "compilation.json"

    main(
        [
            "store",
            str(tmp_path),
            "--database",
            str(database),
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["parsing_status"] == "success"
    assert report["source_row_count"] == report["parsed_row_count"] == 2
    assert report["errors"] == []
    assert {item["path"] for item in report["discovered_files"]} == {
        "exports/bookings.txt",
        "index.xml",
    }
    assert database.exists()


def test_cli_compile_exits_nonzero_after_emitting_failure_report(tmp_path: Path) -> None:
    _write_gdpdu_fixture(tmp_path)
    (tmp_path / "exports" / "bookings.txt").write_bytes(b"one;field\r\n")
    output = tmp_path / "failure.json"

    with pytest.raises(SystemExit) as exit_info:
        main(["store", str(tmp_path), "--output", str(output)])

    assert exit_info.value.code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["parsing_status"] == "failed"
    assert report["errors"][0]["row_number"] == 1
