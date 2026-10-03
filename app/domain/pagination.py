"""Pagination and running totals (spec §7). Pure function, no PDF dependency.

    items → consecutive tables of ``rows_per_table`` → consecutive pages of ``tables_per_page``

The first table of a page is the right-hand one (Arabic reading order); that is a
rendering concern — here a page's ``tables`` are simply in reading order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.domain.calculations import running_totals
from app.domain.models import LineItem

DEFAULT_ROWS_PER_TABLE = 20
DEFAULT_TABLES_PER_PAGE = 2


@dataclass(frozen=True, slots=True)
class Table:
    rows: tuple[LineItem, ...]
    padding_count: int  # empty ruled rows that pad the table to rows_per_table
    running_total: Decimal  # sum of all line totals up to and including this table


@dataclass(frozen=True, slots=True)
class Page:
    number: int  # 1-based
    tables: tuple[Table, ...]  # reading order: tables[0] is the right-hand table
    is_last: bool  # only the last page shows the grand total


def page_count(item_count: int, rows_per_table: int = DEFAULT_ROWS_PER_TABLE,
               tables_per_page: int = DEFAULT_TABLES_PER_PAGE) -> int:
    """``ceil(n / (rows_per_table × tables_per_page))``."""
    per_page = rows_per_table * tables_per_page
    return -(-item_count // per_page)


def paginate(items: Sequence[LineItem], rows_per_table: int = DEFAULT_ROWS_PER_TABLE,
             tables_per_page: int = DEFAULT_TABLES_PER_PAGE) -> tuple[Page, ...]:
    if not items:
        raise ValueError("cannot paginate an empty item list")
    if rows_per_table < 1 or tables_per_page < 1:
        raise ValueError("rows_per_table and tables_per_page must be at least 1")

    cumulative = running_totals(item.total for item in items)

    tables: list[Table] = []
    for start in range(0, len(items), rows_per_table):
        rows = tuple(items[start:start + rows_per_table])
        tables.append(Table(
            rows=rows,
            padding_count=rows_per_table - len(rows),
            running_total=cumulative[start + len(rows) - 1],
        ))

    groups = [tuple(tables[i:i + tables_per_page]) for i in range(0, len(tables), tables_per_page)]
    return tuple(
        Page(number=index + 1, tables=group, is_last=index == len(groups) - 1)
        for index, group in enumerate(groups)
    )
