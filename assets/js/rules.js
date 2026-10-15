/*
 * Invoice rules: input normalization, validation (Arabic messages), money math and formatting.
 * Pure functions — used by the editor (app.js), the printable invoice (invoice.js) and the tests.
 *
 * Money is never a JS number: every value is a big.js decimal built from a string.
 *   line total = (quantity × price − quantity × price × discount / 100), rounded once to 0.01 (half-up)
 *   running / grand totals = sums of the already-rounded line totals
 */
import Big from "../vendor/big.js";

Big.DP = 40; // division precision (only "/ 100" is ever needed, so results stay exact)
Big.RM = Big.roundHalfUp;

// ------------------------------------------------------------------ limits

export const NAME_MAX_LENGTH = 40;
export const QUANTITY_MAX = new Big("1000000");
export const QUANTITY_MAX_DECIMALS = 3;
export const PRICE_MAX = new Big("10000000");
export const PRICE_MAX_DECIMALS = 2;
export const DISCOUNT_MAX = new Big("100");
export const DISCOUNT_MAX_DECIMALS = 2;
export const TOTAL_MAX = new Big("999999999.99"); // widest value the total column is designed for
export const MAX_ITEMS = 1000;
export const ROWS_PER_TABLE = 20;
export const TABLES_PER_PAGE = 2;
const MAX_NUMBER_LENGTH = 32;

export const MSG = {
  nameRequired: "اسم الصنف مطلوب",
  nameTooLong: "اسم الصنف يجب ألا يزيد عن 40 حرفًا",
  quantityNotNumber: "الكمية يجب أن تكون رقمًا",
  quantityNotPositive: "الكمية يجب أن تكون أكبر من صفر",
  quantityInvalid: "الكمية غير صالحة",
  priceNotNumber: "السعر يجب أن يكون رقمًا لا يقل عن صفر",
  priceInvalid: "السعر غير صالح",
  discountInvalid: "الخصم يجب أن يكون بين 0 و 100",
  totalTooLarge: "الإجمالي أكبر من الحد المسموح",
  noItems: "أضف صنفًا واحدًا على الأقل",
  tooManyItems: "عدد الأصناف أكبر من الحد المسموح",
  dateInvalid: "التاريخ غير صالح",
};

export const FIELDS = ["name", "quantity", "unit_price", "discount_percent"];

// ------------------------------------------------------------------ normalization

const DIGIT_MAP = { "٫": "." }; // Arabic decimal separator
"٠١٢٣٤٥٦٧٨٩".split("").forEach((ch, i) => { DIGIT_MAP[ch] = String(i); });
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((ch, i) => { DIGIT_MAP[ch] = String(i); });
const DIGITS_RE = /[٠-٩۰-۹٫]/g;
// Thousands separators (Arabic ٬ and ",") and invisible marks (bidi controls, BOM) are removed.
const REMOVE_RE = /[٬,‎‏؜‪-‮⁦-⁩﻿]/g;
const CONTROL_RE = /[\u0000-\u001f\u007f-\u009f]/g;
// Whitespace: JS \s plus U+001C–U+001F and U+0085 (U+FEFF is removed before use).
const SPACE = "\\s\\x1c-\\x1f\\x85";
const SPACE_CHAR_RE = new RegExp("^[" + SPACE + "]$");
const SPACES_RE = new RegExp("[" + SPACE + "]+");
const TRIM_RE = new RegExp("^[" + SPACE + "]+|[" + SPACE + "]+$", "g");
const BOM_RE = /﻿/g;
const NUMBER_RE = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/;
const DATE_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;
const RTL_RE = /[֐-ࣿיִ-﷿ﹰ-ﻼ]/; // Hebrew and Arabic blocks

/** Western digits, "." as decimal separator, no thousands separators, trimmed. */
export function normalizeNumber(text) {
  return String(text ?? "")
    .replace(DIGITS_RE, (ch) => DIGIT_MAP[ch])
    .replace(REMOVE_RE, "")
    .replace(TRIM_RE, "");
}

/** A Big for a plain number, or null when blank / not a number (no exponents, ASCII digits only). */
export function parseDecimal(text) {
  const s = normalizeNumber(text);
  if (s.length > MAX_NUMBER_LENGTH || !NUMBER_RE.test(s)) return null;
  return new Big(s.charAt(0) === "+" ? s.slice(1) : s);
}

/** Significant fractional digits (big.js drops trailing zeros): 2.50 → 1, 45.000 → 0, 0.125 → 3. */
export function decimalPlaces(big) {
  return Math.max(0, big.c.length - big.e - 1);
}

/** Trim, collapse internal whitespace, drop control characters and BOMs. */
export function cleanName(raw) {
  return String(raw ?? "")
    .replace(BOM_RE, "")
    .replace(CONTROL_RE, (ch) => (SPACE_CHAR_RE.test(ch) ? " " : ""))
    .split(SPACES_RE)
    .filter(Boolean)
    .join(" ");
}

/** Length in characters (code points), not UTF-16 units. */
export function charLength(text) {
  return Array.from(String(text ?? "")).length;
}

/** "rtl" for names containing Arabic/Hebrew letters, "ltr" for the rest (e.g. "iPhone 15", "Model X (2024)"). */
export function nameDirection(name) {
  return RTL_RE.test(name) ? "rtl" : "ltr";
}

export function isValidDate(iso) {
  const m = DATE_RE.exec(String(iso ?? "").trim());
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  return y >= 1 && date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
}

// ------------------------------------------------------------------ math

export function lineTotal(quantity, unitPrice, discount) {
  const gross = quantity.times(unitPrice);
  const total = gross.minus(gross.times(discount).div(100)).round(2, Big.roundHalfUp);
  return total.eq(0) ? new Big(0) : total;
}

export function sum(values) {
  return values.reduce((acc, v) => acc.plus(v), new Big(0));
}

// ------------------------------------------------------------------ formatting (Western digits)

function groupThousands(intPart) {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function trimZeros(text) {
  return text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
}

/** 1250.5 → "1,250.50" */
export function formatMoney(big) {
  const [intPart, frac] = big.round(2, Big.roundHalfUp).toFixed(2).split(".");
  return groupThousands(intPart) + "." + frac;
}

/** Up to 3 decimals, trailing zeros trimmed: 2.500 → "2.5", 1000000 → "1,000,000". */
export function formatQuantity(big) {
  const [intPart, frac] = trimZeros(big.round(3, Big.roundHalfUp).toFixed(3)).split(".");
  return groupThousands(intPart) + (frac ? "." + frac : "");
}

/** 10 → "10%", 12.50 → "12.5%", 0 → "0%" */
export function formatPercent(big) {
  return trimZeros(big.round(2, Big.roundHalfUp).toFixed(2)) + "%";
}

/** "2026-10-03" → "03/10/2026" */
export function formatDate(iso) {
  const [y, m, d] = String(iso).split("-");
  return `${d}/${m}/${y}`;
}

// ------------------------------------------------------------------ validation

function isBlankValues(v) {
  return cleanName(v.name) === "" &&
    normalizeNumber(v.quantity) === "" &&
    normalizeNumber(v.unit_price) === "" &&
    normalizeNumber(v.discount_percent) === "";
}

/**
 * Validate one row of raw strings {name, quantity, unit_price, discount_percent}.
 * Returns { blank, errors: {field: message}, total: Big|null, item: {...}|null }.
 * `total` is also given when only the name is wrong, so the editor can preview it.
 */
export function validateRow(v) {
  const errors = {};
  if (isBlankValues(v)) return { blank: true, errors, total: null, item: null };

  const name = cleanName(v.name);
  if (!name) errors.name = MSG.nameRequired;
  else if (charLength(name) > NAME_MAX_LENGTH) errors.name = MSG.nameTooLong;

  const quantity = parseDecimal(v.quantity);
  if (quantity === null) errors.quantity = MSG.quantityNotNumber;
  else if (quantity.lte(0)) errors.quantity = MSG.quantityNotPositive;
  else if (quantity.gt(QUANTITY_MAX) || decimalPlaces(quantity) > QUANTITY_MAX_DECIMALS) errors.quantity = MSG.quantityInvalid;

  const unitPrice = parseDecimal(v.unit_price);
  if (unitPrice === null || unitPrice.lt(0)) errors.unit_price = MSG.priceNotNumber;
  else if (unitPrice.gt(PRICE_MAX) || decimalPlaces(unitPrice) > PRICE_MAX_DECIMALS) errors.unit_price = MSG.priceInvalid;

  const discountText = normalizeNumber(v.discount_percent);
  const discount = discountText === "" ? new Big(0) : parseDecimal(discountText);
  if (discount === null || discount.lt(0) || discount.gt(DISCOUNT_MAX) || decimalPlaces(discount) > DISCOUNT_MAX_DECIMALS) {
    errors.discount_percent = MSG.discountInvalid;
  }

  let total = null;
  if (!errors.quantity && !errors.unit_price && !errors.discount_percent) {
    total = lineTotal(quantity, unitPrice, discount);
    if (total.gt(TOTAL_MAX)) {
      errors.total = MSG.totalTooLarge;
      total = null;
    }
  }
  const valid = Object.keys(errors).length === 0;
  const item = valid ? { name, quantity, unitPrice, discount, total } : null;
  return { blank: false, errors, total, item };
}

/**
 * Validate a whole invoice: { date: "YYYY-MM-DD", rows: [raw rows in screen order] }.
 * Completely empty rows are ignored; error rows are 1-based screen rows.
 * Returns { ok, invoice: {date, items, grandTotal} | null, errors: [{row, field, message}] }.
 */
export function buildInvoice({ date, rows }) {
  const errors = [];
  if (!isValidDate(date)) errors.push({ row: null, field: "date", message: MSG.dateInvalid });

  const filled = rows.map((raw, index) => ({ row: index + 1, result: validateRow(raw) })).filter((r) => !r.result.blank);
  if (filled.length === 0) errors.push({ row: null, field: "items", message: MSG.noItems });
  if (filled.length > MAX_ITEMS) errors.push({ row: null, field: "items", message: MSG.tooManyItems });

  for (const { row, result } of filled) {
    for (const field of [...FIELDS, "total"]) {
      if (result.errors[field]) errors.push({ row, field, message: result.errors[field] });
    }
  }
  const items = filled.map((r) => r.result.item);
  if (errors.length === 0) {
    const grandTotal = sum(items.map((item) => item.total));
    if (grandTotal.gt(TOTAL_MAX)) errors.push({ row: null, field: "grand_total", message: MSG.totalTooLarge });
    else return { ok: true, invoice: { date: date.trim(), items, grandTotal }, errors };
  }
  return { ok: false, invoice: null, errors };
}
