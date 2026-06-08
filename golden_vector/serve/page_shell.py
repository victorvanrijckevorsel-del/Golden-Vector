"""Page shell and top navigation for the local workspace UI."""

from __future__ import annotations

from html import escape


_NAV_LINKS: tuple[tuple[str, str, str], ...] = (
    ("candidate_finder", "/", "Candidate Finder"),
    ("tool_a", "/tool-a", "Gold Sensitivity"),
    ("tool_b", "/tool-b", "Corporate Finance"),
    ("tool_c", "/tool-c", "Gold Downside"),
    ("tool_d", "/tool-d", "Corporate Resilience"),
    ("option_trading", "/option-trading", "Option Trading"),
    ("portfolio", "/portfolio", "Portfolio"),
)


def _render_top_nav(active: str) -> str:
    items = []
    for nav_id, href, label in _NAV_LINKS:
        cls = "nav-tab active" if nav_id == active else "nav-tab"
        items.append(f"<a class=\"{cls}\" href=\"{escape(href)}\">{escape(label)}</a>")
    return f"<nav class=\"top-nav\">{''.join(items)}</nav>"


def _page_shell(title: str, body: str, *, active_nav: str = "") -> str:
    nav_html = _render_top_nav(active_nav) if active_nav else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="/static/vendor/datatables/datatables-2.1.8.min.css">
  <script src="/static/vendor/datatables/jquery-3.7.1.min.js" defer></script>
  <script src="/static/vendor/datatables/datatables-2.1.8.min.js" defer></script>
  <script src="/static/workspace-tables.js" defer></script>
  <link rel="stylesheet" href="/static/workspace.css">
</head>
<body>
  {nav_html}
  <main>{body}</main>
</body>
</html>"""
