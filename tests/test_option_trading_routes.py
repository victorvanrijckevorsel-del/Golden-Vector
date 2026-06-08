from __future__ import annotations

import io

from golden_vector.app.config import load_app_config
from golden_vector.contracts.config_models import PortfolioConfig
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.option_trading_data import (
    OptionArtifactStaleSchemaError,
    clear_option_trading_cache,
)
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths
from tests.test_option_trading_data import (
    _make_snapshot_untradable,
    _publish_option_artifacts,
    _write_option_inputs,
)


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
    assert "/hedge-readiness/latest.md" not in response["body"]
    assert "Directly hedgeable" not in response["body"]
    assert "Tradable candidate" in response["body"]
    assert "Snapshot Date" in response["body"]
    assert "Put P&amp;L/share @ Gold -10% (60d)" not in response["body"]
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
    assert "No option artifact snapshot exists yet." in response["body"]


def test_workspace_option_trading_route_handles_stale_artifact_schema(tmp_path, monkeypatch):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])

    def fail_stale_schema(*args, **kwargs):
        raise OptionArtifactStaleSchemaError("schema_version expected 2, got 1")

    monkeypatch.setattr(
        "golden_vector.serve.workspace.load_option_trading_data",
        fail_stale_schema,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/option-trading")

    assert response["status"].startswith("503")
    assert "Your local Option Trading data is from the previous version" in response["body"]
    assert "Run python main.py refresh" in response["body"]
    assert "The workspace hit an unexpected error" not in response["body"]


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
    assert body.index("<h4>Puts</h4>") < body.index("<h4>Calls</h4>")
    assert "Option Candidates" in body
    assert "Put Near-ATM" in body
    assert "Call Near-ATM" in body
    assert "Downside Put Scenarios" not in body
    assert "Upside Call Scenarios" not in body
    assert "Plain Beta" not in body
    assert "IV Skew 60d" not in body
    assert "IV/RV Ratio 60d" not in body
    assert "approximate - linear beta can understate real downside" in body
    assert "Leveraged bullish speculation" not in body
    assert "Stock Price" in body
    assert "Snapshot Date" in body
    assert "Source" in body
    assert "Cached Yahoo Finance data via yfinance" in body
    assert "Last" in body
    assert "Bid" in body
    assert "Ask" in body
    assert "Mid" in body
    assert "Half-spread Cost" not in body
    assert "Candidate" in body
    assert "Tradable" in body
    assert "Open Yahoo chain for this expiry" in body
    assert "120d" in body
    assert "30d tactical" not in body
    assert "Put P&amp;L/share @ Gold -10% (60d)" not in body
    assert "Call P&amp;L/share @ Gold +10% (60d)" not in body
    assert "60d put, strike" not in body
    assert "60d call, strike" not in body
    assert "Sizing Calculator" in body


def test_workspace_default_detail_uses_lightweight_option_trading_link(
    tmp_path,
    monkeypatch,
):
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

    def fail_option_load(*args, **kwargs):
        raise AssertionError("default ticker detail should not load option data")

    monkeypatch.setattr(
        "golden_vector.serve.workspace.load_option_trading_data",
        fail_option_load,
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/AEM")

    assert response["status"].startswith("200")
    body = response["body"]
    assert 'class="nav-tab active" href="/"' in body
    assert "Open Option Trading for AEM" in body
    assert "/ticker/AEM?lens=option-trading#option-trading" in body
    assert "Option Candidates" not in body
    assert "Sizing Calculator" not in body


def test_workspace_option_trading_calculator_contracts_mode(tmp_path):
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
    response = _call_wsgi_app(
        app,
        method="GET",
        path=(
            "/ticker/AEM?lens=option-trading&side=call&horizon=60"
            "&size_mode=contracts&quantity=3"
        ),
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Sizing Calculator" in body
    assert 'class="radio-label"' in body
    assert "Selected: 60d Near-ATM call" in body
    assert "Contracts: 3." in body
    assert "Premium spend: 360.00." in body


def test_workspace_option_trading_calculator_budget_mode(tmp_path):
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
    response = _call_wsgi_app(
        app,
        method="GET",
        path=(
            "/ticker/AEM?lens=option-trading&side=put&horizon=60"
            "&size_mode=budget&budget=500"
        ),
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Selected: 60d Near-ATM put" in body
    assert "Contracts: 4." in body
    assert "Premium spend: 480.00." in body
    assert "Leftover cash: 20.00." in body


def test_workspace_option_trading_calculator_invalid_inputs_fall_back(tmp_path):
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
    response = _call_wsgi_app(
        app,
        method="GET",
        path=(
            "/ticker/AEM?lens=option-trading&side=banana&horizon=999"
            "&size_mode=budget&budget=-10&quantity=0"
        ),
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Invalid side; defaulted to put." in body
    assert "Invalid horizon; defaulted to 60d." in body
    assert "Invalid budget; defaulted to contract quantity mode." in body
    assert "Invalid quantity; defaulted to 5." in body
    assert "Contracts: 5." in body


def test_workspace_option_trading_calculator_explains_skipped_scenarios(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        up_beta_core=0.0,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path=(
            "/ticker/AEM?lens=option-trading&side=call&horizon=60"
            "&size_mode=contracts&quantity=3"
        ),
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Selected: 60d Near-ATM call" in body
    assert "Contracts: 3." in body
    assert "Up-beta is too small to model meaningful gold-up scenarios." in body
    assert "Net P&amp;L Now" not in body


def test_workspace_option_trading_calculator_get_writes_no_files(tmp_path):
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
    before = _file_snapshot(paths.repo_root)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path=(
            "/ticker/AEM?lens=option-trading&side=call&horizon=60"
            "&size_mode=contracts&quantity=2"
        ),
    )
    after = _file_snapshot(paths.repo_root)

    assert response["status"].startswith("200")
    assert before == after


def test_workspace_option_trading_detail_discloses_risk_free_rate_fallback(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        risk_free_rate=None,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    overview_response = _call_wsgi_app(app, method="GET", path="/option-trading")
    detail_response = _call_wsgi_app(
        app,
        method="GET",
        path="/ticker/AEM?lens=option-trading",
    )

    assert overview_response["status"].startswith("200")
    assert detail_response["status"].startswith("200")
    assert "Risk-free rate was missing" in overview_response["body"]
    assert "Risk-free rate was missing" in detail_response["body"]


def test_workspace_option_vehicle_detail_page_renders_option_lens_only(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=True,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/GDX?lens=option-trading")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Option vehicle page" in body
    assert "Option Candidates" in body
    assert "Benchmark ETF option vehicle" in body
    assert "Company Inputs" not in body
    assert "Source Verification" not in body


def test_workspace_option_vehicle_without_option_lens_stays_404(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=True,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/GDX")

    assert response["status"].startswith("404")


def test_workspace_option_trading_detail_shows_proxy_fallback_not_overview(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=True,
        publish_artifacts=False,
    )
    _make_snapshot_untradable(paths, refresh_run_id="options-run", ticker="AEM")
    _publish_option_artifacts(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    overview_response = _call_wsgi_app(app, method="GET", path="/option-trading")
    detail_response = _call_wsgi_app(
        app,
        method="GET",
        path="/ticker/AEM?lens=option-trading&side=put&horizon=60",
    )

    assert overview_response["status"].startswith("200")
    assert detail_response["status"].startswith("200")
    assert "ETF Proxy Alternatives" not in overview_response["body"]
    assert "ETF Proxy Alternatives" in detail_response["body"]
    assert "/ticker/GDX?lens=option-trading" in detail_response["body"]
    assert "not AEM one-for-one" in detail_response["body"]


def test_workspace_detail_invalid_lens_falls_back_to_candidate_finder_nav(tmp_path):
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
    response = _call_wsgi_app(app, method="GET", path="/ticker/AEM?lens=garbage")

    assert response["status"].startswith("200")
    body = response["body"]
    assert 'class="nav-tab active" href="/"' in body
    assert 'class="nav-tab active" href="/option-trading"' not in body
    assert 'id="option-trading"' in body


def test_workspace_option_trading_lens_preserves_lens_in_window_switcher(tmp_path):
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
    assert "/ticker/AEM?window=6m&amp;lens=option-trading#option-trading" in body
    assert "/ticker/AEM?lens=option-trading#option-trading" in body
    assert "/ticker/AEM?window=3y&amp;lens=option-trading#option-trading" in body


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
    app_config = load_app_config(paths).app.model_copy(
        update={"portfolio": PortfolioConfig(enabled=True)}
    )
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


def _file_snapshot(root) -> dict[str, int]:
    return {
        path.relative_to(root).as_posix(): path.stat().st_mtime_ns
        for path in root.rglob("*")
        if path.is_file()
    }
