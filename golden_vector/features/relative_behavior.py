"""Relative behavior metrics for Tool C."""

from __future__ import annotations

import math
import pandas as pd

RELATIVE_BEHAVIOR_COLUMNS = [
    "ticker",
    "rel_weakness_vs_gold_pct",
    "rel_weakness_vs_gold_n",
    "rel_weakness_vs_gdx_pct",
    "rel_weakness_vs_gdx_n",
    "rel_weakness_vs_gdxj_pct",
    "rel_weakness_vs_gdxj_n",
    "rel_strength_vs_gold_pct",
    "rel_strength_vs_gold_n",
    "rel_strength_vs_gdx_pct",
    "rel_strength_vs_gdx_n",
    "rel_strength_vs_gdxj_pct",
    "rel_strength_vs_gdxj_n",
    "n_weeks_gold",
    "n_weeks_gdx",
    "n_weeks_gdxj",
    "downside_hit_rate_10pct",
    "downside_hit_rate_n",
    "upside_hit_rate_10pct",
    "upside_hit_rate_n",
    "tail_avg_return_worst10pct",
    "tail_avg_return_worst10pct_n",
    "tail_avg_return_worst20pct",
    "tail_avg_return_worst20pct_n",
    "tail_avg_return_best10pct",
    "tail_avg_return_best10pct_n",
    "tail_avg_return_best20pct",
    "tail_avg_return_best20pct_n",
]


def compute_relative_behavior_metrics(
    *,
    weekly_returns: pd.DataFrame,
    gold_regimes: pd.DataFrame,
    min_events: int,
    downside_hit_rate_log_threshold: float = math.log1p(-0.10),
    upside_hit_rate_log_threshold: float = math.log1p(0.10),
) -> pd.DataFrame:
    """Compute Tool C's per-ticker relative/hit-rate/tail metrics."""

    if min_events <= 0:
        raise ValueError("min_events must be positive")
    if weekly_returns.empty or gold_regimes.empty:
        return pd.DataFrame(columns=RELATIVE_BEHAVIOR_COLUMNS)

    regime_columns = [
        column for column in gold_regimes.columns if column != "gold_log_ret"
    ]
    data = weekly_returns.merge(
        gold_regimes[regime_columns],
        how="left",
        on="week_period",
    )
    if data.empty or "ticker" not in data.columns:
        return pd.DataFrame(columns=RELATIVE_BEHAVIOR_COLUMNS)

    rows: list[dict[str, object]] = []
    for ticker, ticker_rows in data.groupby("ticker", sort=True):
        rows.append(
            {
                "ticker": str(ticker).upper(),
                **_relative_rate(
                    ticker_rows,
                    event_column="gold_worst20_event",
                    compare_column="gold_log_ret",
                    result_column="rel_weakness_vs_gold_pct",
                    count_column="rel_weakness_vs_gold_n",
                    min_events=min_events,
                    high_side=False,
                ),
                **_relative_rate(
                    ticker_rows,
                    event_column="gold_worst20_event",
                    compare_column="gdx_log_ret",
                    result_column="rel_weakness_vs_gdx_pct",
                    count_column="rel_weakness_vs_gdx_n",
                    min_events=min_events,
                    high_side=False,
                ),
                **_relative_rate(
                    ticker_rows,
                    event_column="gold_worst20_event",
                    compare_column="gdxj_log_ret",
                    result_column="rel_weakness_vs_gdxj_pct",
                    count_column="rel_weakness_vs_gdxj_n",
                    min_events=min_events,
                    high_side=False,
                ),
                **_relative_rate(
                    ticker_rows,
                    event_column="gold_best20_event",
                    compare_column="gold_log_ret",
                    result_column="rel_strength_vs_gold_pct",
                    count_column="rel_strength_vs_gold_n",
                    min_events=min_events,
                    high_side=True,
                ),
                **_relative_rate(
                    ticker_rows,
                    event_column="gold_best20_event",
                    compare_column="gdx_log_ret",
                    result_column="rel_strength_vs_gdx_pct",
                    count_column="rel_strength_vs_gdx_n",
                    min_events=min_events,
                    high_side=True,
                ),
                **_relative_rate(
                    ticker_rows,
                    event_column="gold_best20_event",
                    compare_column="gdxj_log_ret",
                    result_column="rel_strength_vs_gdxj_pct",
                    count_column="rel_strength_vs_gdxj_n",
                    min_events=min_events,
                    high_side=True,
                ),
                "n_weeks_gold": _complete_week_count(
                    ticker_rows,
                    ["stock_log_ret", "gold_log_ret"],
                ),
                "n_weeks_gdx": _complete_week_count(
                    ticker_rows,
                    ["stock_log_ret", "gdx_log_ret"],
                ),
                "n_weeks_gdxj": _complete_week_count(
                    ticker_rows,
                    ["stock_log_ret", "gdxj_log_ret"],
                ),
                **_threshold_rate(
                    ticker_rows,
                    event_column="gold_worst20_event",
                    result_column="downside_hit_rate_10pct",
                    count_column="downside_hit_rate_n",
                    min_events=min_events,
                    threshold=downside_hit_rate_log_threshold,
                    high_side=False,
                ),
                **_threshold_rate(
                    ticker_rows,
                    event_column="gold_best20_event",
                    result_column="upside_hit_rate_10pct",
                    count_column="upside_hit_rate_n",
                    min_events=min_events,
                    threshold=upside_hit_rate_log_threshold,
                    high_side=True,
                ),
                **_tail_average(
                    ticker_rows,
                    event_column="gold_worst10_event",
                    result_column="tail_avg_return_worst10pct",
                    count_column="tail_avg_return_worst10pct_n",
                    min_events=min_events,
                ),
                **_tail_average(
                    ticker_rows,
                    event_column="gold_worst20_event",
                    result_column="tail_avg_return_worst20pct",
                    count_column="tail_avg_return_worst20pct_n",
                    min_events=min_events,
                ),
                **_tail_average(
                    ticker_rows,
                    event_column="gold_best10_event",
                    result_column="tail_avg_return_best10pct",
                    count_column="tail_avg_return_best10pct_n",
                    min_events=min_events,
                ),
                **_tail_average(
                    ticker_rows,
                    event_column="gold_best20_event",
                    result_column="tail_avg_return_best20pct",
                    count_column="tail_avg_return_best20pct_n",
                    min_events=min_events,
                ),
            }
        )
    return pd.DataFrame(rows, columns=RELATIVE_BEHAVIOR_COLUMNS).reset_index(drop=True)


def _complete_week_count(rows: pd.DataFrame, columns: list[str]) -> int:
    if not all(column in rows.columns for column in columns):
        return 0
    numeric = rows[columns].apply(pd.to_numeric, errors="coerce")
    return int(numeric.notna().all(axis=1).sum())


def _relative_rate(
    rows: pd.DataFrame,
    *,
    event_column: str,
    compare_column: str,
    result_column: str,
    count_column: str,
    min_events: int,
    high_side: bool,
) -> dict[str, object]:
    event_rows = _event_rows(rows, event_column, required_columns=[compare_column])
    count = len(event_rows.index)
    if count < min_events:
        return {result_column: None, count_column: count}
    stock = pd.to_numeric(event_rows["stock_log_ret"], errors="coerce")
    compare = pd.to_numeric(event_rows[compare_column], errors="coerce")
    hits = stock.gt(compare) if high_side else stock.lt(compare)
    return {result_column: float(hits.mean()), count_column: count}


def _threshold_rate(
    rows: pd.DataFrame,
    *,
    event_column: str,
    result_column: str,
    count_column: str,
    min_events: int,
    threshold: float,
    high_side: bool,
) -> dict[str, object]:
    event_rows = _event_rows(rows, event_column, required_columns=[])
    count = len(event_rows.index)
    if count < min_events:
        return {result_column: None, count_column: count}
    stock = pd.to_numeric(event_rows["stock_log_ret"], errors="coerce")
    hits = stock.ge(threshold) if high_side else stock.le(threshold)
    return {result_column: float(hits.mean()), count_column: count}


def _tail_average(
    rows: pd.DataFrame,
    *,
    event_column: str,
    result_column: str,
    count_column: str,
    min_events: int,
) -> dict[str, object]:
    event_rows = _event_rows(rows, event_column, required_columns=[])
    count = len(event_rows.index)
    if count < min_events:
        return {result_column: None, count_column: count}
    stock = pd.to_numeric(event_rows["stock_log_ret"], errors="coerce")
    return {result_column: float(stock.mean()), count_column: count}


def _event_rows(
    rows: pd.DataFrame,
    event_column: str,
    *,
    required_columns: list[str],
) -> pd.DataFrame:
    if event_column not in rows.columns or "stock_log_ret" not in rows.columns:
        return rows.iloc[0:0].copy()
    event_mask = rows[event_column].fillna(False).astype(bool)
    event_rows = rows.loc[event_mask].copy()
    event_rows = event_rows.loc[
        pd.to_numeric(event_rows["stock_log_ret"], errors="coerce").notna()
    ].copy()
    for column in required_columns:
        if column not in event_rows.columns:
            return event_rows.iloc[0:0].copy()
        event_rows = event_rows.loc[
            pd.to_numeric(event_rows[column], errors="coerce").notna()
        ].copy()
    return event_rows
