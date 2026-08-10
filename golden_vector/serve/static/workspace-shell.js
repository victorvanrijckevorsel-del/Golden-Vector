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

  // Coalesce bursty layout events (resize/toggle) into one measurement per frame
  // so a drag-resize does not force a layout read per pixel.
  var syncQueued = false;
  function queueRegionSync() {
    if (typeof window.requestAnimationFrame !== "function") {
      syncRegionFocusability();
      return;
    }
    if (syncQueued) return;
    syncQueued = true;
    window.requestAnimationFrame(function () {
      syncQueued = false;
      syncRegionFocusability();
    });
  }

  function init() {
    syncRegionFocusability();
    if (window.addEventListener) {
      window.addEventListener("resize", queueRegionSync);
    }
    // A .table-region inside a closed <details> measures 0 and would keep a
    // stale tab stop forever; <details> "toggle" does not bubble, so listen in
    // the capture phase (GV-RD-P34-1).
    document.addEventListener("toggle", queueRegionSync, true);
    var toggle = document.querySelector(".nav-toggle");
    var frame = document.querySelector(".app-frame");
    var sidebar = document.getElementById("app-sidebar");
    var backdrop = document.querySelector(".nav-backdrop");
    if (!toggle || !frame || !sidebar || !backdrop) return;
    var closeButton = sidebar.querySelector(".nav-close");

    // Page regions removed from the tab order and assistive tech while the
    // modal drawer is open (the backdrop stays clickable to close). Only the
    // main region is inerted: the header lives inside .app-content, so inerting
    // that would also disable this drawer's own .nav-toggle (it could not close
    // the drawer and its aria-expanded="true" would be hidden from AT).
    var inertTargets = [];
    var main = document.getElementById("main-content");
    var skipLink = document.querySelector(".skip-link");
    if (main) inertTargets.push(main);
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
      if (returnFocus !== false && toggle.focus) {
        toggle.focus();
        return;
      }
      // No-restore close (link navigation, desktop breakpoint): focus must not
      // stay on a now-hidden sidebar element. #main-content has tabindex="-1".
      if (
        sidebar.contains &&
        document.activeElement &&
        sidebar.contains(document.activeElement) &&
        main &&
        main.focus
      ) {
        main.focus();
      }
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
      // Computed per keydown so it reflects the live DOM. Filtered to elements
      // that can actually take focus: disabled controls and hidden ones
      // (offsetParent === null) would otherwise become dead ends in the cycle.
      var candidates = sidebar.querySelectorAll(
        "a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex=\"-1\"])"
      );
      var focusables = [];
      for (var i = 0; i < candidates.length; i += 1) {
        var node = candidates[i];
        if (node.disabled) continue;
        if ("offsetParent" in node && node.offsetParent === null) continue;
        focusables.push(node);
      }
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
