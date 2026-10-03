"""Phase 0 spike — THROWAWAY CODE. Not part of the application.

Renders the full invoice layout (spec §8) from the 45-item fixture with WeasyPrint,
in two font variants (Noto Sans Arabic / Noto Naskh Arabic), and reports how much
horizontal space the widest cell contents actually use, so column widths, row
height and font size can be tuned with numbers instead of guesses.

Run inside the dev container:
    docker compose -f compose.dev.yml run --rm tests python spike/phase0_spike.py
Output: samples/spike/*.pdf and *.png
"""

from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from weasyprint import HTML

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "app" / "assets"
FIXTURE = ROOT / "tests" / "fixtures" / "items_45.json"
OUT = ROOT / "samples" / "spike"

FONTS = {
    "sans": "Noto Sans Arabic",
    "naskh": "Noto Naskh Arabic",
}

PX_PER_MM = 96 / 25.4  # WeasyPrint layout unit is the CSS px


@dataclass
class Layout:
    margin_top: float = 8
    margin_side: float = 8
    margin_bottom: float = 12
    header_h: float = 12
    summary_h: float = 12
    gap_v: float = 3          # gap between header band / tables / summary band
    table_w: float = 138.5
    cols: dict = field(default_factory=lambda: {
        "name": 58.5, "qty": 20, "price": 22.5, "disc": 13, "total": 24.5,
    })
    row_h: float = 7
    font_pt: float = 8.5
    pad_x: float = 1.1
    num_align: str = "center"


# --------------------------------------------------------------------------- data

def load_items() -> tuple[str, list[dict]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    items = []
    for raw in data["items"]:
        q = Decimal(raw["quantity"])
        p = Decimal(raw["unit_price"])
        d = Decimal(raw["discount_percent"] or "0")
        gross = q * p
        total = (gross - gross * d / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        items.append({"name": raw["name"], "q": q, "p": p, "d": d, "total": total})
    y, m, dd = data["date"].split("-")
    return f"{dd}/{m}/{y}", items


def money(v: Decimal) -> str:
    return format(v, ",.2f")


def trim(v: Decimal) -> str:
    s = format(v, ",f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# --------------------------------------------------------------------------- html

def css(font: str, L: Layout) -> str:
    c = L.cols
    stack = f'"{font}", "Noto Sans", sans-serif'
    faces = []
    for fam, files in {
        "Noto Sans Arabic": ("NotoSansArabic-Regular", "NotoSansArabic-Bold"),
        "Noto Naskh Arabic": ("NotoNaskhArabic-Regular", "NotoNaskhArabic-Bold"),
        "Noto Sans": ("NotoSans-Regular", "NotoSans-Bold"),
    }.items():
        for weight, f in zip((400, 700), files):
            faces.append(
                f'@font-face {{ font-family: "{fam}"; font-weight: {weight}; '
                f'src: url("fonts/{f}.ttf"); }}'
            )
    page_h = 210 - L.margin_top - L.margin_bottom - 0.5   # a hair under the page box: no spill-over page
    tables_top = L.header_h + L.gap_v
    return "\n".join(faces) + f"""
@page {{
  size: A4 landscape;
  margin: {L.margin_top}mm {L.margin_side}mm {L.margin_bottom}mm {L.margin_side}mm;
  @bottom-center {{
    content: "صفحة " counter(page) " من " counter(pages);
    font-family: {stack}; font-size: 8.5pt; color: #333; direction: rtl;
    vertical-align: middle;
  }}
}}
html {{ font-family: {stack}; font-size: {L.font_pt}pt; color: #000; }}
body {{ margin: 0; }}
/* Every page is a fixed block; children are absolutely positioned so tables never move. */
.page {{ position: relative; height: {page_h}mm; break-after: page; }}
.page:last-child {{ break-after: auto; }}

.band {{ position: absolute; top: 0; left: 0; right: 0; height: {L.header_h}mm; border-bottom: 0.8pt solid #000; }}
.band .title {{ float: right; font-size: 20pt; font-weight: 700; line-height: {L.header_h}mm; }}
.band .date {{ float: left; font-size: 11pt; line-height: {L.header_h}mm; }}


table {{
  width: {L.table_w}mm; table-layout: fixed; border-collapse: collapse;
  border: 0.8pt solid #000;
}}
table.first {{ position: absolute; top: {tables_top}mm; right: 0; }}
table.second {{ position: absolute; top: {tables_top}mm; left: 0; }}
col.name {{ width: {c['name']}mm; }} col.qty {{ width: {c['qty']}mm; }}
col.price {{ width: {c['price']}mm; }} col.disc {{ width: {c['disc']}mm; }}
col.total {{ width: {c['total']}mm; }}
th, td {{
  height: {L.row_h}mm; padding: 0 {L.pad_x}mm; border: 0.4pt solid #555;
  white-space: nowrap; overflow: hidden; vertical-align: middle; line-height: 1.2;
}}
th {{ background: #e3e3e3; font-weight: 700; text-align: center; border-bottom: 0.8pt solid #000; }}
td.name {{ text-align: right; }}
/* WeasyPrint's text-overflow is broken for RTL lines: ellipsis only on pure-LTR names, RTL names clip. */
td.name[dir="ltr"] {{ text-overflow: ellipsis; }}
td.num {{ text-align: {L.num_align}; font-variant-numeric: tabular-nums; }}
.num bdi {{ unicode-bidi: isolate; direction: ltr; }}
tfoot td {{ font-weight: 700; background: #f0f0f0; border-top: 0.8pt solid #000; }}
tfoot td.label {{ text-align: right; }}

.summary .box {{
  position: absolute; bottom: 0; right: 0; border: 1pt solid #000; padding: 0 5mm; height: {L.summary_h - 1}mm;
  line-height: {L.summary_h - 1}mm; font-size: 13pt; font-weight: 700; background: #f0f0f0;
}}
.summary .box .amount {{ margin-right: 6mm; font-variant-numeric: tabular-nums; }}
"""


def name_dir(name: str) -> str:
    """Pure-LTR names (no Arabic letters) get dir=ltr so overflow/ellipsis happen at their end."""
    has_rtl = any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in name)
    return "" if has_rtl else ' dir="ltr"'


def table_html(rows: list[dict], running: Decimal, cls: str) -> str:
    out = [f'<table class="{cls}"><colgroup>'
           '<col class="name"><col class="qty"><col class="price"><col class="disc"><col class="total">'
           '</colgroup><thead><tr><th>اسم الصنف</th><th>الكمية</th><th>السعر</th><th>الخصم</th>'
           '<th>الإجمالي</th></tr></thead><tbody>']
    for it in rows:
        out.append(
            f'<tr><td class="name"{name_dir(it["name"])}>{html.escape(it["name"])}</td>'
            f'<td class="num"><bdi dir="ltr">{trim(it["q"])}</bdi></td>'
            f'<td class="num"><bdi dir="ltr">{money(it["p"])}</bdi></td>'
            f'<td class="num"><bdi dir="ltr">{trim(it["d"])}%</bdi></td>'
            f'<td class="num"><bdi dir="ltr">{money(it["total"])}</bdi></td></tr>'
        )
    for _ in range(20 - len(rows)):
        out.append('<tr class="pad"><td></td><td></td><td></td><td></td><td></td></tr>')
    out.append(f'</tbody><tfoot><tr><td class="label" colspan="4">الإجمالي المتراكم</td>'
               f'<td class="num"><bdi dir="ltr">{money(running)}</bdi></td></tr></tfoot></table>')
    return "".join(out)


def document_html(date: str, items: list[dict], font: str, L: Layout) -> str:
    tables, running = [], Decimal("0")
    for i in range(0, len(items), 20):
        chunk = items[i:i + 20]
        running += sum((it["total"] for it in chunk), Decimal("0"))
        tables.append((chunk, running))
    pages = [tables[i:i + 2] for i in range(0, len(tables), 2)]
    grand = running
    body = []
    for pi, page in enumerate(pages):
        last = pi == len(pages) - 1
        ts = "".join(table_html(rows, run, "first" if ti == 0 else "second")
                     for ti, (rows, run) in enumerate(page))
        summary = (f'<div class="box"><span class="label">الإجمالي الكلي</span>'
                   f'<span class="amount"><bdi dir="ltr">{money(grand)}</bdi></span></div>'
                   if last else "")
        body.append(
            f'<section class="page"><header class="band"><div class="title">فاتورة</div>'
            f'<div class="date">التاريخ: <bdi dir="ltr">{date}</bdi></div></header>'
            f'{ts}<div class="summary">{summary}</div></section>'
        )
    return (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
            f'<style>{css(font, L)}</style></head><body>{"".join(body)}</body></html>')


# --------------------------------------------------------------------------- measure

def walk(box):
    """Like box.descendants(), but also enters absolutely-positioned placeholders."""
    yield box
    inner = getattr(box, "_box", None)
    for child in ([inner] if inner is not None else getattr(box, "children", [])):
        yield from walk(child)


def measure(document) -> dict:
    """Widest text per column vs the cell's available content width (mm)."""
    names = {0: "name", 1: "qty", 2: "price", 3: "disc", 4: "total"}
    stats: dict[str, list[float]] = {}
    for page in document.pages:
        for box in walk(page._page_box):
            if type(box).__name__ != "TableCellBox":
                continue
            key = names.get(box.grid_x, "?")
            if box.colspan > 1:
                key = "footer-label"
            elif box.element_tag == "th":
                key = "th-" + key
            used = max((sum(c.width for c in line.children)
                        for line in box.descendants() if type(line).__name__ == "LineBox"),
                       default=0.0)
            if used:
                s = stats.setdefault(key, [0.0, box.width / PX_PER_MM])
                s[0] = max(s[0], used / PX_PER_MM)
    return {k: (round(u, 1), round(a, 1)) for k, (u, a) in stats.items()}


def vertical(document) -> str:
    """Top-bottom (mm from the page top) of the header band, tables and summary box, last page."""
    out = []
    for box in walk(document.pages[-1]._page_box):
        el = getattr(box, "element", None)
        cls = (el.get("class") or "") if el is not None else ""
        if cls in ("band", "first", "second", "box") and type(box).__name__ != "TableBox":
            y0 = box.border_box_y() / PX_PER_MM
            out.append(f"{cls} {y0:.1f}-{y0 + box.border_height() / PX_PER_MM:.1f}")
    return ", ".join(out) + "mm"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", default="sans,naskh")
    ap.add_argument("--align", default="center")
    ap.add_argument("--font-pt", type=float, default=None)
    ap.add_argument("--row-h", type=float, default=None)
    ap.add_argument("--cols", default=None, help="name,qty,price,disc,total in mm")
    ap.add_argument("--table-w", type=float, default=None)
    ap.add_argument("--margin-side", type=float, default=None)
    ap.add_argument("--pad-x", type=float, default=None)
    ap.add_argument("--suffix", default="")
    args = ap.parse_args()

    L = Layout(num_align=args.align)
    if args.font_pt: L.font_pt = args.font_pt
    if args.row_h: L.row_h = args.row_h
    if args.table_w: L.table_w = args.table_w
    if args.margin_side is not None: L.margin_side = args.margin_side
    if args.pad_x is not None: L.pad_x = args.pad_x
    if args.cols:
        L.cols = dict(zip(["name", "qty", "price", "disc", "total"], map(float, args.cols.split(","))))
    assert abs(sum(L.cols.values()) - L.table_w) < 0.01, "columns must add up to table width"

    content_h = 210 - L.margin_top - L.margin_bottom
    used_h = L.header_h + L.gap_v + 22 * L.row_h + L.gap_v + L.summary_h
    print(f"layout: content {297 - 2*L.margin_side:.0f}x{content_h:.0f}mm, "
          f"used height {used_h:.1f}mm, slack {content_h - used_h:.1f}mm; "
          f"gap between tables {297 - 2*L.margin_side - 2*L.table_w:.1f}mm")

    date, items = load_items()
    OUT.mkdir(parents=True, exist_ok=True)
    for key in args.fonts.split(","):
        font = FONTS[key]
        name = f"spike-{key}{args.suffix}"
        doc = HTML(string=document_html(date, items, font, L), base_url=str(ASSETS) + "/").render()
        pdf = OUT / f"{name}.pdf"
        doc.write_pdf(pdf)
        subprocess.run(["pdftoppm", "-r", "110", "-png", str(pdf), str(OUT / name)], check=True)
        print(f"{name}: {len(doc.pages)} pages -> {pdf.relative_to(ROOT)}")
        print(f"    vertical: {vertical(doc)} (page body ends at {210 - L.margin_bottom}mm)")
        for col, (used, avail) in measure(doc).items():
            flag = "  OVERFLOW" if used > avail else ""
            print(f"    {col:13s} widest text {used:5.1f}mm / available {avail:5.1f}mm{flag}")
    print(f"pages expected: {math.ceil(len(items) / 40)}")


if __name__ == "__main__":
    main()
