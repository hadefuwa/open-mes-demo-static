/* Client-side behaviour for the static, read-only copy of Open-MES (built by `manage.py build_static_site`).
 *
 * The live app does search, sorting, filtering and CSV export on the server. In the static copy the
 * pages are pre-rendered, so this script does the same jobs in the browser:
 *   - data tables: search, click-to-sort and CSV export
 *   - GET forms (station, technician, serial lookup ...): jump to the matching pre-rendered page
 *   - POST forms and links to pages that were not rendered: explain that this is a read-only demo
 */
(function () {
  "use strict";

  var rootMeta = document.querySelector('meta[name="static-root"]');
  var ROOT = rootMeta ? rootMeta.content : "";
  var MANIFEST = window.__MES_MANIFEST || { pages: {}, serials: {} };

  function toast(message) {
    var el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 3800);
  }

  /* ---------- links and forms ---------- */

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[data-unavailable]");
    if (link) {
      event.preventDefault();
      toast("That page is not part of the static demo.");
    }
  });

  function canonicalKey(path, params) {
    var pairs = [];
    params.forEach(function (value, name) { if (value !== "") pairs.push([name, value]); });
    pairs.sort(function (a, b) { return a[0] === b[0] ? (a[1] < b[1] ? -1 : 1) : (a[0] < b[0] ? -1 : 1); });
    var query = pairs.map(function (p) { return encodeURIComponent(p[0]) + "=" + encodeURIComponent(p[1]); }).join("&");
    return query ? path + "?" + query : path;
  }

  /* A form with a search box inside a card that holds a table filters that table (the Test reports page). */
  function filterCard(form) {
    var card = form.closest(".card");
    var table = card && card.querySelector("table");
    var search = form.querySelector('input[name="q"]');
    if (!table || !search) return false;
    var result = form.querySelector('select[name="result"]');
    var needle = search.value.trim().toLowerCase();
    var wanted = result ? result.value : "";
    Array.prototype.slice.call(table.querySelectorAll("tr")).slice(1).forEach(function (row) {
      var text = row.textContent;
      var show = (!needle || text.toLowerCase().indexOf(needle) !== -1) && (!wanted || text.indexOf(wanted) !== -1);
      row.style.display = show ? "" : "none";
    });
    return true;
  }

  function handleGetForm(form) {
    if (filterCard(form)) return;
    var path = form.getAttribute("data-key-path") || location.pathname;
    var params = new URLSearchParams(new FormData(form));
    var key = canonicalKey(path, params);
    var target = MANIFEST.pages[key];
    if (!target && params.get("serial")) {
      var serial = MANIFEST.serials[params.get("serial").trim().toLowerCase()];
      if (serial) target = MANIFEST.pages[canonicalKey(path, new URLSearchParams({ serial: serial }))];
      else return toast('No unit with serial "' + params.get("serial") + '" in this dataset.');
    }
    if (target) location.href = ROOT + target;
    else toast("That filter is not available in the static demo.");
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    event.preventDefault();
    if ((form.getAttribute("method") || "get").toLowerCase() === "post") {
      toast("Read-only demo: actions that change data need the live app.");
    } else {
      handleGetForm(form);
    }
  });

  // Selects use onchange="this.form.submit()", which skips the submit event: route it through the handler.
  HTMLFormElement.prototype.submit = function () {
    this.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  };

  // Timeline filters cannot be pre-rendered in every combination.
  document.querySelectorAll('form[data-key-path="/timeline/"]').forEach(function (form) {
    var note = document.createElement("p");
    note.className = "muted";
    note.textContent = "Timeline filters need the live app; this is the default view.";
    form.replaceWith(note);
  });

  /* ---------- data tables ---------- */

  function sortKey(text) {
    var t = text.trim();
    var plain = t.replace(/[£,%\s]/g, "").replace(/min$/, "");
    if (plain !== "" && !isNaN(plain)) return { type: 0, value: parseFloat(plain) };
    var date = /^(\d{1,2}) ([A-Za-z]{3}) (\d{4})/.exec(t);
    if (date) {
      var ms = Date.parse(date[2] + " " + date[1] + ", " + date[3] + (/\d{2}:\d{2}/.test(t) ? " " + /\d{2}:\d{2}/.exec(t)[0] : ""));
      if (!isNaN(ms)) return { type: 0, value: ms };
    }
    return { type: 1, value: t.toLowerCase() };
  }

  function compare(a, b) {
    if (a.type !== b.type) return a.type - b.type;
    return a.value < b.value ? -1 : a.value > b.value ? 1 : 0;
  }

  function csvCell(text) {
    var t = text.replace(/\s+/g, " ").trim();
    return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
  }

  function initTable(card) {
    var table = card.querySelector("table");
    var input = card.querySelector("[data-table-search]");
    var count = card.querySelector("[data-table-count]");
    var csv = card.querySelector("[data-table-csv]");
    var headers = Array.prototype.slice.call(table.querySelectorAll("tr:first-child th"));
    var body = table.querySelector("tbody") || table;
    var rows = Array.prototype.slice.call(table.querySelectorAll("tr")).slice(1)
      .filter(function (row) { return !row.querySelector("td.empty"); });

    function refresh() {
      var needle = input.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var show = !needle || row.textContent.toLowerCase().indexOf(needle) !== -1;
        row.style.display = show ? "" : "none";
        if (show) shown += 1;
      });
      count.textContent = shown + (shown === 1 ? " row" : " rows");
    }
    input.addEventListener("input", refresh);

    var sorted = { column: -1, descending: false };
    headers.forEach(function (th, column) {
      if (!th.hasAttribute("data-sortable")) return;
      th.addEventListener("click", function () {
        sorted.descending = sorted.column === column ? !sorted.descending : false;
        sorted.column = column;
        rows.sort(function (a, b) {
          var order = compare(sortKey(a.children[column].textContent), sortKey(b.children[column].textContent));
          return sorted.descending ? -order : order;
        });
        rows.forEach(function (row) { body.appendChild(row); });
        headers.forEach(function (h) { h.textContent = h.textContent.replace(/ [▲▼]$/, ""); });
        th.textContent += sorted.descending ? " ▼" : " ▲";
      });
    });

    csv.addEventListener("click", function () {
      var lines = [headers.map(function (h) { return csvCell(h.textContent.replace(/ [▲▼]$/, "")); }).join(",")];
      rows.forEach(function (row) {
        if (row.style.display === "none") return;
        lines.push(Array.prototype.map.call(row.children, function (cell) { return csvCell(cell.textContent); }).join(","));
      });
      var name = (document.title.split("·")[0] || "table").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-") + ".csv";
      var link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
    });

    var q = new URLSearchParams(location.search).get("q");
    if (q) { input.value = q; refresh(); }
  }

  document.querySelectorAll("[data-static-table]").forEach(initTable);
})();
