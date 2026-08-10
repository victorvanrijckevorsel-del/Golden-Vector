// Accessible modal navigation drawer for the workspace shell (mobile widths).
// Progressive enhancement (GV-RD-CX-001): the page-shell bootstrap adds the
// "js" class that responsive.css keys on; without JavaScript the sidebar stays
// in normal flow and this script never needs to run. While open, the drawer is
// a modal dialog (GV-RD-CX-005): dialog semantics, inert background, a visible
// close control, focus containment, and focus restoration on close.
// Presentation-only: no routing, storage, fetch, or analytics.
(function () {
  // Table regions keep a keyboard tab stop only while they actually overflow
  // (GV-RD-P34-1): the server-rendered tabindex="0" is the no-JS-safe default;
  // with JS running, redundant stops are removed and restored on layout change.
  function syncRegionFocusability() {
    if (!document.querySelectorAll) return;
    var regions = document.querySelectorAll(".table-region");
    for (var i = 0; i < regions.length; i += 1) {
      var region = regions[i];
      if (region.scrollWidth > region.clientWidth) {
        region.setAttribute("tabindex", "0");
      } else {
        region.removeAttribute("tabindex");
      }
    }
  }

  function init() {
    syncRegionFocusability();
    if (window.addEventListener) {
      window.addEventListener("resize", syncRegionFocusability);
    }
    var toggle = document.querySelector(".nav-toggle");
    var frame = document.querySelector(".app-frame");
    var sidebar = document.getElementById("app-sidebar");
    var backdrop = document.querySelector(".nav-backdrop");
    if (!toggle || !frame || !sidebar || !backdrop) return;
    var closeButton = sidebar.querySelector(".nav-close");

    // Page regions removed from the tab order and assistive tech while the
    // modal drawer is open (the backdrop stays clickable to close).
    var inertTargets = [];
    var content = document.querySelector(".app-content");
    var skipLink = document.querySelector(".skip-link");
    if (content) inertTargets.push(content);
    if (skipLink) inertTargets.push(skipLink);

    function isOpen() {
      return frame.hasAttribute("data-nav-open");
    }

    function open() {
      frame.setAttribute("data-nav-open", "");
      backdrop.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      sidebar.setAttribute("role", "dialog");
      sidebar.setAttribute("aria-modal", "true");
      sidebar.setAttribute("aria-label", "Navigation");
      for (var i = 0; i < inertTargets.length; i += 1) {
        inertTargets[i].setAttribute("inert", "");
      }
      var first = closeButton || sidebar.querySelector("a");
      if (first && first.focus) first.focus();
    }

    function close(returnFocus) {
      frame.removeAttribute("data-nav-open");
      backdrop.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      sidebar.removeAttribute("role");
      sidebar.removeAttribute("aria-modal");
      sidebar.removeAttribute("aria-label");
      for (var i = 0; i < inertTargets.length; i += 1) {
        inertTargets[i].removeAttribute("inert");
      }
      if (returnFocus !== false && toggle.focus) toggle.focus();
    }

    toggle.addEventListener("click", function () {
      if (isOpen()) {
        close();
      } else {
        open();
      }
    });
    if (closeButton) {
      closeButton.addEventListener("click", function () {
        close();
      });
    }
    backdrop.addEventListener("click", function () {
      close();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) close();
    });
    sidebar.addEventListener("click", function (event) {
      var target = event.target;
      var link = target && target.closest ? target.closest("a") : null;
      if (link) close(false); // navigating away; do not steal focus back
    });
    // Keep Tab cycling inside the open drawer (close control <-> last link).
    sidebar.addEventListener("keydown", function (event) {
      if (event.key !== "Tab" || !isOpen()) return;
      var focusables = sidebar.querySelectorAll("a, button");
      if (!focusables.length) return;
      var first = focusables[0];
      var last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    // Normalise state when the layout crosses into desktop (GV-RD-CX-007) so
    // a drawer opened on a narrow viewport cannot reappear stale later.
    if (window.matchMedia) {
      var desktop = window.matchMedia("(min-width: 64rem)");
      var onBreakpointChange = function (event) {
        if (event.matches && isOpen()) close(false);
      };
      if (desktop.addEventListener) {
        desktop.addEventListener("change", onBreakpointChange);
      } else if (desktop.addListener) {
        desktop.addListener(onBreakpointChange);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
