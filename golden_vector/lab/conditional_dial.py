"""Conditional Dial analog table — the Lab's spine deliverable.

For a USER-CHOSEN gold scenario bucket (e.g. "gold −5% to −15% over the
next 13 weeks"), count what each miner actually did across every historical
episode where gold's forward 13-week return landed in that bucket:
P(beat GDX), median alpha vs GDX, and the 10–90% alpha range.

Honesty rules (from the Lab spec — these are contract, not style):
- The scenario bucket is the USER'S hypothetical. Nothing here derives a
  "current" bucket from realized gold — that would leak the answer.
- Pure counting + empirical-Bayes shrinkage toward the pooled rate; no
  fitted models.
- Wilson intervals computed on EPISODE-adjusted N (overlapping weekly
  windows are not independent observations), shown next to raw N.
- A cell below the effective-N floor reports insufficient_history=True and
  carries NO numbers — a blank is more honest than a hallucinated rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from golden_vector.lab.forward_returns import _forward_sum
from golden_vector.lab.walk_forward import effective_n

DEFAULT_BUCKETS: list[tuple[str, float | None, float | None]] = [
    ("gold_down_big", None, -0.15),
    ("gold_down", -0.15, -0.05),
    ("gold_flat", -0.05, 0.05),
    ("gold_up", 0.05, 0.15),
    ("gold_up_big", 0.15, None),
]
MIN_EFFECTIVE_N = 8.0
EB_PRIOR_STRENGTH = 10.0  # pseudo-episodes pulling each cell toward the pooled rate


@dataclass(frozen=True)
class DialCell:
    ticker: str
    bucket: str
    n_weeks: int
    effective_n: float
    insufficient_history: bool
    p_beat_gdx: float | None
    p_beat_gdx_shrunk: float | None
    wilson_low: float | None
    wilson_high: float | None
    median_alpha: float | None
    alpha_q10: float | None
    alpha_q90: float | None


def build_dial_table(
    weekly_frame: pd.DataFrame,
    *,
    horizon_weeks: int = 13,
    buckets: list[tuple[str, float | None, float | None]] | None = None,
    min_effective_n: float = MIN_EFFECTIVE_N,
) -> pd.DataFrame:
    """One row per (ticker, gold bucket) with counted analog outcomes."""

    bucket_defs = buckets if buckets is not None else DEFAULT_BUCKETS
    episodes = _episode_frame(weekly_frame, horizon_weeks=horizon_weeks)
    if episodes.empty:
        return pd.DataFrame()
    episodes["bucket"] = episodes["gold_fwd_simple"].map(
        lambda value: _assign_bucket(value, bucket_defs)
    )
    episodes = episodes.dropna(subset=["bucket"])

    # Pooled beat rate per bucket (across all tickers) = the EB prior mean.
    pooled = (
        episodes.groupby("bucket")["beat_gdx"].mean().to_dict()
    )

    cells: list[DialCell] = []
    for (ticker, bucket), group in episodes.groupby(["ticker", "bucket"], sort=True):
        n_weeks = int(len(group))
        eff_n = effective_n(n_weeks, label_horizon_weeks=horizon_weeks)
        if eff_n < min_effective_n:
            cells.append(
                DialCell(
                    ticker=str(ticker),
                    bucket=str(bucket),
                    n_weeks=n_weeks,
                    effective_n=round(eff_n, 2),
                    insufficient_history=True,
                    p_beat_gdx=None,
                    p_beat_gdx_shrunk=None,
                    wilson_low=None,
                    wilson_high=None,
                    median_alpha=None,
                    alpha_q10=None,
                    alpha_q90=None,
                )
            )
            continue
        p_raw = float(group["beat_gdx"].mean())
        prior = float(pooled[bucket])
        p_shrunk = (p_raw * eff_n + prior * EB_PRIOR_STRENGTH) / (
            eff_n + EB_PRIOR_STRENGTH
        )
        low, high = _wilson_interval(p_raw, eff_n)
        alphas = group["alpha_gdx"]
        cells.append(
            DialCell(
                ticker=str(ticker),
                bucket=str(bucket),
                n_weeks=n_weeks,
                effective_n=round(eff_n, 2),
                insufficient_history=False,
                p_beat_gdx=round(p_raw, 4),
                p_beat_gdx_shrunk=round(p_shrunk, 4),
                wilson_low=round(low, 4),
                wilson_high=round(high, 4),
                median_alpha=round(float(alphas.median()), 6),
                alpha_q10=round(float(alphas.quantile(0.10)), 6),
                alpha_q90=round(float(alphas.quantile(0.90)), 6),
            )
        )
    return pd.DataFrame([cell.__dict__ for cell in cells])


def _episode_frame(weekly_frame: pd.DataFrame, *, horizon_weeks: int) -> pd.DataFrame:
    """Per (ticker, week): forward gold return + forward alpha vs GDX."""

    pieces: list[pd.DataFrame] = []
    for ticker, group in weekly_frame.groupby("ticker", sort=True):
        ordered = group.sort_values("week_period").reset_index(drop=True)
        stock_fwd = _forward_sum(ordered["stock_log_ret"], horizon_weeks)
        gold_fwd = _forward_sum(ordered["gold_log_ret"], horizon_weeks)
        gdx_fwd = _forward_sum(ordered["gdx_log_ret"], horizon_weeks)
        frame = pd.DataFrame(
            {
                "ticker": str(ticker),
                "week_period": ordered["week_period"],
                # Buckets are quoted in simple-return space (what a user
                # means by "gold down 10%"), so convert from log space.
                "gold_fwd_simple": np.exp(gold_fwd.astype(float)) - 1.0,
                "alpha_gdx": (stock_fwd - gdx_fwd).astype("Float64"),
            }
        )
        frame = frame.dropna(subset=["gold_fwd_simple", "alpha_gdx"])
        frame["beat_gdx"] = (frame["alpha_gdx"] > 0).astype(float)
        pieces.append(frame)
    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, ignore_index=True)


def _assign_bucket(
    value: float,
    buckets: list[tuple[str, float | None, float | None]],
) -> str | None:
    for name, low, high in buckets:
        if (low is None or value >= low) and (high is None or value < high):
            return name
    return None


def _wilson_interval(p: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))
