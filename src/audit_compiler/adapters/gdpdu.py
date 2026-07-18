"""Native GDPdU metadata and semicolon-delimited export parsing."""

from __future__ import annotations

import codecs
import csv
import io
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Annotated
from uuid import UUID, uuid4
from xml.etree import ElementTree

from pydantic import Field, model_validator

from audit_compiler.inventory import SourceFile, infer_file_type, sha256_file
from audit_compiler.models import EvidenceRef, ImmutableModel, SourceType

_TABLE_TAGS = {"dataset", "table", "tabelle"}
_FIELD_TAGS = {"field", "column", "feld", "spalte"}
_PATH_NAMES = {"file", "filename", "filepath", "path", "datafile", "datei", "url"}
_ENCODING_NAMES = {"encoding", "charset", "codepage"}
_DELIMITER_NAMES = {"delimiter", "separator", "trennzeichen", "columndelimiter"}
_NAME_NAMES = {"name", "columnname", "fieldname", "bezeichnung"}
_POSITION_NAMES = {"position", "index", "ordinal", "number", "nr"}

EvidenceRefs = Annotated[tuple[EvidenceRef, ...], Field(min_length=1)]
Columns = Annotated[tuple["GdpduColumn", ...], Field(min_length=1)]
Fields = Annotated[tuple["ParsedField", ...], Field(min_length=1)]


class GdpduColumn(ImmutableModel):
    """A column supplied by GDPdU metadata, with its metadata provenance."""

    name: str = Field(min_length=1)
    position: int = Field(ge=0)
    evidence_ref: EvidenceRef


class GdpduTableDefinition(ImmutableModel):
    """Metadata needed to parse one GDPdU data file."""

    table_name: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    delimiter: str = Field(default=";", min_length=1, max_length=1)
    encoding: str | None = None
    columns: Columns
    metadata_evidence_refs: EvidenceRefs


class ParsedField(ImmutableModel):
    """One raw source field mapped to a GDPdU column definition."""

    column_name: str = Field(min_length=1)
    column_position: int = Field(ge=0)
    raw_value: str
    evidence_ref: EvidenceRef


class ParsedRecord(ImmutableModel):
    """A source record preserving every raw field and its row-level provenance."""

    record_id: UUID = Field(default_factory=uuid4)
    table_name: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    row_number: int = Field(ge=1)
    raw_row: str
    raw_row_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_ref: EvidenceRef
    fields: Fields

    @property
    def named_values(self) -> dict[str, str]:
        """Return a fresh named view while the stored representation remains immutable."""

        return {field.column_name: field.raw_value for field in self.fields}


class ParsedTable(ImmutableModel):
    """The parsed output and source-to-parser row-count reconciliation for one file."""

    definition: GdpduTableDefinition
    source_file: SourceFile
    detected_encoding: str = Field(min_length=1)
    records: tuple[ParsedRecord, ...]
    source_row_count: int = Field(ge=0)
    parsed_row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def reconcile_counts(self) -> ParsedTable:
        if self.source_row_count != self.parsed_row_count:
            raise ValueError("source and parsed row counts differ")
        if self.parsed_row_count != len(self.records):
            raise ValueError("parsed row count does not match parsed records")
        return self


class GdpduCompilation(ImmutableModel):
    """An immutable GDPdU compile result containing only native parser output."""

    index_source_path: str = Field(min_length=1)
    index_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    compiled_at: datetime
    tables: tuple[ParsedTable, ...]


def _local_name(value: str) -> str:
    return value.rsplit("}", maxsplit=1)[-1].lower()


def _attribute_or_child(element: ElementTree.Element, names: set[str]) -> str | None:
    for key, value in element.attrib.items():
        if _local_name(key) in names and value.strip():
            return value.strip()
    for child in element:
        if _local_name(child.tag) in names and child.text and child.text.strip():
            return child.text.strip()
    return None


def _attribute_or_descendant(element: ElementTree.Element, names: set[str]) -> str | None:
    direct = _attribute_or_child(element, names)
    if direct is not None:
        return direct
    for descendant in element.iter():
        if descendant is element:
            continue
        if _local_name(descendant.tag) in names and descendant.text and descendant.text.strip():
            return descendant.text.strip()
    return None


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or normalized in {"", "."}:
        raise ValueError(f"GDPdU source path is not dossier-relative: {value!r}")
    return path.as_posix()


def _source_path(path: Path, dossier_root: Path) -> str:
    try:
        return path.resolve().relative_to(dossier_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"source path is outside the supplied dossier: {path}") from exc


def _metadata_evidence(
    *, index_path: Path, dossier_root: Path, index_sha256: str, raw_value: str, passage: str
) -> EvidenceRef:
    return EvidenceRef(
        source_path=_source_path(index_path, dossier_root),
        source_type=SourceType.XML_NODE,
        file_sha256=index_sha256,
        raw_value=raw_value,
        passage=passage,
    )


def _columns_for(
    element: ElementTree.Element,
    *,
    index_path: Path,
    dossier_root: Path,
    index_sha256: str,
) -> tuple[GdpduColumn, ...]:
    fields: list[tuple[int | None, str, EvidenceRef]] = []
    for field in element.iter():
        if _local_name(field.tag) not in _FIELD_TAGS:
            continue
        name = _attribute_or_child(field, _NAME_NAMES)
        if not name:
            continue
        position_text = _attribute_or_child(field, _POSITION_NAMES)
        position = int(position_text) if position_text is not None else None
        evidence = _metadata_evidence(
            index_path=index_path,
            dossier_root=dossier_root,
            index_sha256=index_sha256,
            raw_value=name,
            passage=f"column:{name}",
        )
        fields.append((position, name, evidence))
    if not fields:
        return ()

    # GDPdU metadata commonly uses one-based positions; absent positions follow XML order.
    if any(position is not None for position, _, _ in fields):
        if any(position is None for position, _, _ in fields):
            raise ValueError("GDPdU column positions must be supplied for every column or none")
        if len({position for position, _, _ in fields}) != len(fields):
            raise ValueError("GDPdU column positions must be unique")
        ordered = sorted(fields, key=lambda item: item[0])
        positions = [position for position, _, _ in ordered]
        assert all(position is not None for position in positions)
        if positions == list(range(len(fields))):
            offset = 0
        elif positions == list(range(1, len(fields) + 1)):
            offset = 1
        else:
            raise ValueError("GDPdU column positions must be contiguous and zero- or one-based")
        return tuple(
            GdpduColumn(name=name, position=position - offset, evidence_ref=evidence)
            for position, name, evidence in ordered
        )
    return tuple(
        GdpduColumn(name=name, position=position, evidence_ref=evidence)
        for position, (_, name, evidence) in enumerate(fields)
    )


def parse_gdpdu_index(
    index_path: Path, *, dossier_root: Path | None = None
) -> tuple[GdpduTableDefinition, ...]:
    """Read GDPdU XML metadata and return file-to-column mappings.

    The parser accepts common attribute or child-element forms for a data-file path,
    charset, delimiter, and field definitions. It deliberately rejects incomplete
    mappings instead of inferring columns from a sample row.
    """

    index_path = index_path.expanduser().resolve()
    root = (dossier_root or index_path.parent).expanduser().resolve()
    index_sha256 = sha256_file(index_path)
    try:
        document = ElementTree.fromstring(index_path.read_bytes())
    except ElementTree.ParseError as exc:
        raise ValueError(f"invalid GDPdU index XML: {index_path}") from exc

    definitions: list[GdpduTableDefinition] = []
    for element in document.iter():
        if _local_name(element.tag) not in _TABLE_TAGS:
            continue
        source = _attribute_or_descendant(element, _PATH_NAMES)
        if not source:
            continue
        columns = _columns_for(
            element,
            index_path=index_path,
            dossier_root=root,
            index_sha256=index_sha256,
        )
        if not columns:
            continue
        table_name = _attribute_or_child(element, {"name", "tablename", "table"}) or source
        encoding = _attribute_or_descendant(element, _ENCODING_NAMES)
        delimiter = _attribute_or_descendant(element, _DELIMITER_NAMES) or ";"
        source_path = _safe_relative_path(source)
        source_evidence = _metadata_evidence(
            index_path=index_path,
            dossier_root=root,
            index_sha256=index_sha256,
            raw_value=source,
            passage=f"data-file:{source}",
        )
        definitions.append(
            GdpduTableDefinition(
                table_name=table_name,
                source_path=source_path,
                delimiter=delimiter,
                encoding=encoding,
                columns=columns,
                metadata_evidence_refs=(
                    source_evidence,
                    *(column.evidence_ref for column in columns),
                ),
            )
        )
    if not definitions:
        raise ValueError("GDPdU index contains no table with a source file and field mapping")
    unique_definitions: dict[str, GdpduTableDefinition] = {}
    for definition in definitions:
        existing = unique_definitions.get(definition.source_path)
        if existing is not None:
            existing_columns = tuple(column.name for column in existing.columns)
            new_columns = tuple(column.name for column in definition.columns)
            if existing_columns != new_columns:
                raise ValueError(
                    f"GDPdU index defines conflicting columns for {definition.source_path}"
                )
        # Prefer the innermost definition encountered later in document order.
        unique_definitions[definition.source_path] = definition
    return tuple(unique_definitions.values())


def _decode_text(raw_bytes: bytes, declared_encoding: str | None) -> tuple[str, str]:
    if declared_encoding:
        try:
            encoding = codecs.lookup(declared_encoding).name
        except LookupError as exc:
            raise ValueError(f"unsupported declared encoding: {declared_encoding!r}") from exc
        if encoding == "utf-8" and raw_bytes.startswith(codecs.BOM_UTF8):
            return raw_bytes.decode("utf-8-sig", errors="strict"), "utf-8-sig"
        return raw_bytes.decode(encoding, errors="strict"), encoding

    if raw_bytes.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw_bytes.decode("utf-16", errors="strict"), "utf-16"
    if raw_bytes.startswith(codecs.BOM_UTF8):
        return raw_bytes.decode("utf-8-sig", errors="strict"), "utf-8-sig"
    try:
        return raw_bytes.decode("utf-8", errors="strict"), "utf-8"
    except UnicodeDecodeError:
        # Windows-1252 is a common GDPdU export fallback. Do not silently use a
        # universal single-byte decoder such as latin-1 for arbitrary binary input.
        try:
            return raw_bytes.decode("cp1252", errors="strict"), "cp1252"
        except UnicodeDecodeError as exc:
            raise ValueError("could not safely detect text encoding") from exc


class DelimitedParseError(ValueError):
    """A parse failure carrying the exact source record that could not be admitted."""

    def __init__(
        self,
        message: str,
        *,
        source_path: str,
        source_sha256: str,
        row_number: int | None,
        raw_row: str | None,
        source_row_count: int,
        parsed_row_count: int,
    ) -> None:
        super().__init__(message)
        self.source_path = source_path
        self.source_sha256 = source_sha256
        self.row_number = row_number
        self.raw_row = raw_row
        self.raw_row_sha256 = (
            sha256(raw_row.encode("utf-8")).hexdigest() if raw_row is not None else None
        )
        self.source_row_count = source_row_count
        self.parsed_row_count = parsed_row_count


class _TrackedLines:
    """Track the exact physical lines consumed for each logical CSV record."""

    def __init__(self, text: str) -> None:
        self._stream = io.StringIO(text, newline="")
        self._record_lines: list[str] = []

    def __iter__(self) -> _TrackedLines:
        return self

    def __next__(self) -> str:
        line = self._stream.readline()
        if line == "":
            raise StopIteration
        self._record_lines.append(line)
        return line

    def consume_record(self) -> str:
        raw_row = "".join(self._record_lines)
        self._record_lines.clear()
        return raw_row


def parse_delimited_table(
    path: Path, definition: GdpduTableDefinition, *, dossier_root: Path
) -> ParsedTable:
    """Map a metadata-defined semicolon/CSV file into raw, provenance-bound records."""

    path = path.expanduser().resolve()
    dossier_root = dossier_root.expanduser().resolve()
    source_path = _source_path(path, dossier_root)
    if source_path != definition.source_path:
        raise ValueError(f"metadata source path does not match file: {definition.source_path!r}")

    raw_bytes = path.read_bytes()
    text, encoding = _decode_text(raw_bytes, definition.encoding)
    file_sha256 = sha256_file(path)
    source_type = SourceType.CSV_ROW if path.suffix.lower() == ".csv" else SourceType.TEXT_ROW
    records: list[ParsedRecord] = []
    source_row_count = 0
    previous_line_number = 0
    tracked_lines = _TrackedLines(text)
    reader = csv.reader(tracked_lines, delimiter=definition.delimiter, strict=True)
    while True:
        try:
            raw_values = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raw_row = tracked_lines.consume_record()
            row_number = previous_line_number + 1
            raise DelimitedParseError(
                f"{source_path} row {row_number} is not valid delimited text: {exc}",
                source_path=source_path,
                source_sha256=file_sha256,
                row_number=row_number,
                raw_row=raw_row,
                source_row_count=source_row_count + 1,
                parsed_row_count=len(records),
            ) from exc
        source_row_count += 1
        row_number = previous_line_number + 1
        previous_line_number = reader.line_num
        raw_row = tracked_lines.consume_record()
        if len(raw_values) != len(definition.columns):
            raise DelimitedParseError(
                f"{source_path} row {row_number} has {len(raw_values)} fields; "
                f"GDPdU metadata defines {len(definition.columns)}",
                source_path=source_path,
                source_sha256=file_sha256,
                row_number=row_number,
                raw_row=raw_row,
                source_row_count=source_row_count,
                parsed_row_count=len(records),
            )
        fields = tuple(
            ParsedField(
                column_name=column.name,
                column_position=column.position,
                raw_value=raw_value,
                evidence_ref=EvidenceRef(
                    source_path=source_path,
                    source_type=source_type,
                    file_sha256=file_sha256,
                    raw_value=raw_value,
                    row=row_number,
                ),
            )
            for column, raw_value in zip(definition.columns, raw_values, strict=True)
        )
        records.append(
            ParsedRecord(
                table_name=definition.table_name,
                source_path=source_path,
                row_number=row_number,
                raw_row=raw_row,
                raw_row_sha256=sha256(raw_row.encode("utf-8")).hexdigest(),
                evidence_ref=EvidenceRef(
                    source_path=source_path,
                    source_type=source_type,
                    file_sha256=file_sha256,
                    raw_value=raw_row,
                    row=row_number,
                ),
                fields=fields,
            )
        )

    return ParsedTable(
        definition=definition,
        source_file=SourceFile(
            path=source_path,
            file_type=infer_file_type(path),
            byte_size=len(raw_bytes),
            sha256=file_sha256,
        ),
        detected_encoding=encoding,
        records=tuple(records),
        source_row_count=source_row_count,
        parsed_row_count=len(records),
    )


def compile_gdpdu_dossier(
    index_path: Path, *, dossier_root: Path | None = None
) -> GdpduCompilation:
    """Compile every GDPdU file declared by an XML index without filename assumptions."""

    index_path = index_path.expanduser().resolve()
    root = (dossier_root or index_path.parent).expanduser().resolve()
    definitions = parse_gdpdu_index(index_path, dossier_root=root)
    tables = tuple(
        parse_delimited_table(root / definition.source_path, definition, dossier_root=root)
        for definition in definitions
    )
    return GdpduCompilation(
        index_source_path=_source_path(index_path, root),
        index_sha256=sha256_file(index_path),
        compiled_at=datetime.now(UTC),
        tables=tables,
    )
