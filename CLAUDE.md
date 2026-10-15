# CLAUDE.md — Arabic RTL Invoice → PDF (static site)

The original spec (in git history and on branch `server-version`) is superseded. **Owner decision 2026-10-15:** the app is a **static site**
(HTML/CSS/vanilla JS, no server, no Docker), published on **GitHub Pages**, for 1–3 users. The spec's business rules and
the approved PDF design still apply; its server/API/Docker/hosting/limits sections do not. The complete server version
(FastAPI + WeasyPrint + Docker + Caddy) is preserved on branch **`server-version`**.
Do not change any decision below without asking the owner. Do not invent features.

## How to work
- Keep it minimal: the owner asked for **no test folder, no CI workflow and no unused files** (2026-10-15). No npm, no
  package.json, no build step.
- Verify, don't assume: serve locally with `python3 -m http.server` (module scripts don't run from `file://`) and drive
  the page with headless Chrome (puppeteer-core in the scratchpad). For any change to the printed invoice, check Chrome's
  real print output (`page.pdf()` with `preferCSSPageSize`), render to PNG with `pdftoppm` and look at it: connected
  Arabic, RTL order, intact numbers, aligned rows/columns, page count — also with a non-zero `@page` margin written into
  a copy of invoice.css (a printer's unprintable edge), which must not push anything onto an extra page.

## Business rules (spec §2, unchanged)
- Simple invoice, title **"فاتورة"**. **No VAT.** Header = **date only**. **Western digits** (`1,250.50`). **No currency symbol.**
- Discount **percent only** 0–100 (≤ 2 decimals, empty = 0). Quantity > 0, ≤ 3 decimals, ≤ 1,000,000.
  Price ≥ 0, ≤ 2 decimals, ≤ 10,000,000. Name required, ≤ **40** chars after trim. 1–1000 items.
  Line total and grand total ≤ 999,999,999.99. Arabic error messages as in spec §6. Completely empty rows are ignored.
- **20 rows per table, 2 tables per page, first table on the RIGHT**; partial tables padded with empty ruled rows.
- Table footer **"الإجمالي المتراكم"** (running total); **"الإجمالي الكلي"** on the **last page only**; **"صفحة X من Y"**; **A4 landscape**.
- Arabic-Indic digits typed **inside names are kept as typed**; numeric fields are normalized.

## Money rules
- Never JS numbers for money: big.js decimals built from **strings** (`assets/vendor/big.js`).
- Line total = (qty × price − qty × price × disc/100) rounded **once** to 0.01 half-up; all running/grand totals are sums
  of rounded line totals. The editor's live totals and the PDF use the same functions (`assets/js/rules.js`).

## Approved PDF design (owner-approved 2026-10-04; `assets/css/invoice.css`)
- Font **Noto Sans Arabic** (+ Noto Sans for Latin), bundled TTFs only — no CDN, no Google Fonts.
- A4 landscape, margins **8 mm top/sides, 12 mm bottom**; body **8.5 pt**; rows **7 mm**; cell padding 1.1 mm.
- Tables **138.5 mm** wide, **4 mm** gap; columns name 58.5, qty 20, price 22.5, discount 13, total 24.5 mm.
- Absolute positioning inside fixed-size page blocks (positions identical on every page). The block is
  `min(297mm, 100vw)` × `min(209.5mm, 100vh)` and rows/columns scale with it, so a printer margin shrinks the page to fit
  instead of spilling «صفحة X من Y» onto a new sheet (Chrome: print vh/vw = printable area; Firefox keeps the mm size).
- Numeric columns **right-aligned**, tabular nums, each number in `<bdi dir="ltr">`. Zero discount prints **`0%`**.
- Names: one line, `text-overflow: ellipsis` (browsers handle RTL correctly); names without Arabic letters get `dir="ltr"`.

## Architecture
- `assets/js/rules.js` (pure: validation, math, formatting) ← `pagination.js` ← `invoice.js` (DOM, `textContent` only —
  never `innerHTML` with user text) ← `app.js` (editor). ES modules, relative paths (works under a Pages sub-path).
- PDF = browser print: «إنشاء PDF» renders `#print-root`, loads fonts, sets `document.title` to `invoice-YYYY-MM-DD`
  (suggested file name), calls `window.print()`; `@media print` shows only the invoice.
- No storage of any kind (no localStorage, cookies, analytics), no network requests except the site's own files.
  CSP via `<meta http-equiv>` (`default-src 'self'`); no inline scripts or event handlers.
