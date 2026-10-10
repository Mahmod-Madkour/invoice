import datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.numbers import (
    decimal_places,
    format_date,
    format_money,
    format_percent,
    format_quantity,
    normalize_number,
    parse_decimal,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("٠١٢٣٤٥٦٧٨٩", "0123456789"),  # Arabic-Indic digits
        ("۰۱۲۳۴۵۶۷۸۹", "0123456789"),  # Persian digits
        ("٢٫٥", "2.5"),  # Arabic decimal separator
        ("١٬٢٥٠٫٥٠", "1250.50"),  # Arabic thousands separator
        ("1,250.50", "1250.50"),  # comma thousands separator
        ("١2٣", "123"),  # mixed digit systems
        ("  12.5 \t", "12.5"),  # surrounding whitespace
        ("\u00a012\u00a0", "12"),  # no-break spaces
        ("\u200f\u0661\u0662\u200e", "12"),  # RLM/LRM inserted by Arabic keyboards
        ("\u061c5", "5"),  # Arabic letter mark
        ("\ufeff12\ufeff", "12"),  # byte-order mark (also removed by the browser)
        ("\x1c5\x85", "5"),  # Python-only whitespace characters (the browser trims them too)
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_number(raw, expected):
    assert normalize_number(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2.5", Decimal("2.5")),
        ("٢٫٥", Decimal("2.5")),
        ("۱۲", Decimal("12")),
        ("1,000,000", Decimal("1000000")),
        ("١٬٠٠٠٬٠٠٠٫٥", Decimal("1000000.5")),
        (" 45.00 ", Decimal("45.00")),
        ("0", Decimal("0")),
        ("0.125", Decimal("0.125")),
        ("5.", Decimal("5")),
        (".5", Decimal("0.5")),
        ("-3", Decimal("-3")),  # parsed, so the caller can give a range message
        ("+3", Decimal("3")),
        ("007", Decimal("7")),
    ],
)
def test_parse_decimal_valid(raw, expected):
    value = parse_decimal(raw)
    assert isinstance(value, Decimal)
    assert value == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "١٢x",
        "1.2.3",
        "٫٫",
        ".",
        "-",
        "+-1",
        "--1",
        "1e5",
        "1E5",
        "NaN",
        "nan",
        "Infinity",
        "inf",
        "1 000",  # internal whitespace is not a separator
        "١ ٢",
        "१२",  # Devanagari digits are not accepted
        "١٢٣٤٥٦٧٨٩٠" * 4,  # absurdly long
        "0x10",
        "1/2",
        "50%",
        "١٢،٥",  # Arabic comma is not a decimal separator
    ],
)
def test_parse_decimal_invalid(raw):
    assert parse_decimal(raw) is None


@pytest.mark.parametrize(
    ("raw", "places"),
    [
        ("2.50", 1), ("45.000", 0), ("0.125", 3), ("100", 0), ("0", 0), ("0.000", 0), ("0.001", 3), ("10.10", 1),
        ("1.005", 3),
        # More than 28 significant digits: counting must not round (Python's default precision is 28).
        ("1.0049999999999999999999999999", 28),
        ("1.0099999999999999999999999999", 28),
        ("12.000000000000000000000000000000", 0),
        ("12345678901234567890123456789012", 0),
    ],
)
def test_decimal_places(raw, places):
    assert decimal_places(Decimal(raw)) == places


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1250.5", "1,250.50"),
        ("0", "0.00"),
        ("-0.00", "0.00"),
        ("0.005", "0.01"),  # ROUND_HALF_UP
        ("2.675", "2.68"),
        ("0.125", "0.13"),
        ("999", "999.00"),
        ("1000", "1,000.00"),
        ("1000000", "1,000,000.00"),
        ("10000000.00", "10,000,000.00"),
        ("999999999.99", "999,999,999.99"),
    ],
)
def test_format_money(raw, expected):
    assert format_money(Decimal(raw)) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2.5", "2.5"),
        ("2.500", "2.5"),
        ("10", "10"),
        ("10.000", "10"),
        ("1E+1", "10"),
        ("0.125", "0.125"),
        ("0.100", "0.1"),
        ("1234.5", "1,234.5"),
        ("1000000", "1,000,000"),
        ("999999.999", "999,999.999"),
    ],
)
def test_format_quantity(raw, expected):
    assert format_quantity(Decimal(raw)) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10", "10%"),
        ("12.5", "12.5%"),
        ("12.50", "12.5%"),
        ("0", "0%"),
        ("0.00", "0%"),
        ("100", "100%"),
        ("33.33", "33.33%"),
        ("6.25", "6.25%"),
        ("1E+1", "10%"),
    ],
)
def test_format_percent(raw, expected):
    assert format_percent(Decimal(raw)) == expected


def test_format_date_uses_western_digits_dd_mm_yyyy():
    assert format_date(datetime.date(2026, 10, 3)) == "03/10/2026"
    assert format_date(datetime.date(2027, 1, 31)) == "31/01/2027"


def test_formatting_never_emits_non_western_digits():
    for text in (format_money(Decimal("1234567.89")), format_quantity(Decimal("1234.5")), format_percent(Decimal("12.5"))):
        assert all(ch in "0123456789,.%" for ch in text), text


@given(st.decimals(min_value=0, max_value=Decimal("999999999.99"), places=2, allow_nan=False, allow_infinity=False))
def test_money_round_trips_through_the_parser(value):
    assert parse_decimal(format_money(value)) == value


@given(st.decimals(min_value=Decimal("0.001"), max_value=1_000_000, places=3, allow_nan=False, allow_infinity=False))
def test_quantity_round_trips_through_the_parser(value):
    assert parse_decimal(format_quantity(value)) == value
