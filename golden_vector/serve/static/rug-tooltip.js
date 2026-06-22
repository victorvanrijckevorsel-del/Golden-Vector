// Immediate hover tooltip for the universe-rank "rug" ticks on the ticker detail page.
// Each rug tick (<line class="rug-tick" data-rug="TICKER · beta">) is too thin for the native
// SVG <title> tooltip to be discoverable, so this shows a floating label the moment the cursor
// is over a tick (and CSS gives the tick a faint highlight). The <title> stays as a no-JS fallback.
(function () {
  function init() {
    var tip = document.createElement("div");
    tip.className = "rug-tooltip";
    tip.setAttribute("role", "status");
    tip.hidden = true;
    document.body.appendChild(tip);

    function place(x, y) {
      tip.style.left = x + 14 + "px";
      tip.style.top = y + 14 + "px";
    }

    document.addEventListener("mouseover", function (event) {
      var tick = event.target.closest && event.target.closest(".rug-tick");
      if (!tick) return;
      var label = tick.getAttribute("data-rug");
      if (!label) return;
      tip.textContent = label;
      tip.hidden = false;
      place(event.clientX, event.clientY);
    });

    document.addEventListener("mousemove", function (event) {
      if (tip.hidden) return;
      if (event.target.closest && event.target.closest(".rug-tick")) {
        place(event.clientX, event.clientY);
      } else {
        tip.hidden = true;
      }
    });

    document.addEventListener("mouseout", function (event) {
      if (event.target.closest && event.target.closest(".rug-tick")) {
        tip.hidden = true;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
