/* Progressive series visibility for the ticker Performance comparison.
 *
 * The server always renders every available line and the complete accessible
 * data table. JavaScript only reveals the native checkboxes and hides matching
 * visual SVG/legend nodes. The table is deliberately outside every selector
 * used here and is therefore never filtered.
 */
(function () {
  "use strict";

  var ROOT_SELECTOR = "[data-performance-series]";
  var INPUT_SELECTOR = "[data-performance-series-input]";

  function hiddenKeys(svg) {
    var raw = svg ? svg.getAttribute("data-hidden-series") || "" : "";
    return raw.split(",").filter(Boolean);
  }

  function writeHiddenKeys(svg, keys) {
    if (!svg) return;
    if (keys.length) {
      svg.setAttribute("data-hidden-series", keys.join(","));
    } else {
      svg.removeAttribute("data-hidden-series");
    }
  }

  function syncInput(input) {
    var key = input.getAttribute("data-performance-series-input");
    var chartId = input.getAttribute("aria-controls");
    if (!key || !chartId) return;

    var chart = document.getElementById(chartId);
    if (!chart) return;
    var hidden = !input.checked;
    var selector = ".series-" + key + ", .legend-swatch-" + key;
    var visualNodes = chart.querySelectorAll(selector);
    for (var index = 0; index < visualNodes.length; index += 1) {
      visualNodes[index].style.display = hidden ? "none" : "";
    }

    var svg = chart.querySelector("svg.overlay-chart");
    var keys = hiddenKeys(svg).filter(function (value) { return value !== key; });
    if (hidden) keys.push(key);
    writeHiddenKeys(svg, keys);
  }

  function initialise(root) {
    root.removeAttribute("hidden");
    var inputs = root.querySelectorAll(INPUT_SELECTOR);
    for (var index = 0; index < inputs.length; index += 1) {
      syncInput(inputs[index]);
      inputs[index].addEventListener("change", function (event) {
        syncInput(event.currentTarget);
      });
    }
  }

  function init() {
    var roots = document.querySelectorAll(ROOT_SELECTOR);
    for (var index = 0; index < roots.length; index += 1) initialise(roots[index]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
