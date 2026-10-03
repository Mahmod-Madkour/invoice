"""Money arithmetic (spec §5). Pure Python, ``Decimal`` only.

    gross           = quantity × unit_price
    discount_amount = gross × discount_percent / 100
    total           = (gross − discount_amount) quantized to 0.01, ROUND_HALF_UP

Each line is rounded exactly once; running totals and the grand total are sums of the
already-rounded line totals, so every printed number adds up with a calculator.
The browser preview (``app.js``, big.js) uses the same formula and rounding.
"""

from __future__ import annotations

import decimal
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")

# Far above anything the input limits allow (≤ 25 significant digits), so the intermediate
# products and the division by 100 are always exact; Inexact is trapped to prove it.
_EXACT = decimal.Context(prec=60, rounding=ROUND_HALF_UP, traps=[decimal.Inexact, decimal.InvalidOperation])


@dataclass(frozen=True, slots=True)
class LineAmounts:
    gross: Decimal
    discount_amount: Decimal
    total: Decimal


def round_money(value: Decimal) -> Decimal:
    """Quantize to 0.01 with ROUND_HALF_UP (the only rounding step in the system)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_amounts(quantity: Decimal, unit_price: Decimal, discount_percent: Decimal) -> LineAmounts:
    with decimal.localcontext(_EXACT):
        gross = quantity * unit_price
        discount_amount = gross * discount_percent / HUNDRED
        unrounded = gross - discount_amount
    return LineAmounts(gross=gross, discount_amount=discount_amount, total=round_money(unrounded))


def line_total(quantity: Decimal, unit_price: Decimal, discount_percent: Decimal = ZERO) -> Decimal:
    return line_amounts(quantity, unit_price, discount_percent).total


def running_totals(totals: Iterable[Decimal]) -> list[Decimal]:
    """Cumulative sums: ``[a, b, c]`` → ``[a, a+b, a+b+c]``."""
    result: list[Decimal] = []
    acc = ZERO
    with decimal.localcontext(_EXACT):
        for value in totals:
            acc += value
            result.append(acc)
    return result


def grand_total(totals: Iterable[Decimal]) -> Decimal:
    """Sum of the (already rounded) line totals."""
    acc = ZERO
    with decimal.localcontext(_EXACT):
        for value in totals:
            acc += value
    return round_money(acc)
