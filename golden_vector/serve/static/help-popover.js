// Help popover: a single shared box, shown on hover or keyboard focus of any
// .help-term. The explanation text is computed by the backend (from config)
// and rides in the data-help attribute — this script only reads and positions
// it. No analytics, no formula math in JS.
(function () {
  "use strict";

  var pop = null;

  function ensurePop() {
    if (!pop) {
      pop = document.createElement("div");
      pop.className = "help-pop";
      pop.setAttribute("role", "tooltip");
      document.body.appendChild(pop);
    }
    return pop;
  }

  function show(term) {
    var text = term.getAttribute("data-help");
    if (!text) {
      return;
    }
    var box = ensurePop();
    box.textContent = text; // textContent + CSS white-space:pre-line = line breaks
    box.classList.add("is-visible");

    var rect = term.getBoundingClientRect();
    var top = rect.bottom + 6;
    var left = rect.left;
    var width = box.offsetWidth;
    var margin = 8;
    if (left + width > window.innerWidth - margin) {
      left = window.innerWidth - width - margin;
    }
    if (left < margin) {
      left = margin;
    }
    // If it would fall below the viewport, flip above the term.
    var height = box.offsetHeight;
    if (top + height > window.innerHeight - margin) {
      top = rect.top - height - 6;
    }
    box.style.top = Math.max(margin, top) + "px";
    box.style.left = left + "px";
  }

  function hide() {
    if (pop) {
      pop.classList.remove("is-visible");
    }
  }

  function closest(node) {
    if (!node || !node.closest) {
      return null;
    }
    return node.closest(".help-term");
  }

  document.addEventListener("mouseover", function (event) {
    var term = closest(event.target);
    if (term) {
      show(term);
    }
  });
  document.addEventListener("mouseout", function (event) {
    if (closest(event.target)) {
      hide();
    }
  });
  document.addEventListener("focusin", function (event) {
    var term = closest(event.target);
    if (term) {
      show(term);
    }
  });
  document.addEventListener("focusout", hide);
  // Re-anchoring on scroll/resize is more code than it's worth; just hide.
  window.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      hide();
    }
  });
})();
