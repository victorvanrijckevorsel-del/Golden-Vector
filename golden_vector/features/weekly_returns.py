"""Weekly return frame construction for cross-sectional tools."""

from __future__ import annotations

import numpy as np
import pandas as pd

from golden_vector.model.structural import build_structural_weekly_series

WEEKLY_RETURN_COLUMNS = [
    "ticker",
    "week_period",
    "stock_log_ret",
    "gold_log_ret",
    "gdx_log_ret",
    "gdxj_log_ret",
]

BENCHMARK_COLUMN_MAP = {
    "GDX": "gdx_log_ret",
    "GDXJ": "gdxj_log_ret",
}


def build_weekly_return_frame(
    *,
    normalized_equity_histories: dict[str, pd.DataFrame],
    gold_history: pd.DataFrame,
    benchmark_histories: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Build Tool C's one-row-per-ticker-week return contract.

    Stock/gold returns are produced through Tool A's structural weekly builder
    so Tool C stays on the same W-FRI weekly sampling rule. Benchmark returns
    are joined by that same week key.
    """

    benchmark_returns = _benchmark_return_frame(benchmark_histories or {})
    rows: list[pd.DataFrame] = []
    for ticker, equity_history in sorted(normalized_equity_histories.items()):
        weekly_series, _ = build_structural_weekly_series(
            usd_equity_history=equity_history,
            gold_history=gold_history,
        )
        if weekly_series.empty:
            continue
        ticker_frame = pd.DataFrame(
            {
                "ticker": str(ticker).upper(),
                "week_period": _week_period(weekly_series["stock_week_date"]),
                "stock_log_ret": pd.to_numeric(
                    weekly_series["stock_weekly_log_return"],
                    errors="coerce",
                ),
                "gold_log_ret": pd.to_numeric(
                    weekly_series["gold_weekly_log_return"],
                    errors="coerce",
                ),
            }
        )
        ticker_frame = ticker_frame.merge(
            benchmark_returns,
            how="left",
            on="week_period",
        )
        rows.append(ticker_frame)

    if not rows:
        return pd.DataFrame(columns=WEEKLY_RETURN_COLUMNS)

    result = pd.concat(rows, ignore_index=True)
    for column in WEEKLY_RETURN_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result[WEEKLY_RETURN_COLUMNS].sort_values(
        ["ticker", "week_period"],
    ).reset_index(drop=True)


def _benchmark_return_frame(benchmark_histories: dict[str, pd.DataFrame]) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for ticker, column in BENCHMARK_COLUMN_MAP.items():
        returns = _single_price_weekly_returns(
            benchmark_histories.get(ticker, pd.DataFrame()),
            output_column=column,
        )
        if returns.empty:
            returns = pd.DataFrame(
                {
                    "week_period": pd.Series(dtype="object"),
                    column: pd.Series(dtype="Float64"),
                }
            )
        merged = returns if merged is None else merged.merge(
            returns,
            how="outer",
            on="week_period",
        )
    if merged is None:
        return pd.DataFrame(
            {
                "week_period": pd.Series(dtype="object"),
                "gdx_log_ret": pd.Series(dtype="Float64"),
                "gdxj_log_ret": pd.Series(dtype="Float64"),
            }
        )
    for column in ("gdx_log_ret", "gdxj_log_ret"):
        if column not in merged.columns:
            merged[column] = pd.NA
    return merged[["week_period", "gdx_log_ret", "gdxj_log_ret"]]


def _single_price_weekly_returns(frame: pd.DataFrame, *, output_column: str) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns:
        return pd.DataFrame(columns=["week_period", output_column])
    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working["basis_usd"] = _price_basis(working)
    working = working.loc[working["date"].notna() & working["basis_usd"].gt(0)].copy()
    if working.empty:
        return pd.DataFrame(columns=["week_period", output_column])

    working["week_period"] = working["date"].dt.to_period("W-FRI")
    working = working.sort_values("date")
    latest_period = working["week_period"].max()
    latest_period_end = latest_period.end_time.normalize()
    latest_date = pd.Timestamp(working["date"].max())
    if latest_period_end.date() > latest_date.date():
        working = working.loc[working["week_period"].ne(latest_period)].copy()
    if working.empty:
        return pd.DataFrame(columns=["week_period", output_column])

    weekly = working.groupby("week_period", as_index=False).tail(1).copy()
    weekly = weekly.sort_values("week_period")
    weekly[output_column] = np.log(weekly["basis_usd"] / weekly["basis_usd"].shift(1))
    weekly = weekly.loc[weekly[output_column].notna()].copy()
    weekly["week_period"] = weekly["week_period"].astype(str)
    return weekly[["week_period", output_column]].reset_index(drop=True)


def _price_basis(frame: pd.DataFrame) -> pd.Series:
    if "return_basis_usd" in frame.columns:
        basis = pd.to_numeric(frame["return_basis_usd"], errors="coerce")
    else:
        basis = pd.Series(pd.NA, index=frame.index, dtype="Float64")
    for column in ("adj_close_usd", "close_usd"):
        if column in frame.columns:
            basis = basis.where(
                basis.notna(),
                pd.to_numeric(frame[column], errors="coerce"),
            )
    return basis


def _week_period(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.to_period("W-FRI").astype(str)
