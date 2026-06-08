"""HTTP response, form, and static-file helpers for the workspace UI."""

from __future__ import annotations

import io
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs

from golden_vector.serve.page_shell import _page_shell


_STATIC_ROOT = (Path(__file__).parent / "static").resolve()


_STATIC_ALLOWED_EXTENSIONS: dict[str, str] = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


_IMMUTABLE_STATIC_PREFIXES: tuple[str, ...] = ("vendor/",)


def _flash_message(saved_token: str) -> str | None:
    messages = {
        "company": "Company inputs saved.",
        "reporting": "Reporting calendar saved.",
        "note": "Stock note added.",
        "verification": "Source verification updated.",
        "portfolio": "Portfolio updated.",
    }
    return messages.get(saved_token)


def _render_error_page(message: str, *, detail: str | None = None) -> str:
    detail_html = f"<p class=\"hint\">{escape(detail)}</p>" if detail else ""
    return _page_shell(
        "Golden Vector Workspace Error",
        f"<h1>Workspace Error</h1><div class=\"panel\"><p>{escape(message)}</p>{detail_html}<p><a href=\"/\">Back to workspace</a></p></div>",
        active_nav="candidate_finder",
    )


def _read_form_data(environ: dict[str, Any]) -> dict[str, list[str]]:
    try:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    body = environ.get("wsgi.input", io.BytesIO()).read(content_length)
    return parse_qs(body.decode("utf-8"), keep_blank_values=True)


def _html_response(
    start_response: Callable[..., Any],
    body: str,
    *,
    status: str = "200 OK",
) -> Iterable[bytes]:
    payload = body.encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(payload))),
        ],
    )
    return [payload]


def _redirect_response(start_response: Callable[..., Any], location: str) -> Iterable[bytes]:
    start_response(
        "303 See Other",
        [("Location", location), ("Content-Length", "0")],
    )
    return [b""]


def _no_content_response(start_response: Callable[..., Any]) -> Iterable[bytes]:
    start_response("204 No Content", [("Content-Length", "0")])
    return [b""]


def _download_file_response(
    start_response: Callable[..., Any],
    path: Path,
    *,
    content_type: str,
    download_name: str,
) -> Iterable[bytes]:
    try:
        payload = path.read_bytes()
    except (OSError, ValueError):
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]
    start_response(
        "200 OK",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(payload))),
            ("Content-Disposition", f'attachment; filename="{download_name}"'),
            ("Cache-Control", "no-cache"),
        ],
    )
    return [payload]


def _serve_static_file(
    path: str, start_response: Callable[..., Any]
) -> Iterable[bytes]:
    """Serve a vendored or repo-owned static file under /static/*.

    Rules:
    - Strip the "/static/" prefix, plus any leading slashes/backslashes
      (defence against `/static//../` and `/static/\\foo` on Windows).
    - Resolve the path and require it to live under `_STATIC_ROOT`.
      `Path.resolve()` canonicalizes both POSIX `..` and Windows `..\\`,
      so the ancestor check blocks traversal on either OS.
    - Reject relative segments that look like drive letters (e.g. `C:`)
      which some platforms would otherwise treat as absolute paths.
    - Only serve files whose extension is in the allow-list. Everything
      else returns 404 — no directory listings, no other file types.
    - Any OSError/ValueError turns into a clean 404 rather than a 500.
    """
    prefix = "/static/"
    if not path.startswith(prefix):
        return _static_not_found(start_response)
    relative = path[len(prefix):].lstrip("/\\")
    # Reject drive-letter-looking segments like "c:" or "C:foo" that
    # Path treats as absolute on Windows.
    if len(relative) >= 2 and relative[1] == ":":
        return _static_not_found(start_response)

    try:
        candidate = (_STATIC_ROOT / relative).resolve()
    except (OSError, ValueError):
        return _static_not_found(start_response)

    # Ancestor check: candidate must live under _STATIC_ROOT.
    try:
        resolved_relative = candidate.relative_to(_STATIC_ROOT).as_posix()
    except ValueError:
        return _static_not_found(start_response)

    content_type = _STATIC_ALLOWED_EXTENSIONS.get(candidate.suffix.lower())
    if content_type is None:
        return _static_not_found(start_response)

    try:
        payload = candidate.read_bytes()
    except (OSError, ValueError):
        return _static_not_found(start_response)

    start_response(
        "200 OK",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(payload))),
            # Vendored filenames are version-pinned; repo-owned assets revalidate.
            ("Cache-Control", _static_cache_control(resolved_relative)),
        ],
    )
    return [payload]


def _static_cache_control(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    if normalized.startswith(_IMMUTABLE_STATIC_PREFIXES):
        return "public, max-age=31536000, immutable"
    return "no-cache"


def _static_not_found(start_response: Callable[..., Any]) -> Iterable[bytes]:
    start_response("404 Not Found", [("Content-Length", "0")])
    return [b""]
