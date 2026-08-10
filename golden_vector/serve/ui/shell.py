"""Application shell: grouped navigation, frame, and asset includes."""

from __future__ import annotations

from html import escape


# Grouped navigation (redesign plan section 8.1). Nav ids, hrefs, and labels are
# a preserved contract — only the grouping is presentational.
_NAV_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("Discover", (("candidate_finder", "/", "Candidate Finder"),)),
    (
        "Analyse",
        (
            ("tool_a", "/tool-a", "Gold Sensitivity"),
            ("tool_b", "/tool-b", "Corporate Finance"),
            ("tool_c", "/tool-c", "Gold Downside"),
            ("tool_d", "/tool-d", "Corporate Resilience"),
            ("option_trading", "/option-trading", "Option Trading"),
        ),
    ),
    ("Manage", (("portfolio", "/portfolio", "Portfolio"),)),
    (
        "Research",
        (
            ("lab", "/lab", "Lab"),
            ("scorecard", "/scorecard", "Scorecard"),
        ),
    ),
)

# Flat view preserved for callers/tests that consume the historical structure.
_NAV_LINKS: tuple[tuple[str, str, str], ...] = tuple(
    link for _group_label, links in _NAV_GROUPS for link in links
)

_PAGE_LABELS = {nav_id: label for nav_id, _href, label in _NAV_LINKS}


def _render_nav(active: str) -> str:
    groups: list[str] = []
    for group_label, links in _NAV_GROUPS:
        items: list[str] = []
        for nav_id, href, label in links:
            current = " aria-current=\"page\"" if nav_id == active else ""
            items.append(
                f"<a class=\"nav-link\"{current} href=\"{escape(href)}\">{escape(label)}</a>"
            )
        groups.append(
            "<div class=\"nav-group\">"
            f"<p class=\"nav-group-label\">{escape(group_label)}</p>"
            f"{''.join(items)}"
            "</div>"
        )
    return (
        "<nav class=\"app-nav\" id=\"app-nav\" aria-label=\"Primary\">"
        + "".join(groups)
        + "</nav>"
    )


def _page_shell(title: str, body: str, *, active_nav: str = "") -> str:
    """Semantic application shell: skip link, sidebar navigation, header, main.

    ``active_nav`` selects the ``aria-current`` navigation entry and the header
    page label; an empty value (error pages) renders the full navigation with
    no current item — a documented intentional state (plan section 15.11).
    The signature is a preserved compatibility contract.

    The ``dark`` root class activates the vendored DataTables dark theme
    (GV-RD-CX-004). The inline bootstrap adds the ``js`` class that
    responsive.css keys its drawer rules on, so without JavaScript the sidebar
    stays in normal flow and navigation remains reachable (GV-RD-CX-001).
    """
    page_label = _PAGE_LABELS.get(active_nav, "Golden Vector")
    page_attr = escape(active_nav or "error")
    return f"""<!doctype html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script>document.documentElement.classList.add("js");</script>
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="/static/vendor/datatables/datatables-2.1.8.min.css">
  <script src="/static/vendor/datatables/jquery-3.7.1.min.js" defer></script>
  <script src="/static/vendor/datatables/datatables-2.1.8.min.js" defer></script>
  <script src="/static/workspace-tables.js" defer></script>
  <script src="/static/workspace-shell.js" defer></script>
  <script src="/static/help-popover.js" defer></script>
  <script src="/static/rug-tooltip.js" defer></script>
  <script src="/static/overlay-crosshair.js" defer></script>
  <link rel="stylesheet" href="/static/workspace.css">
</head>
<body data-page="{page_attr}">
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <div class="app-frame">
    <aside class="app-sidebar" id="app-sidebar">
      <button class="nav-close" type="button">Close menu</button>
      <div class="app-brand">
        <span class="app-wordmark">Golden Vector</span>
        <span class="app-descriptor">Gold-equities research</span>
      </div>
      {_render_nav(active_nav)}
    </aside>
    <div class="nav-backdrop" hidden></div>
    <div class="app-content">
      <header class="app-header">
        <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="app-sidebar">Menu</button>
        <span class="app-header-title">{escape(page_label)}</span>
      </header>
      <main id="main-content" tabindex="-1">{body}</main>
    </div>
  </div>
</body>
</html>"""
