"""Locale-explicit normalization helpers for deterministic compilation."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

Locale = Literal["de", "en"]

_CURRENCY_RE = re.compile(r"(?:EUR|USD|GBP|€|\$|£)", re.IGNORECASE)
_GROUPING = {
    "de": re.compile(r"^\d{1,3}(?:\.\d{3})+$"),
    "en": re.compile(r"^\d{1,3}(?:,\d{3})+$"),
}


def parse_decimal(value: str | Decimal | int, *, locale: Locale) -> Decimal:
    """Parse a locale-formatted amount without guessing ambiguous separators.

    ``locale`` is required: for example, ``1,234`` is one point two three four in
    German and one thousand two hundred thirty-four in English.
    """

    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("amount must not be a float or boolean")
    if isinstance(value, int):
        return Decimal(value)
    if not isinstance(value, str):
        raise TypeError("amount must be a string, Decimal, or integer")

    normalized = unicodedata.normalize("NFKC", value).strip()
    negative = normalized.startswith("(") and normalized.endswith(")")
    if negative:
        normalized = normalized[1:-1].strip()
    normalized = _CURRENCY_RE.sub("", normalized).replace(" ", "").replace("'", "")
    if not normalized:
        raise ValueError("amount is empty")

    decimal_mark, grouping_mark = ((",", ".") if locale == "de" else (".", ","))
    if normalized.count(decimal_mark) > 1:
        raise ValueError(f"invalid {locale} decimal amount: {value!r}")
    whole, separator, fraction = normalized.partition(decimal_mark)
    if grouping_mark in fraction:
        raise ValueError(f"invalid {locale} decimal amount: {value!r}")
    if grouping_mark in whole and not _GROUPING[locale].fullmatch(whole.lstrip("+-")):
        raise ValueError(f"invalid {locale} grouping: {value!r}")

    canonical = whole.replace(grouping_mark, "")
    if separator:
        if not fraction.isdigit():
            raise ValueError(f"invalid {locale} decimal amount: {value!r}")
        canonical = f"{canonical}.{fraction}"
    try:
        parsed = Decimal(canonical)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {locale} decimal amount: {value!r}") from exc
    return -parsed if negative else parsed


def parse_date(value: str | date, *, locale: Locale) -> date:
    """Parse an ISO or locale-specific date while refusing implicit date conventions."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError("date must be a date or string")

    formats = ["%Y-%m-%d"]
    formats.extend(["%d.%m.%Y", "%d.%m.%y"] if locale == "de" else ["%m/%d/%Y", "%m/%d/%y"])
    for date_format in formats:
        try:
            return datetime.strptime(value.strip(), date_format).date()
        except ValueError:
            continue
    raise ValueError(f"invalid {locale} date: {value!r}")


def normalize_identifier(value: str | int, *, uppercase: bool = True) -> str:
    """Normalize Unicode and whitespace without stripping meaningful identifier symbols."""

    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("identifier must not be a float or boolean")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        raise TypeError("identifier must be a string or integer")
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip())
    if not normalized:
        raise ValueError("identifier is empty")
    return normalized.upper() if uppercase else normalized
