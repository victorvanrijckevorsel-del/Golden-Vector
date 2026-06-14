"""M0-3: forward-return label panel on the W-FRI weekly grid.

Labels are STRICTLY forward: the h-week forward log return at week t sums
weekly log returns over weeks t+1..t+h (log returns are additive), so the
label never touches week t's own return. A label is only emitted when all h
forward weeks are present (``complete`` accounting — no silently short
windows). Alpha labels subtract the same-window benchmark forward return.

Gold-side columns are deliberately absent from the label set: predicting
gold is banned by the Lab contract (gold enters only as conditioning data).
"""

from __future__ import annotations

import pandas as pd

LABEL_PREFIXES = ("fwd_log_ret", "fwd_alpha_gdx", "fwd_alpha_gdxj")


def build_forward_return_panel(
    weekly_frame: pd.DataFrame,
    *,
    horizons_weeks: list[int],
) -> pd.DataFrame:
    """One row per (ticker, week_period) with forward labels per horizon.

    ``weekly_frame`` is the Tool C contract from
    :func:`golden_vector.features.weekly_returns.build_weekly_return_frame`:
    columns ticker / week_period / stock_log_ret / gold_log_ret /
    gdx_log_ret / gdxj_log_ret.
    """

    if (
        sorted(set(horizons_weeks)) != sorted(horizons_weeks)
        or len(set(horizons_weeks)) != len(horizons_weeks)
    ):
        raise ValueError("horizons_weeks must be unique.")
    if any(int(h) < 1 for h in horizons_weeks):
        raise ValueError("horizons_weeks must be positive.")

    benchmark_forwards = _benchmark_forward_panel(weekly_frame, horizons_weeks)
    pieces: list[pd.DataFrame] = []
    for ticker, group in weekly_frame.groupby("ticker", sort=True):
        ordered = reindex_contiguous_weeks(group)
        out = ordered[["ticker", "week_period"]].copy()
        for horizon in horizons_weeks:
            h = int(horizon)
            out[f"fwd_log_ret_{h}w"] = forward_sum(ordered["stock_log_ret"], h)
        out = out.merge(benchmark_forwards, on="week_period", how="left")
        for horizon in horizons_weeks:
            h = int(horizon)
            out[f"fwd_alpha_gdx_{h}w"] = (
                out[f"fwd_log_ret_{h}w"] - out[f"fwd_gdx_log_ret_{h}w"]
            )
            out[f"fwd_alpha_gdxj_{h}w"] = (
                out[f"fwd_log_ret_{h}w"] - out[f"fwd_gdxj_log_ret_{h}w"]
            )
            out = out.drop(columns=[f"fwd_gdx_log_ret_{h}w", f"fwd_gdxj_log_ret_{h}w"])
        pieces.append(out)

    if not pieces:
        return pd.DataFrame(columns=["ticker", "week_period"])
    return pd.concat(pieces, ignore_index=True)


def _benchmark_forward_panel(
    weekly_frame: pd.DataFrame,
    horizons_weeks: list[int],
) -> pd.DataFrame:
    """Calendar-level benchmark forward returns, computed once per horizon.

    GDX/GDXJ returns are identical for every ticker on a given week in the
    weekly frame. Computing their forward windows inside each ticker group is
    correct but wasteful. This helper keeps the same complete-window semantics
    while avoiding 65 repeated benchmark rolling calculations.
    """

    if weekly_frame.empty:
        columns = ["week_period"] + [
            f"fwd_{bench}_log_ret_{int(h)}w"
            for h in horizons_weeks
            for bench in ("gdx", "gdxj")
        ]
        return pd.DataFrame(columns=columns)
    source = weekly_frame[["week_period", "gdx_log_ret", "gdxj_log_ret"]].sort_values(
        "week_period"
    )
    assert_calendar_values(source, columns=("gdx_log_ret", "gdxj_log_ret"))
    calendar = source.groupby("week_period", as_index=False).first()
    out = calendar[["week_period"]].copy()
    for horizon in horizons_weeks:
        h = int(horizon)
        out[f"fwd_gdx_log_ret_{h}w"] = forward_sum(calendar["gdx_log_ret"], h)
        out[f"fwd_gdxj_log_ret_{h}w"] = forward_sum(calendar["gdxj_log_ret"], h)
    return out


def assert_calendar_values(
    source: pd.DataFrame,
    *,
    columns: tuple[str, ...],
) -> None:
    """Fail if a calendar-level value differs across tickers for the same week.

    Gold and benchmark returns are calendar facts. Vectorized Lab paths compute
    those windows once per week, so an upstream merge bug that creates per-ticker
    disagreements must fail loudly instead of silently taking the first row.
    """

    for column in columns:
        non_null = source.dropna(subset=[column])
        if non_null.empty:
            continue
        conflicts = non_null.groupby("week_period")[column].nunique()
        bad_weeks = conflicts[conflicts > 1]
        if not bad_weeks.empty:
            sample = ", ".join(str(value) for value in bad_weeks.index[:3])
            raise ValueError(
                f"Inconsistent {column} values across tickers for week_period "
                f"{sample}; benchmark returns must be one calendar value per week."
            )


def reindex_contiguous_weeks(group: pd.DataFrame) -> pd.DataFrame:
    """Insert NaN rows for any calendar week missing from the ticker's grid.

    The forward sum shifts over ROW positions; if a week were absent (not
    NaN, missing entirely) an h-week label would silently span more than h
    calendar weeks. Real data is contiguous today (verified across all 65
    tickers), but the label math must not depend on an unstated upstream
    invariant — a halted ticker would corrupt labels without this.
    """

    ordered = group.sort_values("week_period").reset_index(drop=True)
    periods = pd.PeriodIndex(ordered["week_period"].astype(str), freq="W-FRI")
    if periods.has_duplicates:
        # A duplicated week double-counts in positional window math and can
        # mask a gap (lengths coincide) — never compute labels over it.
        ticker = str(ordered["ticker"].iloc[0]) if "ticker" in ordered.columns else "?"
        raise ValueError(
            f"Duplicate week_period rows for ticker {ticker}; "
            "label math requires one row per (ticker, week)."
        )
    if len(periods) < 2:
        return ordered
    full_grid = pd.period_range(periods.min(), periods.max(), freq="W-FRI")
    if len(full_grid) == len(periods):
        return ordered
    reindexed = ordered.set_index(periods).reindex(full_grid)
    reindexed["ticker"] = reindexed["ticker"].ffill().bfill()
    reindexed["week_period"] = [str(period) for period in full_grid]
    return reindexed.reset_index(drop=True)


def forward_sum(series: pd.Series, horizon_weeks: int) -> pd.Series:
    """Sum of weeks t+1..t+h; NA unless every one of the h weeks is present."""

    values = pd.to_numeric(series, errors="coerce")
    # rolling(h) at t covers t-h+1..t; shift(-h) moves that window to t+1..t+h.
    forward = values.rolling(window=horizon_weeks, min_periods=horizon_weeks).sum().shift(-horizon_weeks)
    return forward.astype("Float64")
