"""Dossier-level orchestration and machine-readable compilation reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import duckdb
from pydantic import Field

from audit_compiler.adapters.gdpdu import (
    DelimitedParseError,
    parse_delimited_table,
    parse_gdpdu_index,
)
from audit_compiler.adapters.xlsx import parse_xlsx_workbook
from audit_compiler.duckdb_store import (
    connect,
    engagement_run,
    store_canonical_events,
    store_parse_reconciliation,
    store_parsed_table,
    store_run_source_files,
    store_source_files,
    store_xlsx_workbook,
)
from audit_compiler.inventory import SourceFile, inventory_dossier
from audit_compiler.ir.canonical import map_canonical_events
from audit_compiler.ir.dossier import LoadedDossier, load_dossier
from audit_compiler.models import DataLocale, EngagementIdentity, FinancialEvent, ImmutableModel


class ParsingStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class CompilationIssue(ImmutableModel):
    """A warning or error with all available source provenance."""

    message: str = Field(min_length=1)
    source_path: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    row_number: int | None = Field(default=None, ge=1)
    sheet_name: str | None = None
    cell: str | None = None
    raw_row: str | None = None
    raw_row_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SheetCompilationReport(ImmutableModel):
    sheet_name: str
    dimension: str
    max_row: int = Field(ge=1)
    max_column: int = Field(ge=1)
    detected_header_row: int | None = Field(default=None, ge=1)
    parsed_record_count: int = Field(ge=0)
    warnings: tuple[CompilationIssue, ...] = ()


class SourceCompilationReport(ImmutableModel):
    source_path: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parsing_status: ParsingStatus
    encoding: str | None = None
    extraction_method: str | None = None
    source_row_count: int = Field(ge=0)
    parsed_row_count: int = Field(ge=0)
    sheets: tuple[SheetCompilationReport, ...] = ()
    warnings: tuple[CompilationIssue, ...] = ()
    errors: tuple[CompilationIssue, ...] = ()


class CompilationReport(ImmutableModel):
    schema_version: str = "1.0"
    engagement_id: UUID
    run_id: UUID
    locale: DataLocale
    compiled_at: datetime
    database_path: str
    discovered_files: tuple[SourceFile, ...]
    parsing_status: ParsingStatus
    source_row_count: int = Field(ge=0)
    parsed_row_count: int = Field(ge=0)
    canonical_event_count: int = Field(default=0, ge=0)
    sources: tuple[SourceCompilationReport, ...]
    warnings: tuple[CompilationIssue, ...] = ()
    errors: tuple[CompilationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class CompilationRuntime:
    """Canonical output shared by CLI, API, controls, and storage consumers."""

    report: CompilationReport
    dossier: LoadedDossier
    events: tuple[FinancialEvent, ...]


def _relative_database_path(database: Path, dossier_root: Path) -> str | None:
    try:
        return database.resolve().relative_to(dossier_root).as_posix()
    except ValueError:
        return None


def _issue_from_parse_error(error: DelimitedParseError) -> CompilationIssue:
    return CompilationIssue(
        message=str(error),
        source_path=error.source_path,
        source_sha256=error.source_sha256,
        row_number=error.row_number,
        raw_row=error.raw_row,
        raw_row_sha256=error.raw_row_sha256,
    )


def _compile_sources(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    database_path: Path,
    *,
    identity: EngagementIdentity,
    run_id: UUID,
) -> CompilationReport:
    """Compile native sources on an existing run transaction."""

    manifest = inventory_dossier(root)
    database_relative = _relative_database_path(database_path, root)
    database_artifacts = (
        {database_relative, f"{database_relative}.wal"}
        if database_relative is not None
        else set()
    )
    discovered_files = tuple(
        source for source in manifest.files if source.path not in database_artifacts
    )

    store_source_files(connection, discovered_files)

    source_reports: list[SourceCompilationReport] = []
    warnings: list[CompilationIssue] = []
    errors: list[CompilationIssue] = []
    parsed_source_paths: set[str] = set()
    valid_definitions = []
    index_errors: list[CompilationIssue] = []

    for source in discovered_files:
        if source.file_type != "xlsx":
            continue
        try:
            workbook = parse_xlsx_workbook(
                root / source.path,
                dossier_root=root,
                locale=identity.locale.value,
            )
            stored_count = store_xlsx_workbook(connection, workbook)
            workbook_source_rows = sum(sheet.max_row for sheet in workbook.sheets)
            sheet_reports: list[SheetCompilationReport] = []
            workbook_issues: list[CompilationIssue] = []
            for sheet in workbook.sheets:
                sheet_issues = tuple(
                    CompilationIssue(
                        message=warning.message,
                        source_path=source.path,
                        source_sha256=source.sha256,
                        row_number=warning.row_number,
                        sheet_name=warning.sheet_name,
                        cell=warning.cell,
                    )
                    for warning in sheet.warnings
                )
                workbook_issues.extend(sheet_issues)
                sheet_reports.append(
                    SheetCompilationReport(
                        sheet_name=sheet.name,
                        dimension=sheet.dimension,
                        max_row=sheet.max_row,
                        max_column=sheet.max_column,
                        detected_header_row=sheet.header_row,
                        parsed_record_count=len(sheet.records),
                        warnings=sheet_issues,
                    )
                )
            warnings.extend(workbook_issues)
            store_parse_reconciliation(
                connection,
                source_path=source.path,
                source_sha256=source.sha256,
                status=ParsingStatus.SUCCESS.value,
                source_row_count=workbook_source_rows,
                parsed_row_count=stored_count,
                warnings=tuple(issue.message for issue in workbook_issues),
            )
            source_reports.append(
                SourceCompilationReport(
                    source_path=source.path,
                    source_sha256=source.sha256,
                    parsing_status=ParsingStatus.SUCCESS,
                    extraction_method=workbook.extraction_method,
                    source_row_count=workbook_source_rows,
                    parsed_row_count=stored_count,
                    sheets=tuple(sheet_reports),
                    warnings=tuple(workbook_issues),
                )
            )
        except Exception as exc:
            issue = CompilationIssue(
                message=str(exc),
                source_path=source.path,
                source_sha256=source.sha256,
            )
            errors.append(issue)
            store_parse_reconciliation(
                connection,
                source_path=source.path,
                source_sha256=source.sha256,
                status=ParsingStatus.FAILED.value,
                source_row_count=0,
                parsed_row_count=0,
                errors=(str(exc),),
            )
            source_reports.append(
                SourceCompilationReport(
                    source_path=source.path,
                    source_sha256=source.sha256,
                    parsing_status=ParsingStatus.FAILED,
                    source_row_count=0,
                    parsed_row_count=0,
                    errors=(issue,),
                )
            )

    for source in discovered_files:
        if source.file_type != "xml":
            continue
        index_path = root / source.path
        try:
            definitions = parse_gdpdu_index(index_path, dossier_root=root)
        except (OSError, ValueError) as exc:
            index_errors.append(
                CompilationIssue(
                    message=str(exc),
                    source_path=source.path,
                    source_sha256=source.sha256,
                )
            )
            continue
        valid_definitions.extend(definitions)

    delimited_files = tuple(
        source for source in discovered_files if source.file_type in {"text", "csv"}
    )
    if not valid_definitions and delimited_files:
        if index_errors:
            errors.extend(index_errors)
        else:
            errors.append(CompilationIssue(message="no GDPdU XML metadata file was discovered"))

    inventory_by_path = {source.path: source for source in discovered_files}
    for definition in valid_definitions:
        if definition.source_path in parsed_source_paths:
            warning = CompilationIssue(
                message="source is declared more than once; later declaration was skipped",
                source_path=definition.source_path,
            )
            warnings.append(warning)
            continue
        parsed_source_paths.add(definition.source_path)
        source = inventory_by_path.get(definition.source_path)
        if source is None:
            issue = CompilationIssue(
                message="GDPdU metadata references a source file that was not discovered",
                source_path=definition.source_path,
            )
            errors.append(issue)
            source_reports.append(
                SourceCompilationReport(
                    source_path=definition.source_path,
                    parsing_status=ParsingStatus.FAILED,
                    source_row_count=0,
                    parsed_row_count=0,
                    errors=(issue,),
                )
            )
            continue

        try:
            table = parse_delimited_table(
                root / definition.source_path,
                definition,
                dossier_root=root,
            )
            stored_count = store_parsed_table(connection, table)
            store_parse_reconciliation(
                connection,
                source_path=source.path,
                source_sha256=source.sha256,
                status=ParsingStatus.SUCCESS.value,
                source_row_count=table.source_row_count,
                parsed_row_count=stored_count,
            )
            source_reports.append(
                SourceCompilationReport(
                    source_path=source.path,
                    source_sha256=source.sha256,
                    parsing_status=ParsingStatus.SUCCESS,
                    encoding=table.detected_encoding,
                    source_row_count=table.source_row_count,
                    parsed_row_count=stored_count,
                )
            )
        except DelimitedParseError as exc:
            issue = _issue_from_parse_error(exc)
            errors.append(issue)
            store_parse_reconciliation(
                connection,
                source_path=source.path,
                source_sha256=source.sha256,
                status=ParsingStatus.FAILED.value,
                source_row_count=exc.source_row_count,
                parsed_row_count=exc.parsed_row_count,
                errors=(str(exc),),
            )
            source_reports.append(
                SourceCompilationReport(
                    source_path=source.path,
                    source_sha256=source.sha256,
                    parsing_status=ParsingStatus.FAILED,
                    source_row_count=exc.source_row_count,
                    parsed_row_count=exc.parsed_row_count,
                    errors=(issue,),
                )
            )
        except (OSError, UnicodeError, ValueError) as exc:
            issue = CompilationIssue(
                message=str(exc),
                source_path=source.path,
                source_sha256=source.sha256,
            )
            errors.append(issue)
            store_parse_reconciliation(
                connection,
                source_path=source.path,
                source_sha256=source.sha256,
                status=ParsingStatus.FAILED.value,
                source_row_count=0,
                parsed_row_count=0,
                errors=(str(exc),),
            )
            source_reports.append(
                SourceCompilationReport(
                    source_path=source.path,
                    source_sha256=source.sha256,
                    parsing_status=ParsingStatus.FAILED,
                    source_row_count=0,
                    parsed_row_count=0,
                    errors=(issue,),
                )
            )

    for source in discovered_files:
        if source.file_type not in {"text", "csv"} or source.path in parsed_source_paths:
            continue
        issue = CompilationIssue(
            message="delimited file is not declared by discovered GDPdU metadata",
            source_path=source.path,
            source_sha256=source.sha256,
        )
        warnings.append(issue)
        source_reports.append(
            SourceCompilationReport(
                source_path=source.path,
                source_sha256=source.sha256,
                parsing_status=ParsingStatus.SKIPPED,
                source_row_count=0,
                parsed_row_count=0,
                warnings=(issue,),
            )
        )

    for source in discovered_files:
        if source.file_type != "xls":
            continue
        issue = CompilationIssue(
            message="legacy XLS workbooks are not supported by the XLSX adapter",
            source_path=source.path,
            source_sha256=source.sha256,
        )
        warnings.append(issue)
        source_reports.append(
            SourceCompilationReport(
                source_path=source.path,
                source_sha256=source.sha256,
                parsing_status=ParsingStatus.SKIPPED,
                source_row_count=0,
                parsed_row_count=0,
                warnings=(issue,),
            )
        )

    successful = sum(report.parsing_status == ParsingStatus.SUCCESS for report in source_reports)
    status = (
        ParsingStatus.SUCCESS
        if not errors
        else ParsingStatus.PARTIAL
        if successful
        else ParsingStatus.FAILED
    )
    return CompilationReport(
        engagement_id=identity.engagement_id,
        run_id=run_id,
        locale=identity.locale,
        compiled_at=datetime.now(UTC),
        database_path=str(database_path),
        discovered_files=discovered_files,
        parsing_status=status,
        source_row_count=sum(report.source_row_count for report in source_reports),
        parsed_row_count=sum(report.parsed_row_count for report in source_reports),
        sources=tuple(source_reports),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def compile_runtime(
    dossier_directory: Path,
    *,
    database: Path | None = None,
    name: str | None = None,
    locale: DataLocale | str = DataLocale.DE,
    engagement_id: UUID | None = None,
) -> CompilationRuntime:
    """Compile one isolated run and return the canonical in-memory and stored forms."""

    root = dossier_directory.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"dossier path is not a directory: {dossier_directory}")
    database_path = (
        database or root / ".admissible" / "admissible.duckdb"
    ).expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    explicit_locale = DataLocale(locale)
    stable_id = engagement_id or uuid5(NAMESPACE_URL, f"evidentia:{root.as_posix()}")
    identity = EngagementIdentity(
        engagement_id=stable_id,
        name=name or root.name,
        dossier_root=root.as_posix(),
        locale=explicit_locale,
    )
    connection = connect(database_path)
    try:
        with engagement_run(connection, identity) as run_id:
            report = _compile_sources(
                connection,
                root,
                database_path,
                identity=identity,
                run_id=run_id,
            )
            dossier = load_dossier(root, locale=explicit_locale)
            events = map_canonical_events(dossier)
            report = report.model_copy(
                update={"canonical_event_count": len(events)}
            )
            store_run_source_files(connection, run_id, report.discovered_files)
            store_canonical_events(connection, run_id, events)
        return CompilationRuntime(report=report, dossier=dossier, events=events)
    finally:
        connection.close()


def compile_dossier(
    dossier_directory: Path,
    *,
    database: Path | None = None,
    name: str | None = None,
    locale: DataLocale | str = DataLocale.DE,
    engagement_id: UUID | None = None,
) -> CompilationReport:
    """Backward-compatible report API over the canonical compiler runtime."""

    return compile_runtime(
        dossier_directory,
        database=database,
        name=name,
        locale=locale,
        engagement_id=engagement_id,
    ).report
