# CLAUDE.md — Arabic RTL Invoice PDF Generator

Full reference: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md). **Do not change any decision there without asking the owner first.**
If something in the spec is impossible or wrong, explain and propose an alternative — never silently deviate. Do not invent features.

## How to work
- Work phase by phase (spec §16). Stop at every 🛑 CHECKPOINT and wait for approval.
- Verify, don't assume: run the tests after every change; for any PDF change, render to PNG (`pdftoppm`) and look at the pages
  (connected Arabic letters, correct RTL order, intact numbers, aligned rows/columns).
- Dev host is Linux, but host Python is 3.10 → **run and test everything in Docker** (`compose.dev.yml`).
- One or more meaningful git commits per phase.

## Fixed business rules (§2)
- Simple commercial invoice, title **"فاتورة"**. **No VAT. Header = date only** (no invoice no., customer, company, logo).
- Discount: **percentage only**, 0–100, default 0. Quantity: > 0, ≤ 3 decimals. Price: ≥ 0, ≤ 2 decimals. Name: required, ≤ **40** chars after trim.
- **Western digits** everywhere (`1,250.50`). **No currency symbol anywhere.**
- **20 rows per table, 2 tables per page side by side; first table on the RIGHT.** Partial tables padded with empty ruled rows to 20.
- Each table footer: running total **"الإجمالي المتراكم"** (cumulative through that table).
- Grand total **"الإجمالي الكلي"** on the **last page only**. Page numbers **"صفحة X من Y"**. Paper **A4 landscape**.
- Public, no password (optional `APP_PASSWORD` Basic Auth exists, empty = off). Hosting: Oracle Always Free Arm VM + Docker + Caddy + DuckDNS; Cloud Run fallback.

## Stack (§3)
- Python 3.12, FastAPI + Uvicorn, Pydantic v2 (`Decimal`), Jinja2 (autoescape ON), WeasyPrint, vanilla JS + vendored `big.js`.
- Fonts: bundled Noto Sans Arabic + Noto Sans TTFs (+ OFL) via `@font-face` only.
- Tests: pytest, hypothesis, pypdf, FastAPI TestClient. Pin all Python deps to exact versions.
- **Forbidden:** Django, React/Vue/any frontend framework, npm/build step, any database/ORM, accounts, sessions,
  Celery/background workers, CDN assets, internet-loaded Google Fonts, **`float` for money**, localStorage/drafts.

## Money & architecture rules
- `Decimal` everywhere, constructed **only from strings**; client sends numbers as JSON strings.
- Line total = (qty × price − qty × price × disc/100) quantized 0.01 `ROUND_HALF_UP`, rounded once per line.
  All running/grand totals are sums of rounded line totals. Server recomputes everything; derived fields are never accepted.
- `app/domain` is pure Python (no FastAPI/WeasyPrint). `api` and `pdf` depend on `domain`, never the reverse.
- Templates contain **no arithmetic and no formatting** — only pre-formatted strings from `pdf/viewmodel.py`.

## Security & limits (§11) — mandatory
- `MAX_ITEMS` 1000; max body **256 KB** (Caddy **and** app); **10 PDF req/min/IP** in-memory sliding window → 429 (Arabic msg);
  trust `X-Forwarded-For` only via trusted proxy (uvicorn `--proxy-headers --forwarded-allow-ips`).
- Max **2** concurrent renders (semaphore); no slot within ~10 s → 503.
- Headers: CSP `default-src 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `frame-ancestors 'none'`; HSTS at Caddy.
- WeasyPrint gets a custom `url_fetcher` allowing **only** the local asset dir. Render in memory; never write PDFs to disk.
- Never log request bodies or item contents (method, path, status, duration, item count only).
- Container runs as **non-root**. No inline `<script>`/event handlers (CSP). PDF endpoint is plain `def` (threadpool).
