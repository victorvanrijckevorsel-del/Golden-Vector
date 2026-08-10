// Accessible navigation drawer for the workspace shell (mobile widths).
// Presentation-only: toggles the drawer state, manages focus, and closes on
// Escape / backdrop / navigation. No routing, storage, fetch, or analytics.
(function () {
  function init() {
    var toggle = document.querySelector(".nav-toggle");
    var frame = document.querySelector(".app-frame");
    var sidebar = document.getElementById("app-sidebar");
    var backdrop = document.querySelector(".nav-backdrop");
    if (!toggle || !frame || !sidebar || !backdrop) return;

    function isOpen() {
      return frame.hasAttribute("data-nav-open");
    }

    function open() {
      frame.setAttribute("data-nav-open", "");
      backdrop.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      var first = sidebar.querySelector("a");
      if (first && first.focus) first.focus();
    }

    function close(returnFocus) {
      frame.removeAttribute("data-nav-open");
      backdrop.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      if (returnFocus !== false && toggle.focus) toggle.focus();
    }

    toggle.addEventListener("click", function () {
      if (isOpen()) {
        close();
      } else {
        open();
      }
    });
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
    // Keep Tab cycling inside the open drawer (first <-> last link).
    sidebar.addEventListener("keydown", function (event) {
      if (event.key !== "Tab" || !isOpen()) return;
      var links = sidebar.querySelectorAll("a");
      if (!links.length) return;
      var first = links[0];
      var last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
