"""Program A — tool-validation engine (the Scorecard backend).

Runs the experiments pre-registered in
``reviews/codex/claude_program_a_validation_spec.md`` (variants registered in
the ledger before this code was written; gates are BINDING). Everything here
computes and persists; serve only renders.

Design invariants enforced in code (spec §1):
- Join key is the W-FRI ``week_period``, never the raw as-of date.
- ``structural_delta_core`` / ``down_beta_core`` are reconstructed
  point-in-time as the weighted median across the panel's ELIGIBLE
  6M/12M/3Y windows — the same math the product ships (no forked logic).
- Fold-level t-stats use n = number of folds with a Newey–West lag-1
  standard error; the weekly-evaluator ``effective_n`` (=n/h) MUST NOT be
  applied to the pre-spaced disjoint grid.
- All gate tests are one-sided in the registered direction.
- Every backtest result is capped at SUPPORTED (survivor-only, exploratory)
  and carries the code-vintage caveat.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- constants

GRID_STEP_PERIODS = 26
GRID_ANCHOR = pd.Period("2004-04-23", freq="W-FRI")
MIN_CROSS_SECTION = 15
MIN_COMPLETENESS_FRACTION = 0.80
FORWARD_HORIZON_WEEKS = 26
MIN_FORWARD_WEEKS = 20  # of 26 for a realized-beta label
STABILITY_LAG_PERIODS = 52  # E1a: t vs t+52 (non-overlapping 12M windows)

INCONCLUSIVE_CEILING = 0.30  # split-half below this => INCONCLUSIVE, not NOT SUPPORTED
SURVIVOR_QUALIFIER = "exploratory — survivor-only universe"


# ---------------------------------------------------------------- containers


@dataclass(frozen=True)
class FoldOutcome:
    period: str
    n_names: int
    ic: float | None
    ceiling: float | None  # split-half self-consistency of the outcome
    tercile_spread: float | None


@dataclass(frozen=True)
class ExperimentVerdict:
    signal_id: str
    claim: str
    verdict: str
    n_folds: int
    mean_ic: float | None
    nw_t: float | None
    share_folds_directional: float | None
    tercile_spread_mean: float | None
    tercile_spread_t: float | None
    median_ceiling: float | None
    gate_results: dict[str, bool]
    baseline_lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- stats


def spearman_ic(left: pd.Series, right: pd.Series) -> float | None:
    """Spearman rank correlation; None if undefined."""

    lr = pd.to_numeric(left, errors="coerce")
    rr = pd.to_numeric(right, errors="coerce")
    mask = lr.notna() & rr.notna()
    if int(mask.sum()) < 3:
        return None
    a = lr[mask].rank(method="average")
    b = rr[mask].rank(method="average")
    if a.nunique() < 2 or b.nunique() < 2:
        return None
    corr = float(np.corrcoef(a, b)[0, 1])
    return None if math.isnan(corr) else corr


def newey_west_t(values: list[float]) -> float | None:
    """One-sample t-stat of the mean with a Newey–West lag-1 variance.

    Fold ICs are outcome-disjoint (valid as a null test) but their feature
    windows overlap adjacent folds, so a plain t is mildly anti-conservative.
    The lag-1 NW correction is the registered standard error. n = n_folds.
    """

    clean = [float(v) for v in values if v is not None and not math.isnan(v)]
    n = len(clean)
    if n < 3:
        return None
    arr = np.asarray(clean, dtype=float)
    mean = float(arr.mean())
    resid = arr - mean
    gamma0 = float(np.mean(resid**2))
    gamma1 = float(np.mean(resid[1:] * resid[:-1])) if n > 1 else 0.0
    # Bartlett lag-1 weight = 1/2; long-run variance of the series.
    lrv = gamma0 + 2.0 * 0.5 * gamma1
    lrv = max(lrv, 1e-12)
    se_mean = math.sqrt(lrv / n)
    if se_mean == 0:
        return None
    return mean / se_mean


def _ols_beta(y: np.ndarray, x: np.ndarray) -> float | None:
    """Slope of y on x with intercept; None if degenerate."""

    if len(x) < 2:
        return None
    xc = x - x.mean()
    denom = float((xc**2).sum())
    if denom <= 0:
        return None
    return float((xc * (y - y.mean())).sum() / denom)


# ---------------------------------------------------------------- inputs


def _panel_with_periods(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    out["as_of"] = pd.to_datetime(out["as_of_date"].astype(str))
    out["week_period"] = out["as_of"].dt.to_period("W-FRI")
    return out


def reconstruct_cores_at(
    panel: pd.DataFrame,
    period: pd.Period,
    *,
    column: str,
    weight_map: dict[str, float],
) -> pd.Series:
    """Weighted-median core of ``column`` per ticker at ``period`` (PIT).

    Per ticker: take the latest as-of row set inside the W-FRI period, keep
    ELIGIBLE windows only, weighted-median across them. Mirrors
    ``model/pipeline`` core construction exactly.
    """

    rows = panel[panel["week_period"] == period]
    if rows.empty:
        return pd.Series(dtype="float64")
    result: dict[str, float] = {}
    for ticker, group in rows.groupby("ticker"):
        latest = group["as_of"].max()
        at = group[group["as_of"] == latest]
        eligible = at[at["window_status"].astype(str) == "ELIGIBLE"]
        if eligible.empty:
            continue
        values = {
            str(r["window_id"]).upper(): r[column]
            for _, r in eligible.iterrows()
            if pd.notna(r[column])
        }
        core = _weighted_median(values, weight_map)
        if core is not None:
            result[str(ticker)] = core
    return pd.Series(result, dtype="float64")


def _weighted_median(values: dict[str, float], weights: dict[str, float]) -> float | None:
    usable = [
        (float(v), float(weights.get(k, 1.0)))
        for k, v in values.items()
        if v is not None and pd.notna(v)
    ]
    if not usable:
        return None
    usable.sort(key=lambda item: item[0])
    cutoff = sum(w for _, w in usable) / 2.0
    running = 0.0
    for value, weight in usable:
        running += weight
        if running >= cutoff:
            return float(value)
    return float(usable[-1][0])


def build_as_of_grid(panel: pd.DataFrame) -> list[pd.Period]:
    """26-period grid anchored at the first ≥15-eligible cross-section.

    A scheduled as-of with a thin/partial cross-section steps back up to 2
    weeks before being skipped (spec §1).
    """

    counts = (
        panel[panel["window_id"].astype(str).str.upper() == "12M"]
        .assign(elig=lambda d: d["window_status"].astype(str) == "ELIGIBLE")
        .query("elig")
        .groupby("week_period")["ticker"]
        .nunique()
    )
    if counts.empty:
        return []
    all_periods = pd.period_range(GRID_ANCHOR, counts.index.max(), freq="W-FRI")
    median_by_period = counts.reindex(all_periods).fillna(0)
    grid: list[pd.Period] = []
    scheduled = GRID_ANCHOR
    last = counts.index.max()
    while scheduled <= last:
        chosen = None
        for back in range(0, 3):  # 0, 1, 2 weeks back
            cand = scheduled - back
            n = int(median_by_period.get(cand, 0))
            if n < MIN_CROSS_SECTION:
                continue
            window = median_by_period.loc[
                max(cand - 4, all_periods[0]) : cand + 4
            ]
            local_median = float(window[window > 0].median()) if (window > 0).any() else 0.0
            if local_median > 0 and n < MIN_COMPLETENESS_FRACTION * local_median:
                continue
            chosen = cand
            break
        if chosen is not None and (not grid or chosen != grid[-1]):
            grid.append(chosen)
        scheduled = scheduled + GRID_STEP_PERIODS
    return grid


# ---------------------------------------------------------------- forward outcomes


def _ticker_weekly(weekly: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for ticker, group in weekly.groupby("ticker"):
        g = group.copy()
        g["period"] = g["week_period"].apply(lambda s: pd.Period(str(s), freq="W-FRI"))
        out[str(ticker)] = g.sort_values("period").reset_index(drop=True)
    return out


def forward_realized_beta(
    g: pd.DataFrame,
    t: pd.Period,
    *,
    horizon: int = FORWARD_HORIZON_WEEKS,
    gold_down_only: bool = False,
    gold_up_only: bool = False,
    min_weeks: int = MIN_FORWARD_WEEKS,
    split: str | None = None,
) -> float | None:
    """Realized OLS beta of stock on gold over periods strictly after t.

    ``split='odd'/'even'`` selects alternating forward weeks for the
    split-half noise ceiling (outcome-vs-outcome, never unblinds the rank).
    """

    fwd = g[(g["period"] > t) & (g["period"] <= t + horizon)].copy()
    gold = pd.to_numeric(fwd["gold_log_ret"], errors="coerce")
    stock = pd.to_numeric(fwd["stock_log_ret"], errors="coerce")
    mask = gold.notna() & stock.notna()
    if gold_down_only:
        mask &= gold < 0
    if gold_up_only:
        mask &= gold > 0
    idx = np.where(mask.to_numpy())[0]
    if split == "odd":
        idx = idx[1::2]
    elif split == "even":
        idx = idx[0::2]
    floor = min_weeks if split is None else max(2, min_weeks // 2)
    if len(idx) < floor:
        return None
    y = stock.to_numpy()[idx]
    x = gold.to_numpy()[idx]
    return _ols_beta(y, x)


# ---------------------------------------------------------------- verdict


def _classify(
    *,
    gate_results: dict[str, bool],
    median_ceiling: float | None,
) -> str:
    passed = sum(1 for v in gate_results.values() if v)
    total = len(gate_results)
    if total and passed == total:
        return f"SUPPORTED ({SURVIVOR_QUALIFIER})"
    if median_ceiling is not None and median_ceiling < INCONCLUSIVE_CEILING:
        return "INCONCLUSIVE — outcome unmeasurable at this horizon"
    if passed == 0:
        return "NOT SUPPORTED"
    return "PARTIAL"


# ---------------------------------------------------------------- terciles


def tercile_portfolio_spread(ranks: pd.Series, outcomes: pd.Series) -> float | None:
    """Top-tercile-mean minus bottom-tercile-mean of the outcome.

    Terciles by ``ranks`` (higher rank = top); portfolio averaging cuts the
    per-name estimation noise by ~sqrt(tercile size). Deterministic sort.
    """

    df = pd.DataFrame(
        {
            "rank": pd.to_numeric(ranks, errors="coerce"),
            "out": pd.to_numeric(outcomes, errors="coerce"),
        }
    ).dropna()
    if len(df) < 6:
        return None
    df = df.sort_values(["rank"], kind="mergesort")
    k = len(df) // 3
    if k < 1:
        return None
    bottom = df["out"].iloc[:k].mean()
    top = df["out"].iloc[-k:].mean()
    if pd.isna(top) or pd.isna(bottom):
        return None
    return float(top - bottom)


# ---------------------------------------------------------------- E1a / E1b / E2


def run_e1a(
    panel: pd.DataFrame, grid: list[pd.Period], weight_map: dict[str, float]
) -> ExperimentVerdict:
    """Tool A Δ Core rank STABILITY: Spearman(rank_t, rank_t+52)."""

    pairs: list[float] = []
    for t in grid:
        r1 = reconstruct_cores_at(panel, t, column="structural_delta", weight_map=weight_map)
        r2 = reconstruct_cores_at(
            panel, t + STABILITY_LAG_PERIODS, column="structural_delta", weight_map=weight_map
        )
        common = r1.index.intersection(r2.index)
        if len(common) < MIN_CROSS_SECTION:
            continue
        ic = spearman_ic(r1.loc[common], r2.loc[common])
        if ic is not None:
            pairs.append(ic)
    mean_ic = float(np.mean(pairs)) if pairs else None
    share = float(np.mean([p >= 0.30 for p in pairs])) if pairs else None
    gates = {
        "mean_stability_ic_ge_0.45": mean_ic is not None and mean_ic >= 0.45,
        "ge80pct_folds_ic_ge_0.30": share is not None and share >= 0.80,
    }
    return ExperimentVerdict(
        signal_id="validation_e1a",
        claim="Tool A Δ Core gearing ranking is stable out of sample",
        verdict=_classify(gate_results=gates, median_ceiling=None),
        n_folds=len(pairs),
        mean_ic=mean_ic,
        nw_t=None,
        share_folds_directional=share,
        tercile_spread_mean=None,
        tercile_spread_t=None,
        median_ceiling=None,
        gate_results=gates,
        notes=["Stability claim (no forward outcome); level gate, no t-stat."],
    )


def _validity_experiment(
    *,
    signal_id: str,
    claim: str,
    panel: pd.DataFrame,
    ticker_weekly: dict[str, pd.DataFrame],
    grid: list[pd.Period],
    weight_map: dict[str, float],
    rank_column: str,
    gold_down_only: bool = False,
    gold_up_only: bool = False,
    spread_gate: float = 0.20,
    direction: int = 1,
    min_weeks: int = MIN_FORWARD_WEEKS,
) -> tuple[ExperimentVerdict, list[FoldOutcome]]:
    """Shared engine for E1b/E2-style 'rank vs forward realized beta' tests.

    ``direction`` = +1 means higher rank should give higher forward outcome.
    Metrics are stored in the registered direction, so a pinned-negative
    experiment reports positive when the tool works as claimed.
    """

    folds: list[FoldOutcome] = []
    for t in grid:
        ranks = reconstruct_cores_at(panel, t, column=rank_column, weight_map=weight_map)
        if len(ranks) < MIN_CROSS_SECTION:
            continue
        fwd: dict[str, float] = {}
        odd: dict[str, float] = {}
        even: dict[str, float] = {}
        for ticker in ranks.index:
            g = ticker_weekly.get(ticker)
            if g is None:
                continue
            beta = forward_realized_beta(
                g, t, gold_down_only=gold_down_only, gold_up_only=gold_up_only, min_weeks=min_weeks
            )
            if beta is None:
                continue
            fwd[ticker] = beta
            o = forward_realized_beta(
                g, t, gold_down_only=gold_down_only, gold_up_only=gold_up_only, split="odd", min_weeks=min_weeks
            )
            e = forward_realized_beta(
                g, t, gold_down_only=gold_down_only, gold_up_only=gold_up_only, split="even", min_weeks=min_weeks
            )
            if o is not None and e is not None:
                odd[ticker] = o
                even[ticker] = e
        if len(fwd) < MIN_CROSS_SECTION:
            continue
        common = ranks.index.intersection(pd.Index(list(fwd)))
        out = pd.Series(fwd).loc[common]
        ic = spearman_ic(ranks.loc[common], out)
        ic = None if ic is None else direction * ic
        ceiling = None
        if len(odd) >= MIN_CROSS_SECTION:
            ci = pd.Index(list(odd))
            ceiling = spearman_ic(pd.Series(odd).loc[ci], pd.Series(even).loc[ci])
        spread = tercile_portfolio_spread(ranks.loc[common], out)
        spread = None if spread is None else direction * spread
        folds.append(
            FoldOutcome(
                period=str(t), n_names=len(common), ic=ic, ceiling=ceiling, tercile_spread=spread
            )
        )

    ics = [f.ic for f in folds if f.ic is not None]
    spreads = [f.tercile_spread for f in folds if f.tercile_spread is not None]
    ceilings = [f.ceiling for f in folds if f.ceiling is not None]
    mean_ic = float(np.mean(ics)) if ics else None
    nw_t = newey_west_t(ics)
    share = float(np.mean([i > 0 for i in ics])) if ics else None
    spread_mean = float(np.mean(spreads)) if spreads else None
    spread_t = newey_west_t(spreads)
    median_ceiling = float(np.median(ceilings)) if ceilings else None

    gates = {
        "mean_ic_gt0_nw_t_gt3": nw_t is not None and nw_t > 3,
        "ge70pct_folds_directional": share is not None and share >= 0.70,
        "tercile_spread_gated": (
            spread_mean is not None
            and spread_mean >= spread_gate
            and spread_t is not None
            and spread_t > 2
        ),
    }
    return (
        ExperimentVerdict(
            signal_id=signal_id,
            claim=claim,
            verdict=_classify(gate_results=gates, median_ceiling=median_ceiling),
            n_folds=len(folds),
            mean_ic=mean_ic,
            nw_t=nw_t,
            share_folds_directional=share,
            tercile_spread_mean=spread_mean,
            tercile_spread_t=spread_t,
            median_ceiling=median_ceiling,
            gate_results=gates,
        ),
        folds,
    )


def run_e1b(panel, ticker_weekly, grid, weight_map):
    return _validity_experiment(
        signal_id="validation_e1b",
        claim="Tool A Δ Core ranking forward-predicts realized gold beta",
        panel=panel,
        ticker_weekly=ticker_weekly,
        grid=grid,
        weight_map=weight_map,
        rank_column="structural_delta",
        spread_gate=0.20,
        direction=1,
    )


def run_e2(panel, ticker_weekly, grid, weight_map):
    return _validity_experiment(
        signal_id="validation_e2",
        claim="Down-beta ranking forward-predicts down-beta in gold-down weeks",
        panel=panel,
        ticker_weekly=ticker_weekly,
        grid=grid,
        weight_map=weight_map,
        rank_column="down_beta",
        gold_down_only=True,
        spread_gate=0.35,
        direction=1,
        min_weeks=8,
    )


# ---------------------------------------------------------------- inputs


def load_validation_inputs(paths):
    import glob

    from golden_vector.app.config import load_app_config
    from golden_vector.features.weekly_returns import build_weekly_return_frame

    panel_files = sorted(
        glob.glob(str(paths.data_dir / "intermediate" / "tool_a_structural" / "*latest*.parquet"))
    )
    panel = _panel_with_periods(pd.read_parquet(panel_files[0]))

    cfg = load_app_config(paths)
    weight_map = cfg.app.scoring.structural_weight_map()

    gold = pd.read_parquet(sorted(glob.glob(str(paths.raw_gold_dir / "*.parquet")))[0])
    histories = {
        p.stem: pd.read_parquet(p)
        for p in sorted(paths.intermediate_usd_equities_dir.glob("*.parquet"))
    }
    benchmarks = {
        ticker: pd.read_parquet(paths.benchmarks_dir / f"{ticker}.parquet")
        for ticker in ("GDX", "GDXJ")
        if (paths.benchmarks_dir / f"{ticker}.parquet").exists()
    }
    weekly = build_weekly_return_frame(
        normalized_equity_histories=histories, gold_history=gold, benchmark_histories=benchmarks
    )
    return panel, _ticker_weekly(weekly), weight_map
