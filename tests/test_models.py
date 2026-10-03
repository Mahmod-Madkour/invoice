import dataclasses
import datetime
from decimal import Decimal

import pytest

from app.domain.models import (
    NAME_MAX_LENGTH,
    DomainError,
    Invoice,
    LineItem,
    clean_name,
)

D = Decimal
TODAY = datetime.date(2026, 10, 3)


def item(name="سكر أبيض", qty="2.5", price="45.00", disc="10") -> LineItem:
    return LineItem(name=name, quantity=D(qty), unit_price=D(price), discount_percent=D(disc))


def test_line_item_derives_amounts():
    li = item()
    assert li.gross == D("112.500")
    assert li.discount_amount == D("11.25")
    assert li.total == D("101.25")


def test_discount_defaults_to_zero():
    li = LineItem(name="شاي", quantity=D("12"), unit_price=D("7.25"))
    assert li.discount_percent == 0
    assert li.total == D("87.00")


@pytest.mark.parametrize("derived", ["gross", "discount_amount", "total"])
def test_derived_fields_cannot_be_supplied(derived):
    with pytest.raises(TypeError):
        LineItem(name="x", quantity=D("1"), unit_price=D("1"), **{derived: D("999")})


def test_line_item_is_frozen():
    li = item()
    with pytest.raises(dataclasses.FrozenInstanceError):
        li.total = D("0")  # type: ignore[misc]


@pytest.mark.parametrize("field", ["quantity", "unit_price", "discount_percent"])
def test_floats_are_rejected(field):
    kwargs = {"name": "x", "quantity": D("1"), "unit_price": D("1"), "discount_percent": D("0")}
    kwargs[field] = 1.0
    with pytest.raises(DomainError):
        LineItem(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"qty": "0"},
        {"qty": "-1"},
        {"qty": "1000000.001"},
        {"qty": "1.0001"},
        {"price": "-0.01"},
        {"price": "10000000.01"},
        {"price": "1.001"},
        {"disc": "-1"},
        {"disc": "100.01"},
        {"disc": "12.345"},
        {"qty": "100", "price": "10000000", "disc": "0"},  # line total 1,000,000,000.00 > max
        {"name": ""},
        {"name": "x" * (NAME_MAX_LENGTH + 1)},
        {"name": "  padded  "},  # must be cleaned before construction
        {"name": "two  spaces"},
    ],
)
def test_line_item_invariants(kwargs):
    with pytest.raises(DomainError):
        item(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"qty": "1000000", "price": "0.01"},
        {"qty": "0.001"},
        {"price": "0"},
        {"price": "10000000", "qty": "99.999"},
        {"disc": "100"},
        {"disc": "0"},
        {"name": "x" * NAME_MAX_LENGTH},
        {"price": "45.000"},  # trailing zeros are not significant decimals
    ],
)
def test_line_item_accepts_boundary_values(kwargs):
    item(**kwargs)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  سكر   أبيض \n", "سكر أبيض"),
        ("كابل\tHDMI", "كابل HDMI"),
        ("a\x00b\x07c", "abc"),
        (" شاي ", "شاي"),
        ("شاشة Samsung 55 بوصة", "شاشة Samsung 55 بوصة"),
        ("   ", ""),
    ],
)
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


def test_invoice_grand_total_is_sum_of_line_totals():
    inv = Invoice(date=TODAY, items=[item(), item(qty="1", price="0.01", disc="50")])
    assert inv.items == (item(), item(qty="1", price="0.01", disc="50"))
    assert inv.grand_total == D("101.26")


def test_invoice_requires_items():
    with pytest.raises(DomainError):
        Invoice(date=TODAY, items=())


def test_invoice_rejects_grand_total_over_the_limit():
    big = item(qty="99.999", price="10000000", disc="0")  # 999,990,000.00 — allowed alone
    Invoice(date=TODAY, items=(big,))
    with pytest.raises(DomainError):
        Invoice(date=TODAY, items=(big, big))


def test_invoice_requires_a_date():
    with pytest.raises(DomainError):
        Invoice(date="2026-10-03", items=(item(),))  # type: ignore[arg-type]
