"""Dossier-level orchestration and machine-readable compilation reporting."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from audit_compiler.adapters.gdpdu import (
    DelimitedParseError,
    parse_delimited_table,
    parse_gdpdu_index,
)
from audit_compiler.adapters.xlsx import parse_xlsx_workbook
from audit_compiler.duckdb_store import (
    connect,
    store_parse_reconciliation,
    store_parsed_table,
    store_source_files,
    store_xlsx_workbook,
)
from audit_compiler.inventory import SourceFile, inventory_dossier
from audit_compiler.models import ImmutableModel


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
    compiled_at: datetime
    database_path: str
    discovered_files: tuple[SourceFile, ...]
    parsing_status: ParsingStatus
    source_row_count: int = Field(ge=0)
    parsed_row_count: int = Field(ge=0)
    sources: tuple[SourceCompilationReport, ...]
    warnings: tuple[CompilationIssue, ...] = ()
    errors: tuple[CompilationIssue, ...] = ()


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


def compile_dossier(
    dossier_directory: Path, *, database: Path | None = None
) -> CompilationReport:
    """Compile every GDPdU-declared source and continue reporting after source failures."""

    root = dossier_directory.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"dossier path is not a directory: {dossier_directory}")
    database_path = (database or root / ".admissible" / "admissible.duckdb").expanduser().resolve()
    manifest = inventory_dossier(root)
    database_relative = _relative_database_path(database_path, root)
    discovered_files = tuple(
        source for source in manifest.files if source.path != database_relative
    )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(database_path)
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
            workbook = parse_xlsx_workbook(root / source.path, dossier_root=root)
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

    connection.close()
    successful = sum(report.parsing_status == ParsingStatus.SUCCESS for report in source_reports)
    status = (
        ParsingStatus.SUCCESS
        if not errors
        else ParsingStatus.PARTIAL
        if successful
        else ParsingStatus.FAILED
    )
    return CompilationReport(
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
