from concurrent.futures import ThreadPoolExecutor
import io
import re
import sqlite3

import pytest

from golden_vector.access.store import AccessStore, EMAIL_ATTEMPTS, RateLimited, SESSION_SECONDS
from golden_vector.serve.access_context import visitor_session
from golden_vector.serve.hosted import AccessGate, HostedSettings, create_hosted_app
from golden_vector.serve.ui.shell import _page_shell
from tests.helpers import call_wsgi_app, build_test_paths

ORIGIN = "https://golden-vector.example.org"
EMAIL = "guest@example.org"


@pytest.fixture
def store(tmp_path):
    result = AccessStore(tmp_path / "access.sqlite3")
    result.initialize()
    return result


def _request(app, path="/", *, method="GET", cookies="", data=None, **headers):
    return call_wsgi_app(app, method=method, path=path, data=data, environ_overrides={
        "HTTP_HOST": "golden-vector.example.org", "wsgi.url_scheme": "https",
        "HTTP_ORIGIN": ORIGIN, "HTTP_COOKIE": cookies, "REMOTE_ADDR": "192.0.2.1", **headers,
    })


def _cookie_header(response):
    return "; ".join(value.split(";", 1)[0] for key, value in response["headers_list"] if key == "Set-Cookie")


def _sign_in(app, code, email=EMAIL):
    page = _request(app, "/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page["body"])[1]
    result = _request(app, "/login", method="POST", cookies=_cookie_header(page),
                      data={"email": email, "code": code, "csrf": csrf})
    return result, _cookie_header(result)


def _research(environ, start_response):
    payload = _page_shell("Research", "<h1>Research</h1>").encode()
    start_response("200 OK", [("Content-Type", "text/html"), ("Content-Length", str(len(payload)))])
    return [payload]


def test_codes_are_email_bound_hashed_revocable_and_reissuable(store):
    code = store.issue(" Guest@Example.ORG ", now=100)
    other = store.issue("other@example.org", now=100)
    assert code != other
    assert store.login("other@example.org", code, "a", now=101) is None
    token = store.login(EMAIL, code.lower(), "a", now=101)
    assert store.session(token, now=102).email == EMAIL
    assert code.encode() not in store.path.read_bytes()
    assert token.encode() not in store.path.read_bytes()
    assert "code_hash" not in store.invitations()[0]
    new_store = AccessStore(store.path)
    assert new_store.session(token, now=102).email == EMAIL  # process restart
    new_code = new_store.issue(EMAIL, now=103)
    assert new_store.session(token, now=104) is None
    assert new_store.login(EMAIL, code, "a", now=104) is None
    new_token = new_store.login(EMAIL, new_code, "a", now=104)
    assert new_store.revoke(EMAIL)
    assert new_store.session(new_token, now=105) is None
    assert new_store.login(EMAIL, new_code, "a", now=105) is None
    assert new_store.login("other@example.org", other, "a", now=106)


def test_expiry_applies_to_codes_and_sessions(store):
    code = store.issue(EMAIL, days=1, now=100)
    token = store.login(EMAIL, code, "a", now=101)
    assert store.session(token, now=86499)
    assert store.session(token, now=86500) is None
    assert store.login(EMAIL, code, "a", now=86500) is None
    code = store.issue(EMAIL, days=90, now=100)
    token = store.login(EMAIL, code, "a", now=101)
    assert store.session(token, now=101 + SESSION_SECONDS) is None


def test_rate_limit_persists_and_expires(store):
    code = store.issue(EMAIL, now=100)
    for _ in range(EMAIL_ATTEMPTS):
        assert store.login(EMAIL, "wrong", "a", now=101) is None
    with pytest.raises(RateLimited):
        AccessStore(store.path).login(EMAIL, code, "another-ip", now=102)
    assert store.login(EMAIL, code, "a", now=1001)


def test_missing_or_unknown_schema_database_fails_closed(tmp_path):
    store = AccessStore(tmp_path / "missing.sqlite3")
    with pytest.raises(sqlite3.Error):
        store.check()
    assert not store.path.exists()
    store.initialize()
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError):
        store.check()
    with pytest.raises(ValueError):
        store.initialize()


@pytest.mark.parametrize("origin", ["", "http://public.example.org", "https://example.org/path", "https://a:b@example.org", "https://example.org?x=1"])
def test_invalid_or_insecure_public_origin_rejected(origin):
    with pytest.raises(ValueError):
        HostedSettings(origin)


def test_login_and_research_gate_and_secure_cookies(store):
    code = store.issue(EMAIL)
    app = AccessGate(_research, store, HostedSettings(ORIGIN))
    for path in ["/", "/tool-a", "/ticker/NEM", "/portfolio"]:
        result = _request(app, path)
        assert result["status"].startswith("303")
        assert result["headers"]["Location"] == "/login"
        assert "Research" not in result["body"]
    assert _request(app, "/api/data-status")["status"].startswith("401")
    assert _request(app, "/healthz")["body"] == "ok"
    response, cookie = _sign_in(app, code)
    assert response["status"].startswith("303")
    cookies = [v for k, v in response["headers_list"] if k == "Set-Cookie"]
    assert all("Secure" in value and "HttpOnly" in value and "SameSite=Strict" in value for value in cookies)
    page = _request(app, cookies=cookie)
    assert page["status"].startswith("200")
    assert EMAIL in page["body"] and "Sign out" in page["body"]
    assert 'href="/portfolio"' not in page["body"]
    assert page["headers"]["Cache-Control"] == "no-store"
    assert page["headers"]["X-Frame-Options"] == "DENY"
    assert visitor_session.get() is None
    # The private/local shell stays unchanged after a visitor request.
    assert 'href="/portfolio"' in _page_shell("Local", "Local")
    store.revoke(EMAIL)
    assert _request(app, cookies=cookie)["status"].startswith("303")


@pytest.mark.parametrize("method,path", [
    ("POST", "/refresh"), ("POST", "/option-trading/refresh"),
    ("GET", "/portfolio"), ("GET", "/portfolio/reconciliation.csv"),
    ("GET", "/hedge-readiness/latest.md"), ("GET", "/data/manual/portfolio/manual_lots.json"),
    ("POST", "/portfolio/lots/abc/delete"), ("POST", "/ticker/NEM/company"),
    ("POST", "/ticker/NEM/note"), ("GET", "/ticker/NEM/company"),
    ("PUT", "/"), ("DELETE", "/"), ("GET", "/future-admin-page"),
])
def test_visitor_cannot_reach_private_or_write_routes(store, method, path):
    def forbidden_app(*args):
        pytest.fail("The protected application must not receive this request")
    app = AccessGate(forbidden_app, store, HostedSettings(ORIGIN))
    _, cookie = _sign_in(app, store.issue(EMAIL))
    assert _request(app, path, method=method, cookies=cookie)["status"].startswith("403")


def test_csrf_host_forwarded_header_and_form_limits(store):
    app = AccessGate(_research, store, HostedSettings(ORIGIN))
    code = store.issue(EMAIL)
    page = _request(app, "/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page["body"])[1]
    data = {"email": EMAIL, "code": code, "csrf": csrf}
    assert _request(app, "/login", method="POST", data=data)["status"].startswith("403")
    assert _request(app, "/login", method="POST", cookies=_cookie_header(page), data=data,
                    HTTP_ORIGIN="https://attacker.example.org")["status"].startswith("403")
    assert _request(app, "/login", HTTP_HOST="attacker.example.org", HTTP_X_FORWARDED_HOST="golden-vector.example.org")["status"].startswith("400")
    assert _request(app, "/login", **{"wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": "https"})["status"].startswith("400")
    for bad in ["wrong", "é" * 30]:
        result = _request(app, "/login", method="POST", cookies=_cookie_header(page), data={**data, "csrf": bad})
        assert result["status"].startswith("403")
    result = _request(app, "/login", method="POST", cookies=_cookie_header(page), data=data,
                      CONTENT_LENGTH="100000000", **{"wsgi.input": io.BytesIO(b"")})
    assert result["status"].startswith("403")


def test_logout_invalidates_session_and_requires_csrf(store):
    app = AccessGate(_research, store, HostedSettings(ORIGIN))
    _, cookie = _sign_in(app, store.issue(EMAIL))
    page = _request(app, cookies=cookie)
    csrf = re.search(r'name="csrf" value="([^"]+)"', page["body"])[1]
    assert _request(app, "/logout", method="POST", cookies=cookie, data={"csrf": "wrong"})["status"].startswith("403")
    assert _request(app, cookies=cookie)["status"].startswith("200")
    assert _request(app, "/logout", method="POST", cookies=cookie, data={"csrf": csrf})["status"].startswith("303")
    assert _request(app, cookies=cookie)["status"].startswith("303")


def test_different_guests_do_not_share_request_identity(store):
    app = AccessGate(_research, store, HostedSettings(ORIGIN))
    emails = [f"guest{i}@example.org" for i in range(6)]
    cookies = [_sign_in(app, store.issue(email), email)[1] for email in emails]
    with ThreadPoolExecutor(max_workers=6) as pool:
        pages = list(pool.map(lambda cookie: _request(app, cookies=cookie)["body"], cookies))
    for email, page in zip(emails, pages):
        assert email in page
        assert all(other not in page for other in emails if other != email)


def test_unreadable_access_store_returns_no_research(store):
    app = AccessGate(_research, store, HostedSettings(ORIGIN))
    _, cookie = _sign_in(app, store.issue(EMAIL))
    store.path.rename(store.path.with_suffix(".unavailable"))
    result = _request(app, cookies=cookie)
    assert result["status"].startswith("503") and "<h1>Research</h1>" not in result["body"]
    assert not store.path.exists()


def test_errors_do_not_disclose_internal_data(store):
    def failed(environ, start_response):
        start_response("500 Internal Server Error", [])
        return [b"private portfolio details /local/path"]
    app = AccessGate(failed, store, HostedSettings(ORIGIN))
    _, cookie = _sign_in(app, store.issue(EMAIL))
    result = _request(app, cookies=cookie)
    assert result["status"].startswith("503")
    assert "private portfolio" not in result["body"] and "/local/path" not in result["body"]


def test_real_workspace_retains_research_but_hides_admin_and_notes(tmp_path, monkeypatch):
    from golden_vector.app.config import load_app_config
    from golden_vector.screening.manual_data import bootstrap_manual_screening_data
    from golden_vector.screening.manual_store import add_stock_note
    from golden_vector.serve.workspace import create_workspace_app
    from tests.test_workspace_app import _write_latest_foundation_snapshot, _write_latest_outputs

    paths = build_test_paths(tmp_path / "workspace")
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    add_stock_note(paths, ticker="NEM", note_text="PRIVATE-OWNER-NOTE", note_tag="FOLLOW_UP", note_status="OPEN")
    store = AccessStore(paths.data_dir / "access" / "access.sqlite3")
    store.initialize()
    app = create_hosted_app(paths, public_origin=ORIGIN)
    _, cookie = _sign_in(app, store.issue(EMAIL))
    from golden_vector.screening import manual_store
    original_connect = manual_store._connect

    def checked_connect(path, *, read_only=False):
        if visitor_session.get() is not None:
            assert read_only, "Visitor request attempted a writable research connection"
        return original_connect(path, read_only=read_only)

    monkeypatch.setattr(manual_store, "_connect", checked_connect)
    for route in ["/", "/tool-a", "/tool-b", "/ticker/NEM"]:
        result = _request(app, route, cookies=cookie)
        assert result["status"].startswith("200"), result["body"]
        assert "PRIVATE-OWNER-NOTE" not in result["body"]
        assert 'action="/refresh"' not in result["body"]
        assert 'href="/portfolio"' not in result["body"]
        assert 'action="/ticker/NEM/company"' not in result["body"]
        assert 'id="inputs"' not in result["body"]
    local = create_workspace_app(paths, app_config=load_app_config(paths).app, tool_b_tickers=["NEM"])
    result = call_wsgi_app(local, method="GET", path="/ticker/NEM")
    assert "PRIVATE-OWNER-NOTE" in result["body"]
    assert 'action="/ticker/NEM/company"' in result["body"]


def test_access_page_has_no_analytics():
    from pathlib import Path
    from golden_vector.serve import access_page
    source = Path(access_page.__file__).read_text(encoding="utf-8")
    for forbidden in ("import pandas", "read_parquet", "read_csv", "load_manual", "build_portfolio", "yfinance"):
        assert forbidden not in source


def test_form_policy_preserves_same_origin_without_accepting_null(store):
    app = AccessGate(_research, store, HostedSettings(ORIGIN))
    page = _request(app, "/login")
    assert page["headers"]["Referrer-Policy"] == "same-origin"
    favicon = _request(app, "/favicon.ico", cookies=_cookie_header(page))
    assert favicon["status"].startswith("204")
    assert "Set-Cookie" not in favicon["headers"] and "Location" not in favicon["headers"]
    csrf = re.search(r'name="csrf" value="([^"]+)"', page["body"])[1]
    response = _request(app, "/login", method="POST", HTTP_ORIGIN="null",
                        cookies=_cookie_header(page), data={"csrf": csrf, "email": EMAIL, "code": "wrong"})
    assert response["status"].startswith("403")


def test_read_only_manual_store_never_runs_migrations_and_fails_loud(tmp_path, monkeypatch):
    from golden_vector.screening import manual_store
    paths = build_test_paths(tmp_path / "workspace")
    with pytest.raises(FileNotFoundError, match="missing"):
        manual_store.load_store_tables(paths, read_only=True)
    manual_store.ensure_manual_store(paths, tickers=["NEM"])
    before = paths.manual_screening_store_path.read_bytes()

    def forbidden(*args):
        pytest.fail("Read-only research must not migrate or modify its database")

    monkeypatch.setattr(manual_store, "_create_schema", forbidden)
    assert manual_store.load_store_tables(paths, read_only=True)[0].iloc[0]["ticker"] == "NEM"
    assert paths.manual_screening_store_path.read_bytes() == before
