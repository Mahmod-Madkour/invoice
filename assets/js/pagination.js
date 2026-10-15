/*
 * Pagination and running totals (spec §7).
 *   items → consecutive tables of ROWS_PER_TABLE → consecutive pages of TABLES_PER_PAGE
 * A page's `tables` are in reading order: tables[0] is the right-hand table.
 */
import Big from "../vendor/big.js";
import { ROWS_PER_TABLE, TABLES_PER_PAGE } from "./rules.js";

/** ceil(n / (rowsPerTable × tablesPerPage)) */
export function pageCount(itemCount, rowsPerTable = ROWS_PER_TABLE, tablesPerPage = TABLES_PER_PAGE) {
  return Math.ceil(itemCount / (rowsPerTable * tablesPerPage));
}

/**
 * @param items  [{..., total: Big}] in order (at least one)
 * @returns [{ number, isLast, tables: [{ rows, paddingCount, runningTotal: Big }] }]
 */
export function paginate(items, rowsPerTable = ROWS_PER_TABLE, tablesPerPage = TABLES_PER_PAGE) {
  if (!items.length) throw new Error("cannot paginate an empty item list");
  if (rowsPerTable < 1 || tablesPerPage < 1) throw new Error("rowsPerTable and tablesPerPage must be at least 1");

  const tables = [];
  let running = new Big(0);
  for (let start = 0; start < items.length; start += rowsPerTable) {
    const rows = items.slice(start, start + rowsPerTable);
    for (const row of rows) running = running.plus(row.total);
    tables.push({ rows, paddingCount: rowsPerTable - rows.length, runningTotal: running });
  }

  const pages = [];
  for (let start = 0; start < tables.length; start += tablesPerPage) {
    pages.push({ number: pages.length + 1, isLast: false, tables: tables.slice(start, start + tablesPerPage) });
  }
  pages[pages.length - 1].isLast = true;
  return pages;
}
