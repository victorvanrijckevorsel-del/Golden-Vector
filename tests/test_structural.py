from datetime import date

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.numeric import strict_optional_float as _optional_float
from golden_vector.model.structural import (
    STRUCTURAL_WINDOW_COLUMNS,
    VOLATILITY_DIAGNOSTIC_COLUMNS,
    annualize_downside_volatility,
    annualize_weekly_volatility,
    build_structural_weekly_series,
    build_trailing_window_rows,
    choose_structural_anchor_window,
    compute_structural_window_metrics,
    compute_volatility_diagnostics,
    compute_window_metric,
    summarize_normalization_issues,
)


def _reference_compute_structural_window_metrics(
    *,
    weekly_series: pd.DataFrame,
    normalization_issues: pd.DataFrame,
    scoring_config,
) -> pd.DataFrame:
    if weekly_series.empty:
        return pd.DataFrame(columns=STRUCTURAL_WINDOW_COLUMNS)

    ticker = str(weekly_series["ticker"].iloc[0]).upper()
    as_of_dates = list(pd.to_datetime(weekly_series["as_of_date"]).sort_values().unique())
    rows: list[dict[str, object]] = []
    for as_of_timestamp in as_of_dates:
        as_of_date = pd.Timestamp(as_of_timestamp)
        issue_summary = None
        if not normalization_issues.empty:
            issue_summary = summarize_normalization_issues(
                normalization_issues=normalization_issues,
                as_of_date=as_of_date,
            )
        for window_id in scoring_config.structural_windows:
            window_rows = build_trailing_window_rows(
                weekly_series=weekly_series,
                as_of_date=as_of_date,
                window_id=window_id,
            )
            rows.append(
                compute_window_metric(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    window_id=window_id,
                    window_rows=window_rows,
                    issue_summary=issue_summary,
                    scoring_config=scoring_config,
                )
            )
    return pd.DataFrame(rows, columns=STRUCTURAL_WINDOW_COLUMNS)


def _reference_compute_volatility_diagnostics(
    *,
    weekly_series: pd.DataFrame,
    structural_window_metrics: pd.DataFrame,
    scoring_config,
) -> pd.DataFrame:
    if weekly_series.empty:
        return pd.DataFrame(columns=VOLATILITY_DIAGNOSTIC_COLUMNS)

    weekly = weekly_series.copy()
    weekly["as_of_date"] = pd.to_datetime(weekly["as_of_date"]).dt.date
    grouped_weekly = {
        str(ticker).upper(): frame.sort_values("as_of_date").reset_index(drop=True)
        for ticker, frame in weekly.groupby("ticker", dropna=False)
    }

    metrics = structural_window_metrics.copy()
    if metrics.empty:
        return pd.DataFrame(columns=VOLATILITY_DIAGNOSTIC_COLUMNS)
    metrics["as_of_date"] = pd.to_datetime(metrics["as_of_date"]).dt.date

    rows: list[dict[str, object]] = []
    for (ticker, as_of_date), metric_frame in metrics.groupby(
        ["ticker", "as_of_date"],
        dropna=False,
    ):
        normalized_ticker = str(ticker).upper()
        ordered = grouped_weekly.get(normalized_ticker, pd.DataFrame())
        if ordered.empty:
            continue
        as_of_timestamp = pd.Timestamp(as_of_date)
        trailing = ordered.loc[
            pd.to_datetime(ordered["as_of_date"]).le(as_of_timestamp)
        ].tail(52)
        anchor_window_id = choose_structural_anchor_window(
            window_metrics=metric_frame,
            scoring_config=scoring_config,
            require_eligible=True,
        ) or choose_structural_anchor_window(
            window_metrics=metric_frame,
            scoring_config=scoring_config,
            require_eligible=False,
        )
        anchor_metric = None
        if anchor_window_id:
            anchor_rows = metric_frame.loc[
                metric_frame["window_id"].astype(str).eq(anchor_window_id)
            ]
            if not anchor_rows.empty:
                anchor_metric = anchor_rows.iloc[0]
        total_vol = annualize_weekly_volatility(trailing["stock_weekly_log_return"])
        downside_vol = annualize_downside_volatility(trailing["stock_weekly_log_return"])
        residual_vol = None
        if anchor_metric is not None:
            alpha = _optional_float(anchor_metric.get("intercept_alpha"))
            beta = _optional_float(anchor_metric.get("structural_delta"))
            if alpha is not None and beta is not None:
                x_values = pd.to_numeric(
                    trailing["gold_weekly_log_return"], errors="coerce"
                ).to_numpy(dtype=float)
                y_values = pd.to_numeric(
                    trailing["stock_weekly_log_return"], errors="coerce"
                ).to_numpy(dtype=float)
                valid_mask = np.isfinite(x_values) & np.isfinite(y_values)
                x_values = x_values[valid_mask]
                y_values = y_values[valid_mask]
                if len(x_values) >= 2:
                    residual_vol = annualize_weekly_volatility(
                        y_values - (alpha + (beta * x_values))
                    )
        rows.append(
            {
                "ticker": normalized_ticker,
                "as_of_date": as_of_timestamp.date(),
                "volatility_anchor_window_id": anchor_window_id,
                "total_volatility_52w": total_vol,
                "residual_volatility_52w": residual_vol,
                "downside_volatility_52w": downside_vol,
            }
        )
    return pd.DataFrame(rows, columns=VOLATILITY_DIAGNOSTIC_COLUMNS)


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


def test_compute_structural_window_metrics_matches_reference_loop():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    dates = list(pd.date_range("2023-01-06", periods=170, freq="7D"))
    dates = [
        timestamp
        for index, timestamp in enumerate(dates)
        if index not in {8, 33, 81, 122}
    ]
    dates.extend([pd.Timestamp("2025-04-03"), pd.Timestamp("2026-04-03")])
    dates = sorted(set(dates))
    index = np.arange(len(dates), dtype=float)
    gold_returns = (0.012 * np.sin(index / 4.0)) + (0.004 * np.cos(index / 11.0))
    stock_returns = 0.001 + (1.35 * gold_returns) + (0.006 * np.sin(index / 6.0))
    gold_returns[15] = np.nan
    stock_returns[40] = np.inf
    gold_returns[75] = np.inf
    weekly_series = pd.DataFrame(
        {
            "ticker": "NEM",
            "as_of_date": [timestamp.date() for timestamp in dates],
            "stock_week_date": [timestamp.date() for timestamp in dates],
            "gold_week_date": [timestamp.date() for timestamp in dates],
            "stock_basis_usd": 10.0,
            "gold_basis_usd": 2000.0,
            "stock_weekly_log_return": stock_returns,
            "gold_weekly_log_return": gold_returns,
        }
    )
    normalization_issues = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "date": pd.Timestamp("2023-04-03"),
                "normalization_status": "MISSING_FX",
            },
            {
                "ticker": "NEM",
                "date": pd.Timestamp("2023-04-04"),
                "normalization_status": "STALE_FX",
            },
        ]
    )

    actual = compute_structural_window_metrics(
        weekly_series=weekly_series,
        normalization_issues=normalization_issues,
        scoring_config=scoring,
    )
    expected = _reference_compute_structural_window_metrics(
        weekly_series=weekly_series,
        normalization_issues=normalization_issues,
        scoring_config=scoring,
    )

    assert list(actual.columns) == STRUCTURAL_WINDOW_COLUMNS
    assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
        rtol=0,
        atol=1e-9,
    )
    boundary_rows = build_trailing_window_rows(
        weekly_series=weekly_series,
        as_of_date=pd.Timestamp("2026-04-03"),
        window_id="12M",
    )
    assert pd.Timestamp("2025-04-03") not in set(
        pd.to_datetime(boundary_rows["as_of_date"])
    )
    boundary_metric = actual.loc[
        actual["as_of_date"].eq(pd.Timestamp("2026-04-03").date())
        & actual["window_id"].eq("12M")
    ].iloc[0]
    assert boundary_metric["week_count"] == len(boundary_rows.index)
    assert boundary_metric["normalization_issue_summary"] == "STALE_FX"


def test_compute_structural_window_metrics_keeps_empty_regression_counts_zero():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    weeks = pd.date_range("2026-01-02", periods=4, freq="7D")
    weekly_series = pd.DataFrame(
        {
            "ticker": "NEM",
            "as_of_date": weeks.date,
            "stock_week_date": weeks.date,
            "gold_week_date": weeks.date,
            "stock_basis_usd": 10.0,
            "gold_basis_usd": 2000.0,
            "stock_weekly_log_return": [0.01, 0.02, 0.03, 0.04],
            "gold_weekly_log_return": [0.01, 0.01, 0.01, 0.01],
        }
    )

    metrics = compute_structural_window_metrics(
        weekly_series=weekly_series,
        normalization_issues=pd.DataFrame(columns=["ticker", "date", "normalization_status"]),
        scoring_config=scoring,
    )

    latest_metrics = metrics.loc[metrics["as_of_date"].eq(weeks.max().date())]
    assert set(latest_metrics["window_reason"]) == {"MISSING_GOLD_VARIANCE"}
    assert set(latest_metrics["week_count"]) == {4}
    assert set(latest_metrics["up_week_count"]) == {0}
    assert set(latest_metrics["down_week_count"]) == {0}


def test_compute_structural_window_metrics_preserves_near_constant_regime_betas():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    weeks = pd.date_range("2022-01-07", periods=180, freq="W-FRI")
    index = np.arange(len(weeks), dtype=float)
    gold_returns = np.where(
        (index.astype(int) % 4) < 2,
        0.012 + (index * 1e-16),
        -0.008 - (index * 1e-16),
    )
    stock_returns = np.where(
        gold_returns > 0,
        (2.0 * gold_returns) + 0.001,
        (1.2 * gold_returns) + 0.001,
    )
    weekly_series = pd.DataFrame(
        {
            "ticker": "NEM",
            "as_of_date": weeks.date,
            "stock_week_date": weeks.date,
            "gold_week_date": weeks.date,
            "stock_basis_usd": 10.0,
            "gold_basis_usd": 2000.0,
            "stock_weekly_log_return": stock_returns,
            "gold_weekly_log_return": gold_returns,
        }
    )

    actual = compute_structural_window_metrics(
        weekly_series=weekly_series,
        normalization_issues=pd.DataFrame(columns=["ticker", "date", "normalization_status"]),
        scoring_config=scoring,
    )
    expected = _reference_compute_structural_window_metrics(
        weekly_series=weekly_series,
        normalization_issues=pd.DataFrame(columns=["ticker", "date", "normalization_status"]),
        scoring_config=scoring,
    )

    assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
        rtol=0,
        atol=1e-9,
    )
    latest_rows = actual.loc[actual["as_of_date"].eq(weeks.max().date())]
    assert latest_rows["up_beta"].notna().all()
    assert latest_rows["down_beta"].notna().all()


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


def test_compute_volatility_diagnostics_matches_reference_loop():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    weeks = pd.date_range("2024-01-05", periods=84, freq="W-FRI")
    index = np.arange(len(weeks), dtype=float)
    gold_returns = 0.012 * np.sin(index / 5.0)
    stock_returns = 0.002 + (1.3 * gold_returns) + (0.006 * np.cos(index / 7.0))
    weekly_series = pd.DataFrame(
        {
            "ticker": "NEM",
            "as_of_date": weeks.date,
            "stock_week_date": weeks.date,
            "gold_week_date": weeks.date,
            "stock_basis_usd": 10.0,
            "gold_basis_usd": 2000.0,
            "stock_weekly_log_return": stock_returns,
            "gold_weekly_log_return": gold_returns,
        }
    )
    second_ticker = weekly_series.iloc[:65].copy()
    second_ticker["ticker"] = "GOLD"
    second_ticker["stock_weekly_log_return"] = (
        0.001 + (0.8 * second_ticker["gold_weekly_log_return"])
    )
    weekly_series = pd.concat([weekly_series, second_ticker], ignore_index=True)

    metric_rows: list[dict[str, object]] = []
    for ticker, selected_weeks in {
        "NEM": [weeks[20], weeks[59], weeks[-1]],
        "GOLD": [weeks[40], weeks[64]],
        "MISSING": [weeks[-1]],
    }.items():
        for as_of_date in selected_weeks:
            metric_rows.extend(
                [
                    {
                        "ticker": ticker,
                        "as_of_date": as_of_date.date(),
                        "window_id": "6M",
                        "window_status": "LOW_OBSERVATION",
                        "structural_delta": 1.2,
                        "intercept_alpha": 0.001,
                    },
                    {
                        "ticker": ticker,
                        "as_of_date": as_of_date.date(),
                        "window_id": "12M",
                        "window_status": "ELIGIBLE",
                        "structural_delta": 1.35,
                        "intercept_alpha": 0.002,
                    },
                    {
                        "ticker": ticker,
                        "as_of_date": as_of_date.date(),
                        "window_id": "3Y",
                        "window_status": "ELIGIBLE",
                        "structural_delta": 1.5,
                        "intercept_alpha": 0.003,
                    },
                ]
            )
    structural_metrics = pd.DataFrame(metric_rows)

    actual = compute_volatility_diagnostics(
        weekly_series=weekly_series,
        structural_window_metrics=structural_metrics,
        scoring_config=scoring,
    )
    expected = _reference_compute_volatility_diagnostics(
        weekly_series=weekly_series,
        structural_window_metrics=structural_metrics,
        scoring_config=scoring,
    )

    assert list(actual.columns) == VOLATILITY_DIAGNOSTIC_COLUMNS
    assert "MISSING" not in set(actual["ticker"])
    assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
        rtol=0,
        atol=1e-12,
    )
