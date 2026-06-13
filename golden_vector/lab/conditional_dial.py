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

from golden_vector.features.weekly_returns import BENCHMARK_COLUMN_MAP
from golden_vector.lab.forward_returns import (
    build_forward_return_panel,
    forward_sum,
    reindex_contiguous_weeks,
)
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
    "gold_flat": "Gold flat (−5% to +5%)",
    "gold_up": "Gold up 5% to 15%",
    "gold_up_big": "Gold up more than 15%",
}
MIN_EFFECTIVE_N = 8.0
EB_PRIOR_STRENGTH = 10.0  # pseudo-episodes pulling each cell toward the pooled rate

# Selectable look-ahead lenses, fast -> slow. Measured usable-cell counts drove
# the set: 4w/8w ADD data (more independent episodes — gold_down stays 54-56/65);
# 52w was always empty everywhere so it was dropped; 26w still renders
# insufficient-history honestly for thin scenarios (e.g. gold_down). 13w default.
DIAL_HORIZONS_WEEKS: list[int] = [4, 8, 13, 26]
DIAL_BENCHMARKS: list[str] = ["GDX", "GDXJ"]
DIAL_SIGNAL_ID = "conditional_dial_analog"
# Bumped from the GDX-only-13w artifact: long-form episodes + wide cells keyed
# by horizon and benchmark. The loader fails STALE if an artifact predates this.
DIAL_SCHEMA_VERSION = 2


def dial_config_hash(horizons: list[int], benchmarks: list[str]) -> str:
    """One stable hash over the artifact's full config (schema + horizons +
    benchmarks + buckets + floors).

    ONE copy: ``build_and_save`` stamps it into the meta; the serve loader
    recomputes it from live config and returns STALE on mismatch — so changing a
    bucket threshold / ``MIN_EFFECTIVE_N`` / ``EB_PRIOR_STRENGTH`` (none of which
    bump the schema version) still invalidates a stale artifact.
    """

    from golden_vector.lab.ledger import variant_hash

    return variant_hash(
        DIAL_SIGNAL_ID,
        {
            "schema_version": DIAL_SCHEMA_VERSION,
            "horizons": [int(h) for h in horizons],
            "benchmarks": [str(b).upper() for b in benchmarks],
            "buckets": [[name, low, high] for name, low, high in DEFAULT_BUCKETS],
            "min_effective_n": MIN_EFFECTIVE_N,
            "eb_prior_strength": EB_PRIOR_STRENGTH,
        },
    )


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
    """One row per (ticker, gold bucket) with counted analog outcomes vs GDX.

    The GDX-only legacy shape: the existing /lab overview and the golden parity
    gate (``tests/test_lab_dial_panel_parity.py``) depend on these exact
    columns. The multi-benchmark / multi-horizon overview is
    :func:`build_dial_cells_wide`; both share :func:`_dial_cells` so the
    counting math is one copy.
    """

    bucket_defs = buckets if buckets is not None else DEFAULT_BUCKETS
    episodes = build_episode_frame(
        weekly_frame, horizon_weeks=horizon_weeks, benchmark="GDX", buckets=bucket_defs
    )
    if episodes.empty:
        return pd.DataFrame()
    episodes = episodes.rename(columns={"gold_bucket": "bucket"}).dropna(subset=["bucket"])
    cells = _dial_cells(episodes, horizon_weeks=horizon_weeks, min_effective_n=min_effective_n)
    if cells.empty:
        return cells
    cells = cells.rename(
        columns={"p_beat": "p_beat_gdx", "p_beat_shrunk": "p_beat_gdx_shrunk"}
    )
    # Display-ready columns: the serve layer may only format and sort on the
    # ONE backend rank. Rank within bucket by shrunk P(beat GDX) descending;
    # insufficient-history cells rank last; ties break by ticker.
    cells["bucket_label"] = cells["bucket"].map(BUCKET_LABELS).fillna(cells["bucket"])
    cells["horizon_weeks"] = horizon_weeks
    cells = cells.sort_values(
        ["bucket", "insufficient_history", "p_beat_gdx_shrunk", "ticker"],
        ascending=[True, True, False, True],
        na_position="last",
    )
    cells["rank_in_bucket"] = (cells.groupby("bucket").cumcount() + 1).astype("Int64")
    # Degraded cells get NA rank (house rule), not a number a page could
    # render as if meaningful; they still sort last by construction.
    cells.loc[cells["insufficient_history"], "rank_in_bucket"] = pd.NA
    return cells.reset_index(drop=True)


def _dial_cells(
    episodes: pd.DataFrame,
    *,
    horizon_weeks: int,
    min_effective_n: float,
) -> pd.DataFrame:
    """Per (ticker, bucket) counted cell from an episode frame.

    Expects columns ``ticker``, ``bucket``, ``beat``, ``alpha`` (benchmark-
    agnostic). Returns generic-named columns; callers rename per benchmark. This
    is the single copy of the EB-shrink / Wilson / median-alpha counting math.
    """

    if episodes.empty:
        return pd.DataFrame()
    # EB prior mean per bucket: mean of PER-TICKER means (equal ticker weight) —
    # week-weighted pooling would let long-history tickers dominate the prior.
    pooled = (
        episodes.groupby(["bucket", "ticker"])["beat"]
        .mean()
        .groupby("bucket")
        .mean()
        .to_dict()
    )
    records: list[dict[str, object]] = []
    for (ticker, bucket), group in episodes.groupby(["ticker", "bucket"], sort=True):
        n_weeks = int(len(group))
        eff_n = effective_n(n_weeks, label_horizon_weeks=horizon_weeks)
        if eff_n < min_effective_n:
            records.append(
                {
                    "ticker": str(ticker),
                    "bucket": str(bucket),
                    "n_weeks": n_weeks,
                    "effective_n": round(eff_n, 2),
                    "insufficient_history": True,
                    "p_beat": None,
                    "p_beat_shrunk": None,
                    "wilson_low": None,
                    "wilson_high": None,
                    "median_alpha": None,
                    "alpha_q10": None,
                    "alpha_q90": None,
                }
            )
            continue
        p_raw = float(group["beat"].mean())
        prior = float(pooled[bucket])
        p_shrunk = (p_raw * eff_n + prior * EB_PRIOR_STRENGTH) / (
            eff_n + EB_PRIOR_STRENGTH
        )
        low, high = _wilson_interval(p_raw, eff_n)
        # Alphas are log-return gaps; display basis is simple relative
        # outperformance (exp(x)-1). exp is monotone, so converting the
        # median/quantiles is exact — no resampling needed.
        alphas = np.exp(group["alpha"].astype(float)) - 1.0
        records.append(
            {
                "ticker": str(ticker),
                "bucket": str(bucket),
                "n_weeks": n_weeks,
                "effective_n": round(eff_n, 2),
                "insufficient_history": False,
                "p_beat": round(p_raw, 4),
                "p_beat_shrunk": round(p_shrunk, 4),
                "wilson_low": round(low, 4),
                "wilson_high": round(high, 4),
                "median_alpha": round(float(alphas.median()), 6),
                "alpha_q10": round(float(alphas.quantile(0.10)), 6),
                "alpha_q90": round(float(alphas.quantile(0.90)), 6),
            }
        )
    return pd.DataFrame(records)


def build_episode_frame(
    weekly_frame: pd.DataFrame,
    *,
    horizon_weeks: int,
    benchmark: str,
    buckets: list[tuple[str, float | None, float | None]] | None = None,
) -> pd.DataFrame:
    """Per (ticker, week) episode vs ``benchmark``: forward alpha + beat + the
    conditioning gold bucket.

    Generic over benchmark (GDX/GDXJ). Alpha comes from the shared
    ``build_forward_return_panel`` — ONE copy of the label math, so the dial's
    alpha and the chart's alpha are literally the same column. Gold's forward
    return is computed here only for the bucket (gold is banned from the panel's
    label set), on the same W-FRI reindex + ``forward_sum`` the panel uses, so
    the week keys align exactly.

    Per-WEEK degrade: weeks where the benchmark's forward window is incomplete
    (e.g. GDXJ before its 2009 inception) carry NA alpha and are dropped here, so
    each benchmark carries its OWN week set / effective N — never the ticker's.
    Returns columns: ticker, week_period, gold_fwd_simple, alpha, beat,
    gold_bucket.
    """

    h = int(horizon_weeks)
    bench = str(benchmark).upper()
    if bench not in BENCHMARK_COLUMN_MAP:
        raise ValueError(
            f"Unknown benchmark {benchmark!r}; known: {sorted(BENCHMARK_COLUMN_MAP)}"
        )
    bucket_defs = buckets if buckets is not None else DEFAULT_BUCKETS
    panel = build_forward_return_panel(weekly_frame, horizons_weeks=[h])
    alpha_col = f"fwd_alpha_{bench.lower()}_{h}w"
    empty = pd.DataFrame(
        columns=["ticker", "week_period", "gold_fwd_simple", "alpha", "beat", "gold_bucket"]
    )
    if panel.empty or alpha_col not in panel.columns:
        return empty
    gold = _gold_forward_simple(weekly_frame, horizon_weeks=h)
    merged = panel[["ticker", "week_period", alpha_col]].merge(
        gold, on=["ticker", "week_period"], how="inner"
    )
    frame = pd.DataFrame(
        {
            "ticker": merged["ticker"].astype(str),
            "week_period": merged["week_period"],
            "gold_fwd_simple": merged["gold_fwd_simple"],
            "alpha": merged[alpha_col].astype("Float64"),
        }
    )
    frame = frame.dropna(subset=["gold_fwd_simple", "alpha"])
    if frame.empty:
        return empty
    frame["beat"] = (frame["alpha"] > 0).astype(float)
    frame["gold_bucket"] = frame["gold_fwd_simple"].map(
        lambda value: _assign_bucket(value, bucket_defs)
    )
    return frame.reset_index(drop=True)


def _gold_forward_simple(weekly_frame: pd.DataFrame, *, horizon_weeks: int) -> pd.DataFrame:
    """Forward h-week gold return as a SIMPLE return, per (ticker, week).

    Buckets are quoted in simple-return space (what a user means by "gold down
    10%"), so convert from log space. Same reindex + ``forward_sum`` as the
    panel, keeping week keys aligned for the inner merge in
    ``build_episode_frame``.
    """

    pieces: list[pd.DataFrame] = []
    for ticker, group in weekly_frame.groupby("ticker", sort=True):
        ordered = reindex_contiguous_weeks(group)
        gold_fwd = forward_sum(ordered["gold_log_ret"], int(horizon_weeks))
        pieces.append(
            pd.DataFrame(
                {
                    "ticker": str(ticker),
                    "week_period": ordered["week_period"],
                    "gold_fwd_simple": np.exp(gold_fwd.astype(float)) - 1.0,
                }
            )
        )
    if not pieces:
        return pd.DataFrame(columns=["ticker", "week_period", "gold_fwd_simple"])
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


# Long-form chart detail (one row per episode = a week with a valid forward
# alpha vs the benchmark at the horizon).
EPISODE_COLUMNS = [
    "ticker",
    "horizon_weeks",
    "benchmark",
    "week_period",
    "week_date",
    "gold_fwd_simple",
    "gold_bucket",
    "alpha",
    "beat",
    "is_nonoverlap_anchor",
]
# Wide overview (one row per ticker/bucket/horizon): GDX-ranked, GDXJ as a
# comparison column, each benchmark with its OWN evidence (per-week degrade).
CELLS_COLUMNS = [
    "ticker",
    "bucket",
    "bucket_label",
    "horizon_weeks",
    "rank_in_bucket",
    "p_beat_gdx",
    "p_beat_gdx_shrunk",
    "gdx_wilson_low",
    "gdx_wilson_high",
    "median_alpha_gdx",
    "alpha_q10_gdx",
    "alpha_q90_gdx",
    "gdx_n_weeks",
    "gdx_effective_n",
    "gdx_insufficient_history",
    "p_beat_gdxj",
    "p_beat_gdxj_shrunk",
    "gdxj_wilson_low",
    "gdxj_wilson_high",
    "median_alpha_gdxj",
    "alpha_q10_gdxj",
    "alpha_q90_gdxj",
    "gdxj_n_weeks",
    "gdxj_effective_n",
    "gdxj_insufficient_history",
]


def build_episode_artifact(
    weekly_frame: pd.DataFrame,
    *,
    horizons: list[int],
    benchmarks: list[str],
    buckets: list[tuple[str, float | None, float | None]] | None = None,
) -> pd.DataFrame:
    """Long-form per (ticker, horizon, benchmark, week) — the dots behind the
    dial. One row per episode; serve only filters + draws."""

    bucket_defs = buckets if buckets is not None else DEFAULT_BUCKETS
    pieces: list[pd.DataFrame] = []
    for horizon in horizons:
        h = int(horizon)
        for bench in benchmarks:
            ep = build_episode_frame(
                weekly_frame, horizon_weeks=h, benchmark=bench, buckets=bucket_defs
            )
            if ep.empty:
                continue
            ep = ep.copy()
            ep["horizon_weeks"] = h
            ep["benchmark"] = str(bench).upper()
            ep["week_date"] = _week_period_end_date(ep["week_period"])
            ep["is_nonoverlap_anchor"] = _nonoverlap_anchor_mask(ep, horizon_weeks=h)
            pieces.append(ep[EPISODE_COLUMNS])
    if not pieces:
        return pd.DataFrame(columns=EPISODE_COLUMNS)
    return pd.concat(pieces, ignore_index=True)


def _nonoverlap_anchor_mask(ep: pd.DataFrame, *, horizon_weeks: int) -> list[bool]:
    """Mark every h-th episode per ticker so serve can draw the INDEPENDENT
    (non-overlapping) episodes larger — computed here, never inferred in serve."""

    h = int(horizon_weeks)
    flags = pd.Series(False, index=ep.index)
    for _ticker, group in ep.groupby("ticker", sort=False):
        order = group.sort_values("week_period").index.tolist()
        for position, idx in enumerate(order):
            if position % h == 0:
                flags.at[idx] = True
    return flags.tolist()


def _week_period_end_date(week_periods: pd.Series) -> list[str]:
    """ISO date of each W-FRI week's end, for a real date axis on the chart."""

    periods = pd.PeriodIndex(pd.Index(week_periods).astype(str), freq="W-FRI")
    return [ts.date().isoformat() for ts in periods.end_time]


def build_dial_cells_wide(
    weekly_frame: pd.DataFrame,
    *,
    horizons: list[int],
    benchmarks: list[str],
    buckets: list[tuple[str, float | None, float | None]] | None = None,
    min_effective_n: float = MIN_EFFECTIVE_N,
) -> pd.DataFrame:
    """One row per (ticker, bucket, horizon): GDX-ranked + GDXJ comparison.

    Each benchmark carries its OWN counted evidence (per-week degrade), so a
    GDXJ probability is never shown beside a GDX sample count. The single backend
    rank is by GDX shrunk P(beat) within (horizon, bucket); GDX-insufficient
    cells get NA rank and sort last.
    """

    bucket_defs = buckets if buckets is not None else DEFAULT_BUCKETS
    frames: list[pd.DataFrame] = []
    for horizon in horizons:
        h = int(horizon)
        per_bench: dict[str, pd.DataFrame] = {}
        for bench in benchmarks:
            ep = build_episode_frame(
                weekly_frame, horizon_weeks=h, benchmark=bench, buckets=bucket_defs
            )
            if ep.empty:
                per_bench[str(bench).upper()] = pd.DataFrame()
                continue
            ep = ep.rename(columns={"gold_bucket": "bucket"}).dropna(subset=["bucket"])
            per_bench[str(bench).upper()] = _dial_cells(
                ep, horizon_weeks=h, min_effective_n=min_effective_n
            )
        wide = _merge_benchmark_cells(per_bench)
        if wide.empty:
            continue
        wide["horizon_weeks"] = h
        frames.append(wide)
    if not frames:
        return pd.DataFrame(columns=CELLS_COLUMNS)
    table = pd.concat(frames, ignore_index=True)
    for column in CELLS_COLUMNS:
        if column not in table.columns:
            table[column] = pd.NA  # benchmark wholly absent -> degrade, not crash
    # Insufficiency must be a real bool in the artifact, never inferred from NaN
    # truthiness downstream: a wholly-absent benchmark (NA) degrades to insufficient.
    for column in ("gdx_insufficient_history", "gdxj_insufficient_history"):
        table[column] = table[column].fillna(True).astype(bool)
    table["bucket_label"] = table["bucket"].map(BUCKET_LABELS).fillna(table["bucket"])
    gdx_insufficient = table["gdx_insufficient_history"].fillna(True).astype(bool)
    table = table.assign(_gdx_insufficient=gdx_insufficient).sort_values(
        ["horizon_weeks", "bucket", "_gdx_insufficient", "p_beat_gdx_shrunk", "ticker"],
        ascending=[True, True, True, False, True],
        na_position="last",
    )
    table["rank_in_bucket"] = (
        table.groupby(["horizon_weeks", "bucket"]).cumcount() + 1
    ).astype("Int64")
    table.loc[table["_gdx_insufficient"], "rank_in_bucket"] = pd.NA
    return table[CELLS_COLUMNS].reset_index(drop=True)


def _merge_benchmark_cells(per_bench: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join the per-benchmark generic cells into one wide row per (ticker,bucket).

    GDX is the base: every GDXJ cell has a GDX counterpart (GDXJ weeks are a
    subset of GDX-era weeks), so a left join from GDX keeps every ranked row and
    leaves GDXJ NA where it has no data — explicit degrade, never zero.
    """

    renamed: dict[str, pd.DataFrame] = {}
    for bench, cells in per_bench.items():
        if cells.empty:
            renamed[bench] = pd.DataFrame()
            continue
        b = bench.lower()
        renamed[bench] = cells.rename(
            columns={
                "p_beat": f"p_beat_{b}",
                "p_beat_shrunk": f"p_beat_{b}_shrunk",
                "wilson_low": f"{b}_wilson_low",
                "wilson_high": f"{b}_wilson_high",
                "median_alpha": f"median_alpha_{b}",
                "alpha_q10": f"alpha_q10_{b}",
                "alpha_q90": f"alpha_q90_{b}",
                "n_weeks": f"{b}_n_weeks",
                "effective_n": f"{b}_effective_n",
                "insufficient_history": f"{b}_insufficient_history",
            }
        )
    gdx = renamed.get("GDX", pd.DataFrame())
    if gdx.empty:
        return pd.DataFrame()
    out = gdx
    for bench, cells in renamed.items():
        if bench == "GDX" or cells.empty:
            continue
        out = out.merge(cells, on=["ticker", "bucket"], how="left")
    return out


# Relative-strength context line (Chart B): a DIFFERENT statistic from the dial
# — cumulative WEEKLY (non-overlapping) relative return, every week, NOT
# conditional on the gold scenario. Anchored at the first common week (start),
# never end-anchored (that would leak the end state into earlier points).
RELSTRENGTH_COLUMNS = ["ticker", "benchmark", "week_period", "week_date", "relstrength"]


def cumulative_rebased(log_returns: pd.Series, *, base: float = 100.0) -> pd.Series:
    """Cumulative exp of log returns, rebased so the FIRST value == base.

    Start-anchored on purpose: value at week k depends only on returns through
    week k (a prefix), so the line carries no look-ahead.
    """

    clean = pd.to_numeric(log_returns, errors="coerce")
    level = np.exp(clean.cumsum())
    valid = level.dropna()
    if valid.empty:
        return pd.Series([float("nan")] * len(level), index=log_returns.index, dtype="float64")
    anchor = float(valid.iloc[0])
    return level / anchor * base


def build_relstrength_artifact(
    weekly_frame: pd.DataFrame,
    *,
    benchmarks: list[str],
) -> pd.DataFrame:
    """Per (ticker, benchmark, week): weekly relative-strength rebased to 100.

    Weekly NON-overlapping ``stock - benchmark`` log return, accumulated from the
    pair's first common week. Unconditional (every week) — explicitly a different
    measure from the conditional forward-alpha dots.
    """

    pieces: list[pd.DataFrame] = []
    for ticker, group in weekly_frame.groupby("ticker", sort=True):
        ordered = reindex_contiguous_weeks(group)
        stock = pd.to_numeric(ordered["stock_log_ret"], errors="coerce")
        for bench in benchmarks:
            column = BENCHMARK_COLUMN_MAP[str(bench).upper()]
            relative = stock - pd.to_numeric(ordered[column], errors="coerce")
            valid = relative.notna()
            if not bool(valid.any()):
                continue
            start = valid.idxmax()  # first common (both-present) week
            rel_from = relative.loc[start:]
            level = cumulative_rebased(rel_from)
            out = pd.DataFrame(
                {
                    "ticker": str(ticker),
                    "benchmark": str(bench).upper(),
                    "week_period": ordered.loc[start:, "week_period"].to_numpy(),
                    "relstrength": level.to_numpy(),
                }
            ).dropna(subset=["relstrength"])
            if out.empty:
                continue
            out["week_date"] = _week_period_end_date(out["week_period"])
            pieces.append(out[RELSTRENGTH_COLUMNS])
    if not pieces:
        return pd.DataFrame(columns=RELSTRENGTH_COLUMNS)
    return pd.concat(pieces, ignore_index=True)


DIAL_EPISODES_FILENAME = "dial_episodes_latest.parquet"
DIAL_CELLS_FILENAME = "dial_cells_latest.parquet"
DIAL_RELSTRENGTH_FILENAME = "dial_relstrength_latest.parquet"
DIAL_ARTIFACT_META_FILENAME = "dial_meta.json"


def build_and_save(
    paths,
    *,
    horizons: list[int] | None = None,
    benchmarks: list[str] | None = None,
) -> pd.DataFrame:
    """Compute once → persist; the workspace Lab pages only read the artifacts.

    Registers EVERY (benchmark, horizon) variant in the ledger BEFORE compute
    (multiple-testing discipline; ``n_trials`` is read back from the ledger,
    never hardcoded), then writes:
      - ``dial_cells_latest.parquet``      wide overview (GDX-ranked + GDXJ compare)
      - ``dial_episodes_latest.parquet``   long-form chart detail (Chart A dots)
      - ``dial_relstrength_latest.parquet`` weekly relative-strength line (Chart B)
      - ``dial_meta.json``                 schema_version, config_hash, hashes, N
    GDX-era weeks only (alpha labels need the benchmark); GDXJ degrades per-week.
    Returns the wide cells table.
    """

    import glob
    import json
    from datetime import datetime, timezone

    from golden_vector.common.files import atomic_write_text
    from golden_vector.common.parquet import write_parquet_atomic
    from golden_vector.features.weekly_returns import build_weekly_return_frame
    from golden_vector.lab.ledger import n_trials, register_variant
    from golden_vector.lab.vintages import lab_dir

    horizons = list(horizons) if horizons is not None else list(DIAL_HORIZONS_WEEKS)
    benchmarks = list(benchmarks) if benchmarks is not None else list(DIAL_BENCHMARKS)
    bucket_cfg = [[name, low, high] for name, low, high in DEFAULT_BUCKETS]
    target_dir = lab_dir(paths)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Register every (benchmark, horizon) variant BEFORE compute.
    variant_hashes: dict[str, str] = {}
    for bench in benchmarks:
        for horizon in horizons:
            cfg = {
                "signal": "conditional_dial_analog_v1",
                "horizon_weeks": int(horizon),
                "buckets": bucket_cfg,
                "min_effective_n": MIN_EFFECTIVE_N,
                "eb_prior_strength": EB_PRIOR_STRENGTH,
                "benchmark": str(bench).upper(),
            }
            record = register_variant(
                lab_dir=target_dir, signal_id=DIAL_SIGNAL_ID, config=cfg
            )
            variant_hashes[f"{str(bench).upper()}_{int(horizon)}w"] = record.variant_hash
    config_hash = dial_config_hash(horizons, benchmarks)

    gold = pd.read_parquet(sorted(glob.glob(str(paths.raw_gold_dir / "*.parquet")))[0])
    histories = {
        path.stem: pd.read_parquet(path)
        for path in sorted(paths.intermediate_usd_equities_dir.glob("*.parquet"))
    }
    benchmark_histories = {
        ticker: pd.read_parquet(paths.benchmarks_dir / f"{ticker}.parquet")
        for ticker in ("GDX", "GDXJ")
        if (paths.benchmarks_dir / f"{ticker}.parquet").exists()
    }
    weekly = build_weekly_return_frame(
        normalized_equity_histories=histories,
        gold_history=gold,
        benchmark_histories=benchmark_histories,
    )
    weekly = weekly[weekly["gdx_log_ret"].notna()]

    cells = build_dial_cells_wide(weekly, horizons=horizons, benchmarks=benchmarks)
    episodes = build_episode_artifact(weekly, horizons=horizons, benchmarks=benchmarks)
    relstrength = build_relstrength_artifact(weekly, benchmarks=benchmarks)

    write_parquet_atomic(cells, target_dir / DIAL_CELLS_FILENAME)
    write_parquet_atomic(episodes, target_dir / DIAL_EPISODES_FILENAME)
    write_parquet_atomic(relstrength, target_dir / DIAL_RELSTRENGTH_FILENAME)

    gdx_insufficient = (
        cells["gdx_insufficient_history"].fillna(True).astype(bool)
        if not cells.empty
        else pd.Series(dtype=bool)
    )
    usable_by_horizon = {
        int(h): int(((cells["horizon_weeks"] == int(h)) & (~gdx_insufficient)).sum())
        for h in horizons
        if not cells.empty
    }
    # Per-(horizon, bucket) usable counts: serve reads these for selector labels
    # + the empty-state contract, so it never has to aggregate.
    usable_by_horizon_bucket: dict[str, dict[str, int]] = {}
    if not cells.empty:
        usable_mask = ~gdx_insufficient
        for horizon in horizons:
            per_bucket: dict[str, int] = {}
            hz_mask = cells["horizon_weeks"] == int(horizon)
            for bucket_name in cells.loc[hz_mask, "bucket"].unique():
                per_bucket[str(bucket_name)] = int(
                    (hz_mask & (cells["bucket"] == bucket_name) & usable_mask).sum()
                )
            usable_by_horizon_bucket[str(int(horizon))] = per_bucket
    built_at = datetime.now(timezone.utc).isoformat()
    meta = {
        "built_at_utc": built_at,
        "schema_version": DIAL_SCHEMA_VERSION,
        "config_hash": config_hash,
        "signal_id": DIAL_SIGNAL_ID,
        "horizons_weeks": [int(h) for h in horizons],
        "benchmarks": [str(b).upper() for b in benchmarks],
        "variant_hashes_by_benchmark_horizon": variant_hashes,
        "n_trials": n_trials(target_dir, signal_id=DIAL_SIGNAL_ID),
        "weekly_rows": int(len(weekly)),
        "tickers": int(weekly["ticker"].nunique()),
        "cells": int(len(cells)),
        "episodes": int(len(episodes)),
        "relstrength_rows": int(len(relstrength)),
        "usable_gdx_cells_by_horizon": usable_by_horizon,
        "usable_gdx_cells_by_horizon_bucket": usable_by_horizon_bucket,
        "caveat": "Exploratory, survivor-only universe (no dead-miner records yet); GDX-era weeks only.",
    }
    atomic_write_text(target_dir / DIAL_ARTIFACT_META_FILENAME, json.dumps(meta, indent=2))
    return cells


def main() -> None:
    from golden_vector.app.paths import ProjectPaths

    cells = build_and_save(ProjectPaths.discover())
    if cells.empty:
        print("Dial cells rebuilt: 0 cells.")
        return
    usable = int((~cells["gdx_insufficient_history"].fillna(True).astype(bool)).sum())
    horizons = sorted({int(h) for h in cells["horizon_weeks"].dropna().tolist()})
    print(
        f"Dial cells rebuilt: {len(cells)} cells across horizons {horizons}, "
        f"{usable} GDX-usable."
    )


if __name__ == "__main__":
    main()
