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

// Click-to-explain panel: clicking a header's .help-icon opens a PERSISTENT panel
// with the plain-English meaning + the formula + a "Read more" expansion. The text
// is computed by the backend and rides in data-help-* attributes — this script only
// reads, builds, and positions it (no analytics, no formula math in JS). The click is
// handled in the CAPTURE phase so it never triggers the header's sort.
(function () {
  "use strict";

  var panel = null;
  var openIcon = null;

  function closestSel(node, sel) {
    return node && node.closest ? node.closest(sel) : null;
  }

  function ensurePanel() {
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "help-panel";
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-label", "Column explanation");
      panel.setAttribute("tabindex", "-1"); // so focus can move in (non-modal dialog semantics)
      document.body.appendChild(panel);
    }
    return panel;
  }

  function closePanel() {
    if (panel) {
      panel.classList.remove("is-visible");
    }
    if (openIcon) {
      openIcon.setAttribute("aria-expanded", "false");
      openIcon = null;
    }
  }

  function build(icon) {
    var box = ensurePanel();
    box.textContent = "";

    var title = document.createElement("div");
    title.className = "help-panel-title";
    title.textContent = icon.getAttribute("data-help-title") || "";
    box.appendChild(title);

    var meaning = document.createElement("p");
    meaning.className = "help-panel-meaning";
    meaning.textContent = icon.getAttribute("data-help-meaning") || "";
    box.appendChild(meaning);

    var formula = icon.getAttribute("data-help-formula");
    if (formula) {
      var fwrap = document.createElement("div");
      fwrap.className = "help-panel-formula";
      var flabel = document.createElement("span");
      flabel.className = "help-panel-formula-label";
      flabel.textContent = "Formula";
      var fcode = document.createElement("code");
      fcode.textContent = formula;
      fwrap.appendChild(flabel);
      fwrap.appendChild(fcode);
      box.appendChild(fwrap);
    }

    var more = icon.getAttribute("data-help-more");
    if (more) {
      var moreBox = document.createElement("div");
      moreBox.className = "help-panel-more";
      moreBox.textContent = more;
      moreBox.hidden = true;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "help-readmore";
      btn.textContent = "Read more";
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var showing = !moreBox.hidden;
        moreBox.hidden = showing;
        btn.textContent = showing ? "Read more" : "Show less";
      });
      box.appendChild(btn);
      box.appendChild(moreBox);
    }
    return box;
  }

  function place(box, icon) {
    box.classList.add("is-visible"); // make measurable
    var rect = icon.getBoundingClientRect();
    var margin = 8;
    var left = rect.left;
    var width = box.offsetWidth;
    if (left + width > window.innerWidth - margin) {
      left = window.innerWidth - width - margin;
    }
    if (left < margin) {
      left = margin;
    }
    var top = rect.bottom + 6;
    var height = box.offsetHeight;
    if (top + height > window.innerHeight - margin && rect.top - height - 6 >= margin) {
      top = rect.top - height - 6; // flip above if it would overflow the bottom
    }
    box.style.top = Math.max(margin, top) + "px";
    box.style.left = left + "px";
  }

  document.addEventListener("click", function (event) {
    var icon = closestSel(event.target, ".help-icon");
    if (icon) {
      event.preventDefault();
      event.stopPropagation(); // do NOT let the header sort fire
      if (openIcon === icon) {
        closePanel();
        return;
      }
      closePanel();
      openIcon = icon;
      icon.setAttribute("aria-expanded", "true");
      place(build(icon), icon);
      if (panel) {
        panel.focus(); // read the explanation immediately for keyboard/SR users; Esc returns focus to the icon
      }
      return;
    }
    if (openIcon && !closestSel(event.target, ".help-panel")) {
      closePanel(); // click anywhere outside the open panel dismisses it
    }
  }, true);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && openIcon) {
      var icon = openIcon;
      closePanel();
      icon.focus();
    }
  });
  window.addEventListener("scroll", function () { if (openIcon) { closePanel(); } }, true);
  window.addEventListener("resize", function () { if (openIcon) { closePanel(); } });
})();
