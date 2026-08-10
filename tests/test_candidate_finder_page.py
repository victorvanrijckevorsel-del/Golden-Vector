from __future__ import annotations

import io
from dataclasses import replace

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.serve.candidate_finder_data import (
    CandidateFinderAlignment,
    CandidateFinderCacheKey,
    CandidateFinderData,
)
from golden_vector.serve.candidate_finder_page import _preset_href, render_candidate_finder_page
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths


def test_candidate_finder_page_renders_default_bull_screen():
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data)

    assert "Candidate Finder" in html
    assert '<a class="candidate-preset is-active" href="/candidate-finder?preset=bull">Bull</a>' in html
    assert '<a class="candidate-preset" href="/candidate-finder?preset=bear">Bear</a>' in html
    assert "Cheap, financially solid names to own if gold rises" in html
    assert "candidate-preset is-active" in html
    assert "Universe" in html
    assert "All stocks" in html
    assert "Screen Builder" in html
    assert "Gold price for ranking" in html
    assert "Financials source" in html
    assert "Apply Gold Scenario" in html
    assert "Gold Sensitivity" in html
    assert "Corporate Finance" in html
    assert "Options" in html
    assert "Corporate Resilience" in html
    assert "Advanced Composites" in html
    assert 'class="candidate-criteria-group" open' in html
    assert "View 1: Top Rows By Criterion" in html
    assert "View 2: Fit Ranking" in html
    assert "Eligible Ranking" in html
    assert "Low-Coverage Rows" in html
    assert "js-datatable candidate-ranking-table" in html
    assert 'data-col-name="score" data-sort-numeric' in html
    assert 'data-col-name="criterion_up_beta" data-sort-numeric' in html
    assert 'data-col-name="criterion_down_beta" data-sort-numeric' not in html
    assert "weighted-average percentile across the criteria you chose" in html
    assert "Model build state needs attention" in html
    assert 'aria-label="Use FCF yield"' in html
    assert "Profit cushion per ounce vs the gold price." in html
    assert "<th>Meaning</th>" in html
    assert "<th>Field</th>" not in html
    assert "<code>aisc_usd_per_oz</code>" not in html
    assert "Mixed refreshes in Candidate Finder sources" in html
    assert "/ticker/AEM?lens=option-trading#option-trading" in html
    assert "recommend" not in html.lower()
    assert "should buy" not in html.lower()


def test_candidate_finder_page_custom_query_preserves_side_direction_and_weight():
    data = _candidate_finder_data()

    html = render_candidate_finder_page(
        data,
        query={
            "custom": ["1"],
            "options_side": ["calls"],
            "top_n": ["1"],
            "criteria": ["up_beta"],
            "direction_up_beta": ["low_good"],
            "weight_up_beta": ["2"],
        },
    )

    assert "Custom criteria are active for this screen." in html
    assert '<option value="calls" selected>Only stocks with calls</option>' in html
    assert '<option value="low_good" selected>Low values fit</option>' in html
    assert 'name="weight_up_beta" min="0" max="10" step="0.25" value="2"' in html
    assert "Invalid direction" not in html
    assert "candidate-preset is-active" not in html


def test_candidate_finder_builder_preserves_gold_price_scenario():
    # Applying custom criteria must NOT reset an active gold scenario: the Screen
    # Builder form carries gold_price forward as a hidden input (audit L2). The gold
    # form renders gold_price as a visible number input, so a hidden one is uniquely
    # the builder's preservation.
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data, query={"custom": ["1"], "gold_price": ["3500"]})

    assert '<input type="hidden" name="gold_price" value="3500">' in html


def test_candidate_finder_page_renders_beta_window_selector():
    # Victor's per-horizon screening: the Finder exposes a gold-beta horizon picker that
    # defaults to the cross-window blend and labels 12M as "1Y" (registry rule).
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data)

    assert 'name="beta_window"' in html
    assert "Blend (6M / 1Y / 3Y)" in html
    assert ">1Y</option>" in html
    assert ">12M</option>" not in html
    assert "cross-window blend" in html


def test_candidate_finder_page_beta_window_selected_and_preserved():
    # Picking a window marks it selected, states the basis, and is carried as a hidden input
    # through the other forms (gold scenario / builder) so it is not silently dropped.
    data = replace(_candidate_finder_data(), beta_window="3Y")

    html = render_candidate_finder_page(
        data, query={"beta_window": ["3y"], "gold_price": ["3500"]}
    )

    assert '<option value="3y" selected>3Y</option>' in html
    assert "rank on the 3Y window" in html
    assert '<input type="hidden" name="beta_window" value="3y">' in html


def test_preset_links_preserve_beta_window():
    # Regression (fleet review HIGH): clicking a preset must NOT silently drop the selected
    # gold-beta horizon and revert the screen to the blend. The preset href carries beta_window
    # the same way it carries gold_price / fundamentals_source.
    href = _preset_href(
        base_path="/candidate-finder",
        preset_id="bear",
        query={"beta_window": ["6m"], "gold_price": ["3500"], "fundamentals_source": ["yahoo"]},
    )

    assert "preset=bear" in href
    assert "beta_window=6m" in href
    assert "gold_price=3500" in href
    assert "fundamentals_source=yahoo" in href


def test_criterion_help_keys_resolve_and_cover_every_criterion():
    # Guardrail: every criterion->help-key mapping must resolve in the registry (no typo/rename
    # drift), and every configured criterion must be mapped so its 'Value' info button describes
    # the real metric (a new unmapped criterion would silently fall back to its terse description).
    from golden_vector.serve.candidate_finder_page import _CRITERION_HELP_KEYS
    from golden_vector.serve.column_help import COLUMN_HELP

    for crit_id, key in _CRITERION_HELP_KEYS.items():
        assert key in COLUMN_HELP, f"{crit_id} -> {key} missing from COLUMN_HELP"

    config = _repo_app_config().candidate_finder
    unmapped = [c.id for c in config.criteria if c.id not in _CRITERION_HELP_KEYS]
    assert not unmapped, f"criteria missing a rich help mapping: {unmapped}"


def test_top_list_value_tooltip_uses_rich_metric_help_not_generic():
    # Victor's fix: the 'Value' info button must explain the actual metric, not a generic
    # "raw value for this criterion" line. The default Bull screen selects up_beta, so its rich
    # help (regression on up weeks) must appear, and the generic string must be gone everywhere.
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data, app_config=_repo_app_config())

    assert "raw value for this criterion" not in html
    assert "up markets" in html  # from tool_c_up_beta's meaning, wired via _CRITERION_HELP_KEYS


def test_candidate_finder_route_threads_beta_window_to_loader(monkeypatch, tmp_path):
    # Regression: the route must parse ?beta_window and pass it to the loader (else the selector
    # renders but always screens on the blend).
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()

    import golden_vector.serve.workspace as workspace_module

    captured: dict[str, object] = {}

    def capturing_loader(_paths, *, app_config, scenario=None, fundamentals_source="our", beta_window=None):
        captured["beta_window"] = beta_window
        return _candidate_finder_data()

    monkeypatch.setattr(workspace_module, "load_candidate_finder_data", capturing_loader)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    _call_wsgi_app(app, method="GET", path="/candidate-finder?beta_window=3y")

    assert captured["beta_window"] == "3y"


def test_candidate_finder_page_renders_scenario_status_and_preserves_query():
    data = _candidate_finder_data()
    data = CandidateFinderData(
        frame=data.frame,
        criteria_config=data.criteria_config,
        alignment=data.alignment,
        cache_key=data.cache_key,
        model_state_manifest=data.model_state_manifest,
        gold_price_used=3500.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_basis="custom_scenario",
        rank_basis="custom_gold_scenario",
        scenario_requested_gold_price=3500.0,
        scenario_active=True,
    )

    html = render_candidate_finder_page(
        data,
        query={"preset": ["bear"], "gold_price": ["3500"], "options_side": ["puts"]},
    )

    assert "Scenario ranks gold-dependent fundamentals at $3,500/oz" in html
    assert "/candidate-finder?preset=bull&amp;gold_price=3500" in html
    assert "/candidate-finder?preset=bear&amp;gold_price=3500" in html
    assert 'name="preset" value="bear"' in html
    assert 'name="options_side" value="puts"' in html
    assert 'name="gold_price" min="1" step="1" value="3500"' in html
    assert "/candidate-finder?preset=bear&amp;options_side=puts" in html


def test_candidate_finder_page_preserves_yahoo_fundamentals_source():
    data = _candidate_finder_data()
    data = CandidateFinderData(
        frame=data.frame,
        criteria_config=data.criteria_config,
        alignment=data.alignment,
        cache_key=data.cache_key,
        model_state_manifest=data.model_state_manifest,
        gold_price_used=4000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_basis="latest_daily_gold_close",
        rank_basis="latest_daily_gold_close_yahoo_fundamentals",
        fundamentals_source="yahoo",
        scenario_active=True,
    )

    html = render_candidate_finder_page(
        data,
        query={"fundamentals_source": ["yahoo"], "gold_price": ["4000"]},
    )

    assert (
        '<option value="yahoo" selected>Yahoo Fundamentals</option>'
        in html
    )
    assert "Yahoo Fundamentals recalculates finance-dependent ranking" in html
    assert "/candidate-finder?preset=bull&amp;gold_price=4000&amp;fundamentals_source=yahoo" in html
    assert "/ticker/AEM?lens=option-trading&amp;fundamentals_source=yahoo#option-trading" in html


def test_candidate_finder_page_source_only_yahoo_switch_does_not_submit_spot_as_custom_gold():
    data = _candidate_finder_data()
    data = CandidateFinderData(
        frame=data.frame,
        criteria_config=data.criteria_config,
        alignment=data.alignment,
        cache_key=data.cache_key,
        model_state_manifest=data.model_state_manifest,
        gold_price_used=4000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_basis="latest_daily_gold_close",
        rank_basis="latest_daily_gold_close_yahoo_fundamentals",
        fundamentals_source="yahoo",
        scenario_active=True,
        scenario_requested_gold_price=None,
    )

    html = render_candidate_finder_page(
        data,
        query={"fundamentals_source": ["yahoo"]},
    )

    assert 'name="gold_price" min="1" step="1" value=""' in html
    assert "/candidate-finder?preset=bull&amp;fundamentals_source=yahoo" in html
    assert "/candidate-finder?preset=bull&amp;gold_price=" not in html
    assert "Reset gold price to spot" in html


def test_candidate_finder_page_bear_screen_has_direction_neutral_copy():
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data, query={"preset": ["bear"]})

    assert '<a class="candidate-preset is-active" href="/candidate-finder?preset=bear">Bear</a>' in html
    assert "Fragile names likely to fall hardest if gold falls." in html
    assert "Debt load vs earnings. High values rank higher." in html
    assert "Lower debt burden. High values rank higher." not in html
    assert 'data-col-name="criterion_down_beta" data-sort-numeric' in html
    assert 'data-col-name="criterion_up_beta" data-sort-numeric' not in html


def test_candidate_finder_page_invalid_preset_falls_back_to_default():
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data, query={"preset": ["banana"]})

    assert '<a class="candidate-preset is-active" href="/candidate-finder?preset=bull">Bull</a>' in html
    assert 'is-active" href="/candidate-finder?preset=bear"' not in html
    assert "Pick at least one criterion" not in html
    assert "Unknown preset ignored" not in html


@pytest.mark.parametrize(
    ("legacy_preset", "active_preset"),
    [
        ("bearish_put", "bear"),
        ("bullish_call", "bull"),
        ("strong_corporate_finance", "bull"),
    ],
)
def test_candidate_finder_page_maps_retired_preset_urls(legacy_preset, active_preset):
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data, query={"preset": [legacy_preset]})

    assert (
        f'<a class="candidate-preset is-active" href="/candidate-finder?preset={active_preset}">'
        in html
    )


def test_candidate_finder_page_url_encodes_ticker_links():
    data = _candidate_finder_data()
    data.frame.loc[0, "ticker"] = "A&B"

    html = render_candidate_finder_page(data)

    assert ">A&amp;B</a>" in html
    assert "/ticker/A%26B?lens=option-trading#option-trading" in html


def test_candidate_finder_route_is_reachable(monkeypatch, tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()

    import golden_vector.serve.workspace as workspace_module

    monkeypatch.setattr(
        workspace_module,
        "load_candidate_finder_data",
        lambda _paths, *, app_config, scenario=None, fundamentals_source="our", beta_window=None: _candidate_finder_data(),
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    response = _call_wsgi_app(app, method="GET", path="/candidate-finder")

    assert response["status"].startswith("200")
    assert "Candidate Finder" in response["body"]
    assert "Candidate Finder</a>" in response["body"]


def test_candidate_finder_route_rejects_nonfinite_gold_price(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    response = _call_wsgi_app(
        app,
        method="GET",
        path="/candidate-finder?gold_price=inf",
    )

    assert response["status"].startswith("400")
    assert "gold_price must be a finite positive number" in response["body"]


def _candidate_finder_data() -> CandidateFinderData:
    frame = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "has_usable_put_candidate": True,
                "has_usable_call_candidate": True,
                "down_beta_core": 1.5,
                "up_beta_core": 1.2,
                "aisc_usd_per_oz": 1450.0,
                "leverage": 0.18,
                "margin_pct": 0.60,
                "ev_ebitda": 4.2,
                "forward_pe": 8.0,
                "iv_percentile_cross_sectional": 30.0,
                "confidence_score": 0.92,
                "fcf_yield": 0.05,
                "reserve_life_years": 12.0,
                "fundamental_check_score": 85.7143,
                "interest_cover_gold_usd": 1500.0,
                "debt_stress_gold_usd": 1300.0,
                "fcf_breakeven_gold_usd": 1700.0,
                "cost_curve_aisc_percentile": 40.0,
                "tool_c_downside_rank": 95.0,
                "tool_c_upside_rank": 80.0,
                "tool_d_quality_rank": 60.0,
                "score_eligible": True,
            },
            {
                "ticker": "NEM",
                "has_usable_put_candidate": True,
                "has_usable_call_candidate": False,
                "down_beta_core": 1.2,
                "up_beta_core": 1.0,
                "aisc_usd_per_oz": 1250.0,
                "leverage": 0.10,
                "margin_pct": 0.68,
                "ev_ebitda": 3.8,
                "forward_pe": 7.0,
                "iv_percentile_cross_sectional": 55.0,
                "confidence_score": 0.84,
                "fcf_yield": 0.03,
                "reserve_life_years": 18.0,
                "fundamental_check_score": 100.0,
                "interest_cover_gold_usd": 1200.0,
                "debt_stress_gold_usd": 1100.0,
                "fcf_breakeven_gold_usd": 1400.0,
                "cost_curve_aisc_percentile": 20.0,
                "tool_c_downside_rank": 70.0,
                "tool_c_upside_rank": 55.0,
                "tool_d_quality_rank": 85.0,
                "score_eligible": True,
            },
        ]
    )
    return CandidateFinderData(
        frame=frame,
        criteria_config=_repo_app_config().candidate_finder,
        alignment=CandidateFinderAlignment(
            status="WARN",
            message="Mixed refreshes in Candidate Finder sources.",
            tool_a_refresh_run_ids=("tool-a-run",),
            tool_b_refresh_run_ids=("tool-b-run",),
            tool_c_refresh_run_ids=("tool-c-run",),
            tool_d_refresh_run_ids=("tool-d-run",),
            options_refresh_run_id="options-run",
            manual_store_hash="manual-hash",
            manual_store_as_of="2026-06-04T09:00:00Z",
            messages=("Mixed refreshes in Candidate Finder sources.",),
        ),
        cache_key=CandidateFinderCacheKey(
            tool_a_refresh_run_ids=("tool-a-run",),
            tool_b_refresh_run_ids=("tool-b-run",),
            tool_c_refresh_run_ids=("tool-c-run",),
            tool_d_refresh_run_ids=("tool-d-run",),
            options_refresh_run_id="options-run",
            manual_store_hash="manual-hash",
            tool_a_latest_hash="tool-a-hash",
            tool_b_latest_hash="tool-b-hash",
            tool_c_latest_hash="tool-c-hash",
            tool_d_latest_hash="tool-d-hash",
        ),
    )


def _repo_app_config():
    return load_app_config(ProjectPaths.discover()).app


def _call_wsgi_app(app, *, method: str, path: str) -> dict[str, str]:
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    if "?" in path:
        path_info, _, query_string = path.partition("?")
    else:
        path_info, query_string = path, ""

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
        "CONTENT_LENGTH": "0",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    body = b"".join(app(environ, start_response)).decode("utf-8")
    return {"status": str(captured["status"]), "body": body}


def _resolved_criterion(criterion_id: str, source_field: str = "f"):
    from golden_vector.model.candidate_finder import ResolvedCriterion

    return ResolvedCriterion(
        id=criterion_id,
        label="x",
        description="d",
        source_field=source_field,
        group="g",
        direction="high_good",
        weight=1.0,
    )


def test_beta_criterion_help_keys_match_blend_vs_window_basis():
    """Beta criteria show the cross-window blend by default and a single window when picked; the
    info-button help key must follow so the basis label always matches the displayed value."""
    from golden_vector.serve.candidate_finder_page import _criterion_help_key

    # Default cross-window blend (source_field ends in _core) -> blend-basis help keys.
    assert _criterion_help_key(_resolved_criterion("down_beta", "down_beta_core")) == "tool_c_down_beta_blend"
    assert _criterion_help_key(_resolved_criterion("up_beta", "up_beta_core")) == "tool_c_up_beta_blend"
    assert _criterion_help_key(_resolved_criterion("gold_beta_core", "structural_delta_core")) == "tool_a_delta_blend"
    # A single picked window -> plain per-window help keys (which describe one window).
    assert _criterion_help_key(_resolved_criterion("down_beta", "down_beta_6m")) == "tool_c_down_beta"
    assert _criterion_help_key(_resolved_criterion("up_beta", "up_beta_1y")) == "tool_c_up_beta"
    assert _criterion_help_key(_resolved_criterion("gold_beta_core", "structural_delta_3y")) == "tool_a_delta"
    # Non-beta criteria are unaffected.
    assert _criterion_help_key(_resolved_criterion("aisc", "aisc_usd_per_oz")) == "tool_b_aisc"


def test_finder_value_column_scales_percent_criteria():
    """margin_pct / fcf_yield are stored as fractions; the Value cell must render them as percents
    so it agrees with the metric its info button explains (and the same metric on the other tools)."""
    from golden_vector.serve.candidate_finder_page import _fmt_criterion_value

    assert _fmt_criterion_value(_resolved_criterion("margin_pct"), 0.571) == "57.1%"
    assert _fmt_criterion_value(_resolved_criterion("fcf_yield"), 0.3935) == "39.4%"
    # Registered Tool B criteria use the same compact formatter as the other Tool B surfaces.
    assert _fmt_criterion_value(_resolved_criterion("ev_ebitda"), 7.31) == "7.3"
    # Unknown criteria fall back to the generic 2-decimal number.
    assert _fmt_criterion_value(_resolved_criterion("custom_metric"), 7.31) == "7.31"


def test_candidate_finder_page_renders_saved_confirmation():
    from golden_vector.serve.http_helpers import _flash_message

    html = render_candidate_finder_page(_candidate_finder_data(), query={"saved": ["company"]})

    assert "notice notice-success" in html
    assert _flash_message("company") in html


def test_candidate_finder_page_ignores_unknown_saved_token():
    html = render_candidate_finder_page(_candidate_finder_data(), query={"saved": ["bogus"]})

    assert "notice notice-success" not in html
