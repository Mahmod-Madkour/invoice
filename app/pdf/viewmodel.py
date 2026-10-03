"""Invoice → pre-formatted view model for the PDF template (spec §8).

All formatting happens here; the template only places these strings.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import Invoice
from app.domain.numbers import format_date, format_money, format_percent, format_quantity
from app.domain.pagination import DEFAULT_ROWS_PER_TABLE, DEFAULT_TABLES_PER_PAGE, paginate

# Vertical space reserved for one table (header + body rows + footer) on every page, and the
# designed row height. With the default 20 rows a table uses 22 × 7 mm; more rows shrink the
# row height so the table still fits above the summary band.
TABLE_ROWS_BUDGET_MM = Decimal("154")
MAX_ROW_HEIGHT_MM = Decimal("7")

SIDES = ("right", "left")  # first table of a page sits on the right (Arabic reading order)


@dataclass(frozen=True, slots=True)
class RowView:
    name: str
    name_dir: str  # "rtl", or "ltr" for names without Arabic letters (see name_direction)
    quantity: str
    unit_price: str
    discount: str
    total: str


@dataclass(frozen=True, slots=True)
class TableView:
    side: str  # "right" | "left"
    rows: tuple[RowView, ...]
    padding_count: int
    running_total: str


@dataclass(frozen=True, slots=True)
class PageView:
    number: int
    tables: tuple[TableView, ...]
    is_last: bool


@dataclass(frozen=True, slots=True)
class InvoiceView:
    date: str
    grand_total: str
    row_height: str  # CSS length, e.g. "7mm"
    pages: tuple[PageView, ...]


def name_direction(name: str) -> str:
    """Base direction for a name cell.

    Names containing Arabic letters stay RTL. Names without any (pure Latin/digits) are set LTR
    so that, if one ever overflows, it is clipped and ellipsized at its end — WeasyPrint's
    ``text-overflow`` does not handle RTL lines correctly.
    """
    has_rtl = any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in name)
    return "rtl" if has_rtl else "ltr"


def row_height(rows_per_table: int) -> str:
    height = min(MAX_ROW_HEIGHT_MM, TABLE_ROWS_BUDGET_MM / (rows_per_table + 2))
    return f"{height.quantize(Decimal('0.01'))}mm"


def build_invoice_view(
    invoice: Invoice,
    rows_per_table: int = DEFAULT_ROWS_PER_TABLE,
    tables_per_page: int = DEFAULT_TABLES_PER_PAGE,
) -> InvoiceView:
    if tables_per_page > len(SIDES):
        raise ValueError(f"the layout has room for at most {len(SIDES)} tables per page")

    pages = tuple(
        PageView(
            number=page.number,
            is_last=page.is_last,
            tables=tuple(
                TableView(
                    side=SIDES[index],
                    padding_count=table.padding_count,
                    running_total=format_money(table.running_total),
                    rows=tuple(
                        RowView(
                            name=item.name,
                            name_dir=name_direction(item.name),
                            quantity=format_quantity(item.quantity),
                            unit_price=format_money(item.unit_price),
                            discount=format_percent(item.discount_percent),
                            total=format_money(item.total),
                        )
                        for item in table.rows
                    ),
                )
                for index, table in enumerate(page.tables)
            ),
        )
        for page in paginate(invoice.items, rows_per_table, tables_per_page)
    )
    return InvoiceView(
        date=format_date(invoice.date),
        grand_total=format_money(invoice.grand_total),
        row_height=row_height(rows_per_table),
        pages=pages,
    )
