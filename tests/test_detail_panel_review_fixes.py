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
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.benchmark_comparison import BetaMarker, BetaUniverseComparison
from golden_vector.serve.charts import _build_dual_bar_svg
from golden_vector.serve.detail_panels import (
    _compute_window_volatility,
    _render_tool_a_panel,
    _render_up_down_beta_panel,
    _render_volatility_panel,
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
# --------------------------------------------------------------------------


def test_window_volatility_uses_the_model_date_masked_window(monkeypatch) -> None:
    """The volatility path must go through the model's build_trailing_window_rows,
    the same helper the scatter uses — not a private tail-by-count slice."""

    import golden_vector.serve.detail_panels as panels

    calls: list[dict] = []
    real = panels.build_trailing_window_rows

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(panels, "build_trailing_window_rows", spy)
    diag = _compute_window_volatility(
        tool_a_row=_tool_a_row(as_of_date="2025-07-11"),
        active_window="6M",
        weekly_series=_weekly_series(),
        scoring_config=_scoring_config(),
    )
    assert len(calls) == 1, calls
    assert calls[0]["window_id"] == "6M"
    assert calls[0]["as_of_date"] == pd.Timestamp("2025-07-11")
    assert diag["total_volatility"] is not None


def test_window_volatility_matches_the_scatter_sample_when_series_ends_at_as_of() -> None:
    """When the series' last week IS the as-of date, the date mask and the old
    tail-by-count slice select the same weeks, so the numbers do not move."""

    from golden_vector.model.structural import (
        annualize_downside_volatility,
        annualize_weekly_volatility,
        build_trailing_window_rows,
    )

    weekly = _weekly_series()
    as_of = pd.Timestamp(weekly["as_of_date"].max())
    diag = _compute_window_volatility(
        tool_a_row=_tool_a_row(as_of_date=as_of.strftime("%Y-%m-%d")),
        active_window="6M",
        weekly_series=weekly,
        scoring_config=_scoring_config(),
    )
    sample = build_trailing_window_rows(
        weekly_series=weekly, as_of_date=as_of, window_id="6M"
    )
    expected_total = annualize_weekly_volatility(sample["stock_weekly_log_return"])
    expected_down = annualize_downside_volatility(sample["stock_weekly_log_return"])
    assert diag["total_volatility"] == pytest.approx(expected_total)
    assert diag["downside_volatility"] == pytest.approx(expected_down)


def test_window_volatility_falls_back_to_the_series_last_observation() -> None:
    """A row with no usable as_of_date still anchors on the series' own end."""

    diag = _compute_window_volatility(
        tool_a_row={"volatility_anchor_window_id": "12M"},
        active_window="6M",
        weekly_series=_weekly_series(),
        scoring_config=_scoring_config(),
    )
    assert diag["total_volatility"] is not None
    assert diag["volatility_context"] not in (None, "")


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
    html = _render_up_down_beta_panel(
        _tool_a_row(),
        anchor_metric={"up_beta": None, "down_beta": 1.5},
        active_window="12M",
        comparison=None,
    )
    assert ">n/a<" in html
    assert "0.00" not in html


# --------------------------------------------------------------------------
# Item 3 — no volatility context for an ineligible window
# --------------------------------------------------------------------------


def test_metric_grid_suppresses_volatility_context_for_an_ineligible_window() -> None:
    row = _tool_a_row(window_status_12m="INELIGIBLE_LOW_OBS")
    html = _render_tool_a_panel(
        ticker="NEM",
        tool_a_row=row,
        tool_a_detail=_detail_state(),
        alignment="FOUNDATION_MISSING",
        app_config=_app_config(),
        active_window="12M",
    )
    assert "Not eligible (INELIGIBLE_LOW_OBS)" in html
    # The published label must not leak into the card under the window's name.
    assert "Volatility Context (1Y)</" not in html or "LOW_NOISE" not in html
    # The diagnostics panel already suppressed it; both surfaces now agree.
    assert "is not eligible for this ticker" in html


def test_metric_grid_shows_volatility_context_for_an_eligible_control() -> None:
    html = _render_tool_a_panel(
        ticker="NEM",
        tool_a_row=_tool_a_row(),
        tool_a_detail=_detail_state(),
        alignment="FOUNDATION_MISSING",
        app_config=_app_config(),
        active_window="12M",
    )
    assert "Not eligible" not in html
    assert "LOW_NOISE" in html


# --------------------------------------------------------------------------
# Item 4 — a cross-window fallback carries its true basis
# --------------------------------------------------------------------------


def test_published_fallback_is_labelled_with_its_52w_basis() -> None:
    """No weekly series -> the per-window recompute yields {} and we fall back to
    the published 52-week value. The card must say so, not wear the window's name."""

    state = _detail_state(weekly=pd.DataFrame())
    html = _render_tool_a_panel(
        ticker="NEM",
        tool_a_row=_tool_a_row(volatility_anchor_window_id="12M"),
        tool_a_detail=state,
        alignment="FOUNDATION_MISSING",
        app_config=_app_config(),
        active_window="6M",
    )
    assert "Volatility Context (52w, published)" in html
    assert "Volatility Context (6M)" not in html


def test_per_window_value_keeps_the_window_label_when_it_is_real() -> None:
    """Control: with a usable series the card is a genuine per-window value and
    keeps the active window's label."""

    html = _render_tool_a_panel(
        ticker="NEM",
        tool_a_row=_tool_a_row(),
        tool_a_detail=_detail_state(),
        alignment="FOUNDATION_MISSING",
        app_config=_app_config(),
        active_window="6M",
    )
    assert "Volatility Context (6M)" in html
    assert "Volatility Context (52w, published)" not in html


# --------------------------------------------------------------------------
# Item 5 — the live estimator is labelled, and runs once
# --------------------------------------------------------------------------


def test_non_canonical_volatility_panel_declares_its_live_estimate() -> None:
    html = _render_volatility_panel(
        _tool_a_row(),
        active_window="6M",
        weekly_series=_weekly_series(),
        scoring_config=_scoring_config(),
    )
    assert "Estimated live from the weekly series" in html
    assert "published values are 52-week" in html


def test_canonical_window_panel_carries_no_estimate_hint() -> None:
    html = _render_volatility_panel(
        _tool_a_row(),
        active_window="12M",
        weekly_series=_weekly_series(),
        scoring_config=_scoring_config(),
    )
    assert "Estimated live from the weekly series" not in html


def test_volatility_estimator_runs_once_per_render(monkeypatch) -> None:
    import golden_vector.serve.detail_panels as panels

    real = panels._compute_window_volatility
    calls: list[str] = []

    def counting(**kwargs):
        calls.append(kwargs["active_window"])
        return real(**kwargs)

    monkeypatch.setattr(panels, "_compute_window_volatility", counting)
    panels._render_tool_a_panel(
        ticker="NEM",
        tool_a_row=_tool_a_row(),
        tool_a_detail=_detail_state(),
        alignment="FOUNDATION_MISSING",
        app_config=_app_config(),
        active_window="6M",
    )
    assert calls == ["6M"], calls


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
    html = _render_up_down_beta_panel(
        _tool_a_row(),
        anchor_metric={"up_beta": 1.2, "down_beta": 1.5},
        active_window="12M",
        comparison=_comparison(("GDX",)),
    )
    assert "■ GDX</span>" in html
    # GDXJ was never resolved into the bars, so the legend must not claim it.
    assert "GDXJ" not in html


def test_grouped_bar_legend_lists_every_resolved_benchmark() -> None:
    html = _render_up_down_beta_panel(
        _tool_a_row(),
        anchor_metric={"up_beta": 1.2, "down_beta": 1.5},
        active_window="12M",
        comparison=_comparison(("GDX", "GDXJ")),
    )
    assert "■ GDX</span>" in html
    assert "■ GDXJ</span>" in html
