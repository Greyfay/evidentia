"""Native source adapters for the audit compiler."""

from audit_compiler.adapters.gdpdu import (
    GdpduCompilation,
    GdpduTableDefinition,
    ParsedTable,
    compile_gdpdu_dossier,
    parse_gdpdu_index,
)
from audit_compiler.adapters.xlsx import XlsxWorkbook, parse_xlsx_workbook

__all__ = [
    "GdpduCompilation",
    "GdpduTableDefinition",
    "ParsedTable",
    "compile_gdpdu_dossier",
    "parse_gdpdu_index",
    "XlsxWorkbook",
    "parse_xlsx_workbook",
]
