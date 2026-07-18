"""DuckDB connection and schema initialization for deterministic audit data."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import duckdb

from audit_compiler.adapters.gdpdu import ParsedTable
from audit_compiler.adapters.xlsx import XlsxWorkbook
from audit_compiler.inventory import SourceFile
from audit_compiler.models import EngagementIdentity, EvidenceRef, FinancialEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_files (
    source_path VARCHAR PRIMARY KEY,
    file_type VARCHAR NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    sha256 VARCHAR NOT NULL CHECK (length(sha256) = 64),
    inventoried_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_refs (
    evidence_id UUID PRIMARY KEY,
    source_path VARCHAR NOT NULL REFERENCES source_files(source_path),
    source_type VARCHAR NOT NULL,
    file_sha256 VARCHAR NOT NULL CHECK (length(file_sha256) = 64),
    raw_value VARCHAR NOT NULL,
    raw_value_sha256 VARCHAR NOT NULL CHECK (length(raw_value_sha256) = 64),
    normalized_value VARCHAR,
    extraction_method VARCHAR NOT NULL,
    row_number BIGINT,
    sheet VARCHAR,
    cell VARCHAR,
    page_number BIGINT,
    passage VARCHAR
);

CREATE TABLE IF NOT EXISTS financial_events (
    event_id UUID PRIMARY KEY,
    kind VARCHAR NOT NULL,
    occurred_on DATE NOT NULL,
    party_ids VARCHAR[] NOT NULL,
    account_ids VARCHAR[] NOT NULL,
    user_id VARCHAR,
    document_id VARCHAR,
    net_amount DECIMAL(38, 9),
    tax_amount DECIMAL(38, 9),
    gross_amount DECIMAL(38, 9)
);

CREATE TABLE IF NOT EXISTS event_evidence (
    event_id UUID NOT NULL REFERENCES financial_events(event_id),
    evidence_id UUID NOT NULL REFERENCES evidence_refs(evidence_id),
    PRIMARY KEY (event_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS control_results (
    result_id UUID PRIMARY KEY,
    rule_id VARCHAR NOT NULL,
    rule_version VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    exposure_amount DECIMAL(38, 9),
    calculation_steps VARCHAR[] NOT NULL,
    parameters VARCHAR[] NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS result_evidence (
    result_id UUID NOT NULL REFERENCES control_results(result_id),
    evidence_id UUID NOT NULL REFERENCES evidence_refs(evidence_id),
    PRIMARY KEY (result_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS cases (
    case_id UUID PRIMARY KEY,
    title VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    financial_impact DECIMAL(38, 9),
    uncertainty VARCHAR,
    review_note VARCHAR,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS case_evidence (
    case_id UUID NOT NULL REFERENCES cases(case_id),
    evidence_id UUID NOT NULL REFERENCES evidence_refs(evidence_id),
    PRIMARY KEY (case_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS parsed_records (
    record_id UUID PRIMARY KEY,
    source_path VARCHAR NOT NULL REFERENCES source_files(source_path),
    table_name VARCHAR NOT NULL,
    row_number BIGINT NOT NULL CHECK (row_number >= 1),
    raw_row VARCHAR NOT NULL,
    raw_row_sha256 VARCHAR NOT NULL CHECK (length(raw_row_sha256) = 64),
    raw_values_json VARCHAR NOT NULL,
    evidence_id UUID NOT NULL REFERENCES evidence_refs(evidence_id)
);

CREATE TABLE IF NOT EXISTS parsed_fields (
    record_id UUID NOT NULL REFERENCES parsed_records(record_id),
    column_name VARCHAR NOT NULL,
    column_position BIGINT NOT NULL CHECK (column_position >= 0),
    raw_value VARCHAR NOT NULL,
    evidence_id UUID NOT NULL REFERENCES evidence_refs(evidence_id),
    PRIMARY KEY (record_id, column_position)
);

CREATE TABLE IF NOT EXISTS parse_reconciliations (
    reconciliation_id UUID PRIMARY KEY,
    source_path VARCHAR NOT NULL REFERENCES source_files(source_path),
    source_sha256 VARCHAR NOT NULL CHECK (length(source_sha256) = 64),
    status VARCHAR NOT NULL,
    source_row_count BIGINT NOT NULL CHECK (source_row_count >= 0),
    parsed_row_count BIGINT NOT NULL CHECK (parsed_row_count >= 0),
    warnings_json VARCHAR NOT NULL,
    errors_json VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS xlsx_workbooks (
    source_path VARCHAR PRIMARY KEY REFERENCES source_files(source_path),
    extraction_method VARCHAR NOT NULL,
    sheet_count BIGINT NOT NULL CHECK (sheet_count >= 1)
);

CREATE TABLE IF NOT EXISTS xlsx_sheets (
    sheet_id UUID PRIMARY KEY,
    source_path VARCHAR NOT NULL REFERENCES xlsx_workbooks(source_path),
    sheet_name VARCHAR NOT NULL,
    dimension VARCHAR NOT NULL,
    max_row BIGINT NOT NULL CHECK (max_row >= 1),
    max_column BIGINT NOT NULL CHECK (max_column >= 1),
    header_row BIGINT,
    headers_json VARCHAR NOT NULL,
    metadata_row_count BIGINT NOT NULL CHECK (metadata_row_count >= 0),
    parsed_record_count BIGINT NOT NULL CHECK (parsed_record_count >= 0),
    warnings_json VARCHAR NOT NULL,
    UNIQUE (source_path, sheet_name)
);

CREATE TABLE IF NOT EXISTS xlsx_cells (
    cell_id UUID PRIMARY KEY,
    sheet_id UUID NOT NULL REFERENCES xlsx_sheets(sheet_id),
    coordinate VARCHAR NOT NULL,
    row_number BIGINT NOT NULL CHECK (row_number >= 1),
    column_number BIGINT NOT NULL CHECK (column_number >= 1),
    raw_value VARCHAR NOT NULL,
    value_type VARCHAR NOT NULL,
    normalized_value VARCHAR,
    normalization_kind VARCHAR,
    extraction_method VARCHAR NOT NULL,
    formula VARCHAR,
    evidence_id UUID NOT NULL REFERENCES evidence_refs(evidence_id),
    UNIQUE (sheet_id, coordinate)
);

CREATE TABLE IF NOT EXISTS xlsx_metadata_rows (
    sheet_id UUID NOT NULL REFERENCES xlsx_sheets(sheet_id),
    row_number BIGINT NOT NULL CHECK (row_number >= 1),
    values_json VARCHAR NOT NULL,
    PRIMARY KEY (sheet_id, row_number)
);

CREATE TABLE IF NOT EXISTS xlsx_normalized_records (
    record_id UUID PRIMARY KEY,
    sheet_id UUID NOT NULL REFERENCES xlsx_sheets(sheet_id),
    row_number BIGINT NOT NULL CHECK (row_number >= 1),
    values_json VARCHAR NOT NULL,
    UNIQUE (sheet_id, row_number)
);

CREATE TABLE IF NOT EXISTS engagements (
    engagement_id UUID PRIMARY KEY,
    name VARCHAR NOT NULL,
    dossier_root VARCHAR NOT NULL,
    locale VARCHAR NOT NULL CHECK (locale IN ('de', 'en')),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS compilation_runs (
    run_id UUID PRIMARY KEY,
    engagement_id UUID NOT NULL REFERENCES engagements(engagement_id),
    status VARCHAR NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    error VARCHAR
);

CREATE TABLE IF NOT EXISTS run_source_files (
    run_id UUID NOT NULL REFERENCES compilation_runs(run_id),
    source_path VARCHAR NOT NULL,
    file_type VARCHAR NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    sha256 VARCHAR NOT NULL CHECK (length(sha256) = 64),
    PRIMARY KEY (run_id, source_path)
);

CREATE TABLE IF NOT EXISTS canonical_events (
    run_id UUID NOT NULL REFERENCES compilation_runs(run_id),
    event_id UUID NOT NULL,
    kind VARCHAR NOT NULL,
    occurred_on DATE NOT NULL,
    party_ids VARCHAR[] NOT NULL,
    account_ids VARCHAR[] NOT NULL,
    user_id VARCHAR,
    document_id VARCHAR,
    net_amount DECIMAL(38, 9),
    tax_amount DECIMAL(38, 9),
    gross_amount DECIMAL(38, 9),
    PRIMARY KEY (run_id, event_id)
);

CREATE TABLE IF NOT EXISTS canonical_event_evidence (
    run_id UUID NOT NULL,
    event_id UUID NOT NULL,
    evidence_id UUID NOT NULL,
    source_path VARCHAR NOT NULL,
    source_type VARCHAR NOT NULL,
    file_sha256 VARCHAR NOT NULL CHECK (length(file_sha256) = 64),
    raw_value VARCHAR NOT NULL,
    raw_value_sha256 VARCHAR NOT NULL CHECK (length(raw_value_sha256) = 64),
    normalized_value VARCHAR,
    extraction_method VARCHAR NOT NULL,
    row_number BIGINT,
    sheet VARCHAR,
    cell VARCHAR,
    page_number BIGINT,
    passage VARCHAR,
    PRIMARY KEY (run_id, event_id, evidence_id),
    FOREIGN KEY (run_id, event_id) REFERENCES canonical_events(run_id, event_id)
);
"""


def connect(database: str | Path = ":memory:") -> duckdb.DuckDBPyConnection:
    """Open a DuckDB database and create the foundational evidence schema."""

    connection = duckdb.connect(str(database))
    initialize_schema(connection)
    return connection


def initialize_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """Create idempotent tables for source, provenance, facts, results, and cases."""

    connection.execute(_SCHEMA)


@contextmanager
def engagement_run(
    connection: duckdb.DuckDBPyConnection,
    identity: EngagementIdentity,
    *,
    run_id: UUID | None = None,
) -> Iterator[UUID]:
    """Create an isolated run and atomically commit or roll back all run data."""

    current_run_id = run_id or uuid4()
    started_at = datetime.now(UTC)
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            """
            INSERT INTO engagements
                (engagement_id, name, dossier_root, locale, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (engagement_id) DO NOTHING
            """,
            [
                identity.engagement_id,
                identity.name,
                identity.dossier_root,
                identity.locale.value,
                started_at,
            ],
        )
        stored_identity = connection.execute(
            """
            SELECT dossier_root, locale
            FROM engagements
            WHERE engagement_id = ?
            """,
            [identity.engagement_id],
        ).fetchone()
        if stored_identity != (identity.dossier_root, identity.locale.value):
            raise ValueError(
                "engagement_id is already bound to a different dossier or locale"
            )
        connection.execute(
            """
            INSERT INTO compilation_runs
                (run_id, engagement_id, status, started_at)
            VALUES (?, ?, 'running', ?)
            """,
            [current_run_id, identity.engagement_id, started_at],
        )
        yield current_run_id
        connection.execute(
            """
            UPDATE compilation_runs
            SET status = 'completed', completed_at = ?
            WHERE run_id = ?
            """,
            [datetime.now(UTC), current_run_id],
        )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def store_run_source_files(
    connection: duckdb.DuckDBPyConnection,
    run_id: UUID,
    sources: tuple[SourceFile, ...],
) -> None:
    """Store an immutable source inventory scoped to one compilation run."""

    for source in sources:
        connection.execute(
            """
            INSERT INTO run_source_files
                (run_id, source_path, file_type, byte_size, sha256)
            VALUES (?, ?, ?, ?, ?)
            """,
            [run_id, source.path, source.file_type, source.byte_size, source.sha256],
        )


def store_canonical_events(
    connection: duckdb.DuckDBPyConnection,
    run_id: UUID,
    events: tuple[FinancialEvent, ...],
) -> None:
    """Persist mapped events and self-contained exact provenance for one run."""

    for event in events:
        connection.execute(
            """
            INSERT INTO canonical_events
                (run_id, event_id, kind, occurred_on, party_ids, account_ids,
                 user_id, document_id, net_amount, tax_amount, gross_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run_id,
                event.event_id,
                event.kind,
                event.occurred_on,
                list(event.party_ids),
                list(event.account_ids),
                event.user_id,
                event.document_id,
                event.net_amount,
                event.tax_amount,
                event.gross_amount,
            ],
        )
        for evidence in event.evidence_refs:
            connection.execute(
                """
                INSERT INTO canonical_event_evidence
                    (run_id, event_id, evidence_id, source_path, source_type,
                     file_sha256, raw_value, raw_value_sha256, normalized_value,
                     extraction_method, row_number, sheet, cell, page_number, passage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    event.event_id,
                    evidence.evidence_id,
                    evidence.source_path,
                    evidence.source_type.value,
                    evidence.file_sha256,
                    evidence.raw_value,
                    evidence.raw_value_sha256,
                    evidence.normalized_value,
                    evidence.extraction_method,
                    evidence.row,
                    evidence.sheet,
                    evidence.cell,
                    evidence.page,
                    evidence.passage,
                ],
            )


def store_source_files(
    connection: duckdb.DuckDBPyConnection, sources: tuple[SourceFile, ...]
) -> None:
    """Persist the complete discovered-file inventory before any parsing begins."""

    inventoried_at = datetime.now(UTC)
    for source in sources:
        connection.execute(
            """
            INSERT INTO source_files (source_path, file_type, byte_size, sha256, inventoried_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (source_path) DO UPDATE SET
                file_type = excluded.file_type,
                byte_size = excluded.byte_size,
                sha256 = excluded.sha256,
                inventoried_at = excluded.inventoried_at
            """,
            [source.path, source.file_type, source.byte_size, source.sha256, inventoried_at],
        )


def _store_evidence(
    connection: duckdb.DuckDBPyConnection, evidence: EvidenceRef
) -> None:
    connection.execute(
        """
        INSERT INTO evidence_refs
            (evidence_id, source_path, source_type, file_sha256, raw_value,
             raw_value_sha256, normalized_value, extraction_method,
             row_number, sheet, cell, page_number, passage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            evidence.evidence_id,
            evidence.source_path,
            evidence.source_type.value,
            evidence.file_sha256,
            evidence.raw_value,
            evidence.raw_value_sha256,
            evidence.normalized_value,
            evidence.extraction_method,
            evidence.row,
            evidence.sheet,
            evidence.cell,
            evidence.page,
            evidence.passage,
        ],
    )


def _clear_parsed_source(
    connection: duckdb.DuckDBPyConnection, source_path: str
) -> None:
    evidence_ids = [
        row[0]
        for row in connection.execute(
            """
            SELECT evidence_id FROM parsed_records WHERE source_path = ?
            UNION
            SELECT parsed_fields.evidence_id
            FROM parsed_fields
            JOIN parsed_records USING (record_id)
            WHERE source_path = ?
            """,
            [source_path, source_path],
        ).fetchall()
    ]
    connection.execute(
        "DELETE FROM parsed_fields WHERE record_id IN "
        "(SELECT record_id FROM parsed_records WHERE source_path = ?)",
        [source_path],
    )
    connection.execute("DELETE FROM parsed_records WHERE source_path = ?", [source_path])
    for evidence_id in evidence_ids:
        connection.execute("DELETE FROM evidence_refs WHERE evidence_id = ?", [evidence_id])


def store_parsed_table(
    connection: duckdb.DuckDBPyConnection, table: ParsedTable
) -> int:
    """Persist source rows, fields, raw values, and evidence, then reconcile the row count."""

    source = table.source_file
    store_source_files(connection, (source,))
    _clear_parsed_source(connection, source.path)
    for record in table.records:
        _store_evidence(connection, record.evidence_ref)
        connection.execute(
            """
            INSERT INTO parsed_records
                (record_id, source_path, table_name, row_number, raw_row,
                 raw_row_sha256, raw_values_json, evidence_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record.record_id,
                record.source_path,
                record.table_name,
                record.row_number,
                record.raw_row,
                record.raw_row_sha256,
                json.dumps([field.raw_value for field in record.fields], ensure_ascii=False),
                record.evidence_ref.evidence_id,
            ],
        )
        for field in record.fields:
            evidence = field.evidence_ref
            _store_evidence(connection, evidence)
            connection.execute(
                """
                INSERT INTO parsed_fields
                    (record_id, column_name, column_position, raw_value, evidence_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    record.record_id,
                    field.column_name,
                    field.column_position,
                    field.raw_value,
                    evidence.evidence_id,
                ],
            )
    stored_count = connection.execute(
        "SELECT count(*) FROM parsed_records WHERE source_path = ?", [source.path]
    ).fetchone()[0]
    if stored_count != table.parsed_row_count:
        raise RuntimeError(
            f"stored row count for {source.path} is {stored_count}, "
            f"expected {table.parsed_row_count}"
        )
    return stored_count


def store_parse_reconciliation(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_path: str,
    source_sha256: str,
    status: str,
    source_row_count: int,
    parsed_row_count: int,
    warnings: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
) -> None:
    """Persist a success or failure count comparison for one declared source."""

    connection.execute("DELETE FROM parse_reconciliations WHERE source_path = ?", [source_path])
    connection.execute(
        """
        INSERT INTO parse_reconciliations
            (reconciliation_id, source_path, source_sha256, status,
             source_row_count, parsed_row_count, warnings_json, errors_json, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            uuid4(),
            source_path,
            source_sha256,
            status,
            source_row_count,
            parsed_row_count,
            json.dumps(warnings, ensure_ascii=False),
            json.dumps(errors, ensure_ascii=False),
            datetime.now(UTC),
        ],
    )


def _clear_xlsx_source(
    connection: duckdb.DuckDBPyConnection, source_path: str
) -> None:
    evidence_ids = [
        row[0]
        for row in connection.execute(
            """
            SELECT xlsx_cells.evidence_id
            FROM xlsx_cells
            JOIN xlsx_sheets USING (sheet_id)
            WHERE source_path = ?
            """,
            [source_path],
        ).fetchall()
    ]
    sheet_ids = [
        row[0]
        for row in connection.execute(
            "SELECT sheet_id FROM xlsx_sheets WHERE source_path = ?", [source_path]
        ).fetchall()
    ]
    for sheet_id in sheet_ids:
        connection.execute("DELETE FROM xlsx_metadata_rows WHERE sheet_id = ?", [sheet_id])
        connection.execute("DELETE FROM xlsx_normalized_records WHERE sheet_id = ?", [sheet_id])
        connection.execute("DELETE FROM xlsx_cells WHERE sheet_id = ?", [sheet_id])
    connection.execute("DELETE FROM xlsx_sheets WHERE source_path = ?", [source_path])
    connection.execute("DELETE FROM xlsx_workbooks WHERE source_path = ?", [source_path])
    for evidence_id in evidence_ids:
        connection.execute("DELETE FROM evidence_refs WHERE evidence_id = ?", [evidence_id])


def store_xlsx_workbook(
    connection: duckdb.DuckDBPyConnection, workbook: XlsxWorkbook
) -> int:
    """Persist every XLSX sheet/cell plus metadata and normalized table records."""

    source = workbook.source_file
    store_source_files(connection, (source,))
    _clear_xlsx_source(connection, source.path)
    connection.execute(
        """
        INSERT INTO xlsx_workbooks (source_path, extraction_method, sheet_count)
        VALUES (?, ?, ?)
        """,
        [source.path, workbook.extraction_method, len(workbook.sheets)],
    )
    parsed_record_count = 0
    for sheet in workbook.sheets:
        connection.execute(
            """
            INSERT INTO xlsx_sheets
                (sheet_id, source_path, sheet_name, dimension, max_row, max_column,
                 header_row, headers_json, metadata_row_count, parsed_record_count,
                 warnings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                sheet.sheet_id,
                source.path,
                sheet.name,
                sheet.dimension,
                sheet.max_row,
                sheet.max_column,
                sheet.header_row,
                json.dumps(sheet.headers, ensure_ascii=False),
                len(sheet.metadata_row_numbers),
                len(sheet.records),
                json.dumps(
                    [warning.model_dump(mode="json") for warning in sheet.warnings],
                    ensure_ascii=False,
                ),
            ],
        )
        cells_by_row: dict[int, list[str]] = {}
        for cell in sheet.cells:
            _store_evidence(connection, cell.evidence_ref)
            connection.execute(
                """
                INSERT INTO xlsx_cells
                    (cell_id, sheet_id, coordinate, row_number, column_number,
                     raw_value, value_type, normalized_value, normalization_kind,
                     extraction_method, formula, evidence_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    cell.cell_id,
                    sheet.sheet_id,
                    cell.coordinate,
                    cell.row_number,
                    cell.column_number,
                    cell.raw_value,
                    cell.value_type,
                    cell.normalized_value,
                    cell.normalization_kind,
                    cell.extraction_method,
                    cell.formula,
                    cell.evidence_ref.evidence_id,
                ],
            )
            cells_by_row.setdefault(cell.row_number, []).append(cell.raw_value)
        for row_number in sheet.metadata_row_numbers:
            connection.execute(
                """
                INSERT INTO xlsx_metadata_rows (sheet_id, row_number, values_json)
                VALUES (?, ?, ?)
                """,
                [
                    sheet.sheet_id,
                    row_number,
                    json.dumps(cells_by_row[row_number], ensure_ascii=False),
                ],
            )
        for record in sheet.records:
            connection.execute(
                """
                INSERT INTO xlsx_normalized_records
                    (record_id, sheet_id, row_number, values_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    record.record_id,
                    sheet.sheet_id,
                    record.row_number,
                    json.dumps(dict(record.values), ensure_ascii=False),
                ],
            )
        parsed_record_count += len(sheet.records)

    stored_count = connection.execute(
        """
        SELECT count(*)
        FROM xlsx_normalized_records
        JOIN xlsx_sheets USING (sheet_id)
        WHERE source_path = ?
        """,
        [source.path],
    ).fetchone()[0]
    if stored_count != parsed_record_count:
        raise RuntimeError(
            f"stored XLSX record count for {source.path} is {stored_count}, "
            f"expected {parsed_record_count}"
        )
    return stored_count
