// Run with:  node --test
import assert from "node:assert/strict";
import { test } from "node:test";

import Big from "../assets/vendor/big.js";
import {
  MAX_ITEMS, MSG, buildInvoice, cleanName, decimalPlaces, formatDate, formatMoney, formatPercent,
  formatQuantity, isValidDate, lineTotal, nameDirection, normalizeNumber, parseDecimal, validateRow,
} from "../assets/js/rules.js";

const B = (s) => new Big(s);
const row = (name = "سكر أبيض", quantity = "2.5", unit_price = "45.00", discount_percent = "10") =>
  ({ name, quantity, unit_price, discount_percent });

// ------------------------------------------------------------------ normalization & parsing

test("normalizeNumber: Arabic/Persian digits, separators, invisible marks, whitespace", () => {
  const cases = [
    ["٠١٢٣٤٥٦٧٨٩", "0123456789"],
    ["۰۱۲۳۴۵۶۷۸۹", "0123456789"],
    ["٢٫٥", "2.5"],                         // Arabic decimal separator
    ["١٬٢٥٠٫٥٠", "1250.50"], // Arabic thousands separator
    ["1,250.50", "1250.50"],
    ["  12.5 \t", "12.5"],
    [" 12 ", "12"],
    ["‏١٢‎", "12"],                    // RLM/LRM from Arabic keyboards
    ["﻿12﻿", "12"],                              // BOM
    ["\x1c5\x85", "5"],
    ["", ""],
  ];
  for (const [raw, expected] of cases) assert.equal(normalizeNumber(raw), expected, JSON.stringify(raw));
});

test("parseDecimal accepts plain numbers only", () => {
  for (const [raw, expected] of [["2.5", "2.5"], ["٢٫٥", "2.5"], ["1,000,000", "1000000"],
    [" 45.00 ", "45"], ["0", "0"], ["5.", "5"], [".5", "0.5"], ["-3", "-3"], ["+3", "3"], ["007", "7"]]) {
    assert.ok(parseDecimal(raw).eq(B(expected)), raw);
  }
  for (const raw of ["", "  ", "abc", "1.2.3", ".", "-", "+-1", "1e5", "NaN", "Infinity", "1 000",
    "१२", "0x10", "1/2", "50%", "١٢،٥", "1".repeat(33)]) {
    assert.equal(parseDecimal(raw), null, JSON.stringify(raw));
  }
});

test("decimalPlaces counts significant decimals without rounding", () => {
  for (const [raw, places] of [["2.50", 1], ["45.000", 0], ["0.125", 3], ["100", 0], ["0", 0], ["0.000", 0],
    ["1.005", 3], ["1.0049999999999999999999999999", 28], ["12345678901234567890123456789012", 0]]) {
    assert.equal(decimalPlaces(B(raw)), places, raw);
  }
});

test("cleanName trims, collapses whitespace and drops control characters", () => {
  for (const [raw, expected] of [["  سكر   أبيض \n", "سكر أبيض"], ["كابل\tHDMI", "كابل HDMI"],
    ["a\x00b\x07c", "abc"], [" شاي ", "شاي"], ["﻿", ""], ["a\x1cb\x85c", "a b c"], ["   ", ""]]) {
    assert.equal(cleanName(raw), expected, JSON.stringify(raw));
  }
});

test("nameDirection: Arabic names RTL, Latin-only names LTR", () => {
  assert.equal(nameDirection("شاشة Samsung 55 بوصة"), "rtl");
  assert.equal(nameDirection("iPhone 15 Pro Max"), "ltr");
  assert.equal(nameDirection("Model X (2024)"), "ltr");
});

test("isValidDate", () => {
  for (const ok of ["2026-10-03", "2024-02-29"]) assert.ok(isValidDate(ok), ok);
  for (const bad of ["", "2026-02-30", "2026-13-01", "03/10/2026", "20261003", "2025-02-29", null]) assert.ok(!isValidDate(bad), bad);
});

// ------------------------------------------------------------------ formatting

test("formatting uses Western digits", () => {
  assert.equal(formatMoney(B("1250.5")), "1,250.50");
  assert.equal(formatMoney(B("0")), "0.00");
  assert.equal(formatMoney(B("999999999.99")), "999,999,999.99");
  assert.equal(formatQuantity(B("2.500")), "2.5");
  assert.equal(formatQuantity(B("10")), "10");
  assert.equal(formatQuantity(B("0.125")), "0.125");
  assert.equal(formatQuantity(B("1000000")), "1,000,000");
  assert.equal(formatQuantity(B("999999.999")), "999,999.999");
  assert.equal(formatPercent(B("10")), "10%");
  assert.equal(formatPercent(B("12.50")), "12.5%");
  assert.equal(formatPercent(B("0")), "0%");
  assert.equal(formatPercent(B("33.33")), "33.33%");
  assert.equal(formatDate("2026-10-03"), "03/10/2026");
});

// ------------------------------------------------------------------ math

test("line totals: discounts, decimals, zero price", () => {
  for (const [q, p, d, expected] of [["2", "100.00", "0", "200.00"], ["2", "100.00", "10", "180.00"],
    ["2", "100.00", "12.5", "175.00"], ["2", "100.00", "100", "0.00"], ["2.5", "45.00", "10", "101.25"],
    ["0.125", "480.00", "0", "60.00"], ["3", "54.99", "33.33", "109.99"], ["1", "0", "0", "0.00"],
    ["999999.999", "0.01", "0", "10000.00"]]) {
    assert.equal(lineTotal(B(q), B(p), B(d)).toFixed(2), expected, `${q} × ${p} − ${d}%`);
  }
});

test("rounding at half-cent boundaries is half-up", () => {
  for (const [q, p, d, expected] of [["0.001", "5.00", "0", "0.01"], ["1.005", "1.00", "0", "1.01"],
    ["0.125", "1.00", "0", "0.13"], ["1", "0.25", "50", "0.13"], ["0.004", "1.00", "0", "0.00"],
    ["1", "0.01", "50", "0.01"], ["1", "0.01", "50.01", "0.00"]]) {
    assert.equal(lineTotal(B(q), B(p), B(d)).toFixed(2), expected, `${q} × ${p} − ${d}%`);
  }
});

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test("line totals match exact integer arithmetic on 5000 random lines", () => {
  const rand = mulberry32(42);
  const int = (max) => BigInt(Math.floor(rand() * (max + 1)));
  for (let i = 0; i < 5000; i++) {
    const Q = int(1_000_000_000) || 1n; // quantity × 1000
    const P = int(1_000_000_000);       // price × 100
    const D = int(10_000);              // discount × 100
    // exact total × 10^9 = Q × P × (10000 − D); half-up to cents
    const N = Q * P * (10000n - D);
    const cents = (N + 5_000_000n) / 10_000_000n;
    const expected = `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
    const q = B(Q.toString()).div(1000), p = B(P.toString()).div(100), d = B(D.toString()).div(100);
    assert.equal(lineTotal(q, p, d).toFixed(2), expected, `${q} × ${p} − ${d}%`);
  }
});

// ------------------------------------------------------------------ validation

test("each rule gives its Arabic message on the right field", () => {
  const cases = [
    [row(""), "name", MSG.nameRequired], [row("x".repeat(41)), "name", MSG.nameTooLong],
    [row(undefined, ""), "quantity", MSG.quantityNotNumber], [row(undefined, "abc"), "quantity", MSG.quantityNotNumber],
    [row(undefined, "0"), "quantity", MSG.quantityNotPositive], [row(undefined, "-2"), "quantity", MSG.quantityNotPositive],
    [row(undefined, "1.0001"), "quantity", MSG.quantityInvalid], [row(undefined, "1000000.001"), "quantity", MSG.quantityInvalid],
    [row(undefined, "1.0049999999999999999999999999"), "quantity", MSG.quantityInvalid],
    [row(undefined, undefined, ""), "unit_price", MSG.priceNotNumber], [row(undefined, undefined, "-0.01"), "unit_price", MSG.priceNotNumber],
    [row(undefined, undefined, "1.001"), "unit_price", MSG.priceInvalid], [row(undefined, undefined, "10000000.01"), "unit_price", MSG.priceInvalid],
    [row(undefined, undefined, undefined, "x"), "discount_percent", MSG.discountInvalid],
    [row(undefined, undefined, undefined, "100.01"), "discount_percent", MSG.discountInvalid],
    [row(undefined, undefined, undefined, "12.345"), "discount_percent", MSG.discountInvalid],
    [row(undefined, "100", "10000000", "0"), "total", MSG.totalTooLarge],
  ];
  for (const [raw, field, message] of cases) {
    const result = validateRow(raw);
    assert.deepEqual(result.errors, { [field]: message }, JSON.stringify(raw));
  }
});

test("boundary values are accepted; empty discount means 0", () => {
  for (const raw of [row("x".repeat(40), "0.001", "0", "100"), row(undefined, "1000000", "0.01", "0"),
    row(undefined, "99.999", "10000000", "0"), row(undefined, undefined, "45.000"), row(undefined, undefined, undefined, "")]) {
    assert.deepEqual(validateRow(raw).errors, {}, JSON.stringify(raw));
  }
  assert.equal(validateRow(row(undefined, "2", "10", "")).item.total.toFixed(2), "20.00");
});

test("rows of whitespace or invisible characters are blank", () => {
  assert.ok(validateRow({ name: " ", quantity: "", unit_price: "﻿", discount_percent: "\x85" }).blank);
  assert.ok(validateRow({}).blank);
});

test("buildInvoice: blank rows ignored but row numbers follow the screen", () => {
  const blank = row("", "", "", "");
  assert.ok(buildInvoice({ date: "2026-10-03", rows: [row(), blank, row()] }).ok);
  const result = buildInvoice({ date: "2026-10-03", rows: [row(), blank, row(undefined, "abc")] });
  assert.deepEqual(result.errors, [{ row: 3, field: "quantity", message: MSG.quantityNotNumber }]);
});

test("buildInvoice: invoice-level rules", () => {
  assert.deepEqual(buildInvoice({ date: "2026-10-03", rows: [] }).errors, [{ row: null, field: "items", message: MSG.noItems }]);
  assert.deepEqual(buildInvoice({ date: "2026-02-30", rows: [row()] }).errors, [{ row: null, field: "date", message: MSG.dateInvalid }]);
  const big = row(undefined, "99.999", "10000000", "0");
  assert.deepEqual(buildInvoice({ date: "2026-10-03", rows: [big, big] }).errors,
    [{ row: null, field: "grand_total", message: MSG.totalTooLarge }]);
  const tooMany = Array.from({ length: MAX_ITEMS + 1 }, () => row());
  assert.ok(buildInvoice({ date: "2026-10-03", rows: tooMany }).errors.some((e) => e.message === MSG.tooManyItems));
});

test("buildInvoice: grand total is the sum of rounded line totals", () => {
  const tiny = row("x", "0.001", "5.00", "0"); // 0.005 → 0.01 each
  const result = buildInvoice({ date: "2026-10-03", rows: [tiny, tiny, tiny] });
  assert.equal(result.invoice.grandTotal.toFixed(2), "0.03");
});
