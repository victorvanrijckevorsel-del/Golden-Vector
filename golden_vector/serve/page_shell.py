"""Compatibility facade for the application shell (plan section 10.1).

The implementation lives in ``golden_vector.serve.ui.shell``; this module
preserves the historical import path and public names so migration stays
incremental and no caller churns.
"""

from __future__ import annotations

from golden_vector.serve.ui.shell import (
    _NAV_GROUPS,
    _NAV_LINKS,
    _PAGE_LABELS,
    _page_shell,
    _render_nav,
)

__all__ = [
    "_NAV_GROUPS",
    "_NAV_LINKS",
    "_PAGE_LABELS",
    "_page_shell",
    "_render_nav",
]
