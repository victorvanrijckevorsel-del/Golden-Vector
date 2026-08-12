from __future__ import annotations

import io
import re


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


def test_stale_option_artifact_degrades_the_section_not_the_whole_ticker_page(
    tmp_path,
    monkeypatch,
):
    """A bad option artifact must cost the user ONE section, not the page.

    Self-review P1: option data now loads on every detail GET, so letting the
    loud loader errors escape would have replaced Performance, Corporate
    finance, Market behaviour AND the manual inputs with a 503 whenever a
    single option parquet's sha drifted. The /option-trading overview keeps
    raising (there, the option data IS the page) — see the test above.
    """
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")

    def fail_stale_schema(*args, **kwargs):
        raise OptionArtifactStaleSchemaError("schema_version expected 4, got 3")

    monkeypatch.setattr(
        "golden_vector.serve.workspace.load_option_trading_data",
        fail_stale_schema,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/AEM")

    assert response["status"].startswith("200")
    body = response["body"]
    # The rest of the page survives ...
    assert "Add Note" in body
    assert 'id="market-behaviour"' in body
    # ... and the Options section explains itself instead of vanishing.
    assert '<section id="options"' in body
    assert "schema_version expected 4, got 3" in body
    assert "no options" not in body.lower()
    assert "The workspace hit an unexpected error" not in body


def test_workspace_option_trading_lens_renders_canonical_options_section(tmp_path):
    """``?lens=option-trading`` is still accepted and renders the canonical page.

    The old standalone Option Trading detail PANEL is gone: options are now the
    ``id="options"`` SECTION of the redesigned ticker page (M3d), and the lens simply
    routes to that page. This test pins the section's current contract: the per-side
    ``<h4>Puts</h4>``/``<h4>Calls</h4>`` tables in that order, the ``bucket_label`` row
    labels, the Yahoo chain icon, the three disclosures that replaced "Show chain
    detail", and the re-cased provenance labels.
    """

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
    assert 'aria-current="page" href="/option-trading"' in body
    # The section id and its in-page nav entry (was id="option-trading").
    assert '<section id="options"' in body
    assert '<a class="section-nav-link" href="#options">Options</a>' in body
    assert body.index("<h4>Puts</h4>") < body.index("<h4>Calls</h4>")
    assert "Put Near-ATM" in body
    assert "Call Near-ATM" in body
    assert '<span class="badge badge-verified">Tradable</span>' in body
    # Contract-table columns.
    for column in (
        "Strike",
        "Expiry (DTE)",
        "Delta",
        "Bid / Ask",
        "Mid",
        "Spread",
        "Open interest",
        "Volume",
        "Liquidity",
        "Chain",
    ):
        # Phase 4 (d3b1a8a) added data-sort-numeric to the value columns, so
        # scope="col" is no longer the header's last attribute. The scope
        # relationship itself is what this asserts, and it survived — so match
        # THIS column's own <th>, not merely "a scoped th exists somewhere".
        header = re.search(
            r"<th([^>]*)>" + re.escape(column) + r"(?:<|\s*</th>)", body
        )
        assert header is not None, f"no header cell for {column}"
        assert 'scope="col"' in header.group(1), column
    # Yahoo chain is a compact arrow icon carrying the label in its title.
    assert 'class="yahoo-chain-icon"' in body
    assert "Open Yahoo option chain for this expiry" in body
    # "Show chain detail" was replaced by three named disclosures.
    assert "Show chain detail" not in body
    assert "Where the crowd is positioned" in body
    assert "Work out a position" in body
    assert "Greeks and full chain" in body
    # Provenance labels were re-cased and moved into "Greeks and full chain".
    assert "Share price used" in body
    assert "Snapshot date" in body
    assert "Data source" in body
    assert "Refresh run" in body
    assert "Stock Price" not in body
    assert "Snapshot Date" not in body
    assert "Refresh Run" not in body
    # The 230d target-window chip exists even while the default 90d window is shown.
    assert ">230d</a>" in body
    # Q40: the gold-scenario sizing calculator was DELETED, not moved.
    assert "Sizing Calculator" not in body
    assert "Downside Put Scenarios" not in body
    assert "Upside Call Scenarios" not in body
    assert "Put P&amp;L/share @ Gold -10% (60d)" not in body
    assert "Call P&amp;L/share @ Gold +10% (60d)" not in body


def test_workspace_default_detail_renders_options_section_inline(tmp_path):
    """The default ticker detail renders Options inline instead of linking to a lens.

    Options are a section of the canonical page now, so the default GET loads option
    data and renders the full section itself. The old "Open Option Trading for AEM"
    teaser (which pointed at ``?lens=option-trading#option-trading``) is deleted — the
    page links to its own ``#options`` anchor.
    """

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
    response = _call_wsgi_app(app, method="GET", path="/ticker/AEM")

    assert response["status"].startswith("200")
    body = response["body"]
    # Phase 4 (d3b1a8a) stopped marking Candidate Finder as the current page
    # here: on /ticker/AEM no primary-nav entry IS the current page, and
    # aria-current="page" claimed one was. The page now identifies itself
    # through page_id + a ticker header label instead, and the option-lens page
    # still marks its own nav entry (asserted in the lens tests).
    assert 'aria-current="page"' not in body
    assert 'data-page="ticker_detail"' in body
    # Rendered inline, with real contract rows — not a teaser.
    assert '<section id="options"' in body
    assert '<a class="section-nav-link" href="#options">Options</a>' in body
    assert body.index("<h4>Puts</h4>") < body.index("<h4>Calls</h4>")
    assert "Put Near-ATM" in body
    # The teaser link and the lens it pointed at are gone from the default page.
    assert "Open Option Trading for AEM" not in body
    assert "lens=option-trading" not in body
    assert 'id="option-trading"' not in body
    # Q40: no server-side sizing calculator anywhere.
    assert "Sizing Calculator" not in body


def test_workspace_default_detail_keeps_window_without_option_lens_link(tmp_path):
    """The selected window survives on the default page, and no lens link is emitted.

    Superseded Fix D: the "Open Option Trading" teaser used to carry ``window=`` into
    ``?lens=option-trading``. That link no longer exists, so what still has to hold is
    (a) the requested window stays selected in the page's own controls, and (b) nothing
    on the page links away to ``lens=option-trading``.
    """

    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run"
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    body_2y = _call_wsgi_app(app, method="GET", path="/ticker/AEM?window=2y")["body"]
    assert "window=2y" in body_2y
    assert "lens=option-trading" not in body_2y

    body_default = _call_wsgi_app(app, method="GET", path="/ticker/AEM")["body"]
    assert "lens=option-trading" not in body_default
    assert '<section id="options"' in body_default


def test_workspace_option_sizing_legacy_params_preselect_contract(tmp_path):
    """Legacy ``side``/``horizon``/``bucket`` survive as INITIAL STATE only.

    The server-side sizing calculator is deleted (Q40). Old deep links must still land
    on the contract they named, which now means preselecting the matching
    ``{side}-{horizon}-{bucket}`` ``<option>`` in the client-side tool's select — and
    computing nothing.
    """

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
            "/ticker/AEM?lens=option-trading&side=call&horizon=90&bucket=near_atm"
            "&size_mode=contracts&quantity=3"
        ),
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Work out a position" in body
    assert '<option value="call-90-near_atm" selected>' in body
    # Exactly one contract is preselected, and it is not the put default.
    assert '<option value="put-90-near_atm">' in body
    # Q40: no server-computed sizing or gold-scenario P&L.
    assert "Sizing Calculator" not in body
    assert 'class="radio-label"' not in body
    assert "Contracts: 3." not in body
    assert "Premium spend:" not in body


def test_workspace_option_sizing_legacy_budget_prefills_input(tmp_path):
    """``budget=500`` prefills the budget input; it no longer buys contracts server-side."""

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
            "/ticker/AEM?lens=option-trading&side=put&horizon=90"
            "&size_mode=budget&budget=500"
        ),
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert 'data-role="budget"' in body
    assert 'value="500.00"' in body
    assert '<option value="put-90-near_atm" selected>' in body
    # Q40: the server no longer resolves the budget into a position.
    assert "Contracts: 4." not in body
    assert "Premium spend: 480.00." not in body
    assert "Leftover cash: 20.00." not in body


def test_workspace_option_sizing_invalid_legacy_params_fall_back_to_put(tmp_path):
    """Invalid legacy params silently fall back to the put default — no "Invalid ..." notes.

    The old calculator narrated each coercion ("Invalid side; defaulted to put."). The
    client-side tool has no server-side inputs to validate, so a garbage deep link just
    lands on the default preselection instead of rendering error prose.
    """

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
    assert '<option value="put-90-near_atm" selected>' in body
    # A negative budget prefills nothing rather than being "corrected" in prose.
    assert 'data-role="budget"' in body
    assert 'inputmode="decimal" value=""' in body
    assert "Invalid side; defaulted to put." not in body
    assert "Invalid horizon; defaulted to 90d." not in body
    assert "Invalid budget; defaulted to contract quantity mode." not in body
    assert "Invalid quantity; defaulted to 5." not in body


def test_workspace_option_sizing_embeds_payload_and_script_once(tmp_path):
    """The client-side tool ships its payload and its script exactly once.

    ``option-sizing.js`` reads the embedded JSON by id; a duplicated payload block or a
    duplicated script tag would double-bind the controls, so the counts are the test.
    """

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
        path="/ticker/AEM?lens=option-trading",
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert body.count('<script type="application/json" id="option-sizing-payload">') == 1
    assert body.count('<script src="/static/option-sizing.js" defer></script>') == 1
    assert body.count('<div id="option-sizing"') == 1
    for role in (
        "contract",
        "budget",
        "price",
        "price-out",
        "result",
        "contracts-line",
        "ladder",
        "footnote",
        "reset",
        "live",
    ):
        assert f'data-role="{role}"' in body
    # The payload carries the persisted quote columns the JS sizes from.
    assert '"multiplier":100' in body
    assert '"quote_ok":true' in body


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
            "/ticker/AEM?lens=option-trading&side=call&horizon=90"
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
    # On the ticker page the fallback is now a full sentence next to the greeks it
    # affects, inside the "Greeks and full chain" disclosure.
    assert (
        "The risk-free rate was missing from the options manifest, so the greeks "
        "above were computed with a 0% rate fallback."
    ) in detail_response["body"]


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
    # A benchmark ETF gets an options-ONLY page: the Options section and nothing else.
    assert '<section id="options"' in body
    # Phase 4 (d3b1a8a): section_nav() -> section_tabs() — same renderer, compact
    # class and a page-specific label. Still one anchor, and still only one.
    assert (
        '<nav class="section-nav section-nav--compact" aria-label="Ticker sections">'
        '<a class="section-nav-link" href="#options">Options</a></nav>'
    ) in body
    assert "Company Inputs" not in body
    assert "Source Verification" not in body
    assert 'id="performance"' not in body
    assert 'id="corporate-finance"' not in body


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


def test_workspace_option_trading_detail_shows_no_proxy_fallback(tmp_path):
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
        path="/ticker/AEM?lens=option-trading&side=put&horizon=90",
    )

    assert overview_response["status"].startswith("200")
    assert detail_response["status"].startswith("200")
    # Requirements Q38: "no proxy/fallback suggestion". When AEM's own chain is
    # untradable the page says so in its own Options section; it never redirects the
    # reader to GDX/GDXJ as a stand-in, on either surface.
    assert "ETF Proxy Alternatives" not in overview_response["body"]
    assert "Proxy" not in detail_response["body"]
    assert "not AEM one-for-one" not in detail_response["body"]
    assert "/ticker/GDX?lens=option-trading" not in detail_response["body"]
    assert '<section id="options"' in detail_response["body"]


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
    # Phase 4 (d3b1a8a): the non-option detail page marks NO primary-nav entry
    # as current (see the default-detail test above). What this case is really
    # about is unchanged — an unknown lens must not land on the option lens.
    assert 'aria-current="page" href="/option-trading"' not in body
    assert 'aria-current="page"' not in body
    assert 'data-page="ticker_detail"' in body
    # An unknown lens still renders the canonical page, Options section and all
    # (the section id is "options" now; "option-trading" survives only as the top-nav
    # href asserted above).
    assert '<section id="options"' in body


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
    # W1: the tabs now build on the page's real query params, so the carried
    # `lens` keeps its request-URL position and `window` is appended.
    assert "/ticker/AEM?lens=option-trading&amp;window=6m#option-trading" in body
    assert "/ticker/AEM?lens=option-trading#option-trading" in body
    assert "/ticker/AEM?lens=option-trading&amp;window=3y#option-trading" in body


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
