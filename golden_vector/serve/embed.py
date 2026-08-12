"""Safe JSON-in-HTML embedding (ticker-page plan §9.5).

ONE helper for every page that hands a backend-resolved payload to a
first-party JS module. Hostile content in a ``<script type="application/json">``
block is a real escape hatch: an unescaped ``</script`` inside a string value
ends the block early and the remainder becomes live markup. Everything below is
escaped at the JSON level, so the emitted body is still valid JSON that
``JSON.parse`` returns unchanged.

Escaped, deliberately:

``<`` / ``>``
    Covers ``</script`` in ANY case (``</ScRiPt``), ``<!--``, and ``<![CDATA[``
    by construction — no case-insensitive pattern to get wrong. In JSON these
    characters can only appear inside string literals, so escaping every
    occurrence is safe.
``&``
    HTML entity references are never expanded inside ``<script>``, but escaping
    ``&`` keeps the body inert if the same text is ever moved into an attribute
    or an XHTML-parsed document.
U+2028 / U+2029
    Line/paragraph separators. Legal in JSON strings, historically illegal raw
    in JS source; escaped so the body survives any embedding context.
"""

from __future__ import annotations

import json
import re

#: Payload ids are code-authored tokens, never data — fail loud on anything else
#: (same rule as ``serve/ui/tables.table_region``).
_PAYLOAD_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_:.-]*")

_JSON_ESCAPES: tuple[tuple[str, str], ...] = (
    ("<", "\\u003c"),
    (">", "\\u003e"),
    ("&", "\\u0026"),
    ("\u2028", "\\u2028"),
    ("\u2029", "\\u2029"),
)


def embed_json_payload(payload_id: str, obj: object) -> str:
    """Return ``obj`` as an inert ``<script type="application/json">`` block.

    ``allow_nan=False`` on purpose: ``NaN``/``Infinity`` are not JSON and
    ``JSON.parse`` rejects them, so a missing value must reach here as ``None``
    (JSON ``null``) rather than silently producing a payload no browser can
    read. Keys are sorted so the same payload always renders byte-identically.
    """

    if not _PAYLOAD_ID_RE.fullmatch(payload_id or ""):
        raise ValueError(f"payload_id must be an id token: {payload_id!r}")
    body = json.dumps(
        obj,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    for raw, escaped in _JSON_ESCAPES:
        body = body.replace(raw, escaped)
    return (
        f'<script type="application/json" id="{payload_id}">{body}</script>'
    )
