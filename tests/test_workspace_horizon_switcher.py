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
)
from golden_vector.serve.ticker_page.behaviour import (
    _MEASURED_EXPLANATION_TITLES,
    _build_measured_beta_explanations,
    render_structural_window_table,
    render_up_down_beta_panel,
    render_window_switcher,
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
    html = render_window_switcher(ticker="NEM", active="6M", canonical="12M")
    # All five lookbacks present (12M renders as "1Y").
    for label in ("6M", "1Y", "2Y", "3Y", "5Y"):
        assert f">{label}" in html
    # Active tab marked with the active class.
    assert 'class="window-tab active"' in html
    # Canonical tab carries the 'anchor' marker.
    assert "window-canonical" in html
    # Mismatch banner appears when active != canonical, naming both windows and
    # nothing about the removed score / confidence / profile.
    assert 'class="hint window-mismatch"' in html
    assert (
        "Viewing 6M — the canonical anchor window for this ticker is 1Y."
    ) in html
    # M3c: it is a labelled control group inside the section header, not a panel,
    # the active tab is announced, and every tab anchors back at the section.
    assert '<div class="window-switcher" role="group" aria-label="Beta window">' in html
    assert 'aria-current="true"' in html
    assert html.count("#market-behaviour") == 5


def test_window_switcher_has_no_mismatch_banner_when_active_equals_canonical():
    html = render_window_switcher(ticker="NEM", active="12M", canonical="12M")
    assert 'class="hint window-mismatch"' not in html


def test_window_switcher_preserves_option_sizing_contracts_state():
    # Clicking a window tab must keep the option sizing calculator state (audit L3).
    from golden_vector.hedge.option_trading import OptionSizingRequest

    req = OptionSizingRequest(
        side="call", horizon_days=180, horizon_explicit=True,
        bucket="directional", size_mode="contracts", quantity=7, size_explicit=True,
    )
    html = render_window_switcher(
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
    html = render_window_switcher(
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
    html = render_window_switcher(
        ticker="NEM", active="6M", canonical="12M", lens="option-trading", sizing_request=req,
    )
    assert "horizon=" not in html


def test_window_switcher_omits_silent_default_sizing():
    # A default sizing request (user touched nothing) must not pollute tab URLs.
    from golden_vector.hedge.option_trading import OptionSizingRequest

    html = render_window_switcher(
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
    assert "Gold beta (1Y)" in body
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
    assert "Gold beta (6M)" in body
    assert "Down-minus-up beta (6M)" in body
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
    assert "Gold beta (3Y)" in body
    assert "Down-minus-up beta (3Y)" in body


# ---------------------------------------------------------------- T6, T7 ----

def test_up_down_beta_panel_hint_adapts_to_active_window():
    html = render_up_down_beta_panel(
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
    assert "<h4>Volatility diagnostics (6M)" in body
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
    assert "<h4>Volatility diagnostics (1Y)" in body
    assert "Volatility context" in body
    assert "is not eligible for this ticker" not in body


# ---------------------------------------------------------------- T12 ----

def _window_fit_rows(*windows: str) -> pd.DataFrame:
    """Published ``window_fit`` research-series rows — the table's only input now."""

    return pd.DataFrame(
        [
            {
                "window": window,
                "up_beta": 1.6,
                "down_beta": 1.4,
                "r_squared": 0.5,
                "weeks": 52,
                "window_status": "ELIGIBLE",
            }
            for window in windows
        ]
    )


def test_structural_window_table_marks_the_active_row():
    html = render_structural_window_table(
        _window_fit_rows("6M", "12M", "3Y"), active_window="3Y", canonical_anchor="12M"
    )
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
    assert "Gold beta (1Y)" in body



# -------------------------------------------- T15 (horizon consistency) ----

def test_structural_window_table_lists_all_windows_and_flags_display_only():
    html = render_structural_window_table(
        _window_fit_rows("6M", "12M", "2Y", "3Y", "5Y"),
        active_window="3Y",
        canonical_anchor="12M",
    )
    # all five lookbacks are listed
    for label in ("6M", "1Y", "2Y", "3Y", "5Y"):
        assert f"<td>{label}" in html
    # 2Y/5Y rows are flagged display-only; scoring windows are not
    assert "2Y (display-only)" in html
    assert "5Y (display-only)" in html
    assert "6M (display-only)" not in html
    assert "3Y (Active)" in html


def test_detail_page_is_horizon_consistent_with_no_silent_mixing(tmp_path):
    """Pick a window (2Y) -> every descriptive metric is that window, while the
    cross-window blends are an explicitly-labelled summary (never faked per-window)
    and the canonical-only volatility numbers are withheld rather than estimated.
    This is the anti-mixing guarantee for the ticker page.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    body = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=2y")["body"]

    # Descriptive cards follow the selected window.
    assert "Gold beta (2Y)" in body
    # Volatility is published for the canonical window only, so the 2Y panel refuses
    # rather than dressing the published 52-week numbers up as 2Y values.
    assert "<h4>Volatility diagnostics (2Y)" in body
    assert "Volatility is not shown." in body
    assert "LOW_NOISE" not in body
    # The cross-window blends are a labelled summary, NOT faked as 2Y.
    assert "Across the scoring windows (6M / 1Y / 3Y)" in body
    assert "do not change with the beta-window switcher" in body
    assert "Gold beta (cross-window)" in body
    # The all-lookbacks reference table marks the display-only windows.
    assert "display-only" in body


def test_detail_page_splits_per_window_narrative_from_cross_window_block(tmp_path):
    """Regression (live-verify sweep, Root Cause A): the per-window narrative cards
    (Delta/Gamma/Asymmetry/Volatility) must render UNDER the active-window block, never
    beneath the cross-window 'do not change with the beta-window switcher' banner — which
    previously made the page contradict itself (per-window prose flipping while the banner
    promised invariance).
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    body = _call_wsgi_app(app, method="GET", path="/ticker/NEM?window=2y")["body"]

    per_window_hint = "These read-outs describe the active beta window (2Y)"
    invariant_hint = "do not change with the beta-window switcher"
    assert per_window_hint in body
    assert invariant_hint in body
    # Per-window narrative + its hint sit BEFORE the cross-window invariance banner.
    assert body.index(per_window_hint) < body.index(invariant_hint)
    for title in _MEASURED_EXPLANATION_TITLES:
        assert body.index(f"<h4>{title}</h4>") < body.index(invariant_hint)


def test_detail_page_uses_1y_label_not_raw_12m_anywhere(tmp_path):
    """Regression (live-verify sweep, Root Cause B): the 12M window must surface as its
    display label '1Y' everywhere user-facing — including the active-window narrative prose
    and the beta-window switcher. The raw '12M' id must never leak, and the misleading
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
    # The raw id must not leak from the switcher either: 12M's tab is labelled 1Y and
    # carries the canonical 'anchor' marker.
    assert "12M" not in body
    assert ">1Y <span class=\"window-canonical\">anchor</span></a>" in body
    # The active-window read-outs are labelled with the display label too.
    assert "Active window: 1Y" in body


def test_measured_explanation_cards_are_exactly_the_declared_titles():
    # Regression (fleet review), ported: the narrative grid is driven by exact title membership.
    # A title rename/addition not reflected in the constant would silently drop a card from the
    # grid ("never silently hide results"). Lock the constant against the builder.
    cards = _build_measured_beta_explanations(
        tool_a_row={"score_eligible": True, "score_eligibility_reason": ""},
        active_window="12M",
        scoring_config=_repo_app_config().scoring,
    )
    returned = [title for title, _ in cards]
    assert returned == list(_MEASURED_EXPLANATION_TITLES)
    assert len(set(returned)) == len(returned), "a card title is rendered twice"
    # The score-era cards went with the score and must not come back silently.
    assert {"Confidence", "Interaction", "Summary"}.isdisjoint(returned)


def test_measured_volatility_card_reads_the_published_52w_fields_only():
    # The old builder took a per-window recompute (volatility_diag) and the card flipped with the
    # window; there is no recompute any more, so the card must be identical across windows and
    # sourced from the PUBLISHED 52-week fields.
    scoring_config = _repo_app_config().scoring
    row = {
        "score_eligibility_reason": "",
        "volatility_context": "LOW_NOISE",
        "residual_volatility_52w": 0.28,
        "downside_volatility_52w": 0.24,
    }
    at_5y = dict(_build_measured_beta_explanations(
        tool_a_row=row, active_window="5Y", scoring_config=scoring_config))
    at_1y = dict(_build_measured_beta_explanations(
        tool_a_row=row, active_window="12M", scoring_config=scoring_config))
    assert at_5y["Volatility"] == at_1y["Volatility"]
    # Control: the genuinely per-window cards DO still follow the active window.
    per_window_row = dict(row, structural_delta_12m=1.9, structural_delta_5y=0.4)
    assert (
        dict(_build_measured_beta_explanations(
            tool_a_row=per_window_row, active_window="5Y", scoring_config=scoring_config))["Delta"]
        != dict(_build_measured_beta_explanations(
            tool_a_row=per_window_row, active_window="12M", scoring_config=scoring_config))["Delta"]
    )


def test_resolve_active_window_honors_1y_alias_not_canonical_fallback():
    # Regression (Codex review): ?window=1y must resolve to 12M, NOT fall back to the
    # ticker's canonical anchor. Use a non-12M canonical so the bug would be visible.
    assert _resolve_active_window("1y", "6M") == "12M"
    assert _resolve_active_window("1Y", "3Y") == "12M"
    # Invalid still falls back to the canonical anchor.
    assert _resolve_active_window("nonsense", "6M") == "6M"
