from datetime import date

import numpy as np
import pandas as pd

from golden_vector.features.weekly_returns import (
    WEEKLY_RETURN_COLUMNS,
    build_weekly_return_frame,
)


def test_build_weekly_return_frame_aligns_stock_gold_and_benchmarks():
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 4, 3), "adj_close_usd": 3000.0},
            {"date": date(2026, 4, 10), "adj_close_usd": 3030.0},
            {"date": date(2026, 4, 17), "adj_close_usd": 3060.0},
        ]
    )
    equity_histories = {
        "NEM": pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "date": date(2026, 4, 3),
                    "return_basis_usd": 50.0,
                    "normalization_status": "OK",
                },
                {
                    "ticker": "NEM",
                    "date": date(2026, 4, 10),
                    "return_basis_usd": 55.0,
                    "normalization_status": "OK",
                },
                {
                    "ticker": "NEM",
                    "date": date(2026, 4, 17),
                    "return_basis_usd": 60.0,
                    "normalization_status": "OK",
                },
            ]
        )
    }
    benchmark_histories = {
        "GDX": pd.DataFrame(
            [
                {"date": date(2026, 4, 3), "return_basis_usd": 100.0},
                {"date": date(2026, 4, 10), "return_basis_usd": 101.0},
                {"date": date(2026, 4, 17), "return_basis_usd": 103.0},
            ]
        ),
        "GDXJ": pd.DataFrame(
            [
                {"date": date(2026, 4, 3), "adj_close_usd": 40.0},
                {"date": date(2026, 4, 10), "adj_close_usd": 38.0},
                {"date": date(2026, 4, 17), "adj_close_usd": 39.0},
            ]
        ),
    }

    frame = build_weekly_return_frame(
        normalized_equity_histories=equity_histories,
        gold_history=gold_history,
        benchmark_histories=benchmark_histories,
    )

    assert list(frame.columns) == WEEKLY_RETURN_COLUMNS
    assert list(frame["ticker"]) == ["NEM", "NEM"]
    assert list(frame["week_period"]) == ["2026-04-04/2026-04-10", "2026-04-11/2026-04-17"]
    assert frame.loc[0, "stock_log_ret"] == np.log(55.0 / 50.0)
    assert frame.loc[0, "gold_log_ret"] == np.log(3030.0 / 3000.0)
    assert frame.loc[1, "gdx_log_ret"] == np.log(103.0 / 101.0)
    assert frame.loc[0, "gdxj_log_ret"] == np.log(38.0 / 40.0)


def test_weekly_return_frame_drops_incomplete_current_week():
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 4, 3), "adj_close_usd": 3000.0},
            {"date": date(2026, 4, 10), "adj_close_usd": 3030.0},
            {"date": date(2026, 4, 15), "adj_close_usd": 3040.0},
        ]
    )
    equity_histories = {
        "NEM": pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "date": date(2026, 4, 3),
                    "return_basis_usd": 50.0,
                    "normalization_status": "OK",
                },
                {
                    "ticker": "NEM",
                    "date": date(2026, 4, 10),
                    "return_basis_usd": 55.0,
                    "normalization_status": "OK",
                },
                {
                    "ticker": "NEM",
                    "date": date(2026, 4, 15),
                    "return_basis_usd": 56.0,
                    "normalization_status": "OK",
                },
            ]
        )
    }

    frame = build_weekly_return_frame(
        normalized_equity_histories=equity_histories,
        gold_history=gold_history,
    )

    assert list(frame["week_period"]) == ["2026-04-04/2026-04-10"]


def test_weekly_return_frame_returns_contract_columns_when_empty():
    frame = build_weekly_return_frame(
        normalized_equity_histories={},
        gold_history=pd.DataFrame(),
        benchmark_histories={},
    )

    assert list(frame.columns) == WEEKLY_RETURN_COLUMNS
    assert frame.empty
