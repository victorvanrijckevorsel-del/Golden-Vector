"""Production visitor application: one gate around all research routes.

The entry point binds only to loopback behind HTTPS termination. Invitations do
not assert independently verified mailbox ownership: the owner supplies a code
to the intended email holder. No emails are sent by this application.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
import logging
import os
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import parse_qs, urlsplit

from golden_vector.access.store import AccessStore, RateLimited, SESSION_SECONDS
from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.serve.access_context import visitor_session
from golden_vector.serve.access_page import access_message, login_page
from golden_vector.serve.http_helpers import _no_content_response, _serve_static_file
from golden_vector.serve.visitor_policy import visitor_path_allowed
from golden_vector.serve.ui.shell import visitor_account

LOGGER = logging.getLogger(__name__)
MAX_FORM_BYTES = 4096
@dataclass(frozen=True)
class HostedSettings:
    public_origin: str

    def __post_init__(self):
        url = urlsplit(self.public_origin)
        if (url.path or url.query or url.fragment or url.username or url.password
                or not url.hostname or url.netloc != url.netloc.lower()):
            raise ValueError("Public origin must be an origin only, such as https://golden-vector.example.org")
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if url.scheme != "https" and not (local and url.scheme == "http"):
            raise ValueError("The visitor website requires HTTPS (HTTP is allowed only for local testing).")
        url.port  # Validate malformed/out-of-range ports on startup.

    @property
    def secure(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def cookie_name(self) -> str:
        return "__Host-gv_session" if self.secure else "gv_local_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-gv_login" if self.secure else "gv_local_login"


def _cookie(name: str, value: str, *, secure: bool, max_age: int) -> str:
    result = SimpleCookie()
    result[name] = value
    result[name]["path"] = "/"
    result[name]["httponly"] = True
    result[name]["samesite"] = "Strict"
    result[name]["max-age"] = max_age
    if secure:
        result[name]["secure"] = True
    return result.output(header="").strip()


def _cookies(environ) -> SimpleCookie:
    result = SimpleCookie()
    try:
        result.load(str(environ.get("HTTP_COOKIE", ""))[:8192])
    except CookieError:
        return SimpleCookie()
    return result


def _cookie_value(cookies, name):
    item = cookies.get(name)
    return item.value if item is not None else ""


def _same_token(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _response(start_response, body: str, *, status="200 OK", headers=()):
    payload = body.encode("utf-8")
    start_response(status, [("Content-Type", "text/html; charset=utf-8"),
                            ("Content-Length", str(len(payload))), *headers])
    return [payload]


def _form(environ):
    if str(environ.get("CONTENT_TYPE", "")).split(";", 1)[0] != "application/x-www-form-urlencoded":
        raise ValueError("Unsupported form encoding.")
    length = int(environ.get("CONTENT_LENGTH") or 0)
    if not 0 < length <= MAX_FORM_BYTES:
        raise ValueError("Invalid form size.")
    payload = environ["wsgi.input"].read(length)
    if len(payload) != length:
        raise ValueError("Incomplete form.")
    fields = parse_qs(payload.decode("utf-8"), keep_blank_values=True, max_num_fields=8)
    if any(len(values) != 1 for values in fields.values()):
        raise ValueError("Duplicate form fields.")
    return {name: values[0] for name, values in fields.items()}


class AccessGate:
    def __init__(self, application, store: AccessStore, settings: HostedSettings):
        store.check()
        self.application, self.store, self.settings = application, store, settings

    def __call__(self, environ, start_response):
        settings = self.settings

        def secured_start(status, headers, exc_info=None):
            if not str(environ.get("PATH_INFO", "")).startswith("/static/"):
                headers = [(k, v) for k, v in headers if k.lower() != "cache-control"]
                headers.append(("Cache-Control", "no-store"))
            headers.extend([
                ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                # no-referrer makes browsers send Origin:null on normal form
                # POSTs, breaking our exact-origin CSRF check. same-origin
                # retains that signal without leaking referrers externally.
                ("Referrer-Policy", "same-origin"), ("X-Robots-Tag", "noindex, nofollow"),
                ("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                 "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                 "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
            ])
            if settings.secure:
                headers.append(("Strict-Transport-Security", "max-age=31536000"))
            if exc_info is not None:
                return start_response(status, headers, exc_info)
            return start_response(status, headers)

        try:
            return self._dispatch(environ, secured_start)
        except (sqlite3.Error, OSError):
            LOGGER.exception("Website access storage unavailable")
            return _response(secured_start, access_message("Temporarily unavailable", "Please try again shortly."),
                             status="503 Service Unavailable")

    def _dispatch(self, environ, respond):
        settings = self.settings
        host = str(environ.get("HTTP_HOST", ""))
        # No forwarded headers are trusted here. The production server accepts
        # traffic only from the local reverse proxy; Host is preserved there.
        if host.lower() != urlsplit(settings.public_origin).netloc:
            return _response(respond, "Invalid host.", status="400 Bad Request")
        if settings.secure and environ.get("wsgi.url_scheme") != "https":
            return _response(respond, "HTTPS is required.", status="400 Bad Request")
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if method == "GET" and path == "/healthz":
            self.store.check()
            return _response(respond, "ok")
        if method == "GET" and path.startswith("/static/"):
            return _serve_static_file(path, respond)
        if method == "GET" and path == "/favicon.ico":
            # Browsers fetch this independently. Redirecting it to /login
            # would replace the CSRF cookie after the form has been rendered.
            return _no_content_response(respond)
        if path == "/login":
            return self._login(environ, respond, method)
        cookies = _cookies(environ)
        token = _cookie_value(cookies, settings.cookie_name)
        session = self.store.session(token)
        if session is None:
            if path.startswith("/api/") or method != "GET":
                return _response(respond, "Sign in to continue.", status="401 Unauthorized")
            return _response(respond, "", status="303 See Other", headers=[("Location", "/login")])
        if path == "/logout" and method == "POST":
            fields = self._checked_form(environ)
            if fields is None:
                return _response(respond, "Invalid form.", status="403 Forbidden")
            if not _same_token(fields.get("csrf", ""), session.csrf):
                return _response(respond, "Invalid form.", status="403 Forbidden")
            self.store.logout(token)
            return _response(respond, "", status="303 See Other", headers=[
                ("Location", "/login"), ("Set-Cookie", _cookie(settings.cookie_name, "", secure=settings.secure, max_age=0)),
            ])
        if method != "GET" or not visitor_path_allowed(path):
            return _response(respond, access_message("Page unavailable", "This page is not available with guest access."),
                             status="403 Forbidden")
        context = visitor_session.set(session)
        display_context = visitor_account.set((session.email, session.csrf))
        try:
            # Materialize while the request context is active, including any
            # generator-based renderer. Never leave it attached to a worker.
            captured = {}

            def capture(status, headers, exc_info=None):
                captured.update(status=status, headers=headers)

            output = self.application(environ, capture)
            try:
                body = list(output)
            finally:
                if hasattr(output, "close"):
                    output.close()
            if int(captured["status"].split()[0]) >= 500:
                # Internal reader exceptions can include local paths or data
                # rows. The visitor receives only a calm generic error.
                return _response(respond, access_message("Research temporarily unavailable", "Please try again later."),
                                 status="503 Service Unavailable")
            respond(captured["status"], captured["headers"])
            return body
        finally:
            visitor_account.reset(display_context)
            visitor_session.reset(context)

    def _checked_form(self, environ):
        origin = str(environ.get("HTTP_ORIGIN", ""))
        if origin != self.settings.public_origin:
            return None
        try:
            return _form(environ)
        except (ValueError, UnicodeError, KeyError):
            return None

    def _login(self, environ, respond, method):
        settings = self.settings
        if method not in {"GET", "POST"}:
            return _response(respond, "Method not allowed.", status="405 Method Not Allowed", headers=[("Allow", "GET, POST")])
        error, email, status = "", "", "200 OK"
        if method == "POST":
            fields = self._checked_form(environ)
            csrf_cookie = _cookie_value(_cookies(environ), settings.csrf_cookie_name)
            if (fields is None or not csrf_cookie or len(csrf_cookie) > 128
                    or not _same_token(fields.get("csrf", ""), csrf_cookie)):
                error, status = "Please reload this page and try again.", "403 Forbidden"
            else:
                email = fields.get("email", "")[:254]
                try:
                    token = self.store.login(email, fields.get("code", ""), str(environ.get("REMOTE_ADDR", "unknown")))
                except RateLimited as exc:
                    token, error, status = None, str(exc), "429 Too Many Requests"
                if token:
                    old_token = _cookie_value(_cookies(environ), settings.cookie_name)
                    if old_token:
                        self.store.logout(old_token)
                    return _response(respond, "", status="303 See Other", headers=[
                        ("Location", "/"),
                        ("Set-Cookie", _cookie(settings.cookie_name, token, secure=settings.secure, max_age=SESSION_SECONDS)),
                        ("Set-Cookie", _cookie(settings.csrf_cookie_name, "", secure=settings.secure, max_age=0)),
                    ])
                if not error:
                    error, status = "Email or access code not recognised, expired, or revoked.", "401 Unauthorized"
        csrf = secrets.token_urlsafe(32)
        headers = [("Set-Cookie", _cookie(settings.csrf_cookie_name, csrf, secure=settings.secure, max_age=900))]
        if status.startswith("429"):
            headers.append(("Retry-After", "900"))
        return _response(respond, login_page(csrf=csrf, email=email, error=error), status=status, headers=headers)


def create_hosted_app(paths: ProjectPaths | None = None, *, public_origin: str | None = None,
                      database: Path | None = None):
    from golden_vector.serve.workspace import create_workspace_app

    paths = paths or ProjectPaths.discover()
    origin = public_origin or os.environ.get("GV_PUBLIC_ORIGIN", "")
    if not origin:
        raise ValueError("Set GV_PUBLIC_ORIGIN to the HTTPS website address before starting.")
    settings = HostedSettings(origin)
    config = load_app_config(paths).app
    # A config override can never make holdings visible in this entry point.
    config = config.model_copy(update={"portfolio": config.portfolio.model_copy(update={"enabled": False})})
    tickers = sorted(item.ticker for item in config.universe.tickers if item.active and item.tool_b_enabled)
    app = create_workspace_app(paths, app_config=config, tool_b_tickers=tickers, read_only=True)
    store = AccessStore(database or paths.data_dir / "access" / "access.sqlite3")
    return AccessGate(app, store, settings)


def main():
    from waitress import serve

    application = create_hosted_app()
    if not application.settings.secure:
        raise ValueError("Production entry point requires an HTTPS public origin.")
    serve(application, host="127.0.0.1", port=8080, threads=4,
          trusted_proxy="127.0.0.1", trusted_proxy_count=1,
          trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
          clear_untrusted_proxy_headers=True,
          max_request_body_size=MAX_FORM_BYTES, channel_timeout=30,
          expose_tracebacks=False)


if __name__ == "__main__":
    main()
