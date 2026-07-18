from audit_compiler.duckdb_store import connect


def test_connect_initializes_foundational_schema() -> None:
    connection = connect()
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    expected_tables = {
        "source_files",
        "evidence_refs",
        "financial_events",
        "control_results",
        "cases",
        "parsed_records",
        "parse_reconciliations",
        "xlsx_workbooks",
        "xlsx_sheets",
        "xlsx_cells",
        "xlsx_normalized_records",
    }
    assert expected_tables <= tables
    connection.close()
