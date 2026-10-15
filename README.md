# فاتورة — Arabic Invoice to PDF

A small web page for making a simple Arabic (right-to-left) invoice: type the items, watch the totals
update live, and save a clean **A4 landscape** PDF. It runs entirely in the browser — no server, no
account, no installation. Nothing you type is sent anywhere or stored.

**Live:** https://mahmod-madkour.github.io/invoice/

---

## How to use

1. Open the link (Chrome or Edge recommended).
2. Check the **التاريخ** (date) — it starts as today.
3. Type the items: **name → Enter → quantity → Enter → price → Enter → discount % → Enter** moves to
   the next row. Tab / Shift+Tab also move between fields. Arabic digits (`٢٫٥`) are fine.
4. The row totals, the item count, the number of pages and **الإجمالي الكلي** update as you type.
   A red field shows what to fix; click the red error count in the footer to jump to it.
5. Click **إنشاء PDF**. The print window opens:
   - **Chrome / Edge:** *Destination* → **Save as PDF** («حفظ بتنسيق PDF») → **Save**.
   - **Firefox:** choose **Save to PDF**.
   - Paper size (A4 landscape) is set automatically, and the file name is `invoice-YYYY-MM-DD.pdf`.
   You can also print straight to paper from the same window. If the printer or the print window keeps a
   margin, the invoice shrinks slightly to fit, so nothing spills onto an extra page.

Other actions: **×** deletes a row (an «تراجع» undo button appears for 5 seconds); **مسح الكل** clears
everything after asking.

## What the PDF looks like

- Title **فاتورة** and the date on every page.
- **20 rows per table, 2 tables per page** — the first table on the right. A partly filled table is
  padded with empty ruled rows.
- Under each table: **الإجمالي المتراكم** — the running total of everything up to that table.
- On the last page only: **الإجمالي الكلي** — the grand total. Page numbers: «صفحة 1 من 3».
- Western digits (`1,250.50`), no currency symbol, no VAT.

## The rules

| Field | Rule |
|---|---|
| Item name | required, at most 40 characters |
| Quantity | more than 0, up to 3 decimals, at most 1,000,000 |
| Price | 0 or more, up to 2 decimals, at most 10,000,000 |
| Discount | percent 0–100, up to 2 decimals; empty = 0 |
| Invoice | 1 to 1000 items; a line total or the grand total may not exceed 999,999,999.99 |

**Money math:** line total = quantity × price − discount, rounded **once** to 0.01 (half-up). Every
running total and the grand total is the sum of those rounded line totals, so all printed numbers add
up with a calculator. Calculations use exact decimals ([big.js](https://github.com/MikeMcl/big.js)),
never floating point. Completely empty rows are ignored.

---

## Publish on GitHub Pages

1. Push this folder to a GitHub repository (GitHub Pages is free for **public** repositories).
2. On GitHub: **Settings → Pages → Build and deployment → Source: Deploy from a branch**,
   branch **main**, folder **/ (root)** → **Save**.
3. After a minute the page is live at `https://YOUR-GITHUB-NAME.github.io/YOUR-REPOSITORY/`.
   Every later push to `main` updates it automatically.

Any other static host (Netlify, Cloudflare Pages, a plain web server) works the same way: upload the
folder as is.

## Run it on your computer

Browsers don't run this page from a double-clicked file (they block its scripts), so serve the folder:

```bash
python3 -m http.server 8000      # Windows: py -m http.server 8000
```

Then open http://localhost:8000. (VS Code's *Live Server* extension works too.)

---

## Files

```text
index.html                 the page
assets/css/app.css         the editor's look
assets/css/invoice.css     the printed invoice: A4 landscape layout
assets/js/rules.js         validation (Arabic messages), money math, number formatting
assets/js/pagination.js    20 rows per table, 2 tables per page, running totals
assets/js/invoice.js       builds the printable pages
assets/js/app.js           the editor: rows, keyboard, live totals, «إنشاء PDF»
assets/vendor/big.js       big.js 7.0.1 (exact decimal math, MIT)
assets/fonts/              Noto Sans Arabic + Noto Sans (SIL Open Font License)
.nojekyll                  tells GitHub Pages to serve the files as they are
```

The first version of this project was a server application (Python, FastAPI, WeasyPrint, Docker,
Caddy). It is kept, complete, on the git branch **`server-version`**.

## Licenses

Fonts: Noto Sans Arabic and Noto Sans — SIL Open Font License 1.1 ([assets/fonts/OFL.txt](assets/fonts/OFL.txt)).
big.js — MIT ([assets/vendor/LICENCE-big.js.md](assets/vendor/LICENCE-big.js.md)).
