from __future__ import annotations

import io

from golden_vector.app.config import load_app_config
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.option_trading_data import clear_option_trading_cache
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths
from tests.test_option_trading_data import _write_option_inputs


def test_workspace_option_trading_route_renders_native_tab(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/option-trading")

    assert response["status"].startswith("200")
    assert "Option Trading" in response["body"]
    assert "/option-trading" in response["body"]
    assert "/ticker/AEM?lens=option-trading#option-trading" in response["body"]
    assert "/hedge-readiness/latest.md" in response["body"]
    assert "directly_hedgeable" in response["body"]
    assert "available" in response["body"]
    assert "markdown-report" not in response["body"]


def test_workspace_option_trading_route_handles_missing_snapshot(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/option-trading")

    assert response["status"].startswith("200")
    assert "No options snapshot exists yet." in response["body"]


def test_workspace_option_trading_detail_lens_renders_put_panel(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/AEM?lens=option-trading")

    assert response["status"].startswith("200")
    body = response["body"]
    assert 'class="nav-tab active" href="/option-trading"' in body
    assert 'id="option-trading"' in body
    assert "Downside Put Candidates" in body
    assert "Downside Put Scenarios" in body
    assert "Put P&amp;L/share @ Gold -10% (60d)" in body
    assert "60d put, strike" in body


def test_workspace_hedge_readiness_route_redirects_to_option_trading(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/hedge-readiness")

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/option-trading"
    assert response["body"] == ""


def test_workspace_raw_hedge_report_download_serves_latest_markdown(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    paths.output_hedge_readiness_dir.mkdir(parents=True, exist_ok=True)
    (paths.output_hedge_readiness_dir / "latest.md").write_text(
        "# Hedge Readiness Report\n\nRaw markdown.\n",
        encoding="utf-8",
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/hedge-readiness/latest.md")

    assert response["status"].startswith("200")
    assert response["headers"]["Content-Type"] == "text/markdown; charset=utf-8"
    assert "attachment;" in response["headers"]["Content-Disposition"]
    assert response["body"].startswith("# Hedge Readiness Report")


def _call_wsgi_app(app, *, method: str, path: str, body: str = "") -> dict[str, object]:
    payload = body.encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    if "?" in path:
        path_info, _, query_string = path.partition("?")
    else:
        path_info, query_string = path, ""

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(payload),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    body_bytes = b"".join(app(environ, start_response))
    return {
        "status": captured["status"],
        "headers": dict(captured["headers"]),
        "body": body_bytes.decode("utf-8"),
    }
