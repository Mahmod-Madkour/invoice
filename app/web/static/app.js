/*
 * Invoice editor (spec §9). Vanilla JS, no inline handlers (CSP), no storage of any kind.
 *
 * Normalization, validation and arithmetic mirror the server exactly — keep them identical:
 *   app/domain/numbers.py       normalizeNumber, parseDecimal, decimalPlaces
 *   app/domain/models.py        cleanName, limits
 *   app/domain/calculations.py  lineTotal (big.js, ROUND_HALF_UP, rounded once per line)
 *   app/api/schemas.py          validateRow and the Arabic messages
 * The browser totals are a preview; the server recalculates everything for the PDF.
 */
(function () {
  "use strict";

  // ------------------------------------------------------------------ rules (mirror the server)

  Big.DP = 40;
  Big.RM = Big.roundHalfUp;

  var NAME_MAX_LENGTH = 40;
  var QUANTITY_MAX = new Big("1000000");
  var QUANTITY_MAX_DECIMALS = 3;
  var PRICE_MAX = new Big("10000000");
  var PRICE_MAX_DECIMALS = 2;
  var DISCOUNT_MAX = new Big("100");
  var DISCOUNT_MAX_DECIMALS = 2;
  var TOTAL_MAX = new Big("999999999.99");
  var MAX_NUMBER_LENGTH = 32;

  var MSG = {
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
    busy: "الخادم مشغول، حاول مرة أخرى بعد قليل",
    tooLarge: "حجم الطلب أكبر من الحد المسموح",
    network: "تعذر الاتصال بالخادم، تحقق من الاتصال وحاول مرة أخرى",
    unexpected: "حدث خطأ غير متوقع، حاول مرة أخرى",
    confirmClear: "هل تريد مسح جميع الأصناف؟",
    deleted: "تم حذف الصنف"
  };

  var FIELDS = ["name", "quantity", "unit_price", "discount_percent"];
  var NUMBER_RE = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/;
  var DATE_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
  // Arabic-Indic and Persian digits → ASCII; Arabic decimal separator → "."
  var DIGIT_MAP = { "٫": "." };
  "٠١٢٣٤٥٦٧٨٩".split("").forEach(function (ch, i) { DIGIT_MAP[ch] = String(i); });
  "۰۱۲۳۴۵۶۷۸۹".split("").forEach(function (ch, i) { DIGIT_MAP[ch] = String(i); });
  var DIGITS_RE = /[٠-٩۰-۹٫]/g;
  // Thousands separators (Arabic \u066c and ",") and invisible marks (bidi controls, BOM) are removed.
  var REMOVE_RE = /[\u066c,\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069\ufeff]/g;
  var CONTROL_RE = /[\u0000-\u001f\u007f-\u009f]/g;
  // Python's str.isspace() set: JS \s plus U+001C-U+001F and U+0085 (U+FEFF is removed before use).
  var SPACE = "\\s\\x1c-\\x1f\\x85";
  var SPACE_CHAR_RE = new RegExp("^[" + SPACE + "]$");
  var SPACES_RE = new RegExp("[" + SPACE + "]+");
  var TRIM_RE = new RegExp("^[" + SPACE + "]+|[" + SPACE + "]+$", "g");
  var BOM_RE = /\ufeff/g;
  var RTL_RE = /[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]/;  // Hebrew and Arabic blocks

  function normalizeNumber(text) {
    return String(text || "")
      .replace(DIGITS_RE, function (ch) { return DIGIT_MAP[ch]; })
      .replace(REMOVE_RE, "")
      .replace(TRIM_RE, "");
  }

  /** Big for a plain number, or null when blank / not a number. */
  function parseDecimal(text) {
    var s = normalizeNumber(text);
    if (s.length > MAX_NUMBER_LENGTH || !NUMBER_RE.test(s)) return null;
    return new Big(s.charAt(0) === "+" ? s.slice(1) : s);
  }

  /** Significant fractional digits (big.js drops trailing zeros): 2.50 → 1, 45.000 → 0. */
  function decimalPlaces(big) {
    return Math.max(0, big.c.length - big.e - 1);
  }

  function cleanName(raw) {
    return String(raw || "")
      .replace(BOM_RE, "")
      .replace(CONTROL_RE, function (ch) { return SPACE_CHAR_RE.test(ch) ? " " : ""; })
      .split(SPACES_RE)
      .filter(Boolean)
      .join(" ");
  }

  function charLength(text) {
    return Array.from(text).length; // code points, like Python's len()
  }

  function lineTotal(quantity, unitPrice, discount) {
    var gross = quantity.times(unitPrice);
    var total = gross.minus(gross.times(discount).div(100)).round(2, Big.roundHalfUp);
    return total.eq(0) ? new Big(0) : total;
  }

  function formatMoney(big) {
    var parts = big.toFixed(2).split(".");
    return parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + parts[1];
  }

  function isBlankValues(v) {
    return cleanName(v.name) === "" &&
      normalizeNumber(v.quantity) === "" &&
      normalizeNumber(v.unit_price) === "" &&
      normalizeNumber(v.discount_percent) === "";
  }

  /** Same rules, order and messages as InvoiceRequest._validate_row on the server. */
  function validateRow(v) {
    var errors = {};
    if (isBlankValues(v)) return { blank: true, errors: errors, total: null };

    var name = cleanName(v.name);
    if (!name) errors.name = MSG.nameRequired;
    else if (charLength(name) > NAME_MAX_LENGTH) errors.name = MSG.nameTooLong;

    var quantity = parseDecimal(v.quantity);
    if (quantity === null) errors.quantity = MSG.quantityNotNumber;
    else if (quantity.lte(0)) errors.quantity = MSG.quantityNotPositive;
    else if (quantity.gt(QUANTITY_MAX) || decimalPlaces(quantity) > QUANTITY_MAX_DECIMALS) errors.quantity = MSG.quantityInvalid;

    var price = parseDecimal(v.unit_price);
    if (price === null || price.lt(0)) errors.unit_price = MSG.priceNotNumber;
    else if (price.gt(PRICE_MAX) || decimalPlaces(price) > PRICE_MAX_DECIMALS) errors.unit_price = MSG.priceInvalid;

    var discountText = normalizeNumber(v.discount_percent);
    var discount = discountText === "" ? new Big(0) : parseDecimal(discountText);
    if (discount === null || discount.lt(0) || discount.gt(DISCOUNT_MAX) || decimalPlaces(discount) > DISCOUNT_MAX_DECIMALS) {
      errors.discount_percent = MSG.discountInvalid;
    }

    var total = null;
    if (!errors.quantity && !errors.unit_price && !errors.discount_percent) {
      total = lineTotal(quantity, price, discount);
      if (total.gt(TOTAL_MAX)) {
        errors.total = MSG.totalTooLarge;
        total = null;
      }
    }
    return { blank: false, errors: errors, total: total };
  }

  function pagesText(n) {
    if (n === 1) return "سيتم إنشاء صفحة واحدة";
    if (n === 2) return "سيتم إنشاء صفحتين";
    if (n <= 10) return "سيتم إنشاء " + n + " صفحات";
    return "سيتم إنشاء " + n + " صفحة";
  }

  function errorsText(n) {
    if (n === 1) return "خطأ واحد";
    if (n === 2) return "خطآن";
    if (n <= 10) return n + " أخطاء";
    return n + " خطأ";
  }

  function todayIso() {
    var d = new Date();
    var pad = function (x) { return (x < 10 ? "0" : "") + x; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  // ------------------------------------------------------------------ DOM helpers

  function $(id) { return document.getElementById(id); }

  function setText(el, text) { if (el.textContent !== text) el.textContent = text; }
  function setHidden(el, hidden) { if (el.hidden !== hidden) el.hidden = hidden; }
  function setInvalid(input, invalid) {
    input.classList.toggle("invalid", invalid);
    if (invalid) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }

  var els = {
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
    toastUndo: $("toast-undo")
  };

  var maxItems = parseInt(document.body.dataset.maxItems, 10) || 1000;
  var rowsPerPage = parseInt(document.body.dataset.rowsPerPage, 10) || 40;

  // ------------------------------------------------------------------ state

  var rows = [];               // row objects in display order
  var rowByTr = new WeakMap();
  var showAll = false;         // reveal every error (after clicking the error count or a server 422)
  var busy = false;
  var dateTouched = false;
  var dateServerError = null;
  var serverMessages = [];     // invoice-level messages from the last request
  var pendingUndo = null;      // { row, index }
  var toastTimer = null;
  var firstErrorTarget = null;

  function createRow(values) {
    var tr = els.template.content.firstElementChild.cloneNode(true);
    var row = { tr: tr, inputs: {}, errorEls: {}, touched: new Set(), serverErrors: {}, result: null };
    FIELDS.forEach(function (field) {
      var input = tr.querySelector('[data-field="' + field + '"]');
      row.inputs[field] = input;
      row.errorEls[field] = input.parentElement.querySelector(".field-error");
      if (values) input.value = values[field] || "";
    });
    row.totalEl = tr.querySelector(".row-total");
    row.errorEls.total = tr.querySelector(".c-total .field-error");
    row.counterEl = tr.querySelector(".counter");
    row.noEl = tr.querySelector(".row-no");
    rowByTr.set(tr, row);
    return row;
  }

  function rowValues(row) {
    var v = {};
    FIELDS.forEach(function (field) { v[field] = row.inputs[field].value; });
    return v;
  }

  function insertRow(row, index) {
    rows.splice(index, 0, row);
    var next = rows[index + 1];
    els.rows.insertBefore(row.tr, next ? next.tr : null);
  }

  function removeRow(row) {
    var index = rows.indexOf(row);
    if (index >= 0) {
      rows.splice(index, 1);
      row.tr.remove();
    }
    return index;
  }

  function rowOf(el) {
    var tr = el.closest("tr");
    return tr ? rowByTr.get(tr) : null;
  }

  /** A blank row is always kept at the bottom. */
  function ensureTrailingBlank() {
    var last = rows[rows.length - 1];
    if (!last || !isBlankValues(rowValues(last))) insertRow(createRow(), rows.length);
  }

  // ------------------------------------------------------------------ recompute + render

  function recompute() {
    var count = 0;
    var errorCount = 0;
    var rowErrors = 0;
    var grand = new Big(0);
    firstErrorTarget = null;

    rows.forEach(function (row, index) {
      setText(row.noEl, String(index + 1));
      var values = rowValues(row);
      var result = validateRow(values);
      row.result = result;
      row.tr.classList.toggle("is-blank", result.blank);
      if (!result.blank) count += 1;

      FIELDS.concat(["total"]).forEach(function (field) {
        var message = result.blank ? null : (result.errors[field] || row.serverErrors[field] || null);
        if (message) {
          errorCount += 1;
          rowErrors += 1;
        }
        var visible = Boolean(message) && (
          showAll || field === "total" || Boolean(row.serverErrors[field]) ||
          row.touched.has(field) || (values[field] || "").trim() !== ""
        );
        var target = field === "total" ? row.inputs.quantity : row.inputs[field];
        if (field !== "total") setInvalid(row.inputs[field], visible);
        setText(row.errorEls[field], visible ? message : "");
        setHidden(row.errorEls[field], !visible);
        if (message && !firstErrorTarget) firstErrorTarget = target;
      });

      setText(row.totalEl, result.blank ? "" : (result.total ? formatMoney(result.total) : "—"));
      if (result.total) grand = grand.plus(result.total);

      var nameLength = charLength(values.name);
      setHidden(row.counterEl, nameLength < NAME_MAX_LENGTH - 10);
      setText(row.counterEl, nameLength + "/" + NAME_MAX_LENGTH);
      row.counterEl.classList.toggle("full", nameLength >= NAME_MAX_LENGTH);
      row.inputs.name.dir = values.name.trim() && !RTL_RE.test(values.name) ? "ltr" : "rtl";
    });

    // Date.
    var dateMessage = DATE_RE.test(els.date.value) ? dateServerError : MSG.dateInvalid;
    var dateVisible = Boolean(dateMessage) && (showAll || dateTouched || Boolean(dateServerError));
    if (dateMessage) {
      errorCount += 1;
      if (!firstErrorTarget || rowErrors === 0) firstErrorTarget = els.date;
    }
    setInvalid(els.date, dateVisible);
    setText(els.dateError, dateVisible ? dateMessage : "");
    setHidden(els.dateError, !dateVisible);

    // Invoice-level rules.
    var messages = [];
    if (count > maxItems) messages.push(MSG.tooManyItems);
    if (rowErrors === 0 && grand.gt(TOTAL_MAX)) messages.push(MSG.totalTooLarge);
    errorCount += messages.length;
    messages = messages.concat(serverMessages);
    renderBanner(messages);

    // Footer.
    setText(els.itemCount, String(count));
    setText(els.pagePreview, count ? pagesText(Math.ceil(count / rowsPerPage)) : "");
    setHidden(els.pagePreview, count === 0);
    setText(els.grandTotal, formatMoney(grand));
    setText(els.errorCount, errorsText(errorCount));
    setHidden(els.errorCount, errorCount === 0);
    els.generate.disabled = busy || count === 0 || errorCount > 0;
    if (errorCount === 0) showAll = false;
  }

  function renderBanner(messages) {
    var text = messages.join(" — ");
    setText(els.banner, text);
    setHidden(els.banner, !text);
  }

  function revealErrors() {
    showAll = true;
    recompute();
    var target = firstErrorTarget || (els.banner.hidden ? null : els.banner);
    if (target) {
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      if (target.focus) target.focus({ preventScroll: true });
    }
  }

  // ------------------------------------------------------------------ row actions

  function focusField(row, field) {
    var input = row.inputs[field];
    input.focus();
    input.select();
  }

  /** Enter: next field; from the last field to the next row's name (creating the row if needed). */
  function moveNext(row, field) {
    var i = FIELDS.indexOf(field);
    if (i < FIELDS.length - 1) {
      focusField(row, FIELDS[i + 1]);
      return;
    }
    var index = rows.indexOf(row);
    if (index === rows.length - 1) {
      if (isBlankValues(rowValues(row))) return;
      insertRow(createRow(), rows.length);
      recompute();
    }
    focusField(rows[index + 1], "name");
  }

  function deleteRow(row) {
    if (row.result && row.result.blank) return;
    var index = removeRow(row);
    if (index < 0) return;
    ensureTrailingBlank();
    pendingUndo = { row: row, index: index };
    showToast(MSG.deleted);
    recompute();
  }

  function undoDelete() {
    if (!pendingUndo) return;
    var row = pendingUndo.row;
    var lastIsBlank = rows.length && isBlankValues(rowValues(rows[rows.length - 1]));
    var index = Math.min(pendingUndo.index, lastIsBlank ? rows.length - 1 : rows.length);
    pendingUndo = null;
    hideToast();
    row.serverErrors = {};
    insertRow(row, index);
    ensureTrailingBlank();
    recompute();
    focusField(row, "name");
  }

  function showToast(text) {
    setText(els.toastText, text);
    setHidden(els.toast, false);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      pendingUndo = null;
      hideToast();
    }, 5000);
  }

  function hideToast() {
    clearTimeout(toastTimer);
    setHidden(els.toast, true);
  }

  function clearAll() {
    var hasItems = rows.some(function (row) { return !isBlankValues(rowValues(row)); });
    if (hasItems && !window.confirm(MSG.confirmClear)) return;
    rows.slice().forEach(removeRow);
    pendingUndo = null;
    hideToast();
    showAll = false;
    serverMessages = [];
    dateServerError = null;
    insertRow(createRow(), 0);
    recompute();
    focusField(rows[0], "name");
  }

  // ------------------------------------------------------------------ PDF generation

  function setBusy(value) {
    busy = value;
    setHidden(els.spinner, !value);
    els.generate.setAttribute("aria-busy", value ? "true" : "false");
  }

  function filenameFrom(response) {
    var header = response.headers.get("Content-Disposition") || "";
    var match = /filename="([^"]+)"/.exec(header);
    return match ? match[1] : null;
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
  }

  function applyServerErrors(errors, snapshot) {
    serverMessages = [];
    (errors || []).forEach(function (error) {
      var row = error.row ? snapshot[error.row - 1] : null;
      if (row && rows.indexOf(row) >= 0) {
        row.serverErrors[error.field || "name"] = error.message;
      } else if (error.field === "date") {
        dateServerError = error.message;
      } else if (serverMessages.indexOf(error.message) < 0) {
        serverMessages.push(error.message);
      }
    });
    revealErrors();
  }

  async function errorMessageFrom(response) {
    try {
      var data = await response.json();
      return data.errors && data.errors[0] && data.errors[0].message;
    } catch (e) {
      return null;
    }
  }

  async function generate() {
    recompute();
    if (busy || els.generate.disabled) return;
    setBusy(true);
    serverMessages = [];
    recompute();

    var snapshot = rows.slice();
    var payload = { date: els.date.value, items: snapshot.map(rowValues) }; // numbers stay strings
    try {
      var response = await fetch("/api/invoice/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/pdf, application/json" },
        body: JSON.stringify(payload),
        credentials: "same-origin"
      });
      if (response.ok) {
        var blob = await response.blob();
        downloadBlob(blob, filenameFrom(response) || "invoice-" + els.date.value + ".pdf");
      } else if (response.status === 422) {
        var data = await response.json();
        setBusy(false);
        applyServerErrors(data.errors, snapshot);
        return;
      } else if (response.status === 429 || response.status === 503) {
        serverMessages = [MSG.busy];
      } else if (response.status === 413) {
        serverMessages = [MSG.tooLarge]; // may come from Caddy, with an empty body
      } else {
        serverMessages = [(await errorMessageFrom(response)) || MSG.unexpected];
      }
    } catch (e) {
      serverMessages = [MSG.network];
    } finally {
      setBusy(false);
      recompute();
    }
  }

  // ------------------------------------------------------------------ events

  els.rows.addEventListener("input", function (event) {
    var row = rowOf(event.target);
    var field = event.target.dataset.field;
    if (!row || !field) return;
    delete row.serverErrors[field];
    if (field !== "name") delete row.serverErrors.total;
    serverMessages = [];
    ensureTrailingBlank();
    recompute();
  });

  els.rows.addEventListener("focusout", function (event) {
    var input = event.target;
    var row = rowOf(input);
    var field = input.dataset && input.dataset.field;
    if (!row || !field) return;
    if (field === "name") {
      var cleaned = cleanName(input.value);
      if (cleaned !== input.value) input.value = cleaned;
    } else if (parseDecimal(input.value) !== null) {
      var normalized = normalizeNumber(input.value); // show Western digits, as the PDF will
      if (normalized !== input.value) input.value = normalized;
    }
    if (!isBlankValues(rowValues(row))) row.touched.add(field);
    recompute();
  });

  els.rows.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
    var row = rowOf(event.target);
    var field = event.target.dataset && event.target.dataset.field;
    if (!row || !field) return;
    event.preventDefault();
    moveNext(row, field);
  });

  els.rows.addEventListener("click", function (event) {
    var button = event.target.closest(".del");
    if (!button) return;
    var row = rowOf(button);
    if (row) deleteRow(row);
  });

  els.date.addEventListener("input", function () { dateServerError = null; recompute(); });
  els.date.addEventListener("change", function () { dateServerError = null; recompute(); });
  els.date.addEventListener("blur", function () { dateTouched = true; recompute(); });
  els.date.addEventListener("keydown", function (event) {
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

  // Exposed for the cross-check against the Python implementation (no effect on the page).
  window.InvoiceRules = {
    normalizeNumber: normalizeNumber,
    parseDecimal: parseDecimal,
    decimalPlaces: decimalPlaces,
    cleanName: cleanName,
    lineTotal: lineTotal,
    formatMoney: formatMoney,
    validateRow: validateRow
  };
})();
