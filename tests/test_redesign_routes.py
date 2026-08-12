"""Pre-migration route characterization tests (visual redesign plan, Phase 0 task 13).

These pin CURRENT behaviour before any shared markup is extracted, covering the
gaps the 2026-08-10 audit confirmed: no WSGI coverage for /scorecard, the
reporting POST, Portfolio lot edit/delete, unknown ticker/action pages, and
unsupported-method requests. The app has no 405 or HEAD handling — method
mismatches fall through to a 404 in one of two flavours — and that reality is
pinned exactly. Tests marked ``known-defect`` characterize behaviour recorded
in reviews/codex/milestones/visual_redesign/defect_register.md; they document
what the app DOES today, not the desired contract.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.portfolio_page import _render_lots_link, _ticker_slug
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths, call_wsgi_app
from tests.test_portfolio_m1 import _portfolio_config, _write_foundation_snapshot
from tests.test_workspace_app import (
    _repo_app_config,
    _write_latest_foundation_snapshot,
    _write_latest_outputs,
)


def _minimal_app(tmp_path):
    """App with a bootstrapped manual store and no model artifacts."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    app = create_workspace_app(paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"])
    return paths, app


def _full_app(tmp_path):
    """App with foundation snapshot and Tool A-D artifacts for NEM."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    app = create_workspace_app(paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"])
    return paths, app


def _portfolio_app(tmp_path, *, enabled: bool = True):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config(enabled=enabled)
    if enabled:
        _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    return paths, app


_LOT_PAYLOAD = {
    "ticker": "NEM",
    "shares": "2",
    "buy_price": "50",
    "buy_currency": "USD",
    "buy_date": "2026-01-02",
    "note": "initial-note-marker",
}


# ---------------------------------------------------------------- /scorecard


def test_scorecard_route_renders_not_built_state(tmp_path):
    _, app = _minimal_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/scorecard")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "<h1>Evidence Scorecard</h1>" in body
    assert "Scorecard is not built yet." in body
    assert '<a class="nav-link" aria-current="page" href="/scorecard">Scorecard</a>' in body


# ------------------------------------------------------- reporting POST route


def test_reporting_post_saves_dates_and_notes_and_redirects(tmp_path):
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "2026-09-15",
            "next_production_report_date": "2026-10-01",
            "notes": "Q3 update marker",
            "return_to": "/ticker/NEM?window=6M",
        },
    )

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/ticker/NEM?window=6M&saved=reporting"

    page = call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert 'value="2026-09-15"' in page["body"]
    assert 'value="2026-10-01"' in page["body"]
    assert "Q3 update marker" in page["body"]


def test_reporting_post_blank_clears_stored_values(tmp_path):
    _, app = _full_app(tmp_path)
    call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "2026-09-15",
            "next_production_report_date": "2026-10-01",
            "notes": "Q3 update marker",
        },
    )

    # Reporting deliberately differs from company inputs: blank means CLEAR.
    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "",
            "next_production_report_date": "",
            "notes": "",
        },
    )

    assert response["status"].startswith("303")
    page = call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert 'value="2026-09-15"' not in page["body"]
    assert 'value="2026-10-01"' not in page["body"]
    assert "Q3 update marker" not in page["body"]


def test_reporting_post_invalid_date_returns_400_with_tool_a_data(tmp_path):
    """D1 RESOLVED: with Tool A artifacts present (every real ticker), the
    validation-error re-render now threads app_config through, so the user
    gets a 400 with the full detail page and a danger notice — never the
    generic 500 the pre-fix characterization pinned."""
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "not-a-date",
            "next_production_report_date": "",
            "notes": "",
        },
    )

    assert response["status"].startswith("400")
    assert "The workspace hit an unexpected error." not in response["body"]
    assert "notice-danger" in response["body"]
    # The full page renders around the error (nav + the reporting form itself).
    assert "Reporting Calendar" in response["body"]


def test_company_post_invalid_numeric_returns_400_with_tool_a_data(tmp_path):
    """D1 RESOLVED (company branch): same contract for the company form."""
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        data={"aisc_usd_per_oz": "not-a-number"},
    )

    assert response["status"].startswith("400")
    assert "notice-danger" in response["body"]
    assert "Company Inputs" in response["body"]


def _return_to_values(body: str) -> list[str]:
    return re.findall(r'name="return_to" value="([^"]*)"', body)


def test_reporting_error_rerender_preserves_query_state_and_submitted_values(tmp_path):
    """GV-RD-FINAL-001: the rejected POST must come back on the SAME page the
    user was on (window + fundamentals source), with the values they typed."""
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting?window=6M&fundamentals_source=yahoo",
        data={
            "next_financial_report_date": "not-a-date",
            "notes": "typed marker",
            "return_to": "/ticker/NEM?window=6M&fundamentals_source=yahoo",
        },
    )

    assert response["status"].startswith("400")
    body = response["body"]
    assert "notice-danger" in body

    # The window switcher marks 6M active (not the fixture's canonical anchor).
    active_tabs = re.findall(r'<a class="window-tab active" href="([^"]*)"', body)
    assert len(active_tabs) == 1
    assert "window=6m" in active_tabs[0]

    # Every hidden return_to carries the request's view state.
    returns = _return_to_values(body)
    assert returns
    for value in returns:
        assert "window=6M" in value
        assert "fundamentals_source=yahoo" in value
        assert value != "/ticker/NEM"

    # And the submitted values are echoed back, not the stored row.
    assert "typed marker" in body
    assert 'value="not-a-date"' in body


def test_reporting_error_rerender_recovers_state_from_return_to_only(tmp_path):
    """Real browsers POST to the BARE form action (no query string) — the view
    state travels only in the hidden return_to field."""
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "not-a-date",
            "notes": "typed marker",
            "return_to": "/ticker/NEM?window=6M&fundamentals_source=yahoo",
        },
    )

    assert response["status"].startswith("400")
    body = response["body"]
    assert "notice-danger" in body
    active_tabs = re.findall(r'<a class="window-tab active" href="([^"]*)"', body)
    assert len(active_tabs) == 1
    assert "window=6m" in active_tabs[0]
    returns = _return_to_values(body)
    assert returns
    for value in returns:
        assert "window=6M" in value
        assert "fundamentals_source=yahoo" in value
    assert "typed marker" in body


def test_company_error_rerender_echoes_bad_value_and_window(tmp_path):
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company?window=6M",
        data={"aisc_usd_per_oz": "not-a-number"},
    )

    assert response["status"].startswith("400")
    body = response["body"]
    assert 'value="not-a-number"' in body
    active_tabs = re.findall(r'<a class="window-tab active" href="([^"]*)"', body)
    assert len(active_tabs) == 1
    assert "window=6m" in active_tabs[0]
    returns = _return_to_values(body)
    assert returns
    for value in returns:
        assert "window=6M" in value


# ------------------------------------------- Portfolio lot edit/delete routes


def _add_lot_and_get_id(app) -> str:
    added = call_wsgi_app(app, method="POST", path="/portfolio/lots", data=_LOT_PAYLOAD)
    assert added["status"].startswith("303")
    assert added["headers"]["Location"] == "/portfolio?saved=portfolio"
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    match = re.search(r'/portfolio/lots/([^/"]+)/edit', page["body"])
    assert match, "expected an edit form for the added lot"
    return match.group(1)


def test_portfolio_lot_edit_route_updates_lot_and_redirects(tmp_path):
    _, app = _portfolio_app(tmp_path)
    lot_id = _add_lot_and_get_id(app)

    response = call_wsgi_app(
        app,
        method="POST",
        path=f"/portfolio/lots/{lot_id}/edit",
        data={**_LOT_PAYLOAD, "shares": "3", "note": "edited-note-marker"},
    )

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/portfolio?saved=portfolio"
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    assert "edited-note-marker" in page["body"]
    assert "initial-note-marker" not in page["body"]


def test_portfolio_lot_delete_route_removes_lot_and_redirects(tmp_path):
    _, app = _portfolio_app(tmp_path)
    lot_id = _add_lot_and_get_id(app)

    response = call_wsgi_app(app, method="POST", path=f"/portfolio/lots/{lot_id}/delete")

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/portfolio?saved=portfolio"
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    assert f"/portfolio/lots/{lot_id}/edit" not in page["body"]
    assert "initial-note-marker" not in page["body"]


def test_portfolio_lot_edit_unknown_id_returns_400_with_error(tmp_path):
    _, app = _portfolio_app(tmp_path)
    _add_lot_and_get_id(app)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/portfolio/lots/does-not-exist/edit",
        data=_LOT_PAYLOAD,
    )

    assert response["status"].startswith("400")
    # The portfolio page re-renders with the store error; the lot survives.
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    assert "initial-note-marker" in page["body"]


def test_portfolio_lots_get_is_unsupported_route_404(tmp_path):
    _, app = _portfolio_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/portfolio/lots")

    assert response["status"].startswith("404")
    assert "Unsupported portfolio route." in response["body"]


def test_portfolio_lots_disabled_403_takes_precedence_over_method(tmp_path):
    _, app = _portfolio_app(tmp_path, enabled=False)

    # The enablement check runs before the method check on /portfolio/lots*.
    response = call_wsgi_app(app, method="GET", path="/portfolio/lots")

    assert response["status"].startswith("403")
    assert "Portfolio is disabled" in response["body"]


# --------------------------------------- unknown ticker / action / method 404s


def test_unknown_ticker_renders_scoped_404(tmp_path):
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/ticker/ZZZZ")

    assert response["status"].startswith("404")
    assert "ZZZZ is not an active Corporate Finance ticker." in response["body"]


def test_unknown_ticker_action_renders_unsupported_route_404(tmp_path):
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="POST", path="/ticker/NEM/bogus-action")

    assert response["status"].startswith("404")
    assert "Unsupported workspace route." in response["body"]


@pytest.mark.parametrize(
    ("method", "path", "expected_snippet"),
    [
        ("POST", "/tool-a", "Page not found."),
        ("POST", "/", "Page not found."),
        ("GET", "/refresh", "Page not found."),
        ("GET", "/option-trading/refresh", "Page not found."),
        ("DELETE", "/tool-b", "Page not found."),
        ("HEAD", "/", "Page not found."),
        ("POST", "/portfolio", "Page not found."),
        ("POST", "/static/workspace.css", "Page not found."),
        ("PUT", "/ticker/NEM", "Unsupported workspace route."),
        ("GET", "/ticker/NEM/company", "Unsupported workspace route."),
    ],
)
def test_method_mismatches_fall_through_to_404_not_405(tmp_path, method, path, expected_snippet):
    """The app has no 405 and no HEAD handling; every mismatch is a 404 page."""
    _, app = _minimal_app(tmp_path)

    response = call_wsgi_app(app, method=method, path=path)

    assert response["status"].startswith("404")
    assert "405" not in response["status"]
    assert expected_snippet in response["body"]


def test_ticker_detail_section_nav_lists_every_present_section(tmp_path):
    """Plan 15/23: sticky in-page anchors on the detail page — every anchor in
    the nav resolves to a real section id for the mining-ticker lens.

    M3b: the nav is the redesigned five-entry list (requirements §2 order); the
    old per-form entries (Reporting / Verification / Notes) collapsed into
    "Inputs & notes" and the composite-bearing "Corporate Finance" snapshot
    became the "Corporate finance" section."""
    _paths, app = _full_app(tmp_path)
    body = call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]
    assert '<nav class="section-nav" aria-label="On this page">' in body
    for fragment, label in (
        ("performance", "Performance"),
        ("corporate-finance", "Corporate finance"),
        ("market-behaviour", "Market behaviour"),
        ("options", "Options"),
        ("inputs", "Inputs &amp; notes"),
    ):
        assert f'href="#{fragment}">{label}</a>' in body
        assert f'id="{fragment}"' in body  # the anchor target really exists


# ------------------------------------------------- defect-register regressions


def test_all_blank_company_post_never_claims_a_save(tmp_path):
    """D2 RESOLVED: an all-blank company POST writes nothing and redirects
    WITHOUT the saved marker, so the page cannot claim 'Company inputs saved.'

    The register's contract is "no manual-store content change", so the store
    file's BYTES are compared before/after (not mtime, which a rewrite of
    identical content would still bump)."""
    paths, app = _minimal_app(tmp_path)
    store_path = paths.manual_screening_store_path
    assert store_path.exists(), "bootstrap must have created the company-inputs store"
    before = store_path.read_bytes()

    response = call_wsgi_app(app, method="POST", path="/ticker/NEM/company", data={})

    assert response["status"].startswith("303")
    assert "saved=" not in response["headers"]["Location"]
    assert store_path.read_bytes() == before, "all-blank POST must not touch the manual store"
    page = call_wsgi_app(app, method="GET", path=response["headers"]["Location"])
    assert "notice-success" not in page["body"]


def test_return_to_rejects_control_characters(tmp_path):
    """D4 RESOLVED: CR/LF (and other control chars) in return_to fall back to
    the safe ticker path instead of reaching the Location header."""
    _paths, app = _minimal_app(tmp_path)
    for evil in ("/x\r\nInjected: 1", "/x\nInjected: 1", "//evil.example", r"/x\evil"):
        response = call_wsgi_app(
            app,
            method="POST",
            path="/ticker/NEM/company",
            data={"aisc_usd_per_oz": "1200", "return_to": evil},
        )
        assert response["status"].startswith("303"), evil
        location = response["headers"]["Location"]
        assert location.startswith("/ticker/NEM"), (evil, location)
        assert "\r" not in location and "\n" not in location


def test_unknown_ticker_option_lens_is_a_plain_404(tmp_path):
    """D5 RESOLVED: only configured benchmark tickers attempt the option-vehicle
    resolution, so an unknown ticker 404s without touching option artifacts."""
    _paths, app = _minimal_app(tmp_path)
    bogus = call_wsgi_app(app, method="GET", path="/ticker/BOGUS?lens=option-trading")
    assert bogus["status"].startswith("404")
    # A configured benchmark without a vehicle row in the (artifact-free)
    # fixture still resolves to a clean 404, not an error page.
    gdx = call_wsgi_app(app, method="GET", path="/ticker/GDX?lens=option-trading")
    assert gdx["status"].startswith("404")


def test_unknown_ticker_option_lens_404s_under_a_stale_option_schema(tmp_path):
    """D5 RESOLVED (full contract): with option artifacts ON DISK in a stale
    schema state, an unknown ticker under ``lens=option-trading`` must still 404
    -- the membership check runs BEFORE the option load, so the stale-schema 503
    can never mask a plain 404.

    Fixture: the repo's own stale-schema shape -- real option artifacts written
    to disk, then the current model-state manifest edited so a required option
    artifact (``option_signal_summary``) can no longer be resolved, which is what
    ``load_option_trading_data`` raises ``OptionArtifactStaleSchemaError`` on.
    """
    import json as _json

    from golden_vector.app.model_state import load_current_model_state_manifest
    from golden_vector.serve.option_trading_data import clear_option_trading_cache
    from tests.test_option_trading_data import _write_option_inputs

    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")
    payload = load_current_model_state_manifest(paths)
    assert payload is not None
    del payload["artifacts"]["option_signal_summary"]
    paths.latest_model_state_manifest_path.write_text(_json.dumps(payload), encoding="utf-8")

    app_config = _repo_app_config()
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    try:
        bogus = call_wsgi_app(app, method="GET", path="/ticker/BOGUS?lens=option-trading")
        assert bogus["status"].startswith("404"), bogus["status"]
        assert "not an active Corporate Finance ticker" in bogus["body"]

        # Healthy control: a CONFIGURED benchmark is not rejected as unknown --
        # it proceeds into the option path (and there meets the stale schema),
        # which is what proves the 404 above came from the membership check.
        benchmark = str(app_config.hedge_readiness.benchmark_tickers[0]).strip().upper()
        control = call_wsgi_app(app, method="GET", path=f"/ticker/{benchmark}?lens=option-trading")
        assert not control["status"].startswith("404"), control["status"]
    finally:
        clear_option_trading_cache()


def test_lab_dial_path_is_not_double_decoded(tmp_path, monkeypatch):
    """D8 RESOLVED: PATH_INFO is already WSGI-decoded; a literal %-sequence in
    the path stays literal instead of decoding a second time."""
    import golden_vector.serve.workspace as workspace_module

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    # The dial route gates on the allowed universe (deep-review L3), so the
    # %-bearing ticker must itself be allowed for the decode probe to reach
    # the loader.
    app = create_workspace_app(
        paths, app_config=_repo_app_config(), tool_b_tickers=["NEM", "NEM%20X"]
    )
    seen: dict[str, str] = {}
    real_loader = workspace_module.load_ticker_curve

    def capturing_loader(paths, *, ticker, **kwargs):
        seen["ticker"] = ticker
        return real_loader(paths, ticker=ticker, **kwargs)

    monkeypatch.setattr(workspace_module, "load_ticker_curve", capturing_loader)
    call_wsgi_app(app, method="GET", path="/lab/dial/NEM%20X")
    # PATH_INFO arrives WSGI-decoded; the route must NOT decode again.
    assert seen["ticker"] == "NEM%20X"


def test_refresh_post_signals_already_running(tmp_path, monkeypatch):
    """D9 RESOLVED: an already-running refresh is signalled via the redirect and
    rendered as an info notice instead of being silently discarded."""
    import golden_vector.serve.workspace as workspace_module
    from golden_vector.serve.option_refresh import (
        OptionRefreshStartResult,
        OptionRefreshStatus,
    )

    def read_status_stub():
        return OptionRefreshStatus()

    _paths, app = _minimal_app(tmp_path)
    monkeypatch.setattr(
        workspace_module,
        "start_options_refresh",
        lambda paths: OptionRefreshStartResult(
            status=read_status_stub(), started=False, already_running=True
        ),
    )
    response = call_wsgi_app(app, method="POST", path="/option-trading/refresh", data={})
    assert response["status"].startswith("303")
    assert "refresh=already-running" in response["headers"]["Location"]

    page = call_wsgi_app(app, method="GET", path="/option-trading?refresh=already-running")
    assert "A data refresh is already running; no new refresh was started." in page["body"]
    assert "notice-info" in page["body"]


_ALREADY_RUNNING_NOTICE = "A data refresh is already running; no new refresh was started."


@pytest.mark.parametrize("path", ("/", "/candidate-finder"))
def test_candidate_finder_renders_already_running_refresh_notice(tmp_path, path):
    """GV-RD-FINAL-005: the main "Refresh all model data" control posts from the
    Candidate Finder screen and redirects back here, so both landing surfaces
    must show the same already-running info notice the Option Trading overview
    shows."""
    _paths, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path=f"{path}?refresh=already-running")

    assert response["status"].startswith("200")
    assert "notice-info" in response["body"]
    assert _ALREADY_RUNNING_NOTICE in response["body"]


@pytest.mark.parametrize("path", ("/", "/candidate-finder"))
def test_candidate_finder_has_no_refresh_notice_without_the_flag(tmp_path, path):
    """Control: a plain GET must not claim a refresh is already running."""
    _paths, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path=path)

    assert response["status"].startswith("200")
    assert _ALREADY_RUNNING_NOTICE not in response["body"]


@pytest.mark.parametrize("bad_value", ["abc", "0", "-1", "inf"])
def test_candidate_finder_bad_gold_price_renders_screen_at_400(tmp_path, bad_value):
    """D6 RESOLVED: a rejected gold-price scenario still returns the persisted Candidate
    Finder screen (computed without the scenario) at 400, with a danger notice."""
    _paths, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path=f"/candidate-finder?gold_price={bad_value}")
    assert response["status"].startswith("400")
    assert "notice notice-danger" in response["body"]
    assert "gold_price must be" in response["body"]
    # The real screen rendered, not the bare workspace-error page.
    assert "candidate-gold-scenario-panel" in response["body"]
    assert "Workspace Error" not in response["body"]


def test_landing_bad_gold_price_renders_screen_at_400(tmp_path):
    """D6 RESOLVED: the landing route ("/") behaves identically to /candidate-finder."""
    _paths, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/?gold_price=abc")
    assert response["status"].startswith("400")
    assert "notice notice-danger" in response["body"]
    assert "gold_price must be numeric" in response["body"]
    assert "candidate-gold-scenario-panel" in response["body"]
    assert "Workspace Error" not in response["body"]


def test_candidate_finder_valid_gold_price_has_no_danger_notice(tmp_path):
    """Control: a valid gold price is accepted (200, no danger notice)."""
    _paths, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/candidate-finder?gold_price=2500")
    assert response["status"].startswith("200")
    # No D6 parse-error notice (the model-state banner may legitimately use notice-danger).
    assert "gold_price must be" not in response["body"]


# --------------------------------------------------------------- D11 guards


class _DataTableStructureChecker(HTMLParser):
    """Walk a rendered page and record js-datatable structural violations.

    Contract (defect D11): every ``<table class="js-datatable">`` must carry a
    non-empty ``id`` (DataTables filter-bar targeting) and must contain NO
    nested ``<table>`` — a nested table corrupts the DataTables column model
    and triggers the blocking "Requested unknown parameter" alert.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.violations: list[str] = []
        self._stack: list[str | None] = []  # per open <table>: its js-datatable id or None

    def handle_starttag(self, tag, attrs):
        if tag != "table":
            return
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        is_dt = "js-datatable" in classes
        table_id = (attr.get("id") or "").strip()
        enclosing = next((entry for entry in reversed(self._stack) if entry is not None), None)
        if enclosing is not None:
            self.violations.append(f"nested <table> inside js-datatable id={enclosing!r}")
        if is_dt and not table_id:
            self.violations.append("js-datatable table has no id")
        self._stack.append(table_id if is_dt else None)

    def handle_endtag(self, tag):
        if tag == "table" and self._stack:
            self._stack.pop()


def _datatable_violations(body: str) -> list[str]:
    checker = _DataTableStructureChecker()
    checker.feed(body)
    return checker.violations


_GUARD_FULL_ROUTES = (
    "/",
    "/candidate-finder",
    "/tool-a",
    "/tool-b",
    "/tool-c",
    "/tool-d",
    "/option-trading",
    "/lab",
    "/ticker/NEM",
)

# GV-RD-FINAL-010: every serve module that emits `class="js-datatable"` mapped to
# a route this guard actually renders. `_test_js_datatable_emitter_inventory`
# fails when a new emitter module appears without an entry here, so a new table
# cannot silently escape the structural guard.
_DATATABLE_EMITTER_ROUTES = {
    "candidate_finder_page.py": "/candidate-finder",
    "overview_lab.py": "/lab",
    "overview_option_trading.py": "/option-trading",
    "overview_tool_a.py": "/tool-a",
    "overview_tool_b.py": "/tool-b",
    "overview_tool_c.py": "/tool-c",
    "overview_tool_d.py": "/tool-d",
    "portfolio_page.py": "/portfolio",  # covered by the portfolio guard test below
}


@pytest.mark.parametrize("path", _GUARD_FULL_ROUTES)
def test_js_datatables_have_ids_and_no_nested_tables(tmp_path, path):
    """D11 structural guard.

    Coverage is honest and bounded: it renders ONE fixture state (`_full_app`,
    plus `_portfolio_app` in the sibling test) for each route listed in
    `_GUARD_FULL_ROUTES` / `_DATATABLE_EMITTER_ROUTES`. It does NOT sweep every
    query-parameter state (lenses, windows, search filters, empty states). What
    it does guarantee beyond those renders is the emitter *inventory*: the
    companion test below fails if any `golden_vector/serve/*.py` module emits
    `js-datatable` without a route in the mapping above.
    """
    _paths, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path=path)

    assert response["status"].startswith("200"), path
    assert _datatable_violations(response["body"]) == [], path


def test_js_datatable_emitter_inventory_is_fully_covered():
    """GV-RD-FINAL-010: no `js-datatable` emitter may exist without a guarded route."""
    from pathlib import Path

    import golden_vector.serve as serve_pkg

    serve_dir = Path(serve_pkg.__file__).parent
    emitters = sorted(
        module.name
        for module in serve_dir.glob("*.py")
        if "js-datatable" in module.read_text(encoding="utf-8")
    )
    assert emitters, "static scan found no js-datatable emitters -- the scan is broken"
    covered = set(_GUARD_FULL_ROUTES) | {"/portfolio"}

    unmapped = [name for name in emitters if name not in _DATATABLE_EMITTER_ROUTES]
    assert not unmapped, (
        "serve modules emit js-datatable but have no covered route in "
        f"_DATATABLE_EMITTER_ROUTES: {unmapped}. Add the module with the route the "
        "D11 structural guard should render for it (and add that route to "
        "_GUARD_FULL_ROUTES if it is not already guarded)."
    )
    stale = [name for name in _DATATABLE_EMITTER_ROUTES if name not in emitters]
    assert not stale, f"_DATATABLE_EMITTER_ROUTES lists non-emitters: {stale}"
    uncovered = {
        name: route
        for name, route in _DATATABLE_EMITTER_ROUTES.items()
        if route not in covered
    }
    assert not uncovered, f"emitter routes not rendered by any guard test: {uncovered}"


def test_portfolio_js_datatables_have_ids_and_no_nested_tables(tmp_path):
    _paths, app = _portfolio_app(tmp_path)
    _add_lot_and_get_id(app)

    response = call_wsgi_app(app, method="GET", path="/portfolio")

    assert response["status"].startswith("200")
    assert _datatable_violations(response["body"]) == []


def test_portfolio_positions_table_has_id_and_lots_link_out(tmp_path):
    """D11: the lots cell is a link to a sibling Lot breakdown block, and the
    lot table no longer lives inside a positions row."""
    _paths, app = _portfolio_app(tmp_path)
    _add_lot_and_get_id(app)

    body = call_wsgi_app(app, method="GET", path="/portfolio")["body"]

    assert 'id="portfolio-positions-table"' in body
    assert 'href="#lots-nem"' in body
    assert '<details id="lots-nem"' in body
    assert "<h3>Lot breakdown</h3>" in body
    assert 'aria-label="NEM lots"' in body
    assert 'id="portfolio-lots-nem"' in body
    # The old nested markup (a <details> wrapping the lot table inside a row).
    assert "</summary><table" not in body


def test_ticker_slug_and_zero_lot_cell_render_plainly():
    assert _ticker_slug("BHP.AX") == "bhp-ax"
    assert _ticker_slug("NEM") == "nem"
    assert _render_lots_link("NEM", 0) == "0 lots"
    assert _render_lots_link("BHP.AX", 2) == '<a href="#lots-bhp-ax">2 lots</a>'


# ------------------------------------------------- deep-review H1 / M6 / M2


def test_rejected_company_save_echoes_rate_verbatim_not_display_scaled(tmp_path):
    """Deep-review H1: the error re-render echoes the SUBMITTED string. The old
    row-overlay pushed it through _format_form_value, which display-scales
    stored rate fractions — an echoed "5" became value="500", and a re-save
    silently persisted a 500% royalty."""
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        data={"royalty_rate": "5", "aisc_usd_per_oz": "not-a-number"},
    )

    assert response["status"].startswith("400")
    assert 'name="royalty_rate" type="number" value="5"' in response["body"]
    assert 'value="500"' not in response["body"]


def test_rejected_note_save_keeps_the_typed_note(tmp_path):
    """Deep-review M6: a rejected note save must not discard the typed text."""
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/note",
        data={"note_text": "", "note_tag": "FOLLOW_UP-marker", "note_status": "OPEN"},
    )

    assert response["status"].startswith("400")
    assert "notice-danger" in response["body"]
    assert 'value="FOLLOW_UP-marker"' in response["body"]


def test_percent_suffix_rate_saves_once_not_twice(tmp_path):
    """Deep-review M2: one normalize boundary. Typing "30%" for a rate must
    store 0.30 (round-tripping to a displayed 30), not 0.003 (double divide)."""
    _, app = _full_app(tmp_path)

    saved = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        data={"tax_rate": "30%"},
    )
    assert saved["status"].startswith("303")

    page = call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert 'name="tax_rate" type="number" value="30"' in page["body"]
    assert 'name="tax_rate" type="number" value="0.3"' not in page["body"]


def test_ticker_routes_reject_trailing_segments(tmp_path):
    """Deep-review L2: /ticker/NEM/company/anything must 404, never behave
    like the company save route."""
    _, app = _full_app(tmp_path)

    posted = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company/extra",
        data={"aisc_usd_per_oz": "1200"},
    )
    fetched = call_wsgi_app(app, method="GET", path="/ticker/NEM/company/extra")

    assert posted["status"].startswith("404")
    assert fetched["status"].startswith("404")


def test_return_to_rejects_non_ascii_before_the_location_header(tmp_path):
    """Deep-review M5: wsgiref latin-1-encodes headers after the app returns,
    so non-ASCII return_to must fall back instead of blowing up mid-response."""
    _paths, app = _minimal_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        data={"aisc_usd_per_oz": "1200", "return_to": "/ticker/Café"},
    )

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/ticker/NEM?saved=company"


def test_lab_dial_unknown_ticker_is_a_clean_404(tmp_path):
    """Deep-review L3: the dial route gates on the allowed universe like
    /ticker/ does — arbitrary strings must not get a real-looking page."""
    _paths, app = _full_app(tmp_path)

    unknown = call_wsgi_app(app, method="GET", path="/lab/dial/ZZUNKNOWN")
    known = call_wsgi_app(app, method="GET", path="/lab/dial/NEM")

    assert unknown["status"].startswith("404")
    assert not known["status"].startswith("404")
