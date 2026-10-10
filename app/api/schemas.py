"""Request models, validation with Arabic messages, and the structured error model (spec §6, §10).

Pydantic validates the request *shape*: every value is a JSON string (numbers sent as JSON
numbers are rejected, so no float ever reaches the server). The business rules then run in
``InvoiceRequest.to_invoice`` — mirrored in app.js — and produce one structured error per
invalid cell. Row numbers are 1-based positions in the submitted ``items`` array, i.e. the UI
rows, including completely empty rows (which are otherwise ignored).
"""

from __future__ import annotations

import datetime
import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.domain.calculations import grand_total, line_total
from app.domain.models import (
    DISCOUNT_MAX,
    DISCOUNT_MAX_DECIMALS,
    NAME_MAX_LENGTH,
    PRICE_MAX,
    PRICE_MAX_DECIMALS,
    QUANTITY_MAX,
    QUANTITY_MAX_DECIMALS,
    TOTAL_MAX,
    Invoice,
    LineItem,
    clean_name,
)
from app.domain.numbers import decimal_places, normalize_number, parse_decimal

# Spec §6 messages.
MSG_NAME_REQUIRED = "اسم الصنف مطلوب"
MSG_NAME_TOO_LONG = f"اسم الصنف يجب ألا يزيد عن {NAME_MAX_LENGTH} حرفًا"
MSG_QUANTITY_NOT_NUMBER = "الكمية يجب أن تكون رقمًا"
MSG_QUANTITY_NOT_POSITIVE = "الكمية يجب أن تكون أكبر من صفر"
MSG_QUANTITY_INVALID = "الكمية غير صالحة"
MSG_PRICE_NOT_NUMBER = "السعر يجب أن يكون رقمًا لا يقل عن صفر"
MSG_PRICE_INVALID = "السعر غير صالح"
MSG_DISCOUNT_INVALID = "الخصم يجب أن يكون بين 0 و 100"
MSG_TOTAL_TOO_LARGE = "الإجمالي أكبر من الحد المسموح"
MSG_NO_ITEMS = "أضف صنفًا واحدًا على الأقل"
MSG_TOO_MANY_ITEMS = "عدد الأصناف أكبر من الحد المسموح"
MSG_DATE_INVALID = "التاريخ غير صالح"
MSG_BAD_REQUEST = "الطلب غير صالح"

# Message used when a field has the wrong JSON type (e.g. a number instead of a string).
TYPE_ERROR_MESSAGES = {
    "name": MSG_NAME_REQUIRED,
    "quantity": MSG_QUANTITY_NOT_NUMBER,
    "unit_price": MSG_PRICE_NOT_NUMBER,
    "discount_percent": MSG_DISCOUNT_INVALID,
    "date": MSG_DATE_INVALID,
    "items": MSG_NO_ITEMS,
}

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class FieldError(BaseModel):
    row: int | None  # 1-based UI row, or null for invoice-level errors
    field: str | None  # name | quantity | unit_price | discount_percent | total | date | items | grand_total
    message: str


class ErrorResponse(BaseModel):
    errors: list[FieldError]


def error_content(message: str, field: str | None = None, row: int | None = None) -> dict:
    """JSON body used for every error response (422, 401, 413, 429, 503, ...)."""
    return ErrorResponse(errors=[FieldError(row=row, field=field, message=message)]).model_dump()


class InvoiceValidationError(Exception):
    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__(f"{len(errors)} validation error(s)")
        self.errors = errors


class LineItemIn(BaseModel):
    # Unknown keys — including derived values such as "total" or "gross" — are ignored;
    # the server always recalculates.
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    discount_percent: str | None = None

    def is_blank(self) -> bool:
        return (
            clean_name(self.name or "") == ""
            and all(normalize_number(v or "") == "" for v in (self.quantity, self.unit_price, self.discount_percent))
        )


class InvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str | None = None
    items: list[LineItemIn] = []

    def to_invoice(self, max_items: int) -> Invoice:
        """Validate every rule and build the domain invoice, or raise InvoiceValidationError."""
        errors: list[FieldError] = []

        date = _parse_date(self.date)
        if date is None:
            errors.append(FieldError(row=None, field="date", message=MSG_DATE_INVALID))

        rows = [(index + 1, item) for index, item in enumerate(self.items) if not item.is_blank()]
        if not rows:
            errors.append(FieldError(row=None, field="items", message=MSG_NO_ITEMS))
            raise InvoiceValidationError(errors)
        if len(rows) > max_items:
            errors.append(FieldError(row=None, field="items", message=MSG_TOO_MANY_ITEMS))
            raise InvoiceValidationError(errors)

        items: list[LineItem] = []
        for row, raw in rows:
            item, row_errors = _validate_row(row, raw)
            errors.extend(row_errors)
            if item is not None:
                items.append(item)

        if not errors and grand_total(item.total for item in items) > TOTAL_MAX:
            errors.append(FieldError(row=None, field="grand_total", message=MSG_TOTAL_TOO_LARGE))
        if errors:
            raise InvoiceValidationError(errors)
        assert date is not None
        return Invoice(date=date, items=tuple(items))


def _parse_date(raw: str | None) -> datetime.date | None:
    text = (raw or "").strip()
    if not _ISO_DATE.fullmatch(text):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _validate_row(row: int, raw: LineItemIn) -> tuple[LineItem | None, list[FieldError]]:
    errors: list[FieldError] = []

    def fail(field: str, message: str) -> None:
        errors.append(FieldError(row=row, field=field, message=message))

    name = clean_name(raw.name or "")
    if not name:
        fail("name", MSG_NAME_REQUIRED)
    elif len(name) > NAME_MAX_LENGTH:
        fail("name", MSG_NAME_TOO_LONG)

    quantity = parse_decimal(raw.quantity or "")
    if quantity is None:
        fail("quantity", MSG_QUANTITY_NOT_NUMBER)
    elif quantity <= 0:
        fail("quantity", MSG_QUANTITY_NOT_POSITIVE)
    elif quantity > QUANTITY_MAX or decimal_places(quantity) > QUANTITY_MAX_DECIMALS:
        fail("quantity", MSG_QUANTITY_INVALID)

    unit_price = parse_decimal(raw.unit_price or "")
    if unit_price is None or unit_price < 0:
        fail("unit_price", MSG_PRICE_NOT_NUMBER)
    elif unit_price > PRICE_MAX or decimal_places(unit_price) > PRICE_MAX_DECIMALS:
        fail("unit_price", MSG_PRICE_INVALID)

    discount_text = normalize_number(raw.discount_percent or "")
    discount = Decimal("0") if discount_text == "" else parse_decimal(discount_text)
    if discount is None or not (0 <= discount <= DISCOUNT_MAX) or decimal_places(discount) > DISCOUNT_MAX_DECIMALS:
        fail("discount_percent", MSG_DISCOUNT_INVALID)

    numbers_valid = not any(e.field in ("quantity", "unit_price", "discount_percent") for e in errors)
    if numbers_valid:
        assert quantity is not None and unit_price is not None and discount is not None
        if line_total(quantity, unit_price, discount) > TOTAL_MAX:
            fail("total", MSG_TOTAL_TOO_LARGE)  # reported even when the name is also invalid
    if errors:
        return None, errors
    assert quantity is not None and unit_price is not None and discount is not None
    return LineItem(name=name, quantity=quantity, unit_price=unit_price, discount_percent=discount), errors
