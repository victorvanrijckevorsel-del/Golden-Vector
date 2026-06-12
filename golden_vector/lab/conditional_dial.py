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
BUCKET_LABELS: dict[str, str] = {
    "gold_down_big": "Gold down more than 15%",
    "gold_down": "Gold down 5% to 15%",
    "gold_flat": "Gold flat (within ±5%)",
    "gold_up": "Gold up 5% to 15%",
    "gold_up_big": "Gold up more than 15%",
}
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
        # Alphas are log-return gaps; display basis is simple relative
        # outperformance (exp(x)-1). exp is monotone, so converting the
        # median/quantiles is exact — no resampling needed.
        alphas = np.exp(group["alpha_gdx"].astype(float)) - 1.0
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
    table = pd.DataFrame([cell.__dict__ for cell in cells])
    if table.empty:
        return table
    # Display-ready columns: the serve layer may only format and sort on the
    # ONE backend rank. Rank within bucket by shrunk P(beat GDX) descending;
    # insufficient-history cells rank last; ties break by ticker.
    table["bucket_label"] = table["bucket"].map(BUCKET_LABELS).fillna(table["bucket"])
    table["horizon_weeks"] = horizon_weeks
    table = table.sort_values(
        ["bucket", "insufficient_history", "p_beat_gdx_shrunk", "ticker"],
        ascending=[True, True, False, True],
        na_position="last",
    )
    table["rank_in_bucket"] = table.groupby("bucket").cumcount() + 1
    return table.reset_index(drop=True)


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


DIAL_TABLE_FILENAME = "dial_table_13w_latest.parquet"
DIAL_META_FILENAME = "dial_table_13w_meta.json"


def build_and_save(paths, *, horizon_weeks: int = 13) -> pd.DataFrame:
    """Compute once → persist; the workspace Lab page only reads the artifact.

    GDX-era weeks only (alpha labels need the benchmark), variant registered
    in the ledger before compute.
    """

    import glob
    import json
    from datetime import datetime, timezone

    from golden_vector.features.weekly_returns import build_weekly_return_frame
    from golden_vector.lab.ledger import register_variant
    from golden_vector.lab.vintages import lab_dir

    config = {
        "signal": "conditional_dial_analog_v1",
        "horizon_weeks": horizon_weeks,
        "buckets": [[name, low, high] for name, low, high in DEFAULT_BUCKETS],
        "min_effective_n": MIN_EFFECTIVE_N,
        "eb_prior_strength": EB_PRIOR_STRENGTH,
        "benchmark": "GDX",
    }
    record = register_variant(
        lab_dir=lab_dir(paths), signal_id="conditional_dial_analog", config=config
    )

    gold = pd.read_parquet(sorted(glob.glob(str(paths.raw_gold_dir / "*.parquet")))[0])
    histories = {
        path.stem: pd.read_parquet(path)
        for path in sorted(paths.intermediate_usd_equities_dir.glob("*.parquet"))
    }
    benchmarks = {
        ticker: pd.read_parquet(paths.benchmarks_dir / f"{ticker}.parquet")
        for ticker in ("GDX", "GDXJ")
        if (paths.benchmarks_dir / f"{ticker}.parquet").exists()
    }
    weekly = build_weekly_return_frame(
        normalized_equity_histories=histories,
        gold_history=gold,
        benchmark_histories=benchmarks,
    )
    weekly = weekly[weekly["gdx_log_ret"].notna()]

    from golden_vector.common.parquet import write_parquet_atomic

    table = build_dial_table(weekly, horizon_weeks=horizon_weeks)
    target_dir = lab_dir(paths)
    target_dir.mkdir(parents=True, exist_ok=True)
    write_parquet_atomic(table, target_dir / DIAL_TABLE_FILENAME)
    meta = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "variant_hash": record.variant_hash,
        "horizon_weeks": horizon_weeks,
        "weekly_rows": int(len(weekly)),
        "tickers": int(weekly["ticker"].nunique()),
        "cells": int(len(table)),
        "usable_cells": int((~table["insufficient_history"]).sum()),
        "caveat": "Exploratory, survivor-only universe (no dead-miner records yet); GDX-era weeks only.",
    }
    from golden_vector.common.files import atomic_write_text

    atomic_write_text(target_dir / DIAL_META_FILENAME, json.dumps(meta, indent=2))
    return table


def main() -> None:
    from golden_vector.app.paths import ProjectPaths

    table = build_and_save(ProjectPaths.discover())
    usable = int((~table["insufficient_history"]).sum())
    print(f"Dial table rebuilt: {len(table)} cells, {usable} usable.")


if __name__ == "__main__":
    main()
