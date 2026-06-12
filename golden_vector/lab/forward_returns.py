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

    if sorted(set(horizons_weeks)) != sorted(horizons_weeks) or len(set(horizons_weeks)) != len(horizons_weeks):
        raise ValueError("horizons_weeks must be unique.")
    if any(int(h) < 1 for h in horizons_weeks):
        raise ValueError("horizons_weeks must be positive.")

    pieces: list[pd.DataFrame] = []
    for ticker, group in weekly_frame.groupby("ticker", sort=True):
        ordered = group.sort_values("week_period").reset_index(drop=True)
        out = ordered[["ticker", "week_period"]].copy()
        for horizon in horizons_weeks:
            h = int(horizon)
            out[f"fwd_log_ret_{h}w"] = _forward_sum(ordered["stock_log_ret"], h)
            gdx_fwd = _forward_sum(ordered["gdx_log_ret"], h)
            gdxj_fwd = _forward_sum(ordered["gdxj_log_ret"], h)
            out[f"fwd_alpha_gdx_{h}w"] = out[f"fwd_log_ret_{h}w"] - gdx_fwd
            out[f"fwd_alpha_gdxj_{h}w"] = out[f"fwd_log_ret_{h}w"] - gdxj_fwd
        pieces.append(out)

    if not pieces:
        return pd.DataFrame(columns=["ticker", "week_period"])
    return pd.concat(pieces, ignore_index=True)


def _forward_sum(series: pd.Series, horizon_weeks: int) -> pd.Series:
    """Sum of weeks t+1..t+h; NA unless every one of the h weeks is present."""

    values = pd.to_numeric(series, errors="coerce")
    # rolling(h) at t covers t-h+1..t; shift(-h) moves that window to t+1..t+h.
    forward = values.rolling(window=horizon_weeks, min_periods=horizon_weeks).sum().shift(-horizon_weeks)
    return forward.astype("Float64")
