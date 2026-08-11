from datetime import date

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.numeric import strict_optional_float as _optional_float
from golden_vector.model.structural import (
    STRUCTURAL_WINDOW_COLUMNS,
    VOLATILITY_DIAGNOSTIC_COLUMNS,
    annualize_downside_volatility,
    annualize_weekly_volatility,
    build_rebased_comparison_series,
    build_structural_weekly_series,
    build_trailing_window_rows,
    choose_structural_anchor_window,
    compute_structural_window_metrics,
    compute_volatility_diagnostics,
    compute_window_metric,
    summarize_normalization_issues,
    _window_start,
    _window_start_values,
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
    display_window_ids = {str(w).upper() for w in scoring_config.structural_display_windows}
    rows: list[dict[str, object]] = []
    for as_of_timestamp in as_of_dates:
        as_of_date = pd.Timestamp(as_of_timestamp)
        # Scoring windows share the 3Y-trailing summary; display windows (2Y/5Y) use their
        # own lookback (mirrors compute_structural_window_metrics).
        scoring_issue_summary = None
        if not normalization_issues.empty:
            scoring_issue_summary = summarize_normalization_issues(
                normalization_issues=normalization_issues,
                as_of_date=as_of_date,
            )
        for window_id in (
            *scoring_config.structural_windows,
            *scoring_config.structural_display_windows,
        ):
            if normalization_issues.empty:
                issue_summary = None
            elif str(window_id).upper() in display_window_ids:
                issue_summary = summarize_normalization_issues(
                    normalization_issues=normalization_issues,
                    as_of_date=as_of_date,
                    window_id=window_id,
                )
            else:
                issue_summary = scoring_issue_summary
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
    # Display windows scope the normalization summary to their OWN lookback (Codex P2): at
    # 2026-04-03 the 5Y window (start ~2021-04) covers the 2023-04 issues, while the 2Y
    # window (start ~2024-04) and the scoring 12M row (3Y basis, boundary-excludes the
    # 2023-04-03 issue) do not.
    summary_5y = actual.loc[
        actual["as_of_date"].eq(pd.Timestamp("2026-04-03").date())
        & actual["window_id"].eq("5Y")
    ].iloc[0]["normalization_issue_summary"]
    assert summary_5y == "MISSING_FX,STALE_FX"
    summary_2y = actual.loc[
        actual["as_of_date"].eq(pd.Timestamp("2026-04-03").date())
        & actual["window_id"].eq("2Y")
    ].iloc[0]["normalization_issue_summary"]
    assert pd.isna(summary_2y)


def test_trailing_window_calendar_boundaries_are_exact():
    assert _window_start(pd.Timestamp("2024-02-29"), "1Y") == pd.Timestamp(
        "2023-02-28"
    )
    assert _window_start(pd.Timestamp("2025-02-28"), "1Y") == pd.Timestamp(
        "2024-02-28"
    )
    assert _window_start(pd.Timestamp("2026-03-31"), "12M") == pd.Timestamp(
        "2025-03-31"
    )

    weekly_series = pd.DataFrame(
        {
            "ticker": "NEM",
            "as_of_date": [
                date(2024, 2, 28),
                date(2024, 2, 29),
                date(2025, 2, 28),
                date(2025, 3, 31),
                date(2025, 4, 1),
                date(2026, 3, 31),
            ],
            "stock_week_date": [
                date(2024, 2, 28),
                date(2024, 2, 29),
                date(2025, 2, 28),
                date(2025, 3, 31),
                date(2025, 4, 1),
                date(2026, 3, 31),
            ],
            "gold_week_date": [
                date(2024, 2, 28),
                date(2024, 2, 29),
                date(2025, 2, 28),
                date(2025, 3, 31),
                date(2025, 4, 1),
                date(2026, 3, 31),
            ],
            "stock_basis_usd": 10.0,
            "gold_basis_usd": 2000.0,
            "stock_weekly_log_return": 0.01,
            "gold_weekly_log_return": 0.01,
        }
    )

    leap_rows = build_trailing_window_rows(
        weekly_series=weekly_series,
        as_of_date=pd.Timestamp("2025-02-28"),
        window_id="1Y",
    )
    leap_dates = set(pd.to_datetime(leap_rows["as_of_date"]))
    assert pd.Timestamp("2024-02-28") not in leap_dates
    assert pd.Timestamp("2024-02-29") in leap_dates

    month_end_rows = build_trailing_window_rows(
        weekly_series=weekly_series,
        as_of_date=pd.Timestamp("2026-03-31"),
        window_id="12M",
    )
    month_end_dates = set(pd.to_datetime(month_end_rows["as_of_date"]))
    assert pd.Timestamp("2025-03-31") not in month_end_dates
    assert pd.Timestamp("2025-04-01") in month_end_dates


def test_vectorized_window_starts_match_scalar_calendar_offsets():
    as_of_dates = pd.date_range("2014-01-01", "2026-12-31", freq="D")
    for window_id in ("6M", "12M", "2Y", "3Y", "5Y"):
        vectorized = _window_start_values(as_of_dates, window_id)
        scalar = np.array(
            [
                _window_start(pd.Timestamp(as_of_date), window_id).to_datetime64()
                for as_of_date in as_of_dates
            ],
            dtype="datetime64[ns]",
        )
        np.testing.assert_array_equal(vectorized, scalar)


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


def test_volatility_anchor_never_selects_a_display_window():
    """Phase-2 invariant: an ELIGIBLE 2Y/5Y display row must NEVER be chosen as the
    volatility anchor, even when no scoring window is ELIGIBLE. The anchor (and hence
    residual vol) must fall back through the scoring-window preference only."""
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
    # All scoring windows are LOW_OBSERVATION; only the 2Y DISPLAY window is ELIGIBLE
    # with an extreme delta. If display windows leaked, the anchor would become "2Y".
    as_of = weeks.max().date()
    structural_metrics = pd.DataFrame(
        [
            {"ticker": "NEM", "as_of_date": as_of, "window_id": "6M",
             "window_status": "LOW_OBSERVATION", "structural_delta": 1.45, "intercept_alpha": 0.002},
            {"ticker": "NEM", "as_of_date": as_of, "window_id": "12M",
             "window_status": "LOW_OBSERVATION", "structural_delta": 1.5, "intercept_alpha": 0.002},
            {"ticker": "NEM", "as_of_date": as_of, "window_id": "3Y",
             "window_status": "LOW_OBSERVATION", "structural_delta": 1.55, "intercept_alpha": 0.002},
            {"ticker": "NEM", "as_of_date": as_of, "window_id": "2Y",
             "window_status": "ELIGIBLE", "structural_delta": 99.0, "intercept_alpha": 9.9},
        ]
    )

    diagnostics = compute_volatility_diagnostics(
        weekly_series=weekly_series,
        structural_window_metrics=structural_metrics,
        scoring_config=scoring,
    )

    latest_row = diagnostics.sort_values("as_of_date").iloc[-1]
    # Anchor must be a SCORING window (preference 12M -> 3Y -> 6M), never the 2Y display row.
    assert latest_row["volatility_anchor_window_id"] in {"6M", "12M", "3Y"}
    assert latest_row["volatility_anchor_window_id"] != "2Y"


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


def test_build_rebased_comparison_series_indexes_each_window_to_100():
    dates = list(pd.date_range("2024-01-05", periods=6, freq="W-FRI"))
    series_by_label = {
        # Wildly different absolute scales — the whole reason for rebasing.
        "ABC": (dates, [10.0, 11.0, 12.0, 9.0, 13.0, 14.0]),
        "Gold": (dates, [2000.0, 2100.0, 1900.0, 2200.0, 2300.0, 2400.0]),
    }

    # window_weeks=3 keeps only the last 3 points and re-anchors there.
    out = build_rebased_comparison_series(series_by_label, window_weeks=3)

    assert set(out) == {"ABC", "Gold"}
    abc_dates, abc_values = out["ABC"]
    assert abc_dates == dates[-3:]
    # Last 3 ABC prices [9, 13, 14] -> indexed to 9.
    assert abc_values == pytest.approx([100.0, 13 / 9 * 100, 14 / 9 * 100])
    gold_dates, gold_values = out["Gold"]
    assert gold_dates == dates[-3:]
    # Last 3 Gold prices [2200, 2300, 2400] -> indexed to 2200.
    assert gold_values == pytest.approx([100.0, 2300 / 2200 * 100, 2400 / 2200 * 100])


def test_build_rebased_comparison_series_drops_empty_and_mismatched_series():
    dates = list(pd.date_range("2024-01-05", periods=4, freq="W-FRI"))
    series_by_label = {
        "ABC": (dates, [10.0, 11.0, 12.0, 13.0]),
        "GDXJ": ([], []),  # missing benchmark -> degrade per item, omit the line
        "GDX": (dates, [50.0, 55.0]),  # length mismatch -> dropped, never crashes
    }

    out = build_rebased_comparison_series(series_by_label, window_weeks=52)

    assert set(out) == {"ABC"}
    assert out["ABC"][1] == pytest.approx([100.0, 110.0, 120.0, 130.0])


def test_build_rebased_comparison_series_window_weeks_zero_keeps_full_series():
    # window_weeks=0 means "no windowing" -> keep every point (the `if span else` branch).
    dates = list(pd.date_range("2024-01-05", periods=4, freq="W-FRI"))
    series_by_label = {"ABC": (dates, [10.0, 11.0, 12.0, 13.0])}

    out = build_rebased_comparison_series(series_by_label, window_weeks=0)

    assert out["ABC"][0] == dates  # all dates retained, not a tail slice
    assert out["ABC"][1] == pytest.approx([100.0, 110.0, 120.0, 130.0])


def test_weekly_as_of_date_is_the_later_input_date_thursday_stock_friday_gold():
    """C3: a Thursday stock close paired with Friday gold uses Friday's gold

    value, so the row is only knowable on Friday — it must be dated Friday.
    """
    equity_history = pd.DataFrame(
        [
            {"ticker": "NEM", "date": date(2026, 4, 3), "return_basis_usd": 10.0, "normalization_status": "OK"},
            # Thursday close only in week 2 (exchange holiday Friday)
            {"ticker": "NEM", "date": date(2026, 4, 9), "return_basis_usd": 10.5, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 17), "return_basis_usd": 11.0, "normalization_status": "OK"},
        ]
    )
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 4, 3), "adj_close_usd": 3000.0, "close_usd": 3000.0},
            {"date": date(2026, 4, 10), "adj_close_usd": 3010.0, "close_usd": 3010.0},  # Friday
            {"date": date(2026, 4, 17), "adj_close_usd": 3020.0, "close_usd": 3020.0},
        ]
    )

    weekly_series, _ = build_structural_weekly_series(
        usd_equity_history=equity_history,
        gold_history=gold_history,
    )

    week2 = weekly_series.loc[weekly_series["stock_week_date"].eq(pd.Timestamp("2026-04-09"))]
    assert len(week2) == 1
    assert week2.iloc[0]["as_of_date"] == date(2026, 4, 10)  # the LATER input
    # provenance keeps both source dates
    assert week2.iloc[0]["gold_week_date"] == pd.Timestamp("2026-04-10")


def test_weekly_as_of_date_is_the_later_input_date_friday_stock_thursday_gold():
    """C3 mirror: gold missing Friday, stock trades Friday -> dated Friday."""
    equity_history = pd.DataFrame(
        [
            {"ticker": "NEM", "date": date(2026, 4, 3), "return_basis_usd": 10.0, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 10), "return_basis_usd": 10.5, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 17), "return_basis_usd": 11.0, "normalization_status": "OK"},
        ]
    )
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 4, 3), "adj_close_usd": 3000.0, "close_usd": 3000.0},
            {"date": date(2026, 4, 9), "adj_close_usd": 3010.0, "close_usd": 3010.0},  # Thursday only
            {"date": date(2026, 4, 17), "adj_close_usd": 3020.0, "close_usd": 3020.0},
        ]
    )

    weekly_series, _ = build_structural_weekly_series(
        usd_equity_history=equity_history,
        gold_history=gold_history,
    )

    week2 = weekly_series.loc[weekly_series["gold_week_date"].eq(pd.Timestamp("2026-04-09"))]
    assert len(week2) == 1
    assert week2.iloc[0]["as_of_date"] == date(2026, 4, 10)


def test_weekly_as_of_date_never_precedes_either_input_date():
    """C3 invariant: every row's date is >= both of its source observation dates."""
    equity_history = pd.DataFrame(
        [
            {"ticker": "NEM", "date": date(2026, 3, 20), "return_basis_usd": 9.0, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 3, 26), "return_basis_usd": 9.5, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 2), "return_basis_usd": 10.0, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 10), "return_basis_usd": 10.5, "normalization_status": "OK"},
            {"ticker": "NEM", "date": date(2026, 4, 17), "return_basis_usd": 11.0, "normalization_status": "OK"},
        ]
    )
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 3, 20), "adj_close_usd": 2990.0, "close_usd": 2990.0},
            {"date": date(2026, 3, 27), "adj_close_usd": 2995.0, "close_usd": 2995.0},
            {"date": date(2026, 4, 3), "adj_close_usd": 3000.0, "close_usd": 3000.0},
            {"date": date(2026, 4, 9), "adj_close_usd": 3010.0, "close_usd": 3010.0},
            {"date": date(2026, 4, 17), "adj_close_usd": 3020.0, "close_usd": 3020.0},
        ]
    )

    weekly_series, _ = build_structural_weekly_series(
        usd_equity_history=equity_history,
        gold_history=gold_history,
    )

    assert not weekly_series.empty
    as_of = pd.to_datetime(weekly_series["as_of_date"])
    assert (as_of >= weekly_series["stock_week_date"]).all()
    assert (as_of >= weekly_series["gold_week_date"]).all()
