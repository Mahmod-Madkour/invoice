/*
 * Builds the printable invoice (A4 landscape pages) inside a container element.
 * Text is always set with textContent, so item names can never inject HTML.
 * Layout and measurements live in assets/css/invoice.css.
 */
import { formatDate, formatMoney, formatPercent, formatQuantity, nameDirection } from "./rules.js";
import { paginate } from "./pagination.js";

const SIDES = ["right", "left"]; // the first table of a page sits on the right (Arabic reading order)
const HEADERS = ["اسم الصنف", "الكمية", "السعر", "الخصم", "الإجمالي"];
const COLUMNS = ["name", "qty", "price", "disc", "total"];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** A number isolated left-to-right, so "12.5%" or "1,250.50" is never reordered by the RTL text. */
function num(text) {
  const bdi = el("bdi", null, text);
  bdi.dir = "ltr";
  return bdi;
}

function numCell(text) {
  const td = el("td", "num");
  td.append(num(text));
  return td;
}

function itemTable(table, side) {
  const t = el("table", `items items--${side}`);
  const colgroup = el("colgroup");
  for (const c of COLUMNS) colgroup.append(el("col", `col-${c}`));

  const headRow = el("tr");
  for (const h of HEADERS) headRow.append(el("th", null, h));
  const thead = el("thead");
  thead.append(headRow);

  const tbody = el("tbody");
  for (const item of table.rows) {
    const tr = el("tr");
    const name = el("td", "name", item.name);
    name.dir = nameDirection(item.name);
    tr.append(name, numCell(formatQuantity(item.quantity)), numCell(formatMoney(item.unitPrice)),
      numCell(formatPercent(item.discount)), numCell(formatMoney(item.total)));
    tbody.append(tr);
  }
  for (let i = 0; i < table.paddingCount; i++) {
    const tr = el("tr", "pad");
    for (let c = 0; c < COLUMNS.length; c++) tr.append(el("td"));
    tbody.append(tr);
  }

  const label = el("td", "label", "الإجمالي المتراكم");
  label.colSpan = 4;
  const footRow = el("tr");
  footRow.append(label, numCell(formatMoney(table.runningTotal)));
  const tfoot = el("tfoot");
  tfoot.append(footRow);

  t.append(colgroup, thead, tbody, tfoot);
  return t;
}

function pageElement(page, pageTotal, invoice) {
  const section = el("section", "page");
  const body = el("div", "page-body");

  const band = el("header", "band");
  const date = el("p", "date", "التاريخ: ");
  date.append(num(formatDate(invoice.date)));
  band.append(el("h1", "title", "فاتورة"), date);
  body.append(band);

  page.tables.forEach((table, index) => body.append(itemTable(table, SIDES[index])));

  const summary = el("div", "summary");
  if (page.isLast) {
    const box = el("div", "grand-total");
    const amount = el("span", "amount");
    amount.append(num(formatMoney(invoice.grandTotal)));
    box.append(el("span", "label", "الإجمالي الكلي"), amount);
    summary.append(box);
  }
  body.append(summary);

  const pageNumber = el("p", "page-number", "صفحة ");
  pageNumber.append(num(String(page.number)), " من ", num(String(pageTotal)));
  section.append(body, pageNumber);
  return section;
}

/**
 * Render the invoice into `root`, replacing its content.
 * @param invoice { date: "YYYY-MM-DD", items: [{name, quantity, unitPrice, discount, total}], grandTotal }
 * @returns the number of pages
 */
export function renderInvoice(root, invoice) {
  const pages = paginate(invoice.items);
  root.replaceChildren(...pages.map((page) => pageElement(page, pages.length, invoice)));
  return pages.length;
}
