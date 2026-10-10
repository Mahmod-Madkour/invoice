# فاتورة — Arabic RTL Invoice PDF Generator

A small web app: type invoice items into an Arabic (right-to-left) table, watch the totals update
live, and download a professional **A4 landscape** invoice PDF. Nothing is stored — the server is
stateless and recalculates every number itself.

- **Stack:** Python 3.12 · FastAPI · Pydantic v2 · Jinja2 · WeasyPrint · vanilla JavaScript + big.js
- **PDF:** 20 rows per table, 2 tables per page (first table on the right), running total under
  each table («الإجمالي المتراكم»), grand total on the last page («الإجمالي الكلي»), «صفحة X من Y».
- **Full specification:** [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) ·
  **Deployment:** [Oracle Cloud (primary)](docs/DEPLOY_ORACLE.md) · [Google Cloud Run (fallback)](docs/DEPLOY_CLOUDRUN.md)

---

## Requirements

Everything runs in Docker, on every operating system — you do not need Python installed.

| Your computer | Install |
|---|---|
| Windows 10/11 | [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) (WSL 2 backend) |
| macOS | [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) |
| Linux | [Docker Engine](https://docs.docker.com/engine/install/) + the Compose plugin |

All commands below are typed in a terminal (PowerShell on Windows) **inside the project folder**.
They are identical on Windows, macOS and Linux.

> **Linux only:** the dev containers run as user id 1000. If `id -u` prints something else, add
> `--user "$(id -u):$(id -g)"` after `run --rm` in the test and sample commands, e.g.
> `docker compose -f compose.dev.yml run --rm --user "$(id -u):$(id -g)" tests` — otherwise the
> container cannot write `samples/` or its caches into your folder.

> The first build downloads Python packages and takes a few minutes. Later starts are instant.

---

## Run the app locally (development)

```bash
docker compose -f compose.dev.yml up --build app
```

Open **http://localhost:8000**. The server reloads automatically when you edit files under `app/`.
Interactive API docs are at http://localhost:8000/docs (development only). Stop with **Ctrl+C**.

## Run the tests

```bash
docker compose -f compose.dev.yml run --rm tests
```

Run part of the suite by passing pytest arguments:

```bash
docker compose -f compose.dev.yml run --rm tests pytest tests/test_api.py -k rate_limit -v
```

## Regenerate the sample PDFs and PNGs

```bash
docker compose -f compose.dev.yml run --rm tests python scripts/render_samples.py
```

Every fixture in `tests/fixtures/` is rendered to `samples/<name>.pdf` plus one PNG per page
(`samples/<name>-1.png`, … at 110 dpi). Render only some fixtures by naming them:

```bash
docker compose -f compose.dev.yml run --rm tests python scripts/render_samples.py items_1 items_81
```

`samples/` is git-ignored.

## Run the production stack locally (app + Caddy + HTTPS)

```bash
cp .env.example .env
docker compose up -d --build
```

(`cp` also works in PowerShell. Keep `DOMAIN=localhost` in `.env` for a local test.)

Open **https://localhost**. Caddy issues a certificate from its own local authority, so the browser
warns once — accept the warning for this local test (a real domain gets a trusted Let's Encrypt
certificate automatically). Useful commands:

```bash
docker compose ps              # status (the app should be "healthy")
docker compose logs -f         # follow the logs (Ctrl+C to stop following)
docker compose down            # stop and remove the containers (certificates are kept)
```

The production stack uses ports 80 and 443; the development server uses 8000, so both can run at once.

---

## Configuration

Settings come from environment variables — in production from the `.env` file
(start from [.env.example](.env.example), which documents each one).

| Variable | Default | Purpose |
|---|---|---|
| `DOMAIN` | `localhost` | Domain served by Caddy, e.g. `myinvoice.duckdns.org` |
| `PORT` | `8000` | Port the app listens on inside its container (keep 8000 with `compose.yml`) |
| `ROWS_PER_TABLE` | `20` | Rows per table in the PDF (1–30; row height shrinks above 20) |
| `TABLES_PER_PAGE` | `2` | Tables per page (1–2) |
| `MAX_ITEMS` | `1000` | Maximum items per invoice |
| `RATE_LIMIT_PER_MINUTE` | `10` | PDF requests per client IP per minute |
| `MAX_CONCURRENT_RENDERS` | `2` | PDFs rendered at the same time (others wait up to ~10 s, then get 503) |
| `ENABLE_API_DOCS` | `false` | Expose `/docs` (development only) |
| `APP_PASSWORD` | *(empty)* | Optional HTTP Basic Auth for the whole site; empty = no password |
| `LOG_LEVEL` | `info` | `critical`, `error`, `warning`, `info` or `debug` |

Advanced: `FORWARDED_ALLOW_IPS` (default `*`) is passed to uvicorn's `--forwarded-allow-ips`.
With `compose.yml` the app is reachable only from Caddy, so the default is safe there.

---

## How it works

```text
browser (app.js)                       server
────────────────                       ──────
editable RTL grid ──POST JSON──▶  api/schemas.py   validate every cell (Arabic messages, 422 per cell)
live totals (big.js)                 domain/        Decimal math, pagination, running totals
                                     pdf/           view model (pre-formatted strings) → Jinja2 → WeasyPrint
        ◀──────── application/pdf ── invoice-YYYY-MM-DD.pdf (rendered in memory)
```

- **Money is never a float.** Numbers travel as JSON strings and become `Decimal`. Each line total is
  `(qty × price − discount)` rounded once to 0.01 (half-up); every running and grand total is a sum of
  rounded line totals, so the printed numbers add up with a calculator. The browser uses the same
  formula with big.js — its preview always matches the PDF.
- **Input:** Arabic-Indic (`٠١٢٣`) and Persian (`۰۱۲۳`) digits, `٫` and `٬` are accepted and normalized.
  Completely empty rows are ignored.
- **Layout:** `app/domain` is pure Python; `app/api` (HTTP) and `app/pdf` (rendering) depend on it.
  Templates contain no arithmetic or formatting.

```text
app/
  main.py, config.py        app factory, middleware, settings
  domain/                   models, calculations, pagination, numbers (no framework imports)
  api/                      request schemas + validation, routes, limits
  pdf/                      view model, renderer, invoice template + CSS
  web/                      index.html, app.js, app.css, vendored big.js
  assets/fonts/             Noto Sans Arabic + Noto Sans (+ Naskh) TTFs and OFL.txt
scripts/render_samples.py   fixtures → samples/*.pdf + *.png
tests/                      pytest + hypothesis + pypdf; fixtures/ holds request payloads
```

## Security and limits

The site is public without a password, so these limits always apply:

- max **1000 items** per invoice and **256 KB** per request (enforced by Caddy *and* the app);
- **10 PDF requests per minute per client IP** (in-memory sliding window → 429);
- at most **2 PDFs rendering at once**; no free slot within ~10 s → 503;
- strict Content-Security-Policy (no inline scripts), `nosniff`, `no-referrer`, no framing; HSTS at Caddy;
- the PDF engine can load only the bundled font files — no network or other file access;
- logs contain method, path, status, duration and item count — never request bodies or item names;
- the app container runs as a non-root user on a private network with no outbound internet access.

The app runs **one** uvicorn worker on purpose: the limits live in memory, so a single process keeps
them exact.

---

## Manual UI checklist

Run through this after changes to the UI (the automated tests cover the server and the PDF):

- [ ] **Keyboard-only entry of 45 items:** name → Enter → quantity → Enter → price → Enter → discount →
      Enter jumps to the next row; Tab / Shift+Tab also move between fields. A blank row always stays at
      the bottom. The footer shows «عدد الأصناف: 45» and «سيتم إنشاء صفحتين».
- [ ] **Edit and delete in the middle:** change a value in row 10 → its total and the grand total update.
      Delete a row with **×** → the «تراجع» toast appears for 5 seconds; undo restores the row in place.
- [ ] **Arabic keyboard digits:** type `٢٫٥` and `١٬٢٥٠٫٥٠` → totals are computed; leaving the field shows
      `2.5` / `1250.50`.
- [ ] **Errors and recovery:** an invalid value shows a red border, the Arabic message under it and `—` as
      the row total; the footer shows the error count and «إنشاء PDF» is disabled. Clicking the error count
      jumps to the first error. Fixing the values re-enables the button.
- [ ] **«مسح الكل»** asks for confirmation; cancelling keeps the rows.
- [ ] **Download and print:** «إنشاء PDF» shows a spinner, then downloads `invoice-YYYY-MM-DD.pdf`.
      The grand total in the PDF equals the one on screen. Print it on A4 landscape.
- [ ] **Narrow screen:** the table scrolls sideways inside its own box; the page itself never does.

## Known limitations

- **Copying Arabic text out of the PDF** produces some wrong letters (e.g. «فاةورة»). The printed and
  on-screen PDF is correct — this is how WeasyPrint maps Noto Sans Arabic's shared letter shapes in the
  PDF's text layer. Numbers copy correctly.
- **Very wide 40-character names** (all capitals in Latin, or many wide Arabic letters) may not fit their
  column. Names without Arabic letters end with «…»; Arabic names are cut at their end (WeasyPrint draws
  the ellipsis incorrectly in right-to-left text).
- A 1000-item invoice (25 pages) takes about 8 seconds to render on a desktop CPU, longer on a small VM.

## Licenses

Fonts: Noto Sans Arabic, Noto Naskh Arabic and Noto Sans — SIL Open Font License 1.1
([app/assets/fonts/OFL.txt](app/assets/fonts/OFL.txt)). big.js — MIT
([app/web/static/vendor/LICENCE-big.js.md](app/web/static/vendor/LICENCE-big.js.md)).
