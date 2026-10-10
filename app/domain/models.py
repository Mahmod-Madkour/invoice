"""Domain model (spec §5). Pure Python — no FastAPI / WeasyPrint imports.

The models enforce their invariants; user-facing validation with Arabic messages happens
before construction (``app/api/schemas.py``), using the same limits defined here.
"""

from __future__ import annotations

import datetime
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain import calculations
from app.domain.numbers import decimal_places

# Business limits (spec §2 / §6).
NAME_MAX_LENGTH = 40
QUANTITY_MAX = Decimal("1000000")
QUANTITY_MAX_DECIMALS = 3
PRICE_MAX = Decimal("10000000")
PRICE_MAX_DECIMALS = 2
DISCOUNT_MAX = Decimal("100")
DISCOUNT_MAX_DECIMALS = 2
TOTAL_MAX = Decimal("999999999.99")  # widest value the total column is designed for


class DomainError(ValueError):
    """An invariant of the domain model was violated (a programming error upstream)."""


def clean_name(raw: str) -> str:
    """Trim, collapse internal whitespace (Python's ``str.isspace`` set), drop control characters and BOMs.

    Mirrored by ``cleanName`` in app.js — keep identical.
    """
    without_controls = "".join(
        " " if ch.isspace() else ch
        for ch in raw
        if ch != "\ufeff" and (ch.isspace() or unicodedata.category(ch) != "Cc")
    )
    return " ".join(without_controls.split())


def _require_decimal(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise DomainError(f"{name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise DomainError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class LineItem:
    name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal = calculations.ZERO
    # Derived — never accepted from outside (init=False).
    gross: Decimal = field(init=False, repr=False)
    discount_amount: Decimal = field(init=False, repr=False)
    total: Decimal = field(init=False)

    def __post_init__(self) -> None:
        quantity = _require_decimal("quantity", self.quantity)
        unit_price = _require_decimal("unit_price", self.unit_price)
        discount = _require_decimal("discount_percent", self.discount_percent)

        if not isinstance(self.name, str) or self.name != clean_name(self.name):
            raise DomainError("name must be a cleaned string")
        if not 1 <= len(self.name) <= NAME_MAX_LENGTH:
            raise DomainError(f"name must be 1..{NAME_MAX_LENGTH} characters")
        if not (0 < quantity <= QUANTITY_MAX) or decimal_places(quantity) > QUANTITY_MAX_DECIMALS:
            raise DomainError("quantity out of range")
        if not (0 <= unit_price <= PRICE_MAX) or decimal_places(unit_price) > PRICE_MAX_DECIMALS:
            raise DomainError("unit_price out of range")
        if not (0 <= discount <= DISCOUNT_MAX) or decimal_places(discount) > DISCOUNT_MAX_DECIMALS:
            raise DomainError("discount_percent out of range")

        amounts = calculations.line_amounts(quantity, unit_price, discount)
        if amounts.total > TOTAL_MAX:
            raise DomainError("line total exceeds the maximum")
        object.__setattr__(self, "gross", amounts.gross)
        object.__setattr__(self, "discount_amount", amounts.discount_amount)
        object.__setattr__(self, "total", amounts.total)


@dataclass(frozen=True, slots=True)
class Invoice:
    date: datetime.date
    items: tuple[LineItem, ...]
    grand_total: Decimal = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.date, datetime.date):
            raise DomainError("date must be a datetime.date")
        items = tuple(self.items)
        if not items:
            raise DomainError("an invoice needs at least one item")
        if not all(isinstance(item, LineItem) for item in items):
            raise DomainError("items must be LineItem instances")
        total = calculations.grand_total(item.total for item in items)
        if total > TOTAL_MAX:
            raise DomainError("grand total exceeds the maximum")
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "grand_total", total)
