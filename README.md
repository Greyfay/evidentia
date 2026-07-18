# Admissible

Admissible is an evidence-first audit compiler. This foundation slice inventories source
files, creates immutable provenance-bearing records, normalizes accounting inputs, and
initializes a local DuckDB evidence store. It also natively compiles GDPdU XML metadata
and its declared delimited files. It intentionally contains no fraud controls, web
application, or AI integration.

## Requirements

- Python 3.11+

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Commands

Run all tests:

```bash
pytest
```

Lint the project:

```bash
ruff check .
```

Inventory a dossier without copying it into the repository:

```bash
admissible inventory /path/to/dossier --output /path/to/manifest.json
```

Compile GDPdU metadata and all declared TXT/CSV sources:

```bash
admissible compile /path/to/dossier --output compilation-report.json
```

The same command automatically compiles every XLSX workbook and worksheet in the dossier:

```bash
admissible compile /path/to/xlsx-dossier \
  --database /path/to/admissible.duckdb \
  --output xlsx-compilation-report.json
```

The compiler writes its DuckDB evidence store to
`/path/to/dossier/.admissible/admissible.duckdb` by default. Use `--database /path/to/file.duckdb`
to select another location. The JSON report lists every discovered file, per-source status,
source and parsed row counts, warnings, and provenance-bearing errors. A failed source returns
a non-zero exit status after the report is written.

For XLSX sources, the report includes every sheet's dimensions, detected header row,
normalized-record count, and warnings. Cells above a detected header remain available as
document metadata, and all cells in the worksheet's reported dimensions are retained with
their raw and normalized values.

Omit `--output` to write the JSON manifest to standard output. The manifest contains each
file's relative path, inferred type, byte count, and SHA-256 hash. Dossier contents belong
outside version control; `data/` is ignored as a safeguard.

## Design guarantees

- Money is represented with `decimal.Decimal`; floats are rejected at normalization and
  model boundaries.
- Normalized financial events and results require one or more immutable `EvidenceRef`s.
- German and English amounts and dates require an explicit locale so ambiguous values are
  never guessed.
- DuckDB is a local, deterministic persistence layer; control execution comes in a later
  slice.
- GDPdU fields are mapped from index metadata, raw field values are retained in DuckDB,
  and parsed row counts are reconciled before persistence completes.
- Each parsed record and field has immutable evidence containing the source hash, exact
  one-based row, raw value, and raw-value hash. Amount and date normalization remains a
  separate explicit operation.
- XLSX extraction uses openpyxl in read-only/data-only mode. Cached formula values are marked
  explicitly; formulas without cached results produce warnings rather than invented values.
