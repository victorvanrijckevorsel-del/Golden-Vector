// Immediate hover tooltip for the universe-rank "rug" ticks on the ticker detail page.
// Each rug tick (<line class="rug-tick" data-rug="TICKER · beta">) is too thin for the native
// SVG <title> tooltip to be discoverable, so this shows a floating label the moment the cursor
// is over a tick (and CSS gives the tick a faint highlight). The <title> stays as a no-JS fallback.
(function () {
  function init() {
    // Every page loads this script; only the ticker detail page has rug ticks.
    // Bail before creating the tooltip node and binding four document-level
    // listeners (mirrors overlay-crosshair.js).
    var ticks = document.querySelectorAll(".rug-tick");
    if (!ticks.length) return;

    var tip = document.createElement("div");
    tip.className = "rug-tooltip";
    tip.setAttribute("role", "status");
    tip.hidden = true;
    document.body.appendChild(tip);

    // JS is active, so this floating tooltip replaces the native SVG <title>. Remove the
    // <title> children so browsers don't ALSO show the delayed OS tooltip (double label). The
    // server keeps emitting <title> as the no-JS fallback; we strip it only when JS runs.
    document.querySelectorAll(".rug-tick > title").forEach(function (node) {
      node.remove();
    });

    function place(x, y) {
      // Clamp so the (nowrap) label never clips at the viewport edges.
      var left = x + 14;
      var top = y + 14;
      var rect = tip.getBoundingClientRect();
      if (rect.width && left + rect.width > window.innerWidth - 4) {
        left = Math.max(4, x - 14 - rect.width);
      }
      if (rect.height && top + rect.height > window.innerHeight - 4) {
        top = Math.max(4, y - 14 - rect.height);
      }
      tip.style.left = left + "px";
      tip.style.top = top + "px";
    }

    document.addEventListener("pointerover", function (event) {
      var tick = event.target.closest && event.target.closest(".rug-tick");
      if (!tick) return;
      var label = tick.getAttribute("data-rug");
      if (!label) return;
      tip.textContent = label;
      tip.hidden = false;
      place(event.clientX, event.clientY);
    });

    document.addEventListener("pointermove", function (event) {
      if (tip.hidden) return;
      if (event.target.closest && event.target.closest(".rug-tick")) {
        place(event.clientX, event.clientY);
      } else {
        tip.hidden = true;
      }
    });

    document.addEventListener("pointerout", function (event) {
      if (event.target.closest && event.target.closest(".rug-tick")) {
        tip.hidden = true;
      }
    });

    // Belt-and-braces: clear the label if the pointer leaves the page entirely or the tab is
    // backgrounded while still over a tick (mouseout/mousemove may not fire in those cases).
    document.addEventListener("pointerleave", function () {
      tip.hidden = true;
    });
    window.addEventListener("blur", function () {
      tip.hidden = true;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
