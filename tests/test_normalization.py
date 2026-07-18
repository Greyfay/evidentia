from datetime import date
from decimal import Decimal

import pytest

from audit_compiler.normalization import normalize_identifier, parse_date, parse_decimal


@pytest.mark.parametrize(
    ("value", "locale", "expected"),
    [
        ("1.234,50 EUR", "de", Decimal("1234.50")),
        ("(1,234.50)", "en", Decimal("-1234.50")),
        ("12,50", "de", Decimal("12.50")),
        ("12.50", "en", Decimal("12.50")),
    ],
)
def test_parse_decimal_with_explicit_locale(value: str, locale: str, expected: Decimal) -> None:
    assert parse_decimal(value, locale=locale) == expected  # type: ignore[arg-type]


def test_parse_decimal_rejects_invalid_grouping_and_floats() -> None:
    with pytest.raises(ValueError):
        parse_decimal("12.34,50", locale="de")
    with pytest.raises(TypeError):
        parse_decimal(1.5, locale="en")  # type: ignore[arg-type]


def test_parse_date_is_locale_explicit() -> None:
    assert parse_date("2026-07-18", locale="de") == date(2026, 7, 18)
    assert parse_date("18.07.2026", locale="de") == date(2026, 7, 18)
    assert parse_date("07/18/2026", locale="en") == date(2026, 7, 18)
    with pytest.raises(ValueError):
        parse_date("18/07/2026", locale="en")


def test_normalize_identifier_preserves_symbols_and_normalizes_spacing() -> None:
    assert normalize_identifier("  ab- 42\u00a0") == "AB- 42"
    with pytest.raises(ValueError):
        normalize_identifier("   ")
