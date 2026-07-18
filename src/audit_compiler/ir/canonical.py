"""Deterministic mapping from provenance-bearing source rows to canonical events."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from audit_compiler.ir.dossier import LoadedDossier
from audit_compiler.ir.roles import resolve_column
from audit_compiler.models import FinancialEvent
from audit_compiler.normalization import parse_date, parse_decimal

_EVENT_NAMESPACE = uuid5(NAMESPACE_URL, "evidentia/canonical-event")


def map_canonical_events(
    dossier: LoadedDossier, *, engagement_id: str, run_id: str
) -> tuple[FinancialEvent, ...]:
    """Map only rows with explicit date and amount roles; never infer missing values."""

    events: list[FinancialEvent] = []
    for table in dossier.tables:
        date_column = resolve_column(table, "posting_date")
        amount_column = resolve_column(table, "amount")
        if date_column is None or amount_column is None:
            continue
        kind_column = resolve_column(table, "posting_kind")
        party_column = resolve_column(table, "vendor")
        account_column = resolve_column(table, "account")
        user_column = resolve_column(table, "changed_by")
        document_column = resolve_column(table, "document_no")
        for index, row in enumerate(table.rows):
            try:
                occurred_on = parse_date(row[date_column], locale=dossier.locale.value)
                amount = parse_decimal(row[amount_column], locale=dossier.locale.value)
            except (TypeError, ValueError):
                continue
            evidence = (
                table.evidence(index, date_column, normalized=occurred_on.isoformat()),
                table.evidence(index, amount_column, normalized=format(amount, "f")),
            )
            row_key = (
                f"{table.file_sha256}:{table.source_path}:{table.sheet or ''}:"
                f"{table.row_numbers[index]}"
            )
            events.append(
                FinancialEvent(
                    event_id=uuid5(_EVENT_NAMESPACE, row_key),
                    engagement_id=engagement_id,
                    run_id=run_id,
                    kind=row[kind_column] if kind_column and row[kind_column] else "posting",
                    occurred_on=occurred_on,
                    party_ids=(row[party_column],) if party_column and row[party_column] else (),
                    account_ids=(
                        (row[account_column],)
                        if account_column and row[account_column]
                        else ()
                    ),
                    user_id=row[user_column] if user_column and row[user_column] else None,
                    document_id=(
                        row[document_column]
                        if document_column and row[document_column]
                        else None
                    ),
                    net_amount=amount,
                    evidence_refs=evidence,
                )
            )
    return tuple(events)
