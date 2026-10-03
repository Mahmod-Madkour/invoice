import math
import random
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.calculations import grand_total
from app.domain.models import LineItem
from app.domain.pagination import page_count, paginate


def make_items(n: int, seed: int = 0) -> list[LineItem]:
    rng = random.Random(seed)
    return [
        LineItem(
            name=f"صنف {k + 1}",
            quantity=Decimal(rng.randint(1, 5000)) / 1000,
            unit_price=Decimal(rng.randint(0, 100_000)) / 100,
            discount_percent=Decimal(rng.choice([0, 0, 0, 5, 10, 12.5, 100])).quantize(Decimal("0.01")),
        )
        for k in range(n)
    ]


def shape(pages) -> list[list[int]]:
    return [[len(t.rows) for t in page.tables] for page in pages]


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, [[1]]),
        (19, [[19]]),
        (20, [[20]]),
        (21, [[20, 1]]),
        (39, [[20, 19]]),
        (40, [[20, 20]]),
        (41, [[20, 20], [1]]),
        (65, [[20, 20], [20, 5]]),
        (80, [[20, 20], [20, 20]]),
        (81, [[20, 20], [20, 20], [1]]),
        (100, [[20, 20], [20, 20], [20]]),
        (120, [[20, 20], [20, 20], [20, 20]]),
        (1000, [[20, 20]] * 25),
    ],
)
def test_required_layouts(n, expected):
    items = make_items(n)
    pages = paginate(items)
    assert shape(pages) == expected
    assert [p.number for p in pages] == list(range(1, len(expected) + 1))
    assert [p.is_last for p in pages] == [False] * (len(expected) - 1) + [True]
    assert pages[-1].tables[-1].running_total == grand_total(i.total for i in items)


def test_padding_and_running_totals_for_65_items():
    items = make_items(65, seed=7)
    pages = paginate(items)
    tables = [t for p in pages for t in p.tables]
    assert [t.padding_count for t in tables] == [0, 0, 0, 15]
    for k, table in enumerate(tables):
        last_row = min(20 * (k + 1), 65)
        assert table.running_total == sum((i.total for i in items[:last_row]), Decimal("0"))


def test_empty_input_is_rejected():
    with pytest.raises(ValueError):
        paginate([])


@pytest.mark.parametrize(("rows", "tables"), [(0, 2), (20, 0)])
def test_invalid_parameters_are_rejected(rows, tables):
    with pytest.raises(ValueError):
        paginate(make_items(3), rows_per_table=rows, tables_per_page=tables)


@pytest.mark.parametrize(("n", "pages"), [(1, 1), (40, 1), (41, 2), (80, 2), (81, 3), (1000, 25)])
def test_page_count(n, pages):
    assert page_count(n) == pages


@settings(max_examples=150, deadline=None)
@given(
    n=st.integers(min_value=1, max_value=3000),
    seed=st.integers(min_value=0, max_value=2**32),
    rows_per_table=st.sampled_from([20, 20, 20, 1, 7, 25]),
    tables_per_page=st.sampled_from([2, 2, 2, 1]),
)
def test_pagination_invariants(n, seed, rows_per_table, tables_per_page):
    items = make_items(n, seed)
    pages = paginate(items, rows_per_table, tables_per_page)
    tables = [t for p in pages for t in p.tables]

    # Order is preserved and every item appears exactly once.
    flattened = [row for t in tables for row in t.rows]
    assert len(flattened) == n
    assert all(a is b for a, b in zip(flattened, items))

    # Size limits.
    assert all(len(t.rows) <= rows_per_table for t in tables)
    assert all(len(p.tables) <= tables_per_page for p in pages)
    assert all(len(t.rows) >= 1 for t in tables)

    # Only the last table may be partial; only the last page may have fewer tables.
    assert all(len(t.rows) == rows_per_table for t in tables[:-1])
    assert all(len(p.tables) == tables_per_page for p in pages[:-1])
    assert all(t.padding_count == rows_per_table - len(t.rows) for t in tables)

    # Page count and numbering.
    assert len(pages) == math.ceil(n / (rows_per_table * tables_per_page)) == page_count(n, rows_per_table, tables_per_page)
    assert [p.number for p in pages] == list(range(1, len(pages) + 1))
    assert [p.is_last for p in pages].count(True) == 1 and pages[-1].is_last

    # Running totals = sum of all line totals up to each table's last row; last = grand total.
    seen = 0
    acc = Decimal("0")
    for t in tables:
        acc += sum((row.total for row in t.rows), Decimal("0"))
        seen += len(t.rows)
        assert t.running_total == acc == sum((i.total for i in items[:seen]), Decimal("0"))
    assert tables[-1].running_total == grand_total(i.total for i in items)
