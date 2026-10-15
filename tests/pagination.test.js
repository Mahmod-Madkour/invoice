// Run with:  node --test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import Big from "../assets/vendor/big.js";
import { pageCount, paginate } from "../assets/js/pagination.js";
import { buildInvoice } from "../assets/js/rules.js";

const items = (n, seed = 1) => Array.from({ length: n }, (_, k) => ({
  name: `صنف ${k + 1}`,
  total: new Big(((k * 7919 + seed * 104729) % 100000) / 100 + ""),
}));
const shape = (pages) => pages.map((p) => p.tables.map((t) => t.rows.length));
const sum = (list) => list.reduce((acc, it) => acc.plus(it.total), new Big(0));

test("required layouts (first table = right side)", () => {
  const expected = {
    1: [[1]], 19: [[19]], 20: [[20]], 21: [[20, 1]], 39: [[20, 19]], 40: [[20, 20]],
    41: [[20, 20], [1]], 65: [[20, 20], [20, 5]], 80: [[20, 20], [20, 20]],
    81: [[20, 20], [20, 20], [1]], 100: [[20, 20], [20, 20], [20]], 120: [[20, 20], [20, 20], [20, 20]],
    1000: Array.from({ length: 25 }, () => [20, 20]),
  };
  for (const [n, layout] of Object.entries(expected)) {
    const list = items(Number(n));
    const pages = paginate(list);
    assert.deepEqual(shape(pages), layout, `n=${n}`);
    assert.deepEqual(pages.map((p) => p.number), layout.map((_, i) => i + 1));
    assert.deepEqual(pages.map((p) => p.isLast), layout.map((_, i) => i === layout.length - 1));
    assert.ok(pages.at(-1).tables.at(-1).runningTotal.eq(sum(list)));
    assert.equal(pageCount(Number(n)), layout.length);
  }
});

test("padding and running totals for 65 items", () => {
  const list = items(65, 7);
  const tables = paginate(list).flatMap((p) => p.tables);
  assert.deepEqual(tables.map((t) => t.paddingCount), [0, 0, 0, 15]);
  tables.forEach((t, k) => assert.ok(t.runningTotal.eq(sum(list.slice(0, Math.min(20 * (k + 1), 65))))));
});

test("invariants for n = 1…3000 and other table sizes", () => {
  for (const rowsPerTable of [20, 1, 7, 25]) {
    for (const tablesPerPage of [2, 1]) {
      for (const n of [1, 2, 19, 20, 21, 39, 40, 41, 99, 100, 101, 777, 1000, 2999, 3000]) {
        const list = items(n, n);
        const pages = paginate(list, rowsPerTable, tablesPerPage);
        const tables = pages.flatMap((p) => p.tables);
        const flat = tables.flatMap((t) => t.rows);
        assert.equal(flat.length, n);
        assert.ok(flat.every((it, i) => it === list[i]), "order preserved");
        assert.ok(tables.every((t) => t.rows.length >= 1 && t.rows.length <= rowsPerTable));
        assert.ok(tables.slice(0, -1).every((t) => t.rows.length === rowsPerTable), "only the last table is partial");
        assert.ok(pages.slice(0, -1).every((p) => p.tables.length === tablesPerPage), "only the last page is partial");
        assert.ok(tables.every((t) => t.paddingCount === rowsPerTable - t.rows.length));
        assert.equal(pages.length, Math.ceil(n / (rowsPerTable * tablesPerPage)));
        let seen = 0;
        for (const t of tables) {
          seen += t.rows.length;
          assert.ok(t.runningTotal.eq(sum(list.slice(0, seen))));
        }
        assert.ok(tables.at(-1).runningTotal.eq(sum(list)));
      }
    }
  }
});

test("empty input is rejected", () => {
  assert.throws(() => paginate([]));
});

test("every fixture is a valid invoice with the expected page count", () => {
  for (const name of ["items_1", "items_20", "items_21", "items_40", "items_41", "items_45", "items_65", "items_80", "items_81", "edge_limits"]) {
    const fixture = JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
    const result = buildInvoice({ date: fixture.date, rows: fixture.items });
    assert.ok(result.ok, `${name}: ${JSON.stringify(result.errors)}`);
    assert.equal(paginate(result.invoice.items).length, Math.ceil(fixture.items.length / 40), name);
  }
});
