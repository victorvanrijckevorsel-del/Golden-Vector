from datetime import date

import numpy as np
import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.structural import (
    build_structural_weekly_series,
    choose_structural_anchor_window,
    compute_volatility_diagnostics,
    compute_window_metric,
)


def test_build_structural_weekly_series_drops_incomplete_current_week():
    equity_history = pd.DataFrame(
        [
            {"ticker": "NEM", "date": date(2026, 4, 3), "return_basis_usd": 10.0, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 10), "return_basis_usd": 10.5, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 17), "return_basis_usd": 11.0, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 22), "return_basis_usd": 11.4, "normalization_status": "OK"},
        ]
    )
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 4, 3), "adj_close_usd": 3000.0, "close_usd": 3000.0},
            {"date": date(2026, 4, 10), "adj_close_usd": 3010.0, "close_usd": 3010.0},
            {"date": date(2026, 4, 17), "adj_close_usd": 3020.0, "close_usd": 3020.0},
            {"date": date(2026, 4, 22), "adj_close_usd": 3035.0, "close_usd": 3035.0},
        ]
    )

    weekly_series, _ = build_structural_weekly_series(
        usd_equity_history=equity_history,
        gold_history=gold_history,
    )

    assert list(weekly_series["as_of_date"]) == [date(2026, 4, 10), date(2026, 4, 17)]
    assert weekly_series["as_of_date"].max() == date(2026, 4, 17)


def test_compute_window_metric_preserves_negative_down_beta_asymmetry_ratio():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    up_gold = np.linspace(0.01, 0.03, 8, dtype=float)
    down_gold = np.linspace(-0.03, -0.01, 8, dtype=float)
    gold_returns = np.concatenate([up_gold, down_gold])
    stock_returns = np.concatenate([2.0 * up_gold, -0.5 * down_gold])
    window_rows = pd.DataFrame(
        {
            "gold_weekly_log_return": gold_returns,
            "stock_weekly_log_return": stock_returns,
        }
    )

    result = compute_window_metric(
        ticker="NEM",
        as_of_date=pd.Timestamp("2026-04-17"),
        window_id="6M",
        window_rows=window_rows,
        issue_summary=None,
        scoring_config=scoring,
    )

    assert result["window_status"] == "LOW_OBSERVATION"
    assert result["down_beta"] < 0
    assert result["asymmetry_ratio"] is not None
    assert result["asymmetry_ratio"] < 0
    assert result["gamma_value"] < 0


def test_choose_structural_anchor_window_falls_back_from_12m_to_3y():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    metrics = pd.DataFrame(
        [
            {"window_id": "6M", "window_status": "ELIGIBLE", "structural_delta": 1.4},
            {"window_id": "12M", "window_status": "LOW_OBSERVATION", "structural_delta": 1.5},
            {"window_id": "3Y", "window_status": "ELIGIBLE", "structural_delta": 1.6},
        ]
    )

    anchor_window_id = choose_structural_anchor_window(
        window_metrics=metrics,
        scoring_config=scoring,
        require_eligible=True,
    )

    assert anchor_window_id == "3Y"


def test_compute_volatility_diagnostics_uses_anchor_window_id():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    weeks = pd.date_range("2025-01-03", periods=60, freq="W-FRI")
    gold_returns = np.where(np.arange(60) % 2 == 0, 0.015, -0.01)
    stock_returns = (1.5 * gold_returns) + 0.002
    weekly_series = pd.DataFrame(
        {
            "ticker": "NEM",
            "as_of_date": weeks.date,
            "stock_week_date": weeks.date,
            "gold_week_date": weeks.date,
            "stock_basis_usd": 10.0 * np.exp(np.cumsum(stock_returns)),
            "gold_basis_usd": 1800.0 * np.exp(np.cumsum(gold_returns)),
            "stock_weekly_log_return": stock_returns,
            "gold_weekly_log_return": gold_returns,
        }
    )
    structural_metrics = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": weeks.max().date(),
                "window_id": "6M",
                "window_status": "ELIGIBLE",
                "structural_delta": 1.45,
                "intercept_alpha": 0.002,
            },
            {
                "ticker": "NEM",
                "as_of_date": weeks.max().date(),
                "window_id": "12M",
                "window_status": "ELIGIBLE",
                "structural_delta": 1.5,
                "intercept_alpha": 0.002,
            },
            {
                "ticker": "NEM",
                "as_of_date": weeks.max().date(),
                "window_id": "3Y",
                "window_status": "LOW_OBSERVATION",
                "structural_delta": 1.55,
                "intercept_alpha": 0.002,
            },
        ]
    )

    diagnostics = compute_volatility_diagnostics(
        weekly_series=weekly_series,
        structural_window_metrics=structural_metrics,
        scoring_config=scoring,
    )

    latest_row = diagnostics.sort_values("as_of_date").iloc[-1]
    assert latest_row["volatility_anchor_window_id"] == "12M"
    assert pd.notna(latest_row["residual_volatility_52w"])
