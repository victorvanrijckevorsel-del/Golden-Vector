"""Shared URL/query-string builder for serve pages — ONE copy.

Both the horizon window switcher (``window=``) and the fundamentals source mode
(``fundamentals_source=``) need to add/replace a single query parameter while preserving
every other existing one (search, sort, ticker filter, gold-price override, lens/anchor, …).
Centralised here so neither feature hand-rolls its own query-string logic and they never
drop each other's params. Ratified in ``reviews/codex/AGENT_SYNC.md``.

Returns a raw URL; callers ``escape()`` it when embedding in an HTML attribute.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode


def build_page_url(
    path: str,
    current: Mapping[str, str],
    *,
    set_params: Mapping[str, str | None],
) -> str:
    """Return ``path`` + a query string = ``current`` with ``set_params`` applied.

    - A ``set_params`` value of ``None`` deletes that key.
    - Every other key in ``current`` is preserved, in its original order.
    - ``set_params`` values must be strings (or ``None``); callers stringify non-strings.
    - With no resulting params, just ``path`` is returned (no trailing ``?``).
    """
    merged: dict[str, str] = {
        str(key): str(value) for key, value in current.items() if value is not None
    }
    for key, value in set_params.items():
        if value is None:
            merged.pop(str(key), None)
        else:
            merged[str(key)] = str(value)
    if not merged:
        return path
    return f"{path}?{urlencode(merged)}"
