import base64
import logging
import math
import re
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.api.limits import SlidingWindowRateLimiter
from app.api.schemas import (
    MSG_BAD_REQUEST,
    MSG_DATE_INVALID,
    MSG_DISCOUNT_INVALID,
    MSG_NAME_REQUIRED,
    MSG_NAME_TOO_LONG,
    MSG_NO_ITEMS,
    MSG_PRICE_INVALID,
    MSG_PRICE_NOT_NUMBER,
    MSG_QUANTITY_INVALID,
    MSG_QUANTITY_NOT_NUMBER,
    MSG_QUANTITY_NOT_POSITIVE,
    MSG_TOO_MANY_ITEMS,
    MSG_TOTAL_TOO_LARGE,
)
from app.config import MAX_BODY_BYTES, Settings
from app.main import create_app
from tests.support import FIXTURES_DIR, load_fixture

URL = "/api/invoice/pdf"
DATE = "2026-10-03"


def client(render_slot_timeout: float = 10.0, **settings) -> TestClient:
    return TestClient(create_app(Settings(**settings), render_slot_timeout=render_slot_timeout))


def item(name="سكر أبيض", quantity="2.5", unit_price="45.00", discount_percent="10", **extra) -> dict:
    return {"name": name, "quantity": quantity, "unit_price": unit_price, "discount_percent": discount_percent, **extra}


def body(*items, date=DATE) -> dict:
    return {"date": date, "items": list(items)}


def errors(response) -> list[tuple]:
    return [(e["row"], e["field"], e["message"]) for e in response.json()["errors"]]


@pytest.fixture
def api() -> TestClient:
    return client()


# --------------------------------------------------------------------------- success


def test_valid_request_returns_a_pdf(api):
    r = api.post(URL, json=body(item()))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="invoice-2026-10-03.pdf"'
    assert r.headers["cache-control"] == "no-store"
    assert r.content.startswith(b"%PDF-")
    text = PdfReader(BytesIO(r.content)).pages[0].extract_text()
    assert "101.25" in text


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES_DIR.glob("*.json")))
def test_every_fixture_is_a_valid_request(name):
    payload = load_fixture(name)
    r = client(rate_limit_per_minute=100).post(URL, json=payload)
    assert r.status_code == 200, r.text
    assert len(PdfReader(BytesIO(r.content)).pages) == math.ceil(len(payload["items"]) / 40)


def test_arabic_and_persian_digits_are_accepted(api):
    r = api.post(URL, json=body(item(quantity="٢٫٥", unit_price="١٬٢٥٠٫٥٠", discount_percent="۱۰")))
    assert r.status_code == 200
    assert "2,813.63" in PdfReader(BytesIO(r.content)).pages[0].extract_text()  # 2.5 × 1250.50 × 0.9


def test_empty_discount_means_zero(api):
    r = api.post(URL, json=body(item(discount_percent=""), item(discount_percent=None)))
    assert r.status_code == 200
    assert "112.50" in PdfReader(BytesIO(r.content)).pages[0].extract_text()


def test_fully_empty_rows_are_ignored_but_keep_row_numbers(api):
    blank = {"name": " ", "quantity": "", "unit_price": "", "discount_percent": ""}
    assert api.post(URL, json=body(item(), blank, {}, item())).status_code == 200
    r = api.post(URL, json=body(item(), blank, item(quantity="abc")))
    assert errors(r) == [(3, "quantity", MSG_QUANTITY_NOT_NUMBER)]


def test_rows_of_invisible_characters_count_as_blank(api):
    invisible = {"name": "\ufeff", "quantity": "\ufeff", "unit_price": "\u200f", "discount_percent": "\x85"}
    assert api.post(URL, json=body(item(), invisible)).status_code == 200


def test_derived_fields_sent_by_the_client_are_ignored(api):
    tampered = item(quantity="2", unit_price="10.00", discount_percent="0", total="999999.00", gross="1", discount_amount="5")
    r = api.post(URL, json=body(tampered) | {"grand_total": "999999.00"})
    assert r.status_code == 200
    text = PdfReader(BytesIO(r.content)).pages[0].extract_text()
    assert "20.00" in text and "999,999.00" not in text


def test_pdf_respects_configured_pagination():
    r = client(rows_per_table=10, tables_per_page=1).post(URL, json=body(*[item()] * 25))
    assert r.status_code == 200
    assert len(PdfReader(BytesIO(r.content)).pages) == 3


# --------------------------------------------------------------------------- validation rules (422)


@pytest.mark.parametrize(
    ("row", "field", "message"),
    [
        (item(name=""), "name", MSG_NAME_REQUIRED),
        (item(name="   "), "name", MSG_NAME_REQUIRED),
        (item(name="x" * 41), "name", MSG_NAME_TOO_LONG),
        (item(quantity=""), "quantity", MSG_QUANTITY_NOT_NUMBER),
        (item(quantity="abc"), "quantity", MSG_QUANTITY_NOT_NUMBER),
        (item(quantity="1e3"), "quantity", MSG_QUANTITY_NOT_NUMBER),
        (item(quantity="0"), "quantity", MSG_QUANTITY_NOT_POSITIVE),
        (item(quantity="-2"), "quantity", MSG_QUANTITY_NOT_POSITIVE),
        (item(quantity="1.0001"), "quantity", MSG_QUANTITY_INVALID),
        (item(quantity="1000000.001"), "quantity", MSG_QUANTITY_INVALID),
        (item(unit_price=""), "unit_price", MSG_PRICE_NOT_NUMBER),
        (item(unit_price="x"), "unit_price", MSG_PRICE_NOT_NUMBER),
        (item(unit_price="-0.01"), "unit_price", MSG_PRICE_NOT_NUMBER),
        (item(unit_price="1.001"), "unit_price", MSG_PRICE_INVALID),
        (item(unit_price="10000000.01"), "unit_price", MSG_PRICE_INVALID),
        # > 28 significant digits must not be rounded into an "allowed" number of decimals.
        (item(quantity="1.0049999999999999999999999999"), "quantity", MSG_QUANTITY_INVALID),
        (item(unit_price="1.0099999999999999999999999999"), "unit_price", MSG_PRICE_INVALID),
        (item(discount_percent="12.000000000000000000000000001"), "discount_percent", MSG_DISCOUNT_INVALID),
        (item(discount_percent="x"), "discount_percent", MSG_DISCOUNT_INVALID),
        (item(discount_percent="-1"), "discount_percent", MSG_DISCOUNT_INVALID),
        (item(discount_percent="100.01"), "discount_percent", MSG_DISCOUNT_INVALID),
        (item(discount_percent="12.345"), "discount_percent", MSG_DISCOUNT_INVALID),
        (item(quantity="100", unit_price="10000000", discount_percent="0"), "total", MSG_TOTAL_TOO_LARGE),
    ],
)
def test_each_rule_reports_the_right_row_and_field(api, row, field, message):
    r = api.post(URL, json=body(item(), item(), row))
    assert r.status_code == 422
    assert errors(r) == [(3, field, message)]


def test_all_errors_of_a_row_are_reported(api):
    r = api.post(URL, json=body(item(name="", quantity="0", unit_price="-1", discount_percent="101")))
    assert errors(r) == [
        (1, "name", MSG_NAME_REQUIRED),
        (1, "quantity", MSG_QUANTITY_NOT_POSITIVE),
        (1, "unit_price", MSG_PRICE_NOT_NUMBER),
        (1, "discount_percent", MSG_DISCOUNT_INVALID),
    ]


def test_line_total_error_is_reported_together_with_a_name_error(api):
    r = api.post(URL, json=body(item(name="", quantity="100", unit_price="10000000", discount_percent="0")))
    assert errors(r) == [(1, "name", MSG_NAME_REQUIRED), (1, "total", MSG_TOTAL_TOO_LARGE)]


def test_boundary_values_are_accepted(api):
    rows = [
        item(name="x" * 40, quantity="0.001", unit_price="0", discount_percent="100"),
        item(quantity="1000000", unit_price="0.01", discount_percent="0"),
        item(quantity="99.99", unit_price="10000000", discount_percent="0"),  # grand total stays under the cap
        item(unit_price="45.000"),  # trailing zeros are not significant decimals
    ]
    assert api.post(URL, json=body(*rows)).status_code == 200


def test_grand_total_over_the_limit(api):
    big = item(quantity="99.999", unit_price="10000000", discount_percent="0")
    assert errors(api.post(URL, json=body(big, big))) == [(None, "grand_total", MSG_TOTAL_TOO_LARGE)]


def test_zero_items(api):
    assert errors(api.post(URL, json=body())) == [(None, "items", MSG_NO_ITEMS)]
    assert errors(api.post(URL, json={"date": DATE})) == [(None, "items", MSG_NO_ITEMS)]


def test_more_than_max_items():
    small = client(max_items=5)
    assert small.post(URL, json=body(*[item()] * 5)).status_code == 200
    assert errors(small.post(URL, json=body(*[item()] * 6))) == [(None, "items", MSG_TOO_MANY_ITEMS)]


def test_default_max_items_is_1000(api):
    assert errors(api.post(URL, json=body(*[item()] * 1001))) == [(None, "items", MSG_TOO_MANY_ITEMS)]


@pytest.mark.parametrize("date", ["", "2026-02-30", "2026-13-01", "03/10/2026", "20261003", "2026-W40-6", "٢٠٢٦-١٠-٠٣", None])
def test_invalid_dates(api, date):
    assert (None, "date", MSG_DATE_INVALID) in errors(api.post(URL, json=body(item(), date=date)))


@pytest.mark.parametrize(
    ("value", "field", "message"),
    [
        (2.5, "quantity", MSG_QUANTITY_NOT_NUMBER),  # JSON numbers are rejected: numbers travel as strings
        (45, "unit_price", MSG_PRICE_NOT_NUMBER),
        (10, "discount_percent", MSG_DISCOUNT_INVALID),
        (["x"], "name", MSG_NAME_REQUIRED),
    ],
)
def test_wrong_json_types_map_to_the_cell(api, value, field, message):
    r = api.post(URL, json=body(item(), item(**{field: value})))
    assert errors(r) == [(2, field, message)]


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"[]", b'"text"', b'{"date": "2026-10-03", "items": "x"}', b'{"date": "2026-10-03", "items": [1]}'],
)
def test_malformed_requests(api, payload):
    r = api.post(URL, content=payload, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert all(e["message"] == MSG_BAD_REQUEST for e in r.json()["errors"])


def test_errors_never_echo_the_input(api):
    r = api.post(URL, json=body(item(name="سر-خاص-جدا", quantity="secret-value-123")))
    assert r.status_code == 422
    assert "secret-value-123" not in r.text and "سر-خاص-جدا" not in r.text


# --------------------------------------------------------------------------- limits


def test_body_larger_than_256kb_is_rejected_by_content_length(api):
    padding = "x" * (MAX_BODY_BYTES + 1)
    r = api.post(URL, content=padding.encode(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["errors"][0]["message"] == "حجم الطلب أكبر من الحد المسموح"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_streamed_body_without_content_length_is_rejected(api):
    def chunks():
        for _ in range(40):
            yield b"x" * 8192  # 320 KB in total, no Content-Length header

    r = api.post(URL, content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_body_just_under_the_limit_is_accepted(api):
    payload = body(item(name="x"))
    raw = len(str(payload).encode())
    payload["padding"] = "x" * (MAX_BODY_BYTES - raw - 200)  # unknown keys are ignored
    assert api.post(URL, json=payload).status_code == 200


def test_rate_limit_returns_429_with_retry_after():
    limited = client(rate_limit_per_minute=3)
    for _ in range(3):
        assert limited.post(URL, json=body()).status_code == 422  # invalid requests count too
    r = limited.post(URL, json=body(item()))
    assert r.status_code == 429
    assert r.json()["errors"][0]["message"] == "عدد الطلبات كبير، حاول مرة أخرى بعد دقيقة"
    assert 1 <= int(r.headers["retry-after"]) <= 60
    # A spoofed X-Forwarded-For does not get around the limit (only uvicorn's trusted proxy handling sets the client IP).
    assert limited.post(URL, json=body(item()), headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 429
    # Other routes are not rate limited.
    assert limited.get("/healthz").status_code == 200


def test_sliding_window_limiter():
    now = [1000.0]
    limiter = SlidingWindowRateLimiter(limit=2, window=60, clock=lambda: now[0])
    assert limiter.hit("a") == 0 and limiter.hit("a") == 0
    assert limiter.hit("a") == pytest.approx(60)
    assert limiter.hit("b") == 0  # per key
    now[0] += 30
    assert limiter.hit("a") == pytest.approx(30)
    now[0] += 30.001
    assert limiter.hit("a") == 0  # the oldest hit left the window


def test_render_capacity_busy_returns_503():
    busy = client(max_concurrent_renders=1, render_slot_timeout=0.2)
    semaphore = busy.app.state.render_slots._semaphore
    semaphore.acquire()
    try:
        r = busy.post(URL, json=body(item()))
    finally:
        semaphore.release()
    assert r.status_code == 503
    assert r.json()["errors"][0]["message"] == "الخادم مشغول، حاول مرة أخرى بعد قليل"
    assert r.headers["retry-after"] == "5"
    assert busy.post(URL, json=body(item())).status_code == 200  # slot released


# --------------------------------------------------------------------------- pages, headers, docs, auth


SECURITY_HEADERS = {
    "content-security-policy": "default-src 'self'; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


@pytest.mark.parametrize(("method", "path"), [("get", "/"), ("get", "/healthz"), ("get", "/missing"), ("post", URL), ("get", "/static/app.js")])
def test_security_headers_everywhere(api, method, path):
    r = getattr(api, method)(path, **({"json": body(item())} if method == "post" else {}))
    for key, value in SECURITY_HEADERS.items():
        assert r.headers[key] == value


def test_healthz(api):
    assert api.get("/healthz").json() == {"status": "ok"}


def test_index_page_is_arabic_rtl_and_csp_safe(api):
    r = api.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert '<html lang="ar" dir="rtl">' in html
    assert re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html) is None, "inline <script> found"
    assert re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE) is None, "inline event handler found"
    assert re.search(r"\sstyle\s*=", html, re.IGNORECASE) is None, "inline style attribute found"
    assert "<style" not in html
    assert 'data-max-items="1000"' in html and 'data-rows-per-page="40"' in html


@pytest.mark.parametrize(
    "path",
    ["/static/app.js", "/static/app.css", "/static/vendor/big.min.js", "/fonts/NotoSansArabic-Regular.ttf", "/fonts/NotoSans-Regular.ttf"],
)
def test_static_assets_are_served_locally(api, path):
    assert api.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_disabled_by_default(api, path):
    assert api.get(path).status_code == 404


def test_api_docs_can_be_enabled():
    dev = client(enable_api_docs=True)
    assert dev.get("/openapi.json").status_code == 200
    r = dev.get("/docs")
    assert r.status_code == 200 and "cdn.jsdelivr.net" in r.headers["content-security-policy"]
    assert dev.get("/").headers["content-security-policy"] == SECURITY_HEADERS["content-security-policy"]


def _basic(password: str, user: str = "any") -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_basic_auth_is_off_by_default(api):
    assert api.get("/").status_code == 200


def test_basic_auth_when_app_password_is_set():
    protected = client(app_password="s3cret")
    r = protected.get("/")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")
    assert r.headers["content-security-policy"] == SECURITY_HEADERS["content-security-policy"]
    assert protected.get("/", headers=_basic("wrong")).status_code == 401
    assert protected.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401
    assert protected.get("/", headers=_basic("s3cret")).status_code == 200
    assert protected.post(URL, json=body(item())).status_code == 401
    assert protected.post(URL, json=body(item()), headers=_basic("s3cret")).status_code == 200
    assert protected.get("/healthz").status_code == 200  # Docker healthcheck keeps working


# --------------------------------------------------------------------------- logging


@pytest.fixture
def access_log(caplog):
    logger = logging.getLogger("app.access")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="app.access")
    yield caplog
    logger.removeHandler(caplog.handler)


def test_access_log_has_no_item_contents(api, access_log):
    api.post(URL, json=body(item(name="اسم-سري-للاختبار", unit_price="98765.43")))
    api.post(URL, json=body(item(name="اسم-سري-آخر", quantity="bad")))
    text = access_log.text
    assert "POST /api/invoice/pdf 200" in text and "items=1" in text
    assert "POST /api/invoice/pdf 422" in text
    assert "اسم-سري" not in text and "98765" not in text and "bad" not in text
