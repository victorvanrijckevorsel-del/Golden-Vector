// Hover crosshair for the rebased "Gold vs Stock vs Gold-Miner ETFs" overlay chart.
// On mousemove over the chart, snap to the nearest date, draw a vertical line, place a dot on
// each line, and show a tooltip listing every series' value + % change at that date. Reads the
// pre-computed points embedded in the SVG's data-overlay attribute (no business math in JS):
// each byDate entry is [y-px, value, pct-label], the pct already formatted server-side by the
// SAME formatter as the y-axis gridlines, so the browser never recomputes a percentage.
(function () {
  var NS = "http://www.w3.org/2000/svg";

  // HTML-escape any data string before it enters an innerHTML sink (the series labels are
  // tickers — data, not trusted markup). Mirrors the textContent safety the sibling tooltips use.
  function esc(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Ticks arrive sorted by x from the server, so the nearest one is found by
  // bisection instead of a full scan on every pointermove.
  function nearestTick(ticks, sx) {
    var lo = 0;
    var hi = ticks.length - 1;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (ticks[mid][1] < sx) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0 && Math.abs(ticks[lo - 1][1] - sx) <= Math.abs(ticks[lo][1] - sx)) {
      return ticks[lo - 1];
    }
    return ticks[lo];
  }

  function hiddenSeries(svg) {
    var raw = svg.getAttribute("data-hidden-series") || "";
    var hidden = {};
    raw.split(",").forEach(function (key) {
      if (key) hidden[key] = true;
    });
    return { raw: raw, keys: hidden };
  }

  function setupChart(svg, tip, state) {
    var data;
    try {
      data = JSON.parse(svg.getAttribute("data-overlay"));
    } catch (e) {
      return;
    }
    if (!data || !data.ticks || !data.ticks.length || !data.series) return;

    var layer = document.createElementNS(NS, "g");
    layer.setAttribute("class", "overlay-cursor");
    svg.appendChild(layer);

    var vline = document.createElementNS(NS, "line");
    vline.setAttribute("class", "overlay-cursor-line");
    vline.setAttribute("stroke-width", "1");
    vline.setAttribute("stroke-dasharray", "3 2");
    vline.setAttribute("y1", data.top);
    vline.setAttribute("y2", data.bottom);
    layer.appendChild(vline);

    var dots = data.series.map(function (s) {
      var c = document.createElementNS(NS, "circle");
      c.setAttribute("r", "3.5");
      // Semantic series key from the server; paint lives in css/charts.css.
      c.setAttribute("class", "series-" + s.series);
      layer.appendChild(c);
      return c;
    });

    // Per-chart, not shared: two charts can sit on the same snapped date, and a
    // single shared value only stayed correct via the lastChart tiebreak below.
    var lastDate = null;
    var lastVisibility = null;

    function hide() {
      layer.style.display = "none";
      tip.hidden = true;
      lastDate = null;
      lastVisibility = null;
    }
    hide();
    state.hiders.push(hide);

    function position(event) {
      // Place near the cursor, then clamp so the (white-space:nowrap) box stays on screen.
      var pad = 14;
      var rect = tip.getBoundingClientRect();
      var left = event.clientX + pad;
      var top = event.clientY + pad;
      if (left + rect.width > window.innerWidth) left = event.clientX - pad - rect.width;
      if (top + rect.height > window.innerHeight) top = event.clientY - pad - rect.height;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = Math.max(0, top) + "px";
    }

    svg.addEventListener("pointermove", function (event) {
      var box = svg.getBoundingClientRect();
      if (!box.width) return;
      var vb = svg.viewBox.baseVal;
      var sx = ((event.clientX - box.left) / box.width) * vb.width;

      var nearest = nearestTick(data.ticks, sx);
      var date = nearest[0];
      var xpx = nearest[1];
      var visibility = hiddenSeries(svg);

      layer.style.display = "";
      // The snapped date hasn't changed since the last pixel: only reposition, skip the rebuild
      // (and the innerHTML write) to avoid needless DOM churn while gliding within one column.
      if (
        date === lastDate &&
        visibility.raw === lastVisibility &&
        tip.lastChart === svg
      ) {
        position(event);
        return;
      }
      lastDate = date;
      lastVisibility = visibility.raw;
      tip.lastChart = svg;

      vline.setAttribute("x1", xpx);
      vline.setAttribute("x2", xpx);

      var rows = "<strong>" + esc(date) + "</strong>";
      data.series.forEach(function (s, idx) {
        if (visibility.keys[s.series]) {
          dots[idx].style.display = "none";
          return;
        }
        var pt = s.byDate[date];
        if (pt) {
          dots[idx].style.display = "";
          dots[idx].setAttribute("cx", xpx);
          dots[idx].setAttribute("cy", pt[0]);
          // labelOnly modes (price, count) pre-format the whole value server-side
          // ("USD 51.00"); repeating the raw number in front of it would read as
          // two values. Indexed keeps "level (percent)" — level + change are
          // genuinely two different numbers there.
          rows +=
            "<br><span class=\"legend-swatch-" + esc(s.series) + "\">■</span> " +
            esc(s.label) + ": " +
            (data.labelOnly ? esc(pt[2]) : pt[1].toFixed(1) + " (" + esc(pt[2]) + ")");
        } else {
          dots[idx].style.display = "none";
        }
      });

      tip.innerHTML = rows;
      tip.hidden = false;
      position(event);
    });

    svg.addEventListener("pointerleave", hide);
  }

  function init() {
    var charts = document.querySelectorAll("svg.overlay-chart");
    if (!charts.length) return;
    var tip = document.createElement("div");
    tip.className = "overlay-tooltip";
    tip.setAttribute("role", "status");
    tip.hidden = true;
    document.body.appendChild(tip);

    // Shared dismissal: clear the tooltip if the pointer leaves the document, the tab is
    // backgrounded, or the page scrolls — events the per-SVG mouseleave can miss.
    var state = { hiders: [] };
    function hideAll() {
      state.hiders.forEach(function (h) {
        h();
      });
    }
    document.addEventListener("pointerleave", hideAll);
    window.addEventListener("blur", hideAll);
    window.addEventListener("scroll", hideAll, true);

    charts.forEach(function (svg) {
      setupChart(svg, tip, state);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
