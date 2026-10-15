/*
 * Invoice editor: editable RTL grid, live totals, validation, and printing to PDF.
 * Everything runs in the browser; nothing is sent anywhere or stored.
 */
import Big from "../vendor/big.js";
import {
  FIELDS, MAX_ITEMS, MSG, NAME_MAX_LENGTH, TOTAL_MAX,
  buildInvoice, charLength, cleanName, formatMoney, isValidDate, nameDirection, normalizeNumber,
  parseDecimal, validateRow,
} from "./rules.js";
import { pageCount } from "./pagination.js";
import { renderInvoice } from "./invoice.js";

const MSG_UI = {
  confirmClear: "هل تريد مسح جميع الأصناف؟",
  deleted: "تم حذف الصنف",
};

// ------------------------------------------------------------------ helpers

function pagesText(n) {
  if (n === 1) return "سيتم إنشاء صفحة واحدة";
  if (n === 2) return "سيتم إنشاء صفحتين";
  if (n <= 10) return `سيتم إنشاء ${n} صفحات`;
  return `سيتم إنشاء ${n} صفحة`;
}

function errorsText(n) {
  if (n === 1) return "خطأ واحد";
  if (n === 2) return "خطآن";
  if (n <= 10) return `${n} أخطاء`;
  return `${n} خطأ`;
}

function todayIso() {
  const d = new Date();
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const $ = (id) => document.getElementById(id);
function setText(el, text) { if (el.textContent !== text) el.textContent = text; }
function setHidden(el, hidden) { if (el.hidden !== hidden) el.hidden = hidden; }
function setInvalid(input, invalid) {
  input.classList.toggle("invalid", invalid);
  if (invalid) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

const els = {
  rows: $("rows"),
  template: $("row-template"),
  date: $("invoice-date"),
  dateError: $("date-error"),
  clearAll: $("clear-all"),
  banner: $("banner"),
  itemCount: $("item-count"),
  pagePreview: $("page-preview"),
  errorCount: $("error-count"),
  grandTotal: $("grand-total"),
  generate: $("generate"),
  spinner: document.querySelector("#generate .spinner"),
  toast: $("toast"),
  toastText: $("toast-text"),
  toastUndo: $("toast-undo"),
  printRoot: $("print-root"),
};

// ------------------------------------------------------------------ state

const rows = [];               // row objects in screen order
const rowByTr = new WeakMap();
let showAll = false;           // reveal every error (after clicking the error count or «إنشاء PDF»)
let preparing = false;
let dateTouched = false;
let pendingUndo = null;        // { row, index }
let toastTimer = null;
let firstErrorTarget = null;

function createRow(values) {
  const tr = els.template.content.firstElementChild.cloneNode(true);
  const row = { tr, inputs: {}, errorEls: {}, touched: new Set(), result: null };
  for (const field of FIELDS) {
    const input = tr.querySelector(`[data-field="${field}"]`);
    row.inputs[field] = input;
    row.errorEls[field] = input.parentElement.querySelector(".field-error");
    if (values) input.value = values[field] || "";
  }
  row.totalEl = tr.querySelector(".row-total");
  row.errorEls.total = tr.querySelector(".c-total .field-error");
  row.counterEl = tr.querySelector(".counter");
  row.noEl = tr.querySelector(".row-no");
  rowByTr.set(tr, row);
  return row;
}

function rowValues(row) {
  const v = {};
  for (const field of FIELDS) v[field] = row.inputs[field].value;
  return v;
}

function isBlankRow(row) {
  return validateRow(rowValues(row)).blank;
}

function insertRow(row, index) {
  rows.splice(index, 0, row);
  const next = rows[index + 1];
  els.rows.insertBefore(row.tr, next ? next.tr : null);
}

function removeRow(row) {
  const index = rows.indexOf(row);
  if (index >= 0) {
    rows.splice(index, 1);
    row.tr.remove();
  }
  return index;
}

function rowOf(el) {
  const tr = el.closest("tr");
  return tr ? rowByTr.get(tr) : null;
}

/** A blank row is always kept at the bottom. */
function ensureTrailingBlank() {
  const last = rows[rows.length - 1];
  if (!last || !isBlankRow(last)) insertRow(createRow(), rows.length);
}

// ------------------------------------------------------------------ recompute + render

function recompute() {
  let count = 0;
  let errorCount = 0;
  let rowErrors = 0;
  let grand = new Big(0);
  firstErrorTarget = null;

  rows.forEach((row, index) => {
    setText(row.noEl, String(index + 1));
    const values = rowValues(row);
    const result = validateRow(values);
    row.result = result;
    row.tr.classList.toggle("is-blank", result.blank);
    if (!result.blank) count += 1;

    for (const field of [...FIELDS, "total"]) {
      const message = result.blank ? null : result.errors[field] || null;
      if (message) {
        errorCount += 1;
        rowErrors += 1;
      }
      // Format/range errors show while typing; "required" errors once the field was visited.
      const visible = Boolean(message) && (
        showAll || field === "total" || row.touched.has(field) || (values[field] || "").trim() !== ""
      );
      if (field !== "total") setInvalid(row.inputs[field], visible);
      setText(row.errorEls[field], visible ? message : "");
      setHidden(row.errorEls[field], !visible);
      if (message && !firstErrorTarget) firstErrorTarget = field === "total" ? row.inputs.quantity : row.inputs[field];
    }

    setText(row.totalEl, result.blank ? "" : result.total ? formatMoney(result.total) : "—");
    if (result.total) grand = grand.plus(result.total);

    const nameLength = charLength(values.name);
    setHidden(row.counterEl, nameLength < NAME_MAX_LENGTH - 10);
    setText(row.counterEl, `${nameLength}/${NAME_MAX_LENGTH}`);
    row.counterEl.classList.toggle("full", nameLength >= NAME_MAX_LENGTH);
    row.inputs.name.dir = values.name.trim() ? nameDirection(values.name) : "rtl";
  });

  // Date.
  const dateInvalid = !isValidDate(els.date.value);
  const dateVisible = dateInvalid && (showAll || dateTouched);
  if (dateInvalid) {
    errorCount += 1;
    if (!firstErrorTarget) firstErrorTarget = els.date;
  }
  setInvalid(els.date, dateVisible);
  setText(els.dateError, dateVisible ? MSG.dateInvalid : "");
  setHidden(els.dateError, !dateVisible);

  // Invoice-level rules.
  const messages = [];
  if (count > MAX_ITEMS) messages.push(MSG.tooManyItems);
  if (rowErrors === 0 && grand.gt(TOTAL_MAX)) messages.push(MSG.totalTooLarge);
  errorCount += messages.length;
  setText(els.banner, messages.join(" — "));
  setHidden(els.banner, messages.length === 0);

  // Footer.
  setText(els.itemCount, String(count));
  setText(els.pagePreview, count ? pagesText(pageCount(count)) : "");
  setHidden(els.pagePreview, count === 0);
  setText(els.grandTotal, formatMoney(grand));
  setText(els.errorCount, errorsText(errorCount));
  setHidden(els.errorCount, errorCount === 0);
  els.generate.disabled = preparing || count === 0 || errorCount > 0;
  if (errorCount === 0) showAll = false;
}

function revealErrors() {
  showAll = true;
  recompute();
  const target = firstErrorTarget || (els.banner.hidden ? null : els.banner);
  if (target) {
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    if (target.focus) target.focus({ preventScroll: true });
  }
}

// ------------------------------------------------------------------ row actions

function focusField(row, field) {
  const input = row.inputs[field];
  input.focus();
  input.select();
}

/** Enter: next field; from the last field to the next row's name (creating the row if needed). */
function moveNext(row, field) {
  const i = FIELDS.indexOf(field);
  if (i < FIELDS.length - 1) {
    focusField(row, FIELDS[i + 1]);
    return;
  }
  const index = rows.indexOf(row);
  if (index === rows.length - 1) {
    if (isBlankRow(row)) return;
    insertRow(createRow(), rows.length);
    recompute();
  }
  focusField(rows[index + 1], "name");
}

function deleteRow(row) {
  if (row.result && row.result.blank) return;
  const index = removeRow(row);
  if (index < 0) return;
  ensureTrailingBlank();
  pendingUndo = { row, index };
  showToast(MSG_UI.deleted);
  recompute();
}

function undoDelete() {
  if (!pendingUndo) return;
  const { row } = pendingUndo;
  const lastIsBlank = rows.length && isBlankRow(rows[rows.length - 1]);
  const index = Math.min(pendingUndo.index, lastIsBlank ? rows.length - 1 : rows.length);
  pendingUndo = null;
  hideToast();
  insertRow(row, index);
  ensureTrailingBlank();
  recompute();
  focusField(row, "name");
}

function showToast(text) {
  setText(els.toastText, text);
  setHidden(els.toast, false);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    pendingUndo = null;
    hideToast();
  }, 5000);
}

function hideToast() {
  clearTimeout(toastTimer);
  setHidden(els.toast, true);
}

function clearAll() {
  const hasItems = rows.some((row) => !isBlankRow(row));
  if (hasItems && !window.confirm(MSG_UI.confirmClear)) return;
  rows.slice().forEach(removeRow);
  pendingUndo = null;
  hideToast();
  showAll = false;
  insertRow(createRow(), 0);
  recompute();
  focusField(rows[0], "name");
}

// ------------------------------------------------------------------ PDF (browser print → "Save as PDF")

const PRINT_FONTS = ['400 12px "Noto Sans Arabic"', '700 12px "Noto Sans Arabic"', '400 12px "Noto Sans"', '700 12px "Noto Sans"'];

async function loadPrintFonts() {
  if (!document.fonts) return;
  try {
    await Promise.all(PRINT_FONTS.map((font) => document.fonts.load(font)));
    await document.fonts.ready;
  } catch {
    // Printing still works with fallback fonts.
  }
}

function setBusy(value) {
  preparing = value;
  setHidden(els.spinner, !value);
  els.generate.setAttribute("aria-busy", value ? "true" : "false");
}

async function generate() {
  recompute();
  if (preparing || els.generate.disabled) return;
  const result = buildInvoice({ date: els.date.value, rows: rows.map(rowValues) });
  if (!result.ok) {
    revealErrors();
    return;
  }
  setBusy(true);
  recompute();
  try {
    renderInvoice(els.printRoot, result.invoice);
    await loadPrintFonts();
    // The page title becomes the suggested file name in "Save as PDF".
    const title = document.title;
    document.title = `invoice-${result.invoice.date}`;
    window.addEventListener("afterprint", () => { document.title = title; }, { once: true });
    window.print();
  } finally {
    setBusy(false);
    recompute();
  }
}

// ------------------------------------------------------------------ events

els.rows.addEventListener("input", (event) => {
  if (!rowOf(event.target) || !event.target.dataset.field) return;
  ensureTrailingBlank();
  recompute();
});

els.rows.addEventListener("focusout", (event) => {
  const input = event.target;
  const row = rowOf(input);
  const field = input.dataset && input.dataset.field;
  if (!row || !field) return;
  if (field === "name") {
    const cleaned = cleanName(input.value);
    if (cleaned !== input.value) input.value = cleaned;
  } else if (parseDecimal(input.value) !== null) {
    const normalized = normalizeNumber(input.value); // show Western digits, as the PDF will
    if (normalized !== input.value) input.value = normalized;
  }
  if (!isBlankRow(row)) row.touched.add(field);
  recompute();
});

els.rows.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
  const row = rowOf(event.target);
  const field = event.target.dataset && event.target.dataset.field;
  if (!row || !field) return;
  event.preventDefault();
  moveNext(row, field);
});

els.rows.addEventListener("click", (event) => {
  const button = event.target.closest(".del");
  if (!button) return;
  const row = rowOf(button);
  if (row) deleteRow(row);
});

els.date.addEventListener("input", recompute);
els.date.addEventListener("change", recompute);
els.date.addEventListener("blur", () => { dateTouched = true; recompute(); });
els.date.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  focusField(rows[0], "name");
});

els.clearAll.addEventListener("click", clearAll);
els.errorCount.addEventListener("click", revealErrors);
els.generate.addEventListener("click", generate);
els.toastUndo.addEventListener("click", undoDelete);

// ------------------------------------------------------------------ start

els.date.value = todayIso();
insertRow(createRow(), 0);
recompute();
rows[0].inputs.name.focus();
