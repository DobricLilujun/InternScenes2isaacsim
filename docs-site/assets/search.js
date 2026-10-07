/* SAGE-Bench client-side search (Lunr.js full-text + substring fallback). */
(function () {
  "use strict";

  var input = document.getElementById("search-input");
  var results = document.getElementById("search-results");
  var data = { pages: [] };
  var index = null;
  var loaded = false;
  // base dir of the current page — robust for a project page (…/SAGE-Bench/) or a
  // user page (root). Pages are flat (no nested folders), so this is correct.
  var base = location.pathname.slice(0, location.pathname.lastIndexOf("/") + 1);

  function show() { results.hidden = false; }
  function hide() { results.hidden = true; }
  function esc(s) {
    return s.replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  fetch(base + "assets/search-index.json")
    .then(function (r) { return r.json(); })
    .then(function (d) {
      data = d;
      if (window.lunr) {
        try {
          index = lunr(function () {
            this.ref("slug");
            this.field("title", { boost: 8 });
            this.field("text");
            data.pages.forEach(function (p) { index.add(p); });
          });
        } catch (e) { index = null; }
      }
      loaded = true;
    })
    .catch(function () { loaded = true; });

  function lunrResults(q) {
    if (!index) return [];
    try {
      var hits = index.search(q);
      return hits.map(function (h) { return h.ref; });
    } catch (e) { return []; }
  }

  function substrResults(q) {
    var ql = q.toLowerCase();
    return data.pages
      .map(function (p) {
        var t = 0;
        if (p.title.toLowerCase().indexOf(ql) >= 0) t += 10;
        var c = (p.text || "").toLowerCase();
        if (c.indexOf(ql) >= 0) t += 4;
        return { p: p, score: t };
      })
      .filter(function (x) { return x.score > 0; })
      .sort(function (a, b) { return b.score - a.score; })
      .slice(0, 8)
      .map(function (x) { return x.p; });
  }

  function snippet(p, q) {
    var text = p.text || "";
    var i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return "";
    var s = Math.max(0, i - 40);
    var e = Math.min(text.length, i + q.length + 60);
    var frag = (s > 0 ? "…" : "") + text.slice(s, e) + (e < text.length ? "…" : "");
    // highlight the query
    var re = new RegExp("(" + q.replace(/[.*+?^\${}()|[\]\\]/g, "\\$&") + ")", "ig");
    return esc(frag).replace(re, "<mark>$1</mark>");
  }

  function render(q) {
    if (!q.trim()) { hide(); return; }
    var refs = lunrResults(q);
    var pages = refs.length
      ? refs.map(function (r) {
          return data.pages.find(function (p) { return p.slug === r; });
        }).filter(Boolean)
      : substrResults(q);
    if (!pages.length) {
      results.innerHTML = '<div class="sr-empty">No matches for “' + esc(q) + '”.</div>';
      show();
      return;
    }
    results.innerHTML = pages.slice(0, 8).map(function (p) {
      var snip = snippet(p, q);
      return (
        '<a class="sr-item" href="' + base + p.slug + '.html">' +
        '<div class="sr-title">' + esc(p.title) + "</div>" +
        '<div class="sr-slug">' + p.slug + ".html</div>" +
        (snip ? '<div class="sr-snip">' + snip + "</div>" : "") +
        "</a>"
      );
    }).join("");
    show();
  }

  input.addEventListener("input", function () { render(input.value); });
  input.addEventListener("focus", function () { if (input.value) render(input.value); });

  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== input &&
        !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
      e.preventDefault();
      input.focus();
    }
    if (e.key === "Escape" && document.activeElement === input) {
      input.value = "";
      hide();
      input.blur();
    }
  });

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".search")) hide();
  });
})();
