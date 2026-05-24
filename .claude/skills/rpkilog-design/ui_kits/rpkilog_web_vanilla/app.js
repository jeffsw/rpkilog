/* ============================================================
   rpkilog Web — Vanilla UI Kit · app.js
   ----------------------------------------------------------------
   Plain DOM rendering. No framework, no build step.
   Wires the search form to the result table and pagination.
   ============================================================ */

(function () {
  "use strict";

  // ---- Templates (just functions returning HTML strings) ------------
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function statsLine({ took, shards, hits }) {
    return (
      '<div class="rk-stats">' +
      "took: " + took + "ms" +
      "&nbsp;&nbsp;shards: " + shards +
      "&nbsp;&nbsp;hits: " + hits.toLocaleString() +
      "</div>"
    );
  }

  function resultRow(r) {
    return (
      "<tr>" +
      '<td><a class="rk-link" href="#">' + escapeHtml(r.prefix) + "</a></td>" +
      '<td class="rk-right">' + r.maxLength + "</td>" +
      '<td><a class="rk-link" href="#">' + r.asn + "</a></td>" +
      "<td>" + escapeHtml(r.ta) + "</td>" +
      "<td>" +
        '<span class="rk-expired">' + r.expires_old + "</span><br>" +
        '<a class="rk-link" href="#">' + r.expires_new + "</a>" +
      "</td>" +
      '<td><span class="rk-verb">' + escapeHtml(r.verb) + "</span></td>" +
      "<td>" + r.observation_timestamp + "</td>" +
      "</tr>"
    );
  }

  function resultsTable(result) {
    return (
      statsLine(result) +
      '<table class="rk-table">' +
      "<thead><tr>" +
      "<th>prefix</th>" +
      '<th class="rk-right">maxLength</th>' +
      "<th>asn</th>" +
      "<th>ta</th>" +
      "<th>expires</th>" +
      "<th>verb</th>" +
      "<th>observation_timestamp</th>" +
      "</tr></thead>" +
      "<tbody>" + result.rows.map(resultRow).join("") + "</tbody>" +
      "</table>"
    );
  }

  function pagination(page, pageCount) {
    const pages = [];
    for (let i = 0; i < pageCount; i++) {
      pages.push(
        '<a href="#" data-page="' + i + '"' +
        (i === page ? ' class="rk-current"' : "") +
        ">" + i + "</a>"
      );
    }
    return (
      '<div class="rk-pagination">' +
      '<div class="rk-pagination-label">Page:</div>' +
      '<div class="rk-pagination-pages">' + pages.join("") + "</div>" +
      "</div>"
    );
  }

  // ---- App state ----------------------------------------------------
  const state = {
    query: { prefix: "8.8.8.0/24", asn: "" },
    perPage: 20,
    page: 0,
    result: null,
  };

  // ---- Render -------------------------------------------------------
  function render() {
    const result = state.result;
    const visible = {
      ...result,
      rows: result.rows.slice(state.page * state.perPage, (state.page + 1) * state.perPage),
    };
    document.getElementById("rk-results").innerHTML = resultsTable(visible);
    const pageCount = Math.min(50, Math.max(1, Math.ceil(result.hits / state.perPage)));
    document.getElementById("rk-pagination").innerHTML = pagination(state.page, pageCount);
  }

  function runSearch() {
    state.result = window.RpkilogData.search(state.query);
    state.page = 0;
    render();
  }

  // ---- Wire DOM events ---------------------------------------------
  function init() {
    // Form submit
    const form = document.getElementById("rk-search-form");
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      state.query = {
        prefix: document.getElementById("rk-input-prefix").value.trim(),
        asn: document.getElementById("rk-input-asn").value.trim(),
      };
      state.perPage = parseInt(document.getElementById("rk-input-perpage").value, 10) || 20;
      runSearch();
    });

    // Pagination click (event delegation)
    document.getElementById("rk-pagination").addEventListener("click", function (e) {
      const a = e.target.closest("a[data-page]");
      if (!a) return;
      e.preventDefault();
      state.page = parseInt(a.getAttribute("data-page"), 10);
      render();
    });

    // Initial search
    runSearch();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
