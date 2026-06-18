"""Conditional Dial analog table — the Lab's spine deliverable.

For a USER-CHOSEN gold scenario bucket (e.g. "gold down 5% to 15% over the
next 13 weeks"), count what each miner actually did across every historical
episode where gold's forward return landed in that bucket:
P(beat GDX/GDXJ), median alpha, and the 10-90% alpha range.

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

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from golden_vector.contracts.config_models import GoldProfileConfig

from golden_vector.features.weekly_returns import BENCHMARK_COLUMN_MAP
from golden_vector.lab.forward_returns import (
    assert_calendar_values,
    build_forward_return_panel,
    forward_sum,
    reindex_contiguous_weeks,
)
from golden_vector.lab.statistics import eb_shrink, pooled_prior, wilson_interval
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
# Centralized (single-copy) but MANUAL short labels — the text is hand-written,
# NOT derived from the bounds; a test pins them in lock-step with BUCKET_LABELS so
# a new bucket forces an explicit entry rather than silently desyncing.
BUCKET_SHORT_LABELS: dict[str, str] = {
    "gold_down_big": "down >15%",
    "gold_down": "down 5-15%",
    "gold_flat": "flat",
    "gold_up": "up 5-15%",
    "gold_up_big": "up >15%",
}
# Down/up scenario partitions, derived ONCE from the bucket bounds (one copy:
# serve imports these instead of forking the lists): a bucket is "down" if its
# whole range is <= 0 (high bound <= 0), "up" if >= 0 (low bound >= 0).
DOWN_BUCKETS: tuple[str, ...] = tuple(
    name for name, _low, high in DEFAULT_BUCKETS if high is not None and high <= 0
)
UP_BUCKETS: tuple[str, ...] = tuple(
    name for name, low, _high in DEFAULT_BUCKETS if low is not None and low >= 0
)
DEFAULT_DIAL_BUCKET = "gold_down"
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
DIAL_SCHEMA_VERSION = 4  # v4: episodes also carry stock_fwd_log + stock_fwd_simple (miner's own fwd return)


def default_gold_profile_config() -> GoldProfileConfig:
    """The live gold-profile config, loaded + validated from
    ``config/lab_gold_profile.yaml`` on EVERY call — the single source for both the
    build and the serve staleness check.

    Read UNCACHED on purpose: the serve staleness check computes the expected config
    hash through this, so an edit to the YAML must be reflected immediately (the
    artifact's stored hash then mismatches -> STALE) WITHOUT a process restart. A
    stale in-memory cache would make a running server keep reporting an out-of-date
    artifact as current — exactly the failure the config hash exists to prevent. The
    file is tiny, so the per-call read is negligible. A missing file falls back to
    the model defaults; a present-but-invalid file fails loud (validation raises)."""

    import yaml

    from golden_vector.app.paths import ProjectPaths
    from golden_vector.contracts.config_models import GoldProfileConfig

    try:
        config_path = ProjectPaths.discover().config_path("lab_gold_profile.yaml")
    except Exception:
        return GoldProfileConfig()
    if not config_path.exists():
        return GoldProfileConfig()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return GoldProfileConfig.model_validate(raw)


def dial_config_hash(
    horizons: list[int],
    benchmarks: list[str],
    profile: GoldProfileConfig | None = None,
) -> str:
    """One stable hash over the artifact's full config (schema + horizons +
    benchmarks + buckets + floors + gold-profile thresholds).

    ONE copy: ``build_and_save`` stamps it into the meta; the serve loader
    recomputes it from live config and returns STALE on mismatch — so changing a
    bucket threshold / ``MIN_EFFECTIVE_N`` / ``EB_PRIOR_STRENGTH`` / any gold-profile
    threshold (none of which bump the schema version) still invalidates a stale
    artifact.
    """

    from golden_vector.lab.ledger import variant_hash

    profile = profile if profile is not None else default_gold_profile_config()
    return variant_hash(
        DIAL_SIGNAL_ID,
        {
            "schema_version": DIAL_SCHEMA_VERSION,
            "horizons": sorted({int(h) for h in horizons}),
            "benchmarks": sorted({str(b).upper() for b in benchmarks}),
            "buckets": [[name, low, high] for name, low, high in DEFAULT_BUCKETS],
            "min_effective_n": MIN_EFFECTIVE_N,
            "eb_prior_strength": EB_PRIOR_STRENGTH,
            "gold_profile": {
                "version": int(profile.version),
                "tilt_threshold": float(profile.tilt_threshold),
                "min_usable_down_buckets": int(profile.min_usable_down_buckets),
                "min_usable_up_buckets": int(profile.min_usable_up_buckets),
                "down_buckets": sorted(profile.down_buckets),
                "up_buckets": sorted(profile.up_buckets),
                "default_profile_horizon": int(profile.default_profile_horizon),
            },
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
    pooled = pooled_prior(episodes, group_col="bucket", value_col="beat")
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
        p_shrunk = eb_shrink(p_raw, eff_n, prior, EB_PRIOR_STRENGTH)
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

    artifact = build_episode_artifact(
        weekly_frame,
        horizons=[int(horizon_weeks)],
        benchmarks=[str(benchmark).upper()],
        buckets=buckets,
    )
    if artifact.empty:
        return pd.DataFrame(
            columns=["ticker", "week_period", "gold_fwd_simple", "alpha", "beat", "gold_bucket"]
        )
    return artifact[
        ["ticker", "week_period", "gold_fwd_simple", "alpha", "beat", "gold_bucket"]
    ].reset_index(drop=True)


def _gold_forward_by_week(
    weekly_frame: pd.DataFrame,
    *,
    horizons: list[int],
) -> pd.DataFrame:
    """Calendar-level forward gold returns, computed once per horizon."""

    columns = ["week_period"] + [f"gold_fwd_simple_{int(h)}w" for h in horizons]
    if weekly_frame.empty:
        return pd.DataFrame(columns=columns)
    source = weekly_frame[["week_period", "gold_log_ret"]].sort_values("week_period")
    assert_calendar_values(source, columns=("gold_log_ret",))
    calendar = source.groupby("week_period", as_index=False).first()
    out = calendar[["week_period"]].copy()
    for horizon in horizons:
        h = int(horizon)
        gold_fwd = forward_sum(calendar["gold_log_ret"], h)
        out[f"gold_fwd_simple_{h}w"] = np.exp(gold_fwd.astype(float)) - 1.0
    return out[columns]


def _assign_bucket(
    value: float,
    buckets: list[tuple[str, float | None, float | None]],
) -> str | None:
    for name, low, high in buckets:
        if (low is None or value >= low) and (high is None or value < high):
            return name
    return None


# The Wilson interval lives in lab.statistics now (ONE copy, shared with the capture/
# behaviour engine). Kept as a module-level alias because tests + _dial_cells reference
# the private name.
_wilson_interval = wilson_interval


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
    "stock_fwd_log",
    "stock_fwd_simple",
    "alpha",
    "alpha_simple",
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

    horizon_list = [int(h) for h in horizons]
    benchmark_list = [str(b).upper() for b in benchmarks]
    for bench in benchmark_list:
        if bench not in BENCHMARK_COLUMN_MAP:
            raise ValueError(f"Unknown benchmark {bench!r}; known: {sorted(BENCHMARK_COLUMN_MAP)}")
    bucket_defs = buckets if buckets is not None else DEFAULT_BUCKETS
    panel = build_forward_return_panel(weekly_frame, horizons_weeks=horizon_list)
    gold_by_week = _gold_forward_by_week(weekly_frame, horizons=horizon_list)
    if panel.empty or gold_by_week.empty:
        return pd.DataFrame(columns=EPISODE_COLUMNS)
    pieces: list[pd.DataFrame] = []
    for horizon in horizon_list:
        h = int(horizon)
        gold_col = f"gold_fwd_simple_{h}w"
        if gold_col not in gold_by_week.columns:
            continue
        for bench in benchmark_list:
            alpha_col = f"fwd_alpha_{bench.lower()}_{h}w"
            if alpha_col not in panel.columns:
                continue
            log_col = f"fwd_log_ret_{h}w"
            merged = panel[["ticker", "week_period", alpha_col, log_col]].merge(
                gold_by_week[["week_period", gold_col]], on="week_period", how="left"
            )
            ep = pd.DataFrame(
                {
                    "ticker": merged["ticker"].astype(str),
                    "week_period": merged["week_period"],
                    "gold_fwd_simple": merged[gold_col].astype("Float64"),
                    "stock_fwd_log": merged[log_col].astype("Float64"),
                    "alpha": merged[alpha_col].astype("Float64"),
                }
            )
            ep = ep.dropna(subset=["gold_fwd_simple", "alpha"])
            if ep.empty:
                continue
            # The miner's OWN forward return (simple basis) — the magnitude the capture
            # ratios (vs gold) and the peer rank need; alpha (vs benchmark) can't give it.
            # ONE normalize boundary (exp(log)-1), same as alpha_simple below. stock_fwd_log
            # is non-NA wherever alpha is (alpha = stock_fwd_log - bench_fwd_log).
            ep["stock_fwd_simple"] = (
                np.exp(ep["stock_fwd_log"].astype(float)) - 1.0
            ).astype("Float64")
            # Per-week alpha in SIMPLE-return basis (exp(log gap) - 1), persisted so
            # serve can plot the distribution strip on the SAME basis the cell median
            # uses (median_alpha = median(exp(alpha)-1)) without an exp() at the render
            # boundary. ONE normalize boundary for the per-week magnitude; the log
            # `alpha` stays for the beat decision + the time-series dot chart.
            ep["alpha_simple"] = (np.exp(ep["alpha"].astype(float)) - 1.0).astype("Float64")
            ep["beat"] = (ep["alpha"] > 0).astype(float)
            ep["gold_bucket"] = ep["gold_fwd_simple"].map(
                lambda value: _assign_bucket(value, bucket_defs)
            )
            ep["horizon_weeks"] = h
            ep["benchmark"] = bench
            ep["week_date"] = _week_period_end_date(ep["week_period"])
            ep["is_nonoverlap_anchor"] = _nonoverlap_anchor_mask(ep, horizon_weeks=h)
            pieces.append(ep[EPISODE_COLUMNS])
    if not pieces:
        return pd.DataFrame(columns=EPISODE_COLUMNS)
    return pd.concat(pieces, ignore_index=True)


def _nonoverlap_anchor_mask(ep: pd.DataFrame, *, horizon_weeks: int) -> list[bool]:
    """Mark every h-th SURVIVING episode per ticker (positional, so anchors are
    always >= h calendar weeks apart — conservative across any data gaps) so serve
    can draw the INDEPENDENT (non-overlapping) episodes larger — computed here,
    never inferred in serve."""

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

    values = pd.Index(week_periods).astype(str)
    unique_values = pd.Index(pd.unique(values))
    periods = pd.PeriodIndex(unique_values, freq="W-FRI")
    lookup = {
        value: ts.date().isoformat()
        for value, ts in zip(unique_values, periods.end_time, strict=True)
    }
    return [lookup[value] for value in values]


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

    episodes = build_episode_artifact(
        weekly_frame, horizons=horizons, benchmarks=benchmarks, buckets=buckets
    )
    return build_dial_cells_from_episodes(
        episodes,
        horizons=horizons,
        benchmarks=benchmarks,
        min_effective_n=min_effective_n,
    )


def build_dial_cells_from_episodes(
    episodes: pd.DataFrame,
    *,
    horizons: list[int],
    benchmarks: list[str],
    min_effective_n: float = MIN_EFFECTIVE_N,
) -> pd.DataFrame:
    """Build the overview cells from the persisted episode spine.

    This is the one aggregation path used by the publisher: chart dots and
    overview cells consume the same `episodes` rows, so the table cannot drift
    from the detail chart.
    """

    if episodes.empty:
        return pd.DataFrame(columns=CELLS_COLUMNS)
    horizon_list = [int(h) for h in horizons]
    benchmark_list = [str(b).upper() for b in benchmarks]
    frames: list[pd.DataFrame] = []
    for horizon in horizon_list:
        h = int(horizon)
        per_bench: dict[str, pd.DataFrame] = {}
        for bench in benchmark_list:
            ep = episodes.loc[
                (episodes["horizon_weeks"] == h)
                & (episodes["benchmark"].astype(str).str.upper() == bench)
            ].copy()
            ep = (
                ep.rename(columns={"gold_bucket": "bucket"})
                .dropna(subset=["bucket", "alpha", "beat"])
            )
            if ep.empty:
                per_bench[bench] = pd.DataFrame()
                continue
            per_bench[bench] = _dial_cells(
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
    # skipna=False: an interior gap NA-propagates (post-gap levels become NaN and
    # are dropped) rather than being silently bridged as a zero-return week — the
    # repo rule is "degraded data is EXCLUDED, not bridged".
    level = np.exp(clean.cumsum(skipna=False))
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
DIAL_EPISODES_ARTIFACT = "dial_episodes"
DIAL_CELLS_ARTIFACT = "dial_cells"
DIAL_RELSTRENGTH_ARTIFACT = "dial_relstrength"
DIAL_PROFILE_FILENAME = "dial_profile_latest.parquet"
DIAL_PROFILE_ARTIFACT = "dial_profile"

# The FULL dial artifact set: key -> (run-stamped prefix, latest-alias filename).
# ONE place that knows the set, so a build can never half-wire (or silently drop) an
# artifact — ``write_dial_artifacts`` requires exactly these keys.
DIAL_ARTIFACT_SPECS: dict[str, tuple[str, str]] = {
    "cells": (DIAL_CELLS_ARTIFACT, DIAL_CELLS_FILENAME),
    "episodes": (DIAL_EPISODES_ARTIFACT, DIAL_EPISODES_FILENAME),
    "relstrength": (DIAL_RELSTRENGTH_ARTIFACT, DIAL_RELSTRENGTH_FILENAME),
    "profile": (DIAL_PROFILE_ARTIFACT, DIAL_PROFILE_FILENAME),
}

# The build decides these labels; serve never picks them (it renders the
# persisted ``gold_tilt_label``). The serve no-arithmetic guardrail forbids these
# literals in the serve Lab modules.
GOLD_TILT_LABELS = ("Defensive", "Steady", "Pro-cyclical")
# Machine-readable label statuses (serve chooses display text from these + the
# persisted label only — never by re-deciding the threshold).
PROFILE_LABEL_STATUSES = (
    "OK",
    "INSUFFICIENT_CROSS_SCENARIO_HISTORY",
    "MISSING_COMPONENTS",
)
PROFILE_COLUMNS = [
    "ticker",
    "horizon_weeks",
    "benchmark",
    "gold_tilt",
    "gold_tilt_label",
    "label_status",
    "down_mean_p_beat",
    "up_mean_p_beat",
    "usable_down_bucket_count",
    "usable_up_bucket_count",
    "used_buckets",
    "tilt_threshold",
    "min_usable_down_buckets",
    "min_usable_up_buckets",
    "config_hash",
    "caveat",
]
PROFILE_CAVEAT = (
    "gold_tilt = equal-weighted mean P(beat, shrunk) over usable down buckets minus "
    "usable up buckets (equal bucket weight, NOT episode-weighted); counted history, "
    "survivor-only, exploratory — not a prediction."
)


def cell_bucket_is_usable(row: Any, benchmark: str) -> bool:
    """The ONE 'usable cell' rule shared by the profile build and the serve reader
    (so the two can never drift): the benchmark's history is sufficient AND its
    shrunk P(beat) is a real number. A missing flag/row is treated as not usable."""

    if row is None:
        return False
    b = str(benchmark).lower()
    insufficient = row.get(f"{b}_insufficient_history")
    # NA-safe: pandas pd.NA would make ``bool(insufficient)`` / ``shrunk == shrunk``
    # raise "boolean value of NA is ambiguous". A missing/NA flag means not usable
    # (matches the docstring), never a crash.
    if insufficient is None or pd.isna(insufficient) or bool(insufficient):
        return False
    shrunk = row.get(f"p_beat_{b}_shrunk")
    return shrunk is not None and not pd.isna(shrunk)


def _gold_tilt_label(tilt: float, threshold: float) -> str:
    """tilt >= +T -> Defensive; tilt <= -T -> Pro-cyclical; else Steady."""
    if tilt >= threshold:
        return "Defensive"
    if tilt <= -threshold:
        return "Pro-cyclical"
    return "Steady"


def build_profile_artifact(
    cells: pd.DataFrame,
    *,
    horizons: list[int],
    benchmarks: list[str],
    config: GoldProfileConfig | None = None,
    config_hash: str | None = None,
) -> pd.DataFrame:
    """One row per (ticker, horizon, benchmark): the equal-weighted ``gold_tilt`` and
    its Defensive/Steady/Pro-cyclical label — computed in the BUILD (serve only
    reads). ``gold_tilt`` and ``gold_tilt_label`` are null unless ``label_status`` is
    OK (>= the configured usable-bucket floor on BOTH sides).

    Status meaning:
    - MISSING_COMPONENTS: no down/up scenario cells for this ticker/horizon at all.
    - INSUFFICIENT_CROSS_SCENARIO_HISTORY: cells exist but too few usable buckets on
      a side to meet the floor.
    - OK: both sides meet the floor; the tilt + label are emitted.
    """

    cfg = config if config is not None else default_gold_profile_config()
    chash = (
        config_hash
        if config_hash is not None
        else dial_config_hash(horizons, benchmarks, cfg)
    )
    if cells is None or cells.empty:
        return pd.DataFrame(columns=PROFILE_COLUMNS)

    records: list[dict[str, Any]] = []
    for horizon in horizons:
        hz = cells.loc[cells["horizon_weeks"] == int(horizon)]
        for ticker, group in hz.groupby("ticker", sort=True):
            by_bucket = {str(r["bucket"]): r for r in group.to_dict(orient="records")}
            for bench in benchmarks:
                b = str(bench).upper()
                bl = b.lower()
                down_vals: list[float] = []
                up_vals: list[float] = []
                used: list[str] = []
                present_any = False
                for bucket in cfg.down_buckets:
                    row = by_bucket.get(bucket)
                    if row is not None:
                        present_any = True
                    if cell_bucket_is_usable(row, b):
                        down_vals.append(float(row[f"p_beat_{bl}_shrunk"]))
                        used.append(bucket)
                for bucket in cfg.up_buckets:
                    row = by_bucket.get(bucket)
                    if row is not None:
                        present_any = True
                    if cell_bucket_is_usable(row, b):
                        up_vals.append(float(row[f"p_beat_{bl}_shrunk"]))
                        used.append(bucket)
                down_n = len(down_vals)
                up_n = len(up_vals)
                # Equal-weighted across usable buckets (NOT episode-weighted), so a
                # common regime can't dominate a rare extreme one.
                down_mean = sum(down_vals) / down_n if down_n else None
                up_mean = sum(up_vals) / up_n if up_n else None
                if not present_any:
                    status = "MISSING_COMPONENTS"
                elif (
                    down_n >= cfg.min_usable_down_buckets
                    and up_n >= cfg.min_usable_up_buckets
                ):
                    status = "OK"
                else:
                    status = "INSUFFICIENT_CROSS_SCENARIO_HISTORY"
                if status == "OK":
                    tilt: float | None = round(down_mean - up_mean, 6)
                    label: str | None = _gold_tilt_label(tilt, cfg.tilt_threshold)
                else:
                    tilt = None
                    label = None
                records.append(
                    {
                        "ticker": str(ticker),
                        "horizon_weeks": int(horizon),
                        "benchmark": b,
                        "gold_tilt": tilt,
                        "gold_tilt_label": label,
                        "label_status": status,
                        "down_mean_p_beat": (
                            round(down_mean, 6) if down_mean is not None else None
                        ),
                        "up_mean_p_beat": (
                            round(up_mean, 6) if up_mean is not None else None
                        ),
                        "usable_down_bucket_count": int(down_n),
                        "usable_up_bucket_count": int(up_n),
                        "used_buckets": ",".join(used),
                        "tilt_threshold": float(cfg.tilt_threshold),
                        "min_usable_down_buckets": int(cfg.min_usable_down_buckets),
                        "min_usable_up_buckets": int(cfg.min_usable_up_buckets),
                        "config_hash": chash,
                        "caveat": PROFILE_CAVEAT,
                    }
                )
    return pd.DataFrame.from_records(records, columns=PROFILE_COLUMNS)


def write_dial_artifacts(
    target_dir,
    frames: dict[str, pd.DataFrame],
    *,
    stamp: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Write each dial artifact as an immutable run-stamped file PLUS a ``latest``
    alias, in ONE place that knows the full artifact set.

    Requires EXACTLY ``DIAL_ARTIFACT_SPECS`` keys and fails loud on a missing/extra
    one, so a build can never silently stop emitting an artifact (a dropped
    ``profile`` would otherwise go unnoticed because serve degrades the label to
    UNAVAILABLE). Returns ``(run_stamped_artifacts, latest_aliases)`` for the meta.
    """

    from golden_vector.common.parquet import write_run_stamped_set

    # One copy of the all-or-nothing publish (shared with the behaviour engine).
    return write_run_stamped_set(target_dir, frames, DIAL_ARTIFACT_SPECS, stamp=stamp)


def build_and_save(
    paths,
    *,
    horizons: list[int] | None = None,
    benchmarks: list[str] | None = None,
) -> pd.DataFrame:
    """Compute once → persist; the workspace Lab pages only read the artifacts.

    Registers EVERY (benchmark, horizon) variant in the ledger BEFORE compute
    (multiple-testing discipline; ``n_trials`` is read back from the ledger,
    never hardcoded), then writes immutable run-stamped artifacts plus latest
    aliases:
      - ``dial_cells_<run_id>.parquet`` + ``dial_cells_latest.parquet``
      - ``dial_episodes_<run_id>.parquet`` + ``dial_episodes_latest.parquet``
      - ``dial_relstrength_<run_id>.parquet`` + ``dial_relstrength_latest.parquet``
      - ``dial_meta.json`` with schema_version, config_hash, timings, provenance
    GDX-era weeks only (alpha labels need the benchmark); GDXJ degrades per-week.
    Returns the wide cells table.
    """

    import json
    import time
    from datetime import datetime, timezone

    from golden_vector.common.files import atomic_write_text, optional_sha256_file
    from golden_vector.features.weekly_returns import build_weekly_return_frame
    from golden_vector.lab.ledger import n_trials, register_variant
    from golden_vector.lab.vintages import lab_dir

    horizons = list(horizons) if horizons is not None else list(DIAL_HORIZONS_WEEKS)
    benchmarks = list(benchmarks) if benchmarks is not None else list(DIAL_BENCHMARKS)
    bucket_cfg = [[name, low, high] for name, low, high in DEFAULT_BUCKETS]
    target_dir = lab_dir(paths)
    target_dir.mkdir(parents=True, exist_ok=True)
    stage_timings: dict[str, float] = {}

    def mark(stage: str, start: float) -> None:
        stage_timings[stage] = round(time.perf_counter() - start, 3)

    t_register = time.perf_counter()
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
    mark("register_variants_seconds", t_register)
    gp_config = default_gold_profile_config()
    config_hash = dial_config_hash(horizons, benchmarks, gp_config)

    t_read = time.perf_counter()
    gold_candidates = sorted(paths.raw_gold_dir.glob("*.parquet"))
    if not gold_candidates:
        raise FileNotFoundError(f"No raw gold parquet found in {paths.raw_gold_dir}")
    gold_path = gold_candidates[0]
    gold = pd.read_parquet(gold_path)
    equity_paths = sorted(paths.intermediate_usd_equities_dir.glob("*.parquet"))
    histories = {
        path.stem: pd.read_parquet(path)
        for path in equity_paths
    }
    benchmark_paths = {
        ticker: paths.benchmarks_dir / f"{ticker}.parquet"
        for ticker in ("GDX", "GDXJ")
    }
    benchmark_histories = {
        ticker: pd.read_parquet(path)
        for ticker, path in benchmark_paths.items()
        if path.exists()
    }
    mark("read_inputs_seconds", t_read)
    t_weekly = time.perf_counter()
    weekly = build_weekly_return_frame(
        normalized_equity_histories=histories,
        gold_history=gold,
        benchmark_histories=benchmark_histories,
    )
    weekly = weekly[weekly["gdx_log_ret"].notna()]
    mark("build_weekly_seconds", t_weekly)

    t_episodes = time.perf_counter()
    episodes = build_episode_artifact(weekly, horizons=horizons, benchmarks=benchmarks)
    mark("build_episodes_seconds", t_episodes)
    t_cells = time.perf_counter()
    cells = build_dial_cells_from_episodes(
        episodes, horizons=horizons, benchmarks=benchmarks
    )
    mark("build_cells_seconds", t_cells)
    t_relstrength = time.perf_counter()
    relstrength = build_relstrength_artifact(weekly, benchmarks=benchmarks)
    mark("build_relstrength_seconds", t_relstrength)
    t_profile = time.perf_counter()
    profile = build_profile_artifact(
        cells,
        horizons=horizons,
        benchmarks=benchmarks,
        config=gp_config,
        config_hash=config_hash,
    )
    mark("build_profile_seconds", t_profile)

    t_write = time.perf_counter()
    moment = datetime.now(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%S%fZ")  # microsecond precision: immutable names
    stamped, latest_aliases = write_dial_artifacts(
        target_dir,
        {
            "cells": cells,
            "episodes": episodes,
            "relstrength": relstrength,
            "profile": profile,
        },
        stamp=stamp,
    )
    mark("write_artifacts_seconds", t_write)

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
    family_trials = n_trials(target_dir, signal_id=DIAL_SIGNAL_ID)
    active_variant_count = len(variant_hashes)
    built_at = moment.isoformat()
    # Per-equity provenance: the normalized miner inputs DOMINATE the spine, so record each
    # one at file level ({ticker, sha256, rows}) plus a single aggregate hash over the whole
    # sorted set — not just a count/rows total — so every behaviour number is auditable back
    # to the exact inputs and a changed/missing miner file is detectable (Codex F6).
    equity_manifest = [
        {
            "ticker": path.stem,
            "sha256": optional_sha256_file(path),
            "rows": int(len(histories.get(path.stem, []))),
        }
        for path in equity_paths
    ]
    equities_aggregate_sha256 = hashlib.sha256(
        "\n".join(
            f"{e['ticker']}:{e['sha256']}:{e['rows']}" for e in equity_manifest
        ).encode("utf-8")
    ).hexdigest()
    meta = {
        "built_at_utc": built_at,
        "schema_version": DIAL_SCHEMA_VERSION,
        "config_hash": config_hash,
        "signal_id": DIAL_SIGNAL_ID,
        "horizons_weeks": [int(h) for h in horizons],
        "benchmarks": [str(b).upper() for b in benchmarks],
        "variant_hashes_by_benchmark_horizon": variant_hashes,
        "n_trials": family_trials,
        "registered_family_trials": family_trials,
        "active_variant_count": active_variant_count,
        "retired_variant_count": max(0, family_trials - active_variant_count),
        "run_stamped_artifacts": stamped,
        "latest_aliases": latest_aliases,
        "stage_timings": stage_timings,
        "input_provenance": {
            "raw_gold": {
                "path": str(gold_path),
                "sha256": optional_sha256_file(gold_path),
                "rows": int(len(gold)),
            },
            "normalized_equities": {
                "count": int(len(equity_paths)),
                "rows": int(sum(len(frame) for frame in histories.values())),
                "aggregate_sha256": equities_aggregate_sha256,
                "files": equity_manifest,
            },
            "benchmarks": {
                ticker: {
                    "path": str(path),
                    "sha256": optional_sha256_file(path),
                    "rows": int(len(benchmark_histories.get(ticker, pd.DataFrame()))),
                }
                for ticker, path in benchmark_paths.items()
                if path.exists()
            },
        },
        "weekly_rows": int(len(weekly)),
        "tickers": int(weekly["ticker"].nunique()),
        "cells": int(len(cells)),
        "episodes": int(len(episodes)),
        "relstrength_rows": int(len(relstrength)),
        "profile_rows": int(len(profile)),
        "gold_profile_config": {
            "tilt_threshold": float(gp_config.tilt_threshold),
            "min_usable_down_buckets": int(gp_config.min_usable_down_buckets),
            "min_usable_up_buckets": int(gp_config.min_usable_up_buckets),
            "down_buckets": list(gp_config.down_buckets),
            "up_buckets": list(gp_config.up_buckets),
            "weighting": "equal_bucket",
        },
        "usable_gdx_cells_by_horizon": usable_by_horizon,
        "usable_gdx_cells_by_horizon_bucket": usable_by_horizon_bucket,
        "legacy_artifacts": {
            "dial_table_13w_latest.parquet": "Superseded by dial_cells_latest.parquet.",
            "dial_table_13w_meta.json": "Superseded by dial_meta.json.",
        },
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
