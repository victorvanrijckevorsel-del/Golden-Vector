"""Shared fail-closed visitor route policy; new endpoints stay private."""

import re

_RESEARCH_PATHS = frozenset({
    "/", "/tool-a", "/tool-b", "/tool-c", "/tool-d", "/option-trading",
    "/candidate-finder", "/ticker", "/lab", "/scorecard", "/api/data-status", "/favicon.ico",
})
_DETAIL_PATH = re.compile(r"/(?:ticker|lab/dial)/[A-Za-z0-9.^=_-]+")


def visitor_path_allowed(path: str) -> bool:
    return path in _RESEARCH_PATHS or bool(_DETAIL_PATH.fullmatch(path)) or path.startswith("/static/")
