"""Regressions for the detail-panel review findings (items 1-7).

Each test pins the BEHAVIOUR the finding was about, not the implementation:
a window sample defined in one place, a missing beta that never renders as a
measured zero, an ineligible window that shows no volatility, a fallback that
carries its true basis, a live estimate that says it is one, a signal history
that survives a horizon filter matching nothing, and a legend that names only
the benchmarks actually drawn.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.benchmark_comparison import BetaMarker, BetaUniverseComparison
from golden_vector.serve.charts import _build_dual_bar_svg
from golden_vector.serve.ticker_page.behaviour import (
    render_market_behaviour_section,
    render_up_down_beta_panel,
)
from golden_vector.serve.option_signal_charts import _render_signal_history_chart
from golden_vector.serve.workspace_state import ToolADetailState, StructuralHistoryLoad


# --------------------------------------------------------------------------
# Fixtures / builders
# --------------------------------------------------------------------------


def _app_config():
    return load_app_config(ProjectPaths.discover()).app


def _scoring_config():
    return _app_config().scoring


def _weekly_series(*, n: int = 80, weekly_vol: float = 0.04) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    dates = pd.date_range("2024-01-05", periods=n, freq="W-FRI")
    gold = rng.normal(0, 0.015, n)
    return pd.DataFrame(
        {
            "as_of_date": dates,
            "gold_weekly_log_return": gold,
            "stock_weekly_log_return": 1.4 * gold + rng.normal(0, weekly_vol, n),
        }
    )


def _tool_a_row(**overrides) -> dict:
    """An otherwise-healthy published row; each test perturbs ONE field."""

    row = {
        "ticker": "NEM",
        "as_of_date": "2025-07-11",
        "anchor_window_id": "12M",
        "volatility_anchor_window_id": "12M",
        "window_status_6m": "ELIGIBLE",
        "window_status_12m": "ELIGIBLE",
        "window_status_3y": "ELIGIBLE",
        "structural_delta_12m": 1.4,
        "gamma_12m": 0.2,
        "asymmetry_ratio_12m": 1.1,
        "r_squared_12m": 0.55,
        "weeks_12m": 52,
        "up_beta_12m": 1.2,
        "down_beta_12m": 1.5,
        "structural_delta_6m": 1.3,
        "gamma_6m": 0.1,
        "asymmetry_ratio_6m": 1.05,
        "r_squared_6m": 0.5,
        "weeks_6m": 26,
        "total_volatility_52w": 0.42,
        "residual_volatility_52w": 0.31,
        "downside_volatility_52w": 0.27,
        "volatility_context": "LOW_NOISE",
        "confidence_label": "MEDIUM",
        "tool_a_score": 61.0,
        "profile_label": "CONVEX",
        "score_eligible": True,
    }
    row.update(overrides)
    return row


def _detail_state(weekly: pd.DataFrame | None = None) -> ToolADetailState:
    return ToolADetailState(
        weekly_series=_weekly_series() if weekly is None else weekly,
        structural_window_metrics=pd.DataFrame(),
        structural_metrics_load=StructuralHistoryLoad(status="ok", history=pd.DataFrame()),
        exploratory_horizons=pd.DataFrame(),
    )


def _marker(label: str, *, subject: bool, up: float | None, down: float | None) -> BetaMarker:
    return BetaMarker(
        label=label,
        is_subject=subject,
        is_benchmark=not subject,
        down_beta=down,
        up_beta=up,
        down_pos=0.5,
        up_pos=0.5,
        down_percentile=50.0,
        up_percentile=50.0,
    )


def _comparison(benchmark_labels: tuple[str, ...]) -> BetaUniverseComparison:
    return BetaUniverseComparison(
        window_id="12M",
        window_label="1Y",
        available=True,
        universe_down_n=60,
        universe_up_n=60,
        down_domain=(0.0, 2.0),
        up_domain=(0.0, 2.0),
        subject=_marker("NEM", subject=True, up=1.2, down=1.5),
        benchmarks=tuple(
            _marker(label, subject=False, up=1.0, down=1.1) for label in benchmark_labels
        ),
    )


# --------------------------------------------------------------------------
# Item 1 — the window's sample has ONE definition
#
# M3c deleted the serve-side per-window volatility recompute entirely, so there
# is no longer a second sample definition that could drift from the scatter's.
# The replacement guarantee ("never estimate off-canonical") is proved in
# tests/test_detail_volatility_context.py.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Item 2 — a missing beta is n/a, never a 0.00 bar
# --------------------------------------------------------------------------


def test_dual_bar_renders_na_for_a_missing_side_and_keeps_the_present_one() -> None:
    svg = _build_dual_bar_svg(
        left_label="Up-Gold",
        left_value=None,
        right_label="Down-Gold",
        right_value=1.5,
    )
    assert ">n/a<" in svg
    assert "0.00" not in svg
    # Control: the side that DOES have a value still draws its bar and number.
    assert "1.50" in svg
    assert "<rect" in svg


def test_dual_bar_still_draws_a_genuine_measured_zero() -> None:
    """A real 0.0 must keep rendering as 0.00 — only None becomes n/a."""

    svg = _build_dual_bar_svg(
        left_label="Up-Gold", left_value=0.0, right_label="Down-Gold", right_value=1.5
    )
    assert "0.00" in svg
    assert ">n/a<" not in svg


def test_up_down_panel_does_not_invent_a_zero_for_a_missing_beta() -> None:
    html = render_up_down_beta_panel(
        anchor_metric={"up_beta": None, "down_beta": 1.5},
        active_window="12M",
        comparison=None,
    )
    assert ">n/a<" in html
    assert "0.00" not in html


# --------------------------------------------------------------------------
# Item 3 — no volatility context for an ineligible window
# --------------------------------------------------------------------------


def test_behaviour_section_suppresses_volatility_context_for_an_ineligible_window() -> None:
    row = _tool_a_row(window_status_12m="INELIGIBLE_LOW_OBS")
    html = render_market_behaviour_section(
        ticker="NEM",
        tool_a_row=row,
        tool_a_detail=_detail_state(),
        alignment="FOUNDATION_MISSING",
        app_config=_app_config(),
        active_window="12M",
        canonical_anchor="12M",
    )
    assert "The 1Y window is not eligible for this ticker" in html
    assert "INELIGIBLE_LOW_OBS" in html
    # The published label must not leak into the section under the window's name.
    assert "LOW_NOISE" not in html


def test_behaviour_section_shows_volatility_context_for_an_eligible_control() -> None:
    html = render_market_behaviour_section(
        ticker="NEM",
        tool_a_row=_tool_a_row(),
        tool_a_detail=_detail_state(),
        alignment="FOUNDATION_MISSING",
        app_config=_app_config(),
        active_window="12M",
        canonical_anchor="12M",
    )
    assert "is not eligible for this ticker" not in html
    assert "LOW_NOISE" in html


# --------------------------------------------------------------------------
# Items 4 and 5 — the cross-window fallback's basis label, and the live
# estimator's "estimated live" hint / single-call guarantee.
#
# Both described the deleted request-path estimator: there is no fallback to
# label and no estimator to run. The panel now shows published values on the
# canonical window and an honest note everywhere else
# (tests/test_detail_volatility_context.py).
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Item 6 — signal history survives a horizon filter that matches nothing
# --------------------------------------------------------------------------


def _signal_points(with_horizon: bool) -> list[dict]:
    points = []
    for day in (1, 8, 15):
        point = {
            "as_of_date": f"2025-07-{day:02d}",
            "skew_residual": 0.02,
            "atm_iv": 0.45,
            "iv_rv_ratio": 1.2,
        }
        if with_horizon:
            point["signal_horizon_days"] = 30
        points.append(point)
    return points


def test_signal_history_falls_back_when_the_horizon_filter_empties_the_points() -> None:
    """Pre-migration points carry no signal_horizon_days; the row's 45d horizon
    matches none of them. Showing "no history exists" would be a lie."""

    html = _render_signal_history_chart(_signal_points(with_horizon=False), signal_horizon_days=45)
    assert "No persisted signal history exists" not in html
    assert "2025-07-01" in html
    assert "2025-07-15" in html
    # With no horizon on the points, the generic label is used, not "45d".
    assert "45d Skew Residual" not in html
    assert "Signal Skew Residual" in html


def test_signal_history_still_filters_when_the_horizon_matches() -> None:
    """Control: matching points are filtered normally and keep the horizon label."""

    points = _signal_points(with_horizon=True)
    points.append(
        {
            "as_of_date": "2025-07-22",
            "skew_residual": 0.09,
            "atm_iv": 0.99,
            "iv_rv_ratio": 3.3,
            "signal_horizon_days": 90,
        }
    )
    html = _render_signal_history_chart(points, signal_horizon_days=30)
    assert "30d Skew Residual" in html
    assert "2025-07-22" not in html
    assert "2025-07-01" in html


def test_signal_history_still_reports_a_genuinely_empty_history() -> None:
    html = _render_signal_history_chart([], signal_horizon_days=30)
    assert "No persisted signal history exists" in html


# --------------------------------------------------------------------------
# Item 7 — the legend names the benchmarks that were actually drawn
# --------------------------------------------------------------------------


def test_grouped_bar_legend_follows_the_resolved_benchmarks() -> None:
    html = render_up_down_beta_panel(
        anchor_metric={"up_beta": 1.2, "down_beta": 1.5},
        active_window="12M",
        comparison=_comparison(("GDX",)),
    )
    assert "■ GDX</span>" in html
    # GDXJ was never resolved into the bars, so the legend must not claim it.
    assert "GDXJ" not in html


def test_grouped_bar_legend_lists_every_resolved_benchmark() -> None:
    html = render_up_down_beta_panel(
        anchor_metric={"up_beta": 1.2, "down_beta": 1.5},
        active_window="12M",
        comparison=_comparison(("GDX", "GDXJ")),
    )
    assert "■ GDX</span>" in html
    assert "■ GDXJ</span>" in html
