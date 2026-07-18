"""Run a control's arithmetic in DuckDB so every calculation is exact and replayable.

Rows are loaded into a typed temporary table and the control's SQL is executed verbatim.
Money columns use ``DECIMAL(18,2)`` (never floats); the SQL string stored on the finding
is exactly the query that produced the number.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb


def compute(
    schema: Sequence[tuple[str, str]],
    rows: Sequence[Sequence[Any]],
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[tuple[Any, ...]]:
    """Create table ``t`` from ``schema``/``rows`` and return the result of ``sql``."""

    connection = duckdb.connect()
    try:
        columns = ", ".join(f'"{name}" {type_}' for name, type_ in schema)
        connection.execute(f"CREATE TABLE t ({columns})")
        if rows:
            placeholders = ", ".join(["?"] * len(schema))
            connection.executemany(
                f"INSERT INTO t VALUES ({placeholders})", [list(r) for r in rows]
            )
        return connection.execute(sql, list(params or [])).fetchall()
    finally:
        connection.close()
