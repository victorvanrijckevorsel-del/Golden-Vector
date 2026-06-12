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

from golden_vector.model.structural import weighted_median

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

# Gate thresholds — these MUST match the registered ledger configs (a drift
# test asserts it). Changing one here without a new registered variant is the
# malpractice pre-registration forbids.
E1A_MEAN_IC_GATE = 0.45
E1A_FOLD_IC_FLOOR = 0.30
E1A_SHARE_GATE = 0.80
NW_T_GATE = 3.0
SHARE_DIRECTIONAL_GATE = 0.70
SPREAD_T_GATE = 2.0
E1B_SPREAD_GATE = 0.20
E2_SPREAD_GATE = 0.35
E2_DOWN_WEEK_FLOOR = 8
BASELINE_PAIRED_T_GATE = 2.0
TIME_REVERSAL_MIN_CONTRAST = 0.15


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
    contaminated: bool = False  # set only by leakage probes; refused at publish


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
    # Standard HAC convention: both autocovariances divide by n (not n-1).
    gamma0 = float(np.sum(resid**2) / n)
    gamma1 = float(np.sum(resid[1:] * resid[:-1]) / n) if n > 1 else 0.0
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
        # Use the PRODUCT'S weighted_median (model/structural) — the same
        # primitive model/pipeline builds the cores with. No forked copy:
        # its drift would invalidate the study, so there must be one
        # implementation (a committed parity test pins reconstruction to the
        # live artifact).
        values = {
            str(r["window_id"]).upper(): r[column]
            for _, r in eligible.iterrows()
            if pd.notna(r[column])
        }
        core = weighted_median(values, weights=weight_map)
        if core is not None:
            result[str(ticker)] = core
    return pd.Series(result, dtype="float64")


def fixed_cohort_panel(panel: pd.DataFrame, *, before: str = "2010-01-01") -> pd.DataFrame:
    """Survivorship robustness slice: keep only tickers with an ELIGIBLE 12M
    window before ``before`` (constant membership across the later folds)."""

    early = panel[
        (panel["window_id"].astype(str).str.upper() == "12M")
        & (panel["window_status"].astype(str) == "ELIGIBLE")
        & (panel["as_of"] < pd.Timestamp(before))
    ]
    cohort = set(early["ticker"].astype(str))
    return panel[panel["ticker"].astype(str).isin(cohort)].copy()


def build_as_of_grid(panel: pd.DataFrame, *, step: int = GRID_STEP_PERIODS) -> list[pd.Period]:
    """``step``-period grid anchored at the first ≥15-eligible cross-section.

    A scheduled as-of with a thin/partial cross-section steps back up to 2
    weeks before being skipped (spec §1). ``step=52`` gives the registered
    robustness slice (~half the folds).
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
        scheduled = scheduled + step
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
            "ticker": [str(i) for i in ranks.index],
        }
    ).dropna()
    if len(df) < 6:
        return None
    # Deterministic: ties on rank broken by ticker (spec §1), independent of
    # the caller's input order.
    df = df.sort_values(["rank", "ticker"], kind="mergesort")
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
    share = float(np.mean([p >= E1A_FOLD_IC_FLOOR for p in pairs])) if pairs else None
    gates = {
        "mean_stability_ic_ge_gate": mean_ic is not None and mean_ic >= E1A_MEAN_IC_GATE,
        "share_folds_ic_ge_floor": share is not None and share >= E1A_SHARE_GATE,
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


def single_window_ranks(
    panel: pd.DataFrame, period: pd.Period, *, column: str, window: str = "12M"
) -> pd.Series:
    """The raw single-window value per ticker at ``period`` (PIT baseline)."""

    rows = panel[
        (panel["week_period"] == period)
        & (panel["window_id"].astype(str).str.upper() == window)
        & (panel["window_status"].astype(str) == "ELIGIBLE")
    ]
    out: dict[str, float] = {}
    for ticker, group in rows.groupby("ticker"):
        latest = group["as_of"].max()
        value = group[group["as_of"] == latest][column].iloc[0]
        if pd.notna(value):
            out[str(ticker)] = float(value)
    return pd.Series(out, dtype="float64")


def trailing_realized_beta(
    g: pd.DataFrame,
    t: pd.Period,
    *,
    lookback: int = FORWARD_HORIZON_WEEKS,
    gold_down_only: bool = False,
    min_weeks: int = MIN_FORWARD_WEEKS,
) -> float | None:
    """OLS beta over the lookback periods up to and including t (PIT baseline)."""

    win = g[(g["period"] > t - lookback) & (g["period"] <= t)]
    gold = pd.to_numeric(win["gold_log_ret"], errors="coerce")
    stock = pd.to_numeric(win["stock_log_ret"], errors="coerce")
    mask = gold.notna() & stock.notna()
    if gold_down_only:
        mask &= gold < 0
    idx = np.where(mask.to_numpy())[0]
    if len(idx) < min_weeks:
        return None
    return _ols_beta(stock.to_numpy()[idx], gold.to_numpy()[idx])


@dataclass(frozen=True)
class BaselineSpec:
    label: str
    beaten_line: str  # appended VERBATIM when the core does NOT beat it
    kind: str  # 'single_window' or 'trailing_beta'
    window: str = "12M"


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
    baselines: list[BaselineSpec] | None = None,
) -> tuple[ExperimentVerdict, list[FoldOutcome]]:
    """Shared engine for E1b/E2-style 'rank vs forward realized beta' tests.

    ``direction`` = +1 means higher rank should give higher forward outcome.
    Metrics are stored in the registered direction, so a pinned-negative
    experiment reports positive when the tool works as claimed.

    ``baselines`` are scored on the SAME folds/outcomes; a paired NW-t on the
    per-fold (core IC − baseline IC) decides whether the core beats each one.
    """

    baselines = baselines or []
    folds: list[FoldOutcome] = []
    # per-fold (core_ic, baseline_ic) for the paired comparisons
    paired: dict[str, list[tuple[float, float]]] = {b.label: [] for b in baselines}
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
        ic_raw = spearman_ic(ranks.loc[common], out)
        ic = None if ic_raw is None else direction * ic_raw
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
        # baseline ICs on the SAME common names + outcome
        if ic_raw is not None:
            for b in baselines:
                if b.kind == "single_window":
                    br = single_window_ranks(panel, t, column=rank_column, window=b.window)
                else:
                    br = pd.Series(
                        {
                            tk: v
                            for tk in common
                            if (
                                v := trailing_realized_beta(
                                    ticker_weekly[tk], t,
                                    gold_down_only=gold_down_only, min_weeks=min_weeks,
                                )
                            )
                            is not None
                        },
                        dtype="float64",
                    )
                bcommon = common.intersection(br.index)
                if len(bcommon) < MIN_CROSS_SECTION:
                    continue
                core_ic = spearman_ic(ranks.loc[bcommon], out.loc[bcommon])
                base_ic = spearman_ic(br.loc[bcommon], out.loc[bcommon])
                if core_ic is not None and base_ic is not None:
                    paired[b.label].append((direction * core_ic, direction * base_ic))

    baseline_lines: list[str] = []
    for b in baselines:
        diffs = [c - x for c, x in paired[b.label]]
        t_pair = newey_west_t(diffs)
        # core fails to beat the baseline => paired t not > 2 => verbatim line
        if not (t_pair is not None and t_pair > BASELINE_PAIRED_T_GATE):
            baseline_lines.append(b.beaten_line)

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
        "mean_ic_nw_t_gt_gate": nw_t is not None and nw_t > NW_T_GATE,
        "share_folds_directional_ge_gate": share is not None and share >= SHARE_DIRECTIONAL_GATE,
        "tercile_spread_gated": (
            spread_mean is not None
            and spread_mean >= spread_gate
            and spread_t is not None
            and spread_t > SPREAD_T_GATE
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
            baseline_lines=baseline_lines,
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
        spread_gate=E1B_SPREAD_GATE,
        direction=1,
        baselines=[
            BaselineSpec(
                label="single_12m_window",
                beaten_line=(
                    "A simpler 12M-window beta ranked as well or better "
                    "(paired p ≥ 0.05); the multi-window core adds no measured edge."
                ),
                kind="single_window",
                window="12M",
            ),
            BaselineSpec(
                label="trailing_26w_beta",
                beaten_line=(
                    "A simpler 26-week trailing beta ranked as well or better "
                    "(paired p ≥ 0.05); the longer window adds no measured edge."
                ),
                kind="trailing_beta",
            ),
        ],
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
        spread_gate=E2_SPREAD_GATE,
        direction=1,
        min_weeks=E2_DOWN_WEEK_FLOOR,
        baselines=[
            BaselineSpec(
                label="trailing_26w_down_beta",
                beaten_line=(
                    "A simpler 26-week trailing down-beta ranked as well or better "
                    "(paired p ≥ 0.05); the structural core adds no measured edge."
                ),
                kind="trailing_beta",
            ),
        ],
    )


# ---------------------------------------------------------------- inputs


def time_reversal_ic_contrast(
    panel: pd.DataFrame,
    ticker_weekly: dict[str, pd.DataFrame],
    grid: list[pd.Period],
    weight_map: dict[str, float],
    *,
    rank_column: str,
    gold_down_only: bool = False,
    min_weeks: int = MIN_FORWARD_WEEKS,
) -> tuple[float | None, float | None]:
    """Spec §4 canary 3 — time-reversal contrast.

    Returns (honest_mean_ic, contaminated_mean_ic). The honest rank is the
    PIT core at t; the contaminated rank uses the forward outcome itself
    (perfect future information). A working harness — one that genuinely
    cannot see the future on the honest path — must show the contaminated
    run beating the honest run by a wide margin (≥ 0.15). If they are close,
    the honest path is leaking.
    """

    honest: list[float] = []
    contaminated: list[float] = []
    for t in grid:
        ranks = reconstruct_cores_at(panel, t, column=rank_column, weight_map=weight_map)
        if len(ranks) < MIN_CROSS_SECTION:
            continue
        fwd: dict[str, float] = {}
        for ticker in ranks.index:
            g = ticker_weekly.get(ticker)
            if g is None:
                continue
            beta = forward_realized_beta(
                g, t, gold_down_only=gold_down_only, min_weeks=min_weeks
            )
            if beta is not None:
                fwd[ticker] = beta
        if len(fwd) < MIN_CROSS_SECTION:
            continue
        common = ranks.index.intersection(pd.Index(list(fwd)))
        out = pd.Series(fwd).loc[common]
        h = spearman_ic(ranks.loc[common], out)
        c = spearman_ic(out, out)  # contaminated: rank IS the future outcome
        if h is not None:
            honest.append(h)
        if c is not None:
            contaminated.append(c)
    return (
        float(np.mean(honest)) if honest else None,
        float(np.mean(contaminated)) if contaminated else None,
    )


def assert_publishable(verdicts: list[ExperimentVerdict]) -> None:
    """Publish guard: a contaminated (leakage-probe) verdict can never ship."""

    for verdict in verdicts:
        if verdict.contaminated:
            raise ValueError(
                f"Refusing to publish a contaminated verdict for "
                f"{verdict.signal_id} — this is a leakage probe, not a result."
            )


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
