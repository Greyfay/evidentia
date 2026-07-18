"""Configuration-driven, bilingual resolution of source columns and roles.

Controls never reference a filename, sheet name, vendor id, or amount. They ask for a
*concept* (e.g. ``changed_by``) and this module resolves it against the German/English
column headers actually present in the dossier. This is what lets the same controls run
on an unseen dossier whose files are renamed, reordered, or translated.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from decimal import Decimal

from audit_compiler.ir.dossier import LoadedDossier, SourceTable
from audit_compiler.normalization import Locale, parse_date, parse_decimal

_ACTIVE_LOCALE: ContextVar[Locale] = ContextVar("audit_compiler_locale", default="de")

# Concept -> candidate header names (compared case-insensitively, punctuation-loose).
COLUMN_SYNONYMS: dict[str, set[str]] = {
    "account": {"konto", "kontonummer", "sachkontonummer", "lieferantenkontonummer",
                "kundenkontonummer", "kreditor", "debitor", "account", "accountno"},
    "account_name": {"name", "sachkontoname", "lieferantenname", "kundenname", "bezeichnung",
                     "kreditorname", "debitorname", "accountname"},
    "account_type": {"sachkontotyp", "kontenart", "kontoart", "accounttype", "typ"},
    "change_type": {"art", "aenderungsart", "changetype", "type"},
    "field_changed": {"feld", "field", "attribut"},
    "changed_by": {"geaendert_von", "erfasser", "ersteller", "changedby", "createdby",
                   "angelegt_von", "benutzer", "benutzerkennung", "user"},
    "approved_by": {"genehmigt_von", "freigeber", "approvedby", "approver", "genehmiger"},
    "approved_flag": {"genehmigt", "freigabe", "approved", "freigabestatus"},
    "amount": {"betrag", "betrag_eur", "buchungsbetrag", "summe", "summe_abs_eur", "amount",
               "buchungswert", "wert"},
    "currency": {"waehrung", "buchungswaehrung", "currency", "waehrungskennung"},
    "posting_date": {"buchungsdatum", "belegdatum", "datum", "wertstellung", "date",
                     "postingdate", "erfasst_am"},
    "invoice_date": {"fakturadatum", "rechnungsdatum", "belegdatum", "invoicedate"},
    "service_date": {"leistungsdatum", "servicedate", "wareneingang_datum", "lieferdatum"},
    "document_no": {"belegnummer", "dokument", "beleg", "rechnungsnummer", "referenz",
                    "documentno", "reference", "erfassungsnummer"},
    "payment_reference": {"dokument", "sammelbeleg", "sammel", "zahllaufnummer",
                          "paymentref", "batchreference", "zahlungsreferenz"},
    "posting_text": {"buchungstext", "bemerkung", "text", "verwendungszweck", "narrative"},
    "posting_kind": {"buchungstyp", "buchungsart", "postingtype", "kind"},
    "vendor": {"kreditor", "lieferantenkontonummer", "vendor", "supplier", "kreditornummer"},
    "asset_no": {"anlagennummer", "assetno", "assetnumber"},
    "asset_desc": {"anlagenbezeichnung", "assetdescription", "bezeichnung"},
    "asset_group": {"anlagengruppe", "assetgroup", "anlagenklasse"},
    "counter_account": {"gegenkonto", "counteraccount"},
    "goods_receipt_no": {"wareneingang_nr", "goodsreceiptno", "grno", "we_nr", "receiptno"},
    "permission_user": {"benutzer", "user", "benutzerkennung", "mitarbeiter", "userid"},
}


def _canon(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_column(table: SourceTable, concept: str) -> str | None:
    """Return the header in ``table`` that matches ``concept``, or None."""

    wanted = {_canon(s) for s in COLUMN_SYNONYMS.get(concept, {concept})}
    for column in table.columns:
        if _canon(column) in wanted:
            return column
    return None


def find_tables(dossier: LoadedDossier, concepts: set[str]) -> list[SourceTable]:
    """Return tables that can resolve every concept in ``concepts``, best coverage first."""

    matches = [
        t for t in dossier.tables
        if all(resolve_column(t, c) is not None for c in concepts)
    ]
    return sorted(matches, key=lambda t: len(t.rows), reverse=True)


@contextmanager
def using_locale(locale: Locale) -> Iterator[None]:
    """Scope legacy control helpers to one explicit, concurrency-safe run locale."""

    token = _ACTIVE_LOCALE.set(locale)
    try:
        yield
    finally:
        _ACTIVE_LOCALE.reset(token)


def money(value: str, *, locale: Locale | None = None) -> Decimal | None:
    """Parse money using the explicit argument or active compilation locale."""

    try:
        return parse_decimal(value, locale=locale or _ACTIVE_LOCALE.get())
    except (ValueError, TypeError):
        return None


def as_date(value: str, *, locale: Locale | None = None) -> date | None:
    """Parse a date using the explicit argument or active compilation locale."""

    try:
        return parse_date(value, locale=locale or _ACTIVE_LOCALE.get())
    except (ValueError, TypeError):
        return None


_NUM_BEFORE_EUR = re.compile(r"(\d[\d.\s]*\d|\d)\s*(?:EUR|€)", re.IGNORECASE)


def extract_threshold(dossier: LoadedDossier, *, default: Decimal) -> tuple[Decimal, object | None]:
    """Find the second-approval payment threshold stated in a policy document.

    Returns ``(threshold, evidence_ref_or_None)``. Falls back to ``default`` (a
    methodology parameter) when no policy sentence is found, so behaviour is explicit.
    """

    keywords = ("zweite freigabe", "vier-augen", "vier augen", "second approval",
                "two approvers", "dual approval")
    for table in dossier.tables:
        text_col = "paragraph" if "paragraph" in table.columns else (
            "text" if "text" in table.columns else None)
        if text_col is None:
            continue
        for index, row in enumerate(table.rows):
            text = row[text_col]
            low = text.lower()
            if not any(k in low for k in keywords):
                continue
            for match in _NUM_BEFORE_EUR.finditer(text):
                amount = money(match.group(1).replace(" ", ""))
                if amount and amount > 0:
                    return amount, table.evidence(index, text_col, normalized=str(amount))
    return default, None


_FY_END = re.compile(r"(?:stichtag|year[- ]?end|per)\D{0,12}(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
                     re.IGNORECASE)


def extract_fiscal_year_end(dossier: LoadedDossier, *, default: date) -> tuple[date, object | None]:
    """Find the balance-sheet date (Abschlussstichtag) stated in a policy document."""

    for table in dossier.tables:
        text_col = "paragraph" if "paragraph" in table.columns else (
            "text" if "text" in table.columns else None)
        if text_col is None:
            continue
        for index, row in enumerate(table.rows):
            match = _FY_END.search(row[text_col])
            if match:
                parsed = as_date(match.group(1))
                if parsed:
                    return parsed, table.evidence(index, text_col, normalized=parsed.isoformat())
    return default, None
