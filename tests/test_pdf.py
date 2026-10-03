import logging
import math
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader
from weasyprint import HTML

from app.domain.numbers import format_money
from app.domain.pagination import paginate
from app.pdf.renderer import ASSETS_DIR, AssetURLFetcher, InvoicePdfRenderer
from app.pdf.viewmodel import build_invoice_view, name_direction, row_height
from tests.support import FIXTURES_DIR, fixture_invoice

A4_LANDSCAPE_PT = (841.89, 595.28)
SIZES = [1, 20, 21, 40, 41, 45, 65, 80, 81]
ALL_FIXTURES = sorted(p.stem for p in FIXTURES_DIR.glob("*.json"))
REGULAR_FIXTURES = [name for name in ALL_FIXTURES if name != "edge_limits"]
PX_PER_MM = 96 / 25.4


@pytest.fixture(scope="module")
def renderer() -> InvoicePdfRenderer:
    return InvoicePdfRenderer()


@pytest.fixture(scope="module")
def rendered(renderer):
    """name → (invoice, PdfReader); every fixture is rendered once per test module."""
    cache = {}

    def get(name):
        if name not in cache:
            invoice = fixture_invoice(name)
            pdf = renderer.render_pdf(build_invoice_view(invoice))
            assert pdf.startswith(b"%PDF-")
            cache[name] = (invoice, PdfReader(BytesIO(pdf)))
        return cache[name]

    return get


# --------------------------------------------------------------------------- PDF output


@pytest.mark.parametrize("n", SIZES)
def test_page_count(rendered, n):
    invoice, reader = rendered(f"items_{n}")
    assert len(invoice.items) == n
    assert len(reader.pages) == math.ceil(n / 40)


@pytest.mark.parametrize("n", SIZES)
def test_pages_are_a4_landscape(rendered, n):
    _, reader = rendered(f"items_{n}")
    for page in reader.pages:
        box = page.mediabox
        assert float(box.width) == pytest.approx(A4_LANDSCAPE_PT[0], abs=0.5)
        assert float(box.height) == pytest.approx(A4_LANDSCAPE_PT[1], abs=0.5)


def _fonts(reader: PdfReader) -> dict[str, bool]:
    fonts = {}
    for page in reader.pages:
        for ref in page["/Resources"]["/Font"].values():
            font = ref.get_object()
            descriptor_owner = font["/DescendantFonts"][0].get_object() if "/DescendantFonts" in font else font
            descriptor = descriptor_owner["/FontDescriptor"].get_object()
            name = str(font["/BaseFont"]).split("+", 1)[-1]
            fonts[name] = any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
    return fonts


@pytest.mark.parametrize("n", SIZES)
def test_fonts_are_embedded(rendered, n):
    _, reader = rendered(f"items_{n}")
    fonts = _fonts(reader)
    assert fonts, "no fonts found"
    assert all(fonts.values()), fonts
    assert all(name.startswith("Noto-Sans") for name in fonts), fonts  # bundled fonts only
    assert "Noto-Sans-Arabic" in fonts and "Noto-Sans-Arabic-Bold" in fonts


@pytest.mark.parametrize("n", SIZES)
def test_running_totals_and_grand_total_appear(rendered, n):
    invoice, reader = rendered(f"items_{n}")
    texts = [page.extract_text() for page in reader.pages]
    for page, text in zip(paginate(invoice.items), texts):
        for table in page.tables:
            assert format_money(table.running_total) in text
    grand = format_money(invoice.grand_total)
    # On the last page: the last table's running total and the grand-total box.
    assert texts[-1].count(grand) >= 2
    # Grand total is printed on the last page only (fixtures end with non-zero lines).
    for text in texts[:-1]:
        assert grand not in text


def test_every_line_total_is_printed(rendered):
    invoice, reader = rendered("items_45")
    text = "".join(page.extract_text() for page in reader.pages)
    for item in invoice.items:
        assert format_money(item.total) in text


def test_render_returns_bytes_in_memory(renderer):
    pdf = renderer.render_pdf(build_invoice_view(fixture_invoice("items_1")))
    assert isinstance(pdf, bytes) and pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")


# --------------------------------------------------------------------------- geometry


def _walk(box):
    """Like box.descendants(), but also enters absolutely-positioned placeholders."""
    yield box
    inner = getattr(box, "_box", None)
    for child in [inner] if inner is not None else getattr(box, "children", []):
        yield from _walk(child)


def _overflowing_cells(document) -> list[tuple[int, str, str, float, float]]:
    """(page, cell class, text, used mm, available mm) for every table cell whose text overflows.

    Uses WeasyPrint's layout tree (internal API; WeasyPrint is pinned in requirements.txt).
    """
    found = []
    for page_number, page in enumerate(document.pages, 1):
        for box in _walk(page._page_box):
            if type(box).__name__ != "TableCellBox":
                continue
            lines = [b for b in _walk(box) if type(b).__name__ == "LineBox"]
            used = max((sum(child.width for child in line.children) for line in lines), default=0)
            if used > box.width + 0.01:
                text = "".join(b.text for b in _walk(box) if type(b).__name__ == "TextBox")
                found.append((page_number, box.element.get("class") or box.element_tag, text,
                              round(used / PX_PER_MM, 1), round(box.width / PX_PER_MM, 1)))
    return found


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_numbers_and_labels_never_overflow(renderer, name):
    document = renderer.layout(build_invoice_view(fixture_invoice(name)))
    assert [cell for cell in _overflowing_cells(document) if cell[1] != "name"] == []


@pytest.mark.parametrize("name", REGULAR_FIXTURES)
def test_names_fit_on_one_line(renderer, name):
    document = renderer.layout(build_invoice_view(fixture_invoice(name)))
    assert _overflowing_cells(document) == []


def test_edge_fixture_only_the_deliberately_wide_names_overflow(renderer):
    document = renderer.layout(build_invoice_view(fixture_invoice("edge_limits")))
    overflowing = {cell[2] for cell in _overflowing_cells(document)}
    # The layout tree keeps the full width of an ellipsized LTR line, so the all-caps name is
    # reported here even though it is drawn truncated with "…" (checked visually in samples/).
    assert overflowing <= {
        "SAMSUNG GALAXY S24 ULTRA 5G 512GB VIOLET",
        "مكيف شارب 1.5 حصان بارد ساخن مع تركيب مج",
        "<b>وسم</b> & \"اقتباس\" 'مفرد' <img src=x>",
    }


# --------------------------------------------------------------------------- template / escaping


def test_item_names_are_html_escaped(renderer):
    html = renderer.render_html(build_invoice_view(fixture_invoice("edge_limits")))
    assert "&lt;img src=x&gt;" in html
    assert "&lt;b&gt;وسم&lt;/b&gt; &amp; &#34;اقتباس&#34; &#39;مفرد&#39;" in html
    assert "<img" not in html and "<b>" not in html


def test_template_structure(renderer):
    html = renderer.render_html(build_invoice_view(fixture_invoice("items_65")))
    assert '<html lang="ar" dir="rtl">' in html
    assert html.count('<section class="page">') == 2
    assert html.count("items--right") == 2 and html.count("items--left") == 2
    assert html.count('<tr class="pad">') == 15
    assert html.count("الإجمالي الكلي") == 1
    assert html.count("التاريخ: <bdi dir=\"ltr\">03/10/2026</bdi>") == 2


# --------------------------------------------------------------------------- url fetcher


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/font.ttf",
        "https://169.254.169.254/latest/meta-data/",
        "ftp://example.com/x",
        "data:text/plain,hello",
        "file:///etc/passwd",
        "file://remote-host" + str(ASSETS_DIR / "fonts" / "NotoSans-Regular.ttf"),
        (ASSETS_DIR / "fonts").as_uri() + "/../../pdf/renderer.py",
        (ASSETS_DIR / "fonts").as_uri() + "/missing.ttf",
        ASSETS_DIR.as_uri(),  # a directory, not a file
    ],
)
def test_url_fetcher_refuses_everything_outside_the_assets(url):
    with pytest.raises(PermissionError):
        AssetURLFetcher(ASSETS_DIR).fetch(url)


def test_url_fetcher_serves_bundled_fonts():
    font = ASSETS_DIR / "fonts" / "NotoSansArabic-Regular.ttf"
    response = AssetURLFetcher(ASSETS_DIR).fetch(font.as_uri())
    assert response.read() == font.read_bytes()


def test_url_fetcher_refuses_symlinks_that_escape(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (root / "link.txt").symlink_to(secret)
    with pytest.raises(PermissionError):
        AssetURLFetcher(root).fetch((root / "link.txt").as_uri())


def test_injected_resources_are_not_loaded(caplog):
    fetcher = AssetURLFetcher(ASSETS_DIR)
    html = '<img src="file:///etc/passwd"><img src="http://127.0.0.1:1/x.png"><p>x</p>'
    with caplog.at_level(logging.WARNING):
        pdf = HTML(string=html, base_url=ASSETS_DIR.as_uri() + "/", url_fetcher=fetcher).write_pdf()
    assert pdf.startswith(b"%PDF-")
    assert b"/Subtype /Image" not in pdf
    assert caplog.text.count("Blocked resource request") == 2


# --------------------------------------------------------------------------- view model


@pytest.mark.parametrize(
    ("name", "direction"),
    [
        ("سكر أبيض", "rtl"),
        ("شاشة Samsung 55 بوصة", "rtl"),
        ("Samsung شاشة", "rtl"),
        ("iPhone 15 Pro Max 256GB", "ltr"),
        ("Model X (2024)", "ltr"),
        ("12345", "ltr"),
    ],
)
def test_name_direction(name, direction):
    assert name_direction(name) == direction


@pytest.mark.parametrize(("rows", "height"), [(20, "7.00mm"), (10, "7.00mm"), (25, "5.70mm"), (30, "4.81mm")])
def test_row_height_shrinks_only_when_more_rows_are_configured(rows, height):
    assert row_height(rows) == height


def test_view_model_contains_only_preformatted_strings():
    view = build_invoice_view(fixture_invoice("items_21"))
    assert view.date == "03/10/2026"
    assert view.grand_total == "210,240.63"
    first, second = view.pages[0].tables
    assert (first.side, second.side) == ("right", "left")
    assert (len(first.rows), first.padding_count, len(second.rows), second.padding_count) == (20, 0, 1, 19)
    assert first.running_total == "210,079.13" and second.running_total == "210,240.63"
    row = first.rows[0]
    assert (row.name, row.quantity, row.unit_price, row.discount, row.total) == ("سكر أبيض", "2.5", "45.00", "10%", "101.25")
    assert first.rows[2].discount == "5%" and first.rows[8].unit_price == "0.00" and first.rows[9].discount == "100%"
    for page in view.pages:
        for table in page.tables:
            for r in table.rows:
                assert all(isinstance(v, str) for v in (r.name, r.quantity, r.unit_price, r.discount, r.total))


def test_view_model_rejects_more_than_two_tables_per_page():
    with pytest.raises(ValueError):
        build_invoice_view(fixture_invoice("items_1"), tables_per_page=3)


def test_custom_rows_per_table(renderer):
    invoice = fixture_invoice("items_41")
    view = build_invoice_view(invoice, rows_per_table=25, tables_per_page=1)
    assert [len(t.rows) for p in view.pages for t in p.tables] == [25, 16]
    reader = PdfReader(BytesIO(renderer.render_pdf(view)))
    assert len(reader.pages) == 2
    assert format_money(Decimal(invoice.grand_total)) in reader.pages[-1].extract_text()
