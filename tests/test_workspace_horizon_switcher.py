"""Tests for the Tool A detail-page horizon switcher (6M / 12M / 3Y).

Covers:
  T1  window resolver — URL param mapping, fallbacks, canonical anchor recovery
  T2  window switcher HTML — three tabs, active + canonical markers
  T3  backward-compat — no query param renders the canonical anchor
  T4  window param routes the active_window through to scorecards
  T5  switching windows changes the delta/gamma scorecards
  T6  scatter panel hint adapts to the active window
  T7  up/down beta panel hint adapts to the active window
  T8  narrative cards regenerate from live band math (single source of truth)
  T9  volatility panel suppresses numbers when the window is not ELIGIBLE
  T10 volatility panel renders for a canonical-matching eligible window
  T11 rolling chart renders one <polyline> per window when all three have history
  T12 structural window table flags the active row with the active-row class
  T13 mismatch banner appears when active != canonical
  T14 invalid window param falls back to canonical without 500
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.serve.detail_panels import (
    _canonical_anchor_window,
    _resolve_active_window,
    _render_window_switcher,
    _render_structural_window_table,
)
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths
from tests.test_workspace_app import (
    _call_wsgi_app,
    _repo_app_config,
    _write_latest_foundation_snapshot,
    _write_latest_outputs,
    bootstrap_manual_screening_data,
)


# ---------------------------------------------------------------- T1 ----

def test_resolve_active_window_uses_url_param_case_insensitive():
    assert _resolve_active_window("6m", "12M") == "6M"
    assert _resolve_active_window("12M", "12M") == "12M"
    assert _resolve_active_window("3y", "12M") == "3Y"


def test_resolve_active_window_falls_back_to_canonical_for_invalid_values():
    assert _resolve_active_window("", "12M") == "12M"
    assert _resolve_active_window("9M", "6M") == "6M"
    assert _resolve_active_window("garbage", "3Y") == "3Y"


def test_resolve_active_window_recovers_when_canonical_is_malformed():
    # If the ticker somehow has an invalid anchor_window_id, fall back to 12M.
    assert _resolve_active_window("", "SEMIANNUAL") == "12M"


def test_canonical_anchor_window_defaults_to_12m_when_missing():
    assert _canonical_anchor_window({}) == "12M"
    assert _canonical_anchor_window({"anchor_window_id": None}) == "12M"
    assert _canonical_anchor_window({"anchor_window_id": float("nan")}) == "12M"
    assert _canonical_anchor_window({"anchor_window_id": "foobar"}) == "12M"
    assert _canonical_anchor_window({"anchor_window_id": "3y"}) == "3Y"


# ---------------------------------------------------------------- T2 ----

def test_window_switcher_renders_three_tabs_and_marks_active_and_canonical():
    html = _render_window_switcher(ticker="NEM", active="6M", canonical="12M")
    # Three tabs present.
    for window in ("6M", "12M", "3Y"):
        assert f">{window}" in html
    # Active tab marked with the active class.
    assert 'class="window-tab active"' in html
    # Canonical tab carries the 'anchor' marker.
    assert "window-canonical" in html
    # Mismatch banner appears when active != canonical.
    assert 'class="hint window-mismatch"' in html


def test_window_switcher_has_no_mismatch_banner_when_active_equals_canonical():
    html = _render_window_switcher(ticker="NEM", active="12M", canonical="12M")
    assert 'class="hint window-mismatch"' not in html


def test_window_switcher_preserves_option_sizing_contracts_state():
    # Clicking a window tab must keep the option sizing calculator state (audit L3).
    from golden_vector.hedge.option_trading import OptionSizingRequest

    req = OptionSizingRequest(
        side="call", horizon_days=180, horizon_explicit=True,
        bucket="directional", size_mode="contracts", quantity=7, size_explicit=True,
    )
    html = _render_window_switcher(
        ticker="NEM", active="6M", canonical="12M",
        lens="option-trading", anchor="option-trading", sizing_request=req,
    )
    assert "side=call" in html
    assert "horizon=180" in html
    assert "bucket=directional" in html
    assert "quantity=7" in html


def test_window_switcher_preserves_budget_mode_and_omits_quantity():
    from golden_vector.hedge.option_trading import OptionSizingRequest

    req = OptionSizingRequest(side="put", size_mode="budget", budget=500.0, size_explicit=True)
    html = _render_window_switcher(
        ticker="NEM", active="6M", canonical="12M", lens="option-trading", sizing_request=req,
    )
    assert "size_mode=budget" in html
    assert "budget=500" in html
    assert "quantity=" not in html  # contracts-only param omitted in budget mode


def test_window_switcher_omits_non_explicit_horizon():
    # A non-explicit horizon must NOT be pinned, so the backend most-liquid default
    # still drives the detail page after a window switch.
    from golden_vector.hedge.option_trading import OptionSizingRequest

    req = OptionSizingRequest(side="put", horizon_days=90, horizon_explicit=False)
    html = _render_window_switcher(
        ticker="NEM", active="6M", canonical="12M", lens="option-trading", sizing_request=req,
    )
    assert "horizon=" not in html


def test_window_switcher_omits_silent_default_sizing():
    # A default sizing request (user touched nothing) must not pollute tab URLs.
    from golden_vector.hedge.option_trading import OptionSizingRequest

    html = _render_window_switcher(
        ticker="NEM", active="6M", canonical="12M",
        lens="option-trading", sizing_request=OptionSizingRequest(),
    )
    assert "side=" not in html
    assert "quantity=" not in html
    assert "horizon=" not in html


# ---------------------------------------------------------------- T3 ----

def test_detail_page_without_window_param_defaults_to_canonical_anchor(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)  # canonical anchor = 12M

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    # The 12M-specific scorecard label must appear.
    assert "Structural Delta (12M)" in body
    # 12M is the canonical anchor, so no mismatch banner should show.
    # Check for the banner paragraph, not the CSS class selector block.
    assert 'class="hint window-mismatch"' not in body


# ---------------------------------------------------------------- T4, T5 ----

def test_detail_page_with_6m_window_param_renders_6m_scorecards(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=6m")
    body = response["body"]
    assert "Structural Delta (6M)" in body
    assert "Gamma Down-Up (6M)" in body
    # Mismatch banner: user picked 6M but canonical is 12M.
    assert 'class="hint window-mismatch"' in body
    assert "canonical anchor" in body


def test_detail_page_with_3y_window_param_renders_3y_scorecards(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=3y")
    body = response["body"]
    assert "Structural Delta (3Y)" in body
    assert "Gamma Down-Up (3Y)" in body


# ---------------------------------------------------------------- T6, T7 ----

def test_scatter_panel_hint_adapts_to_active_window():
    """Unit test: the scatter panel's hint / empty-state text must name the
    active window (not the ticker's canonical anchor). Tested at the render-
    function layer because the WSGI fixture does not ship a weekly-return
    sample for the scatter SVG path.
    """
    from golden_vector.serve.detail_panels import _render_scatter_panel
    # Empty-state path: references the active window.
    html_empty = _render_scatter_panel(
        ticker="NEM",
        tool_a_row={"anchor_window_id": "12M"},
        anchor_metric={},
        anchor_sample=pd.DataFrame(),
        active_window="6M",
    )
    assert "6M window" in html_empty
    # Populated path: hint text references the active window, not anchor.
    sample = pd.DataFrame(
        {
            "gold_weekly_log_return": [0.01, -0.02, 0.03, -0.01, 0.005, 0.0],
            "stock_weekly_log_return": [0.02, -0.03, 0.04, -0.015, 0.008, -0.001],
        }
    )
    html_live = _render_scatter_panel(
        ticker="NEM",
        tool_a_row={"anchor_window_id": "12M"},
        anchor_metric={"structural_delta": 1.8, "intercept_alpha": 0.0},
        anchor_sample=sample,
        active_window="3Y",
    )
    # Hint names the ACTIVE window (3Y), not the ticker's canonical anchor (12M).
    assert "3Y sample" in html_live
    assert "12M sample" not in html_live


def test_up_down_beta_panel_hint_adapts_to_active_window():
    from golden_vector.serve.detail_panels import _render_up_down_beta_panel
    html = _render_up_down_beta_panel(
        {"anchor_window_id": "12M"},
        anchor_metric={"up_beta": 2.0, "down_beta": 1.5},
        active_window="3Y",
    )
    # Hint names the ACTIVE window (3Y), not the ticker's canonical anchor (12M).
    assert "3Y sample" in html
    assert "12M sample" not in html


# ---------------------------------------------------------------- T8 ----

def test_narrative_cards_regenerate_from_live_band_math(tmp_path):
    """The workspace must NOT read the pre-baked `*_explanation` fields on the
    Tool A row. Instead it regenerates each card live from numeric inputs +
    band thresholds (single source of truth = model/explanations.py). This
    guards against future drift between the pipeline's cached narratives
    and what the user actually sees.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            # Pre-baked explanation claims "Negative gamma" but live fields say
            # gamma_12m = 0.35 (very positive). The workspace should print the
            # live text, not the stale pre-bake.
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 22),
                "anchor_window_id": "12M",
                "volatility_anchor_window_id": "12M",
                "structural_delta_6m": 1.6,
                "structural_delta_12m": 1.7,
                "structural_delta_3y": 1.5,
                "structural_delta_core": 1.7,
                "gamma_6m": 0.32,
                "gamma_12m": 0.35,
                "gamma_3y": 0.30,
                "structural_gamma_core": 0.35,
                "up_beta_6m": 1.3,
                "down_beta_6m": 1.7,
                "up_beta_12m": 1.4,
                "down_beta_12m": 1.8,
                "up_beta_3y": 1.2,
                "down_beta_3y": 1.6,
                "up_beta_core": 1.4,
                "down_beta_core": 1.8,
                "asymmetry_ratio_6m": 0.76,
                "asymmetry_ratio_12m": 0.78,
                "asymmetry_ratio_3y": 0.75,
                "asymmetry_ratio_core": 0.78,
                "r_squared_6m": 0.45,
                "r_squared_12m": 0.42,
                "r_squared_3y": 0.39,
                "weeks_6m": 26,
                "weeks_12m": 52,
                "weeks_3y": 156,
                "window_status_6m": "ELIGIBLE",
                "window_status_12m": "ELIGIBLE",
                "window_status_3y": "ELIGIBLE",
                "total_volatility_52w": 0.36,
                "residual_volatility_52w": 0.28,
                "downside_volatility_52w": 0.24,
                "volatility_context": "LOW_NOISE",
                "delta_stability_score": 0.85,
                "confidence_score": 0.78,
                "confidence_label": "MODERATE",
                "profile_label": "FRAGILE",
                "tool_a_score": 64.2,
                "tool_a_rank": 1,
                "score_eligible": True,
                "score_eligibility_reason": "OK",
                "eligible_structural_window_count": 3,
                "positive_delta_window_count": 3,
                "normalization_issue_summary": None,
                "snapshot_refresh_run_id": "refresh-run",
                "fx_policy_max_staleness_days": 5,
                "fx_policy_block_on_stale_fx": False,
                # Stale pre-baked text — workspace must NOT use this.
                "delta_explanation": "PRE_BAKED_STALE_TEXT",
                "gamma_explanation": "PRE_BAKED_STALE_TEXT",
                "asymmetry_explanation": "PRE_BAKED_STALE_TEXT",
                "volatility_explanation": "PRE_BAKED_STALE_TEXT",
                "confidence_explanation": "PRE_BAKED_STALE_TEXT",
                "interaction_explanation": "PRE_BAKED_STALE_TEXT",
                "tool_a_summary_explanation": "PRE_BAKED_STALE_TEXT",
                "source_run_id": "tool-a-run",
            }
        ],
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    # Regenerated text must appear.
    assert "Positive gamma means sensitivity has been stronger in down-gold weeks" in body
    # Stale pre-baked text must NOT appear anywhere.
    assert "PRE_BAKED_STALE_TEXT" not in body


# ---------------------------------------------------------------- T9, T10 ----

def test_volatility_panel_suppresses_numbers_when_window_not_eligible(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 22),
                "anchor_window_id": "12M",
                "volatility_anchor_window_id": "12M",
                "structural_delta_6m": None,
                "structural_delta_12m": 1.9,
                "structural_delta_3y": 1.7,
                "structural_delta_core": 1.9,
                "window_status_6m": "INELIGIBLE_LOW_OBSERVATIONS",
                "window_status_12m": "ELIGIBLE",
                "window_status_3y": "ELIGIBLE",
                "gamma_12m": -0.22,
                "up_beta_12m": 2.1,
                "down_beta_12m": 1.5,
                "asymmetry_ratio_12m": 1.4,
                "weeks_12m": 52,
                "r_squared_12m": 0.42,
                "total_volatility_52w": 0.36,
                "residual_volatility_52w": 0.28,
                "downside_volatility_52w": 0.24,
                "volatility_context": "LOW_NOISE",
                "confidence_label": "HIGH",
                "confidence_score": 0.82,
                "profile_label": "CONVEX",
                "tool_a_score": 85.0,
                "tool_a_rank": 1,
                "score_eligible": True,
                "score_eligibility_reason": "OK",
                "snapshot_refresh_run_id": "refresh-run",
                "source_run_id": "tool-a-run",
            }
        ],
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=6m")
    body = response["body"]
    # Volatility panel must explicitly say the window is not eligible.
    assert "Volatility Diagnostics (6M)" in body
    assert "is not eligible for this ticker" in body


def test_volatility_panel_renders_numbers_for_canonical_eligible_window(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)  # 12M is canonical and ELIGIBLE

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert "Volatility Diagnostics (12M)" in body
    assert "Volatility Context" in body
    assert "is not eligible for this ticker" not in body


# ---------------------------------------------------------------- T11 ----

def test_rolling_chart_default_draws_only_active_window_line(tmp_path):
    """Post-legend-toggle default: only the active window's line is drawn.
    The other two windows appear in the legend as opt-in toggle links so the
    user can add or remove them one at a time.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_multi_window_structural_history(paths, ticker="NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    # Exactly one line (the active 12M one) drawn.
    assert body.count("<polyline points=") == 1
    # Two hidden toggle <a> legend links present for the other two windows.
    assert body.count('class="chart-legend-item chart-legend-link"') == 2
    # Active window labeled.
    assert "12M (active)" in body


def test_rolling_chart_honors_show_param_to_add_lines(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_multi_window_structural_history(paths, ticker="NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    # Explicitly show all three windows.
    response = _call_wsgi_app(
        app, method="GET", path="/ticker/NEM?show=6m,3y"
    )
    body = response["body"]
    assert body.count("<polyline points=") == 3


def test_rolling_chart_legend_link_drops_window_from_show_when_visible(tmp_path):
    """When a window is currently visible, its legend link should navigate to
    a URL that removes it from `show=` (toggle off).
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_multi_window_structural_history(paths, ticker="NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    # With 6M shown, the 6M legend link should drop it (→ only window=12m).
    response = _call_wsgi_app(
        app, method="GET", path="/ticker/NEM?show=6m"
    )
    body = response["body"]
    # The 6M legend link should point to a URL WITHOUT 6m in show=.
    assert 'href="/ticker/NEM?window=12m"' in body
    # The 3Y legend link should ADD 3y while keeping 6m (toggle on, preserving context).
    assert 'href="/ticker/NEM?window=12m&amp;show=6m,3y"' in body or "show=6m,3y" in body


# ---------------------------------------------------------------- T12 ----

def test_structural_window_table_marks_the_active_row():
    tool_a_row = {
        "anchor_window_id": "12M",
        "structural_delta_6m": 1.8,
        "structural_delta_12m": 1.9,
        "structural_delta_3y": 1.7,
        "window_status_6m": "ELIGIBLE",
        "window_status_12m": "ELIGIBLE",
        "window_status_3y": "ELIGIBLE",
    }
    html = _render_structural_window_table(tool_a_row, active_window="3Y")
    # Exactly the active row carries the active-row class.
    assert html.count('class="active-row"') == 1
    # 3Y cell is marked as Active; 12M as Anchor.
    assert "3Y (Active)" in html
    assert "12M (Anchor)" in html


# ---------------------------------------------------------------- T13 ----

def test_mismatch_banner_appears_only_when_active_differs_from_canonical(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)  # canonical = 12M

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    # Canonical → no banner.
    canonical_body = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=12m")["body"]
    assert 'class="hint window-mismatch"' not in canonical_body
    # Non-canonical → banner.
    mismatch_body = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=3y")["body"]
    assert 'class="hint window-mismatch"' in mismatch_body


# ---------------------------------------------------------------- T14 ----

def test_invalid_window_param_falls_back_to_canonical_without_error(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=9M")
    assert response["status"].startswith("200")
    body = response["body"]
    # Falls back to canonical (12M).
    assert "Structural Delta (12M)" in body


# ---------------------------------------------------------------- helpers ----

def _write_multi_window_structural_history(paths, *, ticker: str, source_run_id: str):
    """Fixture: write a structural-history parquet with all three windows.

    The real pipeline writes one row per (ticker, as_of_date, window_id). For
    chart tests we need at least two points in each window so the polyline has
    a real segment.
    """
    import numpy as np

    weeks = pd.date_range("2024-06-07", periods=60, freq="W-FRI")
    rows: list[dict] = []
    # Different baseline per window so the lines are visibly distinct.
    for window_id, baseline in (("6M", 1.4), ("12M", 1.7), ("3Y", 2.1)):
        for i, w in enumerate(weeks):
            delta = float(baseline + 0.05 * np.sin((i / 12.0) * 2 * np.pi))
            rows.append(
                {
                    "ticker": ticker,
                    "as_of_date": w.date(),
                    "window_id": window_id,
                    "week_count": {"6M": 26, "12M": 52, "3Y": 156}[window_id],
                    "window_status": "ELIGIBLE",
                    "window_reason": "OK",
                    "structural_delta": delta,
                    "intercept_alpha": 0.001,
                    "r_squared": 0.5,
                    "up_week_count": 25,
                    "down_week_count": 25,
                    "up_beta": baseline + 0.2,
                    "down_beta": baseline - 0.2,
                    "gamma_value": -0.2,
                    "asymmetry_ratio": 1.14,
                    "normalization_issue_summary": None,
                    "source_run_id": source_run_id,
                }
            )
    frame = pd.DataFrame(rows)
    out_path = paths.latest_tool_a_structural_metrics_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_path, index=False)
