# Project Brief for Claude Code — Arabic RTL Invoice PDF Generator

> **Status (2026-10-15):** the owner changed the architecture to a **static website** (HTML/CSS/JavaScript, no server,
> no Docker) published on GitHub Pages, for one to three users. The business rules (§2, §5–§7) and the approved PDF
> design still apply; the server, API, security-limit, Docker, configuration, hosting and deployment sections
> (§3 stack, §10–§14) describe the earlier server version, which is preserved on the git branch `server-version`.
> See [CLAUDE.md](../CLAUDE.md) and the [README](../README.md) for the current design.

You are acting as a **Senior Software Architect and Senior Python Developer**. Build the complete project described below, phase by phase. Every decision in this document was agreed with the project owner after a full requirements and architecture review. **Do not change any decision in this document without asking first.**

---

## 0. How you must work

1. Read this entire document before writing anything.
2. Create `CLAUDE.md` in the repository root. It must contain a short summary of the non-negotiable rules from sections 2, 3 and 11, so they persist across sessions. Keep this file (`PROJECT_SPEC.md`) in `docs/` as the full reference.
3. Work in the phases defined in section 16. At every **🛑 CHECKPOINT**, stop, summarize what you built, show the results (files, test output, rendered PDF pages), and wait for approval before continuing.
4. Use `git`: initialize the repo, keep a proper `.gitignore`/`.dockerignore`, and make one or more meaningful commits per phase.
5. **Verify, don't assume.** After every change:
   - Run the tests.
   - For any PDF change, render the PDF pages to PNG with `pdftoppm` and look at the images yourself. Check that Arabic letters are connected, the RTL order is correct, numbers are intact, and rows/columns are aligned.
6. If something in this spec is technically impossible or clearly wrong, explain why and propose an alternative. Do not silently deviate.
7. Do not invent features. Anything not described here (VAT, invoice number, customer, currency, database, login, etc.) is **out of scope**.
8. **Development environment.** WeasyPrint needs Pango system libraries, which are awkward to install on native Windows.
   - On Windows, run and test everything inside Docker (or WSL2).
   - On Linux/macOS, a local virtualenv is fine, but the Docker path must always work.
   - Detect the OS at the start and tell me which path you are using.

---

## 1. Product summary

A small web application in Arabic (RTL):

1. The user opens the app in a browser.
2. The user enters invoice items in an editable table. Each row has: item name, quantity, price, discount %. The row total is calculated automatically.
3. The app shows the Grand Total live.
4. The user clicks **"إنشاء PDF"**.
5. The server validates everything, recalculates every value, paginates the items, and returns a professional **A4 landscape, Arabic, RTL** invoice PDF for download/printing.

No data is stored anywhere. The server is stateless.

---

## 2. Fixed business decisions (do not change)

| Topic | Decision |
|---|---|
| Document type | Simple commercial invoice. Title: **"فاتورة"** |
| VAT | **None** |
| Header fields | **Date only** (no invoice number, no customer, no company name/logo) |
| Discount | **Percentage only**, 0–100, default 0 |
| Quantity | Decimals allowed (up to 3 decimal places), must be > 0 |
| Price | Up to 2 decimal places, must be ≥ 0 (free items allowed) |
| Item name | Required, max **40 characters** after trimming |
| Digits | **Western digits** everywhere (e.g. `1,250.50`) |
| Currency | **No currency symbol anywhere** |
| Rows per table | **20** |
| Tables per page | **2**, side by side. The **right-hand table comes first** (Arabic reading order) |
| Partial tables | **Padded with empty ruled rows** to 20 rows for a uniform look |
| Table footer row | **Running (carried-forward) total**: the cumulative sum of all line totals up to and including that table. Label: **"الإجمالي المتراكم"** |
| Grand Total | Bottom of the **last page only**. Label: **"الإجمالي الكلي"** |
| Page numbers | Yes: **"صفحة 1 من 3"** |
| Paper | A4 **landscape** |
| Access | Public link, **no password** (but resource limits are mandatory, see section 11) |
| Hosting | Oracle Cloud Always Free Arm VM + Docker + Caddy (HTTPS), free DuckDNS subdomain. Google Cloud Run is the documented fallback |

---

## 3. Technology stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Web framework | FastAPI + Uvicorn |
| Validation | Pydantic v2 (with `Decimal` fields) |
| Templates | Jinja2 (autoescape ON) for both the UI page and the PDF |
| Frontend | One HTML page, plain CSS, **vanilla JavaScript**. No build step, no npm |
| Client-side math | `big.js`, **vendored** into `static/vendor/` (no CDN at runtime) |
| PDF engine | **WeasyPrint** (Pango + HarfBuzz + FriBidi handle Arabic shaping and bidi) |
| Fonts | **Noto Sans Arabic** + **Noto Sans** (Latin fallback for mixed names), TTF files bundled in the repo with their OFL license. Also bundle **Noto Naskh Arabic** for the Phase 0 comparison. Download them from the official notofonts / Google Fonts GitHub repositories |
| Tests | pytest, hypothesis, pypdf, FastAPI TestClient (httpx) |
| Packaging | Docker (multi-arch: arm64 + amd64), Docker Compose |
| Reverse proxy / HTTPS | Caddy 2 (automatic Let's Encrypt) |

**Explicitly forbidden (non-goals):** Django, React/Vue/any frontend framework, any database or ORM, user accounts, sessions, Celery/background workers, CDN-hosted assets, Google Fonts loaded from the internet, using `float` for money.

Pin all Python dependencies to exact versions (latest stable at implementation time).

---

## 4. Project structure

```text
invoice-app/
├── CLAUDE.md
├── README.md
├── docs/
│   ├── PROJECT_SPEC.md          # this file
│   ├── DEPLOY_ORACLE.md         # step-by-step runbook (section 14)
│   └── DEPLOY_CLOUDRUN.md       # fallback runbook
├── app/
│   ├── main.py                  # app factory, routers, static mount, middleware
│   ├── config.py                # settings from environment variables (section 12)
│   ├── domain/                  # PURE Python — no FastAPI/WeasyPrint imports
│   │   ├── models.py            # LineItem, Invoice (frozen dataclasses, Decimal)
│   │   ├── calculations.py      # line totals, running totals, grand total, rounding
│   │   ├── pagination.py        # paginate(items) → pages → tables
│   │   └── numbers.py           # Arabic-digit normalization, parsing, formatting
│   ├── api/
│   │   ├── schemas.py           # Pydantic request models + structured error model
│   │   ├── routes.py            # GET /, POST /api/invoice/pdf, GET /healthz
│   │   └── limits.py            # rate limiter, concurrency limiter, body-size guard
│   ├── pdf/
│   │   ├── viewmodel.py         # Invoice → pre-formatted view model (strings only)
│   │   ├── renderer.py          # view model → HTML → PDF bytes (engine isolated here)
│   │   ├── templates/invoice.html
│   │   └── styles/invoice.css
│   ├── web/
│   │   ├── templates/index.html
│   │   └── static/
│   │       ├── app.js
│   │       ├── app.css
│   │       └── vendor/big.min.js
│   └── assets/fonts/            # TTF files + OFL.txt
├── scripts/
│   └── render_samples.py        # generates sample PDFs (+ PNGs) from fixtures
├── tests/
│   ├── fixtures/                # JSON item lists (Arabic, mixed, edge cases)
│   ├── test_numbers.py
│   ├── test_calculations.py
│   ├── test_pagination.py
│   ├── test_api.py
│   └── test_pdf.py
├── Dockerfile
├── compose.yml                  # production: app + caddy
├── compose.dev.yml              # development/testing
├── Caddyfile
├── .env.example
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

**Dependency rule:** `api` and `pdf` depend on `domain`; `domain` depends on nothing. Templates contain **no arithmetic and no formatting logic**. They only place pre-formatted strings.

---

## 5. Domain model and calculations

### Data model

```text
LineItem (input)
  name:       str      # trimmed, internal whitespace collapsed, 1..40 chars
  quantity:   Decimal  # > 0, ≤ 3 decimal places
  unit_price: Decimal  # ≥ 0, ≤ 2 decimal places
  discount_percent: Decimal  # 0..100, ≤ 2 decimal places, default 0

LineItem (derived — NEVER accepted from the client)
  gross           = quantity × unit_price
  discount_amount = gross × discount_percent / 100
  total           = (gross − discount_amount) quantized to 0.01, ROUND_HALF_UP

Invoice
  date:  datetime.date        # from the user; UI defaults to today
  items: list[LineItem]       # 1..MAX_ITEMS
  grand_total (derived)       = sum of the ROUNDED line totals
```

### Rules

- Use `Decimal` everywhere for money and quantities. Construct `Decimal` **only from strings**, never from floats. The client sends all numbers as JSON **strings**.
- Round each line once (2 decimals, `ROUND_HALF_UP`). All subtotals, running totals and the grand total are sums of already-rounded line totals, so every number printed on the PDF adds up with a calculator.
- The server is the single source of truth. The browser's live totals are a preview only, computed with `big.js` using the same formula and rounding so they match the PDF exactly.

---

## 6. Input normalization and validation

### Normalization (identical logic on client and server)

- Convert Arabic-Indic digits `٠١٢٣٤٥٦٧٨٩` and Persian digits `۰۱۲۳۴۵۶۷۸۹` to `0-9`.
- Arabic decimal separator `٫` → `.`
- Arabic thousands separator `٬` and the comma `,` are treated as thousands separators and removed.
- Trim whitespace. An empty discount means `0`.
- A row that is **completely empty** (all fields blank) is ignored, not reported as an error. This applies to the trailing blank row in the UI.

### Validation rules (Arabic error messages)

| Field | Rule | Example message |
|---|---|---|
| name | required after trim | `اسم الصنف مطلوب` |
| name | ≤ 40 chars | `اسم الصنف يجب ألا يزيد عن 40 حرفًا` |
| quantity | numeric | `الكمية يجب أن تكون رقمًا` |
| quantity | > 0 | `الكمية يجب أن تكون أكبر من صفر` |
| quantity | ≤ 3 decimals, ≤ 1,000,000 | `الكمية غير صالحة` |
| price | numeric, ≥ 0 | `السعر يجب أن يكون رقمًا لا يقل عن صفر` |
| price | ≤ 2 decimals, ≤ 10,000,000 | `السعر غير صالح` |
| discount | numeric, 0–100, ≤ 2 decimals | `الخصم يجب أن يكون بين 0 و 100` |
| line total / grand total | ≤ 999,999,999.99 (fits the column) | `الإجمالي أكبر من الحد المسموح` |
| invoice | at least 1 item | `أضف صنفًا واحدًا على الأقل` |
| invoice | ≤ MAX_ITEMS items | `عدد الأصناف أكبر من الحد المسموح` |
| date | valid date | `التاريخ غير صالح` |

### Two validation layers

1. **Browser:** instant feedback. Invalid inputs get a red border and the Arabic message under the field. The row total shows `—`. The Generate button is disabled while errors exist, and the footer shows the error count. Clicking it scrolls to the first error.
2. **Server (authoritative):** returns HTTP 422 with a structured list:
   ```json
   {"errors": [{"row": 17, "field": "unit_price", "message": "السعر غير صالح"}]}
   ```
   The UI maps each error back to the exact cell with the same styling. Row numbers are 1-based and refer to the UI rows.

---

## 7. Pagination and running totals

Constants come from config: `ROWS_PER_TABLE = 20`, `TABLES_PER_PAGE = 2`.

### Algorithm (pure function, no PDF dependency)

```text
items (ordered, n ≥ 1)
  → chunk into consecutive groups of ROWS_PER_TABLE      → ceil(n/20) tables
  → for each table: rows, padding_count = 20 − len(rows),
                    running_total = cumulative sum through this table
  → chunk tables into consecutive groups of TABLES_PER_PAGE → ceil(n/40) pages
  → mark the last page: is_last = True (shows the Grand Total)
```

### Required results

| Items | Pages and tables (first table = right side) |
|---|---|
| 1 | P1: [1] |
| 20 | P1: [20] |
| 21 | P1: [20, 1] |
| 40 | P1: [20, 20] |
| 41 | P1: [20, 20] P2: [1] |
| 65 | P1: [20, 20] P2: [20, 5] |
| 80 | P1: [20, 20] P2: [20, 20] |
| 81 | P1: [20, 20] P2: [20, 20] P3: [1] |

### Invariants (test with hypothesis for n = 1…3000)

- Order is preserved.
- No table has more than 20 rows and no page has more than 2 tables.
- Only the last table can be partial, and only the last page can have a single table.
- The page count equals `ceil(n/40)`.
- The sum of all rows equals n.
- Each table's running total equals the sum of all line totals up to its last row.
- The last table's running total equals the grand total.

---

## 8. PDF specification

### Page

- A4 landscape (297 × 210 mm).
- Starting margins: 10 mm sides/top, ~12 mm bottom. Tune these in Phase 0.
- `html lang="ar" dir="rtl"`.

### Layout of every page (identical structure, so tables never move)

1. **Header band:** title **"فاتورة"** and **"التاريخ: DD/MM/YYYY"** (Western digits) on every page.
2. **Two-column area:**
   - First table on the **right**, second on the **left**, with a small gap between them.
   - On a page with one table, it sits on the **right** and the left half stays blank.
3. **Summary band:** space is reserved on **every** page so table positions are identical. It is filled only on the last page, with **"الإجمالي الكلي"** and the grand total, prominent and right-aligned.
4. **Page number** in the bottom margin box: **"صفحة X من Y"**, using `counter(page)` / `counter(pages)` in `@page` margin boxes.

### Each table

- **Columns from right to left:**

  | اسم الصنف | الكمية | السعر | الخصم | الإجمالي |
  |---|---|---|---|---|

- Rows: a header row, 20 body rows (real items followed by empty padded rows with borders and no content), and a footer row **"الإجمالي المتراكم"** with the running total in the الإجمالي column.
- **Fixed row height, single line, never wrapping.** Starting values, to tune in Phase 0:
  - Each table is ≈ 134 mm wide.
  - Column widths ≈ name 52 mm, quantity 18 mm, price 22 mm, discount 16 mm, total 26 mm.
  - Rows ≈ 7 mm high, with 9.5–10 pt font.
- As a safety net, the name cell uses `overflow: hidden; white-space: nowrap; text-overflow: ellipsis`, even though names are already limited to 40 characters.
- A table must **never** split across pages. Pagination is fully controlled by our algorithm: each page is a fixed block followed by `break-after: page` (except the last page).

### Number formatting (done in `viewmodel.py`, not in the template)

- **Money** (price, totals): 2 decimals with thousands separators → `1,250.50`.
- **Quantity:** up to 3 decimals with trailing zeros trimmed → `2.5`, `10`, `0.125`, plus thousands separators.
- **Discount:** percentage with trailing zeros trimmed → `10%`, `12.5%`, `0%`.
- Wrap every numeric cell in `<bdi dir="ltr">…</bdi>` (or use `unicode-bidi: isolate`) so numbers and `%` are never reordered by the RTL context.
- Use `font-variant-numeric: tabular-nums`. Numeric columns are centered or left-aligned consistently; choose what looks best in Phase 0 and keep it uniform.

### Fonts and rendering

- Fonts are loaded via `@font-face` from the bundled TTF files only. The font stack is `"Noto Sans Arabic", "Noto Sans", sans-serif`.
- WeasyPrint embeds and subsets the fonts automatically. Verify with pypdf that the fonts are embedded.
- Give WeasyPrint a **custom `url_fetcher` that only allows the app's local asset directory**. Any other URL must be refused, to prevent SSRF/file access through injected content.
- Render entirely in memory. Never write PDFs to disk on the server.
- The design should be professional and printable: clean thin borders, a subtle header-row shade, a bold footer row, and good contrast in black-and-white printing.

---

## 9. Web UI specification

- Single page, fully Arabic, `dir="rtl"`. It uses the same bundled font via `@font-face`.
- **Top:** title **"فاتورة"** and a date field (`<input type="date">`, defaulting to today).
- **Main area:** an editable grid, spreadsheet-like. Columns from right to left:
  `#` | اسم الصنف | الكمية | السعر | الخصم % | الإجمالي (read-only) | delete button.
- **Inputs:**
  - Numeric fields use `type="text" inputmode="decimal"`, **not** `type="number"`, so Arabic digits and RTL behave correctly. They are normalized as in section 6.
  - The name input has `maxlength="40"` and a small character counter appears when near the limit.
- **Keyboard flow:**
  - Tab and Shift+Tab move between fields.
  - **Enter** moves to the next field; Enter in the last field of a row moves to the next row's name field.
  - On the last row, Enter creates a new row.
  - A blank row is always kept at the bottom.
- **Live calculation:** row totals and the Grand Total update as the user types, using `big.js` with the exact server formula and rounding.
- **Delete:** a per-row delete button with a 5-second "تراجع" (undo) toast. No confirmation dialog.
- **"مسح الكل"** clears all rows, with a confirmation dialog.
- **Sticky footer bar** containing:
  - The item count.
  - The page-count preview: "سيتم إنشاء N صفحة/صفحات", where `ceil(n/40)`.
  - **الإجمالي الكلي**.
  - The **"إنشاء PDF"** button.
- **Generate PDF:**
  1. Disable the button and show a spinner.
  2. `POST` the JSON (numbers as strings).
  3. On success, download the returned PDF with the filename `invoice-YYYY-MM-DD.pdf`.
  4. On 422, show field errors as in section 6.
  5. On 429/503, show a friendly Arabic message: `الخادم مشغول، حاول مرة أخرى بعد قليل`.
- **No inline `<script>` or inline event handlers.** All JavaScript lives in `app.js` (CSP-compatible).
- Desktop-first. On narrow screens the grid scrolls horizontally inside its own container and the page itself never scrolls sideways.
- **No localStorage, no drafts, no saved data.** This is out of scope.

---

## 10. API specification

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Serves the UI page |
| POST | `/api/invoice/pdf` | Validates, calculates, paginates, renders. Returns `application/pdf` with `Content-Disposition: attachment; filename="invoice-YYYY-MM-DD.pdf"` |
| GET | `/healthz` | Returns `{"status": "ok"}` (used by Docker healthcheck) |

**Request body for `/api/invoice/pdf`:**

```json
{
  "date": "2026-10-03",
  "items": [
    {"name": "سكر أبيض", "quantity": "2.5", "unit_price": "45.00", "discount_percent": "10"}
  ]
}
```

**Responses:**
- 200: the PDF.
- 413: body too large.
- 422: validation errors (format in section 6).
- 429: rate limited.
- 503: render capacity busy.

**Implementation notes:**
- Define the PDF endpoint with a plain `def` (not `async def`) so the CPU-bound WeasyPrint rendering runs in FastAPI's threadpool and doesn't block the event loop.
- Disable FastAPI's `/docs` and `/redoc` in production via config.

---

## 11. Security and resource limits (mandatory — the app is public with no password)

- **Max items per request:** `MAX_ITEMS` (default **1000**).
- **Max request body:** **256 KB**. Enforce it in Caddy *and* in the app.
- **Rate limit:** **10 PDF requests per minute per client IP**, using a small in-memory sliding-window limiter (no external dependency required). It returns 429 with an Arabic message. Use the real client IP from `X-Forwarded-For` **only** when the request comes through the trusted proxy (configure Uvicorn `--proxy-headers --forwarded-allow-ips` for the Docker network).
- **Concurrency:** at most **2** PDF renders at the same time (a semaphore). If a slot doesn't free up within ~10 s, return 503.
- **Security headers:** `Content-Security-Policy` (`default-src 'self'`; adjust only as strictly needed), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `frame-ancestors 'none'`. HSTS is added at Caddy.
- **Escaping:** Jinja2 autoescape is ON for all templates, because item names are user input.
- **Logging:** never log request bodies or item contents. Log the method, path, status, duration and item count only.
- **Container:** the app runs as a **non-root** user inside the container.
- **Optional `APP_PASSWORD` environment variable:** HTTP Basic Auth. It is **empty by default, which means disabled**, as the owner chose no password. It exists only so a password can be switched on later without code changes.

---

## 12. Configuration (environment variables, documented in `.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Port the app listens on (Cloud Run/Render convention) |
| `ROWS_PER_TABLE` | `20` | Pagination |
| `TABLES_PER_PAGE` | `2` | Pagination |
| `MAX_ITEMS` | `1000` | Request limit |
| `RATE_LIMIT_PER_MINUTE` | `10` | PDF requests per IP |
| `MAX_CONCURRENT_RENDERS` | `2` | Render semaphore |
| `ENABLE_API_DOCS` | `false` | Expose `/docs` (dev only) |
| `APP_PASSWORD` | *(empty)* | Optional Basic Auth; empty = off |
| `DOMAIN` | `localhost` | Used by Caddy (e.g. `myinvoice.duckdns.org`) |
| `LOG_LEVEL` | `info` | Logging |

---

## 13. Docker and local development

### Dockerfile

- Base image: `python:3.12-slim` (multi-arch, so it works on Oracle's Arm VM and on amd64).
- Install WeasyPrint's system dependencies per the current official WeasyPrint installation docs for Debian (Pango / pangoft2 / HarfBuzz subset libraries). Note: **Cairo is not required** by modern WeasyPrint.
- Install pinned Python dependencies, copy the app (including fonts), create and switch to a non-root user.
- Add a `HEALTHCHECK` that calls `/healthz`.
- Command: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=*` (restrict the allowed IPs where practical), with 2 workers.
- Keep the image small: no build tools left behind and a proper `.dockerignore`.

### compose.yml (production)

- **`app` service:** built from the Dockerfile, `restart: unless-stopped`, `env_file: .env`, not exposed publicly (internal network only), with the healthcheck.
- **`caddy` service:** `caddy:2` image, ports 80 and 443, mounts the `Caddyfile`, with persistent named volumes `caddy_data` and `caddy_config` (so certificates survive restarts).

### Caddyfile

Must include:
- `{$DOMAIN}` site block.
- `reverse_proxy app:8000`.
- `encode gzip`.
- `request_body { max_size 256KB }`.
- An HSTS header.
- Sensible timeouts.

### compose.dev.yml

- Runs the app with auto-reload on port 8000, with the source mounted.
- Includes a `tests` service that runs `pytest` with dev dependencies and `poppler-utils` (for `pdftoppm`) installed.

The README must document the exact commands for:
- Running the app locally.
- Running the tests.
- Regenerating the sample PDFs/PNGs with `scripts/render_samples.py`.
- Building and running the production stack locally.

Write these commands so they work on Windows (PowerShell), macOS and Linux. Avoid `make`.

---

## 14. Deployment documentation (write these; you cannot execute them)

### docs/DEPLOY_ORACLE.md (primary)

A beginner-friendly, step-by-step runbook for someone comfortable with Python but not DevOps. It must cover:

1. **Create an Oracle Cloud Free Tier account.** Choose the **home region carefully** (it can't be changed; Always Free resources exist only there). **Do not upgrade to Pay As You Go.** Explain why: on the Free Tier, exceeding limits stops resources instead of billing the card. During the 30-day trial, create **only resources labeled "Always Free-eligible"**.
2. **Create the VM.**
   - Shape `VM.Standard.A1.Flex` with **1 OCPU / ~2 GB RAM**. This leaves headroom, likely keeps memory utilization above Oracle's 20% idle threshold, and survives future allowance cuts.
   - Image: Ubuntu LTS (aarch64), with an SSH key.
   - If you get an "Out of host capacity" error: try another availability domain, retry later, or fall back to `VM.Standard.E2.1.Micro` (x86, 1 GB). In the fallback case, build the image elsewhere or on a machine with more RAM.
3. **Open ports 80 and 443 in TWO places:**
   - The VCN **security list**, as ingress rules.
   - The VM's **iptables**. Oracle's Ubuntu images ship with restrictive rules: insert the ACCEPT rules before the REJECT rule, then persist them with `netfilter-persistent`.
4. **Install Docker Engine and the Compose plugin** (official Docker apt repository, arm64), and enable unattended security upgrades.
5. **Create a DuckDNS subdomain** pointing to the VM's public IP. Add a cron-based DuckDNS updater in case the IP ever changes.
6. **Deploy:**
   - `git clone` the repo.
   - Create `.env` from `.env.example` and set `DOMAIN`.
   - Run `docker compose up -d --build`.
   - Verify that HTTPS works and the PDF downloads.
7. **Updating:** `git pull && docker compose up -d --build`.
8. **Ongoing care:**
   - After the first week, check the instance's CPU, memory and network metrics against the idle-reclamation thresholds.
   - Log into the Oracle console at least monthly.
   - If Oracle ever stops the instance, simply start it again.
   - Check that disk space and Docker images are being pruned.
9. **Troubleshooting:** the site is unreachable (check the two firewalls), Caddy can't get a certificate (check DNS and port 80), and reading container logs.

### docs/DEPLOY_CLOUDRUN.md (fallback)

- Build and push an amd64 image, or deploy from source with `gcloud run deploy`.
- Settings: `--max-instances 1`, `--memory 512Mi`, `--cpu 1`, request-based billing, port from `$PORT`.
- Explain clearly that Cloud Run's Always Free allowance requires a **Paid billing account**, so overages are charged to the card.
- Recommend creating a **budget alert**, and note that budgets alert but do not cap spending.
- The free `*.run.app` URL includes HTTPS.

---

## 15. Testing strategy

### Unit tests

- **`test_numbers.py`:**
  - Arabic-Indic and Persian digit normalization, `٫`, `٬`, commas, whitespace.
  - Invalid strings.
  - All the formatting rules from section 8 (money, quantity trimming, percent).
- **`test_calculations.py`:**
  - Discounts of 0%, 10%, 12.5% and 100%.
  - Decimal quantities and prices, and price 0.
  - Rounding at `.005` boundaries (`ROUND_HALF_UP`).
  - Large values near the limits.
  - The grand total equals the sum of rounded line totals.
  - Running totals are correct.
- **`test_pagination.py`:**
  - Every row of the table in section 7, plus 19, 39, 100, 120 and 1000 items.
  - Hypothesis property tests for all the invariants in section 7.
- **`test_api.py`:**
  - Valid request → 200 `application/pdf`.
  - Each validation rule → 422 with the correct `row`/`field`.
  - 0 items → 422; more than MAX_ITEMS → 422.
  - Oversized body → 413.
  - The rate limit triggers 429.
  - Derived fields sent by the client are ignored or rejected.
  - Fully empty rows are ignored.

### PDF tests (`test_pdf.py`)

For fixtures of 1, 20, 21, 40, 41, 45, 65, 80 and 81 items, check:
- Page count = `ceil(n/40)`.
- Pages are A4 landscape size.
- Fonts are embedded.
- The grand total and running totals appear in the extracted text (compare numbers only, since Arabic text extraction is unreliable).

### Visual checks (you do these yourself at every PDF checkpoint)

`scripts/render_samples.py` renders each fixture to PDF and to PNG (`pdftoppm -r 110`) under `samples/` (git-ignored). Open the PNGs and verify:
- Arabic letters are connected.
- The first table is on the right.
- Columns are in the right-to-left order from section 8.
- Numbers and `%` are intact and aligned.
- Padded rows are present.
- The running-total row is correct.
- The grand total appears on the last page only.
- Page numbers are correct.
- Nothing overflows or clips.

### Fixtures must include

- Short and long Arabic names, plus names of exactly 40 characters.
- Mixed Arabic/English/numbers names (e.g. `شاشة Samsung 55 بوصة`, `كابل HDMI 2.1 طول 3م`).
- Decimal quantities, zero price, and 0% / 100% discounts.
- Large numbers near the limits.

### Manual UI checklist (document it in the README)

- Keyboard-only entry of 45 items.
- Editing and deleting rows in the middle of the list, including undo.
- Typing values with an Arabic keyboard (Arabic digits).
- Error display and recovery.
- Downloading and printing a PDF.

---

## 16. Phases and checkpoints

### Phase 0 — Arabic PDF spike (de-risk first)

1. Create the minimal repo skeleton, Dockerfile, `compose.dev.yml`, fonts with their license, and a 45-item Arabic fixture.
2. Write a **standalone** script (it may contain throwaway code) that renders the full layout from section 8 with WeasyPrint inside Docker:
   - Two pages: the first with 20 + 20 items, the second with 5 items plus 15 padded rows.
   - Running totals, the grand total on the last page, the date header and page numbers.
3. Produce **two variants**, one with **Noto Sans Arabic** and one with **Noto Naskh Arabic**, as both PDFs and PNGs.
4. Tune the margins, column widths, row height and font size until 20 rows plus header and footer fit comfortably and 40-character names fit on one line.

**🛑 CHECKPOINT:** show both variants and the final measurements, and list any open visual questions (font choice, alignment of numeric columns, showing `0%` vs `—` for a zero discount).

### Phase 1 — Domain core

Build `models.py`, `calculations.py` and `numbers.py`, with full unit tests.

### Phase 2 — Pagination

Build `pagination.py` with the running totals, plus example tests and hypothesis property tests.

### Phase 3 — PDF renderer

Build `viewmodel.py`, `renderer.py`, the final template and CSS (based on the approved Phase 0 design), the restricted `url_fetcher`, `render_samples.py` and `test_pdf.py`.

**🛑 CHECKPOINT:** show PNGs for the 1, 21, 41, 65 and 81-item fixtures.

### Phase 4 — API

Build the schemas, routes, structured 422 errors, all limits from section 11, config, the security headers and `test_api.py`.

### Phase 5 — UI

Build `index.html`, `app.css` and `app.js` per section 9, including the vendored `big.js`, live totals, keyboard flow, client validation, server-error mapping and the download.

**🛑 CHECKPOINT:** explain how to run it locally and walk through the manual checklist.

### Phase 6 — Production packaging

Finalize the Dockerfile (multi-arch, non-root, healthcheck), `compose.yml`, the `Caddyfile` and `.env.example`. Run the full production stack locally (with `DOMAIN=localhost`) and verify end to end.

### Phase 7 — Documentation

Write the README, `docs/DEPLOY_ORACLE.md` and `docs/DEPLOY_CLOUDRUN.md`.

**Optional, ask first:** a GitHub Actions workflow that runs the tests inside Docker on every push.

### Phase 8 — Final verification

Run the full test suite, regenerate all samples and visually re-check them, and review the code against this spec.

**🛑 FINAL CHECKPOINT:** report anything that deviates from this spec, and why.

---

## 17. Definition of done

- [ ] All tests pass inside Docker.
- [ ] Sample PDFs for all fixtures are visually correct (section 15 checklist).
- [ ] The UI works fully in Arabic RTL with keyboard-only entry, and its live totals match the PDF exactly.
- [ ] `docker compose up -d --build` runs the production stack with Caddy, and the PDF downloads over HTTPS (locally with the `localhost` domain).
- [ ] The image builds for both `linux/arm64` and `linux/amd64`.
- [ ] No forbidden technology from section 3 is used. No `float` is used for money. No data is persisted.
- [ ] README, `DEPLOY_ORACLE.md` and `DEPLOY_CLOUDRUN.md` are complete enough for a non-DevOps person to deploy.
