"""Number normalization, parsing and formatting (spec §6 and §8).

Pure Python. The browser mirrors ``normalize_number`` / ``parse_decimal`` / ``decimal_places``
in ``app/web/static/app.js`` — keep the two implementations identical.
"""

from __future__ import annotations

import datetime
import decimal
import re
from decimal import ROUND_HALF_UP, Decimal

# Arabic-Indic (U+0660–0669) and Persian/Extended Arabic-Indic (U+06F0–06F9) digits → ASCII,
# Arabic decimal separator (U+066B) → ".".
_TRANSLATE = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫",
    "01234567890123456789.",
)
# Thousands separators (Arabic U+066C and the ASCII comma) and invisible characters that Arabic
# keyboards and copy/paste insert (LRM, RLM, ALM, bidi embeddings/isolates, BOM U+FEFF) are removed.
_REMOVE = dict.fromkeys(
    map(ord, "\u066c,\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"),
)
_REMOVE_AND_TRANSLATE = {**_TRANSLATE, **_REMOVE}

# ASCII digits only (``\d`` would also accept other scripts' digits). Signs are accepted so a
# negative value gets a range message rather than a "not a number" message. No exponents.
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")

# Anything longer than this cannot be a valid value under any limit; refuse it early.
MAX_NUMBER_LENGTH = 32

CENT = Decimal("0.01")
_MILLI = Decimal("0.001")


def normalize_number(text: str) -> str:
    """Western digits, ``.`` as decimal separator, no thousands separators, trimmed."""
    return text.translate(_REMOVE_AND_TRANSLATE).strip()


def parse_decimal(text: str) -> Decimal | None:
    """Parse user input into a ``Decimal``; ``None`` if blank or not a plain number.

    The ``Decimal`` is always constructed from a string, never from a float.
    """
    normalized = normalize_number(text)
    if len(normalized) > MAX_NUMBER_LENGTH or not _NUMBER_RE.fullmatch(normalized):
        return None
    return Decimal(normalized)


def decimal_places(value: Decimal) -> int:
    """Significant fractional digits: ``2.50`` → 1, ``45.000`` → 0, ``0.125`` → 3.

    ``normalize()`` runs with a precision equal to the number's own digit count, so it only strips
    trailing zeros and never rounds (the default 28-digit context would turn
    ``1.0049999999999999999999999999`` into ``1.005`` and hide the extra decimals).
    """
    exact = decimal.Context(prec=max(1, len(value.as_tuple().digits)))
    exponent = value.normalize(exact).as_tuple().exponent
    assert isinstance(exponent, int), "special values are never parsed"
    return max(0, -exponent)


def _trim_zeros(text: str) -> str:
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _positive_zero(value: Decimal) -> Decimal:
    return value.copy_abs() if value.is_zero() else value


def format_money(value: Decimal) -> str:
    """``1250.5`` → ``1,250.50`` (2 decimals, ROUND_HALF_UP, thousands separators)."""
    return format(_positive_zero(value.quantize(CENT, rounding=ROUND_HALF_UP)), ",f")


def format_quantity(value: Decimal) -> str:
    """Up to 3 decimals, trailing zeros trimmed: ``2.500`` → ``2.5``, ``1000000`` → ``1,000,000``."""
    return _trim_zeros(format(_positive_zero(value.quantize(_MILLI, rounding=ROUND_HALF_UP)), ",f"))


def format_percent(value: Decimal) -> str:
    """``10`` → ``10%``, ``12.50`` → ``12.5%``, ``0`` → ``0%``."""
    return _trim_zeros(format(_positive_zero(value.quantize(CENT, rounding=ROUND_HALF_UP)), "f")) + "%"


def format_date(value: datetime.date) -> str:
    """``DD/MM/YYYY`` with Western digits."""
    return f"{value.day:02d}/{value.month:02d}/{value.year:04d}"
