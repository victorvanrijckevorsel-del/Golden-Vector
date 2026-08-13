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
    "downside_hit_count",
    "downside_period_start",
    "downside_period_end",
    "downside_compare_n",
    "downside_compare_period_start",
    "downside_compare_period_end",
    "downside_compare_stock_hit_rate",
    "downside_compare_stock_hit_count",
    "downside_compare_stock_median_return",
    "downside_compare_stock_worst_return",
    "downside_compare_gdx_hit_rate",
    "downside_compare_gdx_hit_count",
    "downside_compare_gdx_median_return",
    "downside_compare_gdx_worst_return",
    "downside_recent_n",
    "downside_recent_period_start",
    "downside_recent_period_end",
    "downside_recent_stock_hit_rate",
    "downside_recent_stock_hit_count",
    "downside_recent_stock_median_return",
    "downside_recent_stock_worst_return",
    "downside_recent_gdx_hit_rate",
    "downside_recent_gdx_hit_count",
    "downside_recent_gdx_median_return",
    "downside_recent_gdx_worst_return",
    "upside_hit_rate_10pct",
    "upside_hit_rate_n",
    "upside_hit_count",
    "upside_period_start",
    "upside_period_end",
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
    downside_recent_years: int = 2,
    downside_hit_rate_log_threshold: float = math.log1p(-0.10),
    upside_hit_rate_log_threshold: float = math.log1p(0.10),
) -> pd.DataFrame:
    """Compute Tool C's per-ticker relative/hit-rate/tail metrics."""

    if min_events <= 0:
        raise ValueError("min_events must be positive")
    if downside_recent_years <= 0:
        raise ValueError("downside_recent_years must be positive")
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
        comparison = _downside_comparison(
            ticker_rows,
            min_events=min_events,
            threshold=downside_hit_rate_log_threshold,
            prefix="downside_compare",
        )
        recent_rows = _recent_rows(ticker_rows, years=downside_recent_years)
        recent_comparison = _downside_comparison(
            recent_rows,
            min_events=min_events,
            threshold=downside_hit_rate_log_threshold,
            prefix="downside_recent",
        )
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
                    hit_count_column="downside_hit_count",
                    period_start_column="downside_period_start",
                    period_end_column="downside_period_end",
                    min_events=min_events,
                    threshold=downside_hit_rate_log_threshold,
                    high_side=False,
                ),
                **comparison,
                **recent_comparison,
                **_threshold_rate(
                    ticker_rows,
                    event_column="gold_best20_event",
                    result_column="upside_hit_rate_10pct",
                    count_column="upside_hit_rate_n",
                    hit_count_column="upside_hit_count",
                    period_start_column="upside_period_start",
                    period_end_column="upside_period_end",
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


def _recent_rows(rows: pd.DataFrame, *, years: int) -> pd.DataFrame:
    """Return the configured trailing calendar window using real week dates."""

    if rows.empty or "week_period" not in rows.columns:
        return rows.iloc[0:0].copy()
    dates = pd.Series(pd.NaT, index=rows.index, dtype="datetime64[ns]")
    for index, value in rows["week_period"].items():
        try:
            dates.loc[index] = pd.Period(str(value), freq="W-FRI").end_time.normalize()
        except ValueError:
            continue
    latest = dates.dropna().max()
    if pd.isna(latest):
        return rows.iloc[0:0].copy()
    cutoff = pd.Timestamp(latest) - pd.DateOffset(years=years)
    return rows.loc[dates.ge(cutoff)].copy()


def _downside_comparison(
    rows: pd.DataFrame,
    *,
    min_events: int,
    threshold: float,
    prefix: str,
) -> dict[str, object]:
    """Persist stock/GDX frequency and conditional severity on aligned events."""

    events = _event_rows(
        rows,
        "gold_worst20_event",
        required_columns=["gdx_log_ret"],
    )
    count = len(events.index)
    period_start, period_end = _event_period(events)
    result: dict[str, object] = {
        f"{prefix}_n": count,
        f"{prefix}_period_start": period_start,
        f"{prefix}_period_end": period_end,
    }
    for label, column in (("stock", "stock_log_ret"), ("gdx", "gdx_log_ret")):
        rate_key = f"{prefix}_{label}_hit_rate"
        count_key = f"{prefix}_{label}_hit_count"
        median_key = f"{prefix}_{label}_median_return"
        worst_key = f"{prefix}_{label}_worst_return"
        if count < min_events:
            result.update(
                {rate_key: None, count_key: None, median_key: None, worst_key: None}
            )
            continue
        values = pd.to_numeric(events[column], errors="coerce")
        hit_values = values.loc[values.le(threshold)]
        result[rate_key] = float(len(hit_values.index) / count)
        result[count_key] = int(len(hit_values.index))
        if hit_values.empty:
            result[median_key] = None
            result[worst_key] = None
        else:
            # Weekly inputs are log returns; user-facing severity is an ordinary
            # price return. Convert once in the producer, never in the renderer.
            simple = hit_values.map(math.expm1)
            result[median_key] = float(simple.median())
            result[worst_key] = float(simple.min())
    return result


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
    hit_count_column: str,
    period_start_column: str,
    period_end_column: str,
    min_events: int,
    threshold: float,
    high_side: bool,
) -> dict[str, object]:
    """Exact hit evidence: numerator, denominator, and the qualifying-event
    period — persisted upstream so no consumer ever reconstructs a count from
    a rounded rate."""

    event_rows = _event_rows(rows, event_column, required_columns=[])
    count = len(event_rows.index)
    period_start, period_end = _event_period(event_rows)
    if count < min_events:
        return {
            result_column: None,
            count_column: count,
            hit_count_column: None,
            period_start_column: period_start,
            period_end_column: period_end,
        }
    stock = pd.to_numeric(event_rows["stock_log_ret"], errors="coerce")
    hits = stock.ge(threshold) if high_side else stock.le(threshold)
    return {
        result_column: float(hits.mean()),
        count_column: count,
        hit_count_column: int(hits.sum()),
        period_start_column: period_start,
        period_end_column: period_end,
    }


def _event_period(event_rows: pd.DataFrame) -> tuple[object, object]:
    """First/last qualifying-event date, when the rows carry dates."""

    if event_rows.empty:
        return None, None
    if "as_of_date" in event_rows.columns:
        dates = pd.to_datetime(event_rows["as_of_date"], errors="coerce").dropna()
    elif "week_period" in event_rows.columns:
        # ``build_weekly_return_frame`` publishes W-FRI period strings rather
        # than an ``as_of_date`` column. Persist the actual week-ending dates;
        # looking only for ``as_of_date`` left every live downside/upside
        # evidence period null even though the qualifying rows were present.
        parsed: list[pd.Timestamp] = []
        for value in event_rows["week_period"].dropna():
            try:
                parsed.append(pd.Period(str(value), freq="W-FRI").end_time.normalize())
            except ValueError:
                continue
        dates = pd.DatetimeIndex(parsed)
    else:
        return None, None
    if dates.empty:
        return None, None
    return dates.min(), dates.max()


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
