"""Tests for the Tool A detail-page horizon switcher (6M / 1Y / 2Y / 3Y / 5Y).

Covers:
  T1  window resolver — URL param mapping, fallbacks, canonical anchor recovery
  T2  window switcher HTML — five tabs, active + canonical markers
  T3  backward-compat — no query param renders the canonical anchor
  T4  window param routes the active_window through to scorecards
  T5  switching windows changes the delta/gamma scorecards
  T6  scatter panel hint adapts to the active window
  T7  up/down beta panel hint adapts to the active window
  T8  narrative cards regenerate from live band math (single source of truth)
  T9  volatility panel suppresses numbers when the window is not ELIGIBLE
  T10 volatility panel renders for a canonical-matching eligible window
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
    assert _resolve_active_window("1y", "6M") == "12M"
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

def test_window_switcher_renders_all_tabs_and_marks_active_and_canonical():
    html = _render_window_switcher(ticker="NEM", active="6M", canonical="12M")
    # All five lookbacks present (12M renders as "1Y").
    for label in ("6M", "1Y", "2Y", "3Y", "5Y"):
        assert f">{label}" in html
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
    # The canonical 12M window renders under the user-facing 1Y label.
    assert "Structural Delta (1Y)" in body
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
    assert "Volatility Diagnostics (1Y)" in body
    assert "Volatility Context" in body
    assert "is not eligible for this ticker" not in body


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
    # 3Y cell is marked as Active; canonical 12M renders as 1Y Anchor.
    assert "3Y (Active)" in html
    assert "1Y (Anchor)" in html


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
    # Falls back to canonical (12M), rendered under the user-facing 1Y label.
    assert "Structural Delta (1Y)" in body



# -------------------------------------------- T15 (horizon consistency) ----

def test_structural_window_table_lists_all_windows_and_flags_display_only():
    row = {"anchor_window_id": "12M"}
    for w in ("6m", "12m", "2y", "3y", "5y"):
        row.update({
            f"structural_delta_{w}": 1.5, f"gamma_{w}": -0.2, f"up_beta_{w}": 1.6,
            f"down_beta_{w}": 1.4, f"asymmetry_ratio_{w}": 1.14, f"r_squared_{w}": 0.5,
            f"weeks_{w}": 52, f"window_status_{w}": "ELIGIBLE",
        })
    html = _render_structural_window_table(row, active_window="3Y")
    # all five lookbacks are listed
    for label in ("6M", "1Y", "2Y", "3Y", "5Y"):
        assert f"<td>{label}" in html
    # 2Y/5Y rows are flagged display-only; scoring windows are not
    assert "2Y (display-only)" in html
    assert "5Y (display-only)" in html
    assert "6M (display-only)" not in html
    assert "3Y (Active)" in html


def test_detail_page_is_horizon_consistent_with_no_silent_mixing(tmp_path):
    """Pick a horizon (2Y) -> every descriptive metric is that horizon, while
    Score/Confidence/Profile are an explicitly-labelled cross-window summary (never
    faked per-window). This is the anti-mixing guarantee for the detail page.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    body = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=2y")["body"]

    # Descriptive cards follow the selected horizon.
    assert "Structural Delta (2Y)" in body
    assert "Volatility Context (2Y)" in body
    # Score/Confidence/Profile are a labelled cross-window summary, NOT faked as 2Y.
    assert "Across scoring windows" in body
    assert "do not change with the horizon switcher" in body
    assert "Gold Sensitivity Score" in body
    assert "Gold Sensitivity Score (2Y)" not in body
    # The all-lookbacks reference table marks the display-only windows.
    assert "display-only" in body


def test_detail_page_splits_per_window_narrative_from_cross_window_block(tmp_path):
    """Regression (live-verify sweep, Root Cause A): the per-window narrative cards
    (Delta/Gamma/Asymmetry/Volatility) must render UNDER the active-window block, never
    beneath the cross-window 'do not change with the horizon switcher' banner — which
    previously made the page contradict itself (per-window prose flipping while the banner
    promised invariance). The cross-window narrative (Confidence/Interaction/Summary) stays
    under the cross-window block.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    body = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=2y")["body"]

    per_window_hint = "These read-outs describe the active window"
    invariant_hint = "do not change with the horizon switcher"
    assert per_window_hint in body
    assert invariant_hint in body
    # Per-window narrative + its hint sit BEFORE the cross-window invariance banner.
    assert body.index(per_window_hint) < body.index(invariant_hint)
    assert body.index("<h3>Delta</h3>") < body.index(invariant_hint)
    assert body.index("<h3>Volatility</h3>") < body.index(invariant_hint)
    # Cross-window narrative sits AFTER the banner (it really is invariant).
    assert body.index(invariant_hint) < body.index("<h3>Interaction</h3>")
    assert body.index(invariant_hint) < body.index("<h3>Summary</h3>")


def test_detail_page_uses_1y_label_not_raw_12m_anywhere(tmp_path):
    """Regression (live-verify sweep, Root Cause B): the 12M window must surface as its
    display label '1Y' everywhere user-facing — including the active-window narrative prose
    and the Canonical Anchor card. The raw '12M' id must never leak, and the misleading
    'anchor window' wording is gone (the active window is not always the canonical anchor).
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    body = _call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]

    # Default window renders as 1Y in the narrative prose...
    assert "in the 1Y window" in body
    # ...and the raw id / old wording must not leak anywhere user-facing.
    assert "12M anchor window" not in body
    assert "12M window" not in body
    assert "anchor window" not in body
    # Canonical Anchor card is present and shows the LABEL ('1Y'), not the raw '12M' id — assert
    # the exact card so a regression of the anchor-card label mapping fails here.
    assert "Canonical Anchor" in body
    assert "<h3>Canonical Anchor</h3><p>1Y</p>" in body


def test_interaction_summary_use_cross_window_volatility_not_active_window():
    # Regression (fleet review): Interaction + Summary are CROSS-WINDOW cards rendered under the
    # "does not change with the horizon switcher" banner, so they must read the PUBLISHED
    # cross-window volatility_context, never the active-window recompute. Previously they flipped
    # per window for CONVEX tickers whose volatility band crossed between windows.
    from golden_vector.serve.detail_panels import _build_active_window_explanations

    scoring_config = _repo_app_config().scoring
    row = {
        "score_eligible": True,
        "score_eligibility_reason": "OK",
        "profile_label": "CONVEX",
        "confidence_label": "HIGH",
        "confidence_score": 0.9,
        "volatility_context": "LOW_NOISE",  # published cross-window value
        "structural_delta_core": 2.0,
        "structural_gamma_core": -0.1,
        "asymmetry_ratio_core": 1.5,
    }
    # Active-window recompute says HIGH_NOISE at 5Y but LOW_NOISE at 1Y — the per-window
    # Volatility card SHOULD reflect that; Interaction/Summary must NOT.
    at_5y = dict(_build_active_window_explanations(
        tool_a_row=row, active_window="5Y", scoring_config=scoring_config,
        volatility_diag={"volatility_context": "HIGH_NOISE"}))
    at_1y = dict(_build_active_window_explanations(
        tool_a_row=row, active_window="12M", scoring_config=scoring_config,
        volatility_diag={"volatility_context": "LOW_NOISE"}))

    assert at_5y["Interaction"] == at_1y["Interaction"]
    assert at_5y["Summary"] == at_1y["Summary"]
    # Control: the per-window Volatility card DOES track the active-window context (so the test
    # would fail if the builder ignored the active window entirely).
    assert at_5y["Volatility"] != at_1y["Volatility"]


def test_explanation_card_partition_is_exhaustive_and_disjoint():
    # Regression (fleet review): the per-window / cross-window split is by exact title membership.
    # A future title rename/addition not reflected in the two constants would silently drop a card
    # from BOTH grids ("never silently hide results"). Lock the partition against the builder.
    from golden_vector.serve.detail_panels import (
        _CROSS_WINDOW_EXPLANATION_TITLES,
        _PER_WINDOW_EXPLANATION_TITLES,
        _build_active_window_explanations,
    )

    cards = _build_active_window_explanations(
        tool_a_row={"score_eligible": True, "score_eligibility_reason": "OK"},
        active_window="12M",
        scoring_config=_repo_app_config().scoring,
        volatility_diag={},
    )
    returned = {title for title, _ in cards}
    per = set(_PER_WINDOW_EXPLANATION_TITLES)
    cross = set(_CROSS_WINDOW_EXPLANATION_TITLES)

    assert per.isdisjoint(cross), "a card title is in both grids"
    assert per | cross == returned, "every narrative card must be categorized (none silently dropped)"


def test_resolve_active_window_honors_1y_alias_not_canonical_fallback():
    # Regression (Codex review): ?window=1y must resolve to 12M, NOT fall back to the
    # ticker's canonical anchor. Use a non-12M canonical so the bug would be visible.
    assert _resolve_active_window("1y", "6M") == "12M"
    assert _resolve_active_window("1Y", "3Y") == "12M"
    # Invalid still falls back to the canonical anchor.
    assert _resolve_active_window("nonsense", "6M") == "6M"
