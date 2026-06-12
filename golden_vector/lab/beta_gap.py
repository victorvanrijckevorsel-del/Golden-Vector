"""Beta-gap nowcast experiment — the Lab's flagship, run as a GATED experiment.

Question: does a James-Stein-shrunk fast beta (26w-window exponentially
weighted, halflife 13w) predict each miner's NEXT-26-week realized gold beta
better than the two persistence baselines?

PRE-REGISTERED GATE (locked in the plan before any compute; the variant must
be registered in the ledger before run_experiment will execute):
- Beat BOTH baselines (slow-structural-beta-persists AND raw-fast-beta-
  persists) on next-26w-beta MAE by >= 10%,
- t > 3 on the per-fold MAE differences (episode-adjusted N),
- in >= 70% of walk-forward folds.
Anything less and the dial keeps its current betas. The null is shippable.

All betas here are weekly stock-log-return on gold-log-return slopes; the
label is the plain OLS beta over weeks t+1..t+26 (strictly forward).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from golden_vector.lab.evaluation import mae_improvement_pct
from golden_vector.lab.forward_returns import reindex_contiguous_weeks
from golden_vector.lab.walk_forward import generate_folds

FAST_HALFLIFE_WEEKS = 13
FAST_MIN_PERIODS = 26
SLOW_WINDOW_WEEKS = 156
SLOW_MIN_PERIODS = 104
LABEL_WINDOW_WEEKS = 26
LABEL_MIN_PERIODS = 26  # complete forward windows only
GATE_MIN_IMPROVEMENT_PCT = 10.0
GATE_MIN_T_STAT = 3.0
GATE_MIN_FOLD_WIN_RATE = 0.70

EXPERIMENT_CONFIG = {
    "signal": "beta_gap_nowcast_v1",
    "fast_halflife_weeks": FAST_HALFLIFE_WEEKS,
    "fast_min_periods": FAST_MIN_PERIODS,
    "slow_window_weeks": SLOW_WINDOW_WEEKS,
    "slow_min_periods": SLOW_MIN_PERIODS,
    "label_window_weeks": LABEL_WINDOW_WEEKS,
    "shrinkage": "james_stein_positive_part_standardized_heteroscedastic_v2",
    "baselines": ["slow_beta_persists", "fast_beta_persists"],
    "gate": {
        "min_mae_improvement_pct_vs_both": GATE_MIN_IMPROVEMENT_PCT,
        "min_t_stat": GATE_MIN_T_STAT,
        "min_fold_win_rate": GATE_MIN_FOLD_WIN_RATE,
    },
    "folds": {"min_train_weeks": 156, "test_weeks": 26, "step_weeks": 52},
}


@dataclass(frozen=True)
class FoldResult:
    fold_index: int
    n_observations: int
    mae_model: float
    mae_slow: float
    mae_fast: float


@dataclass(frozen=True)
class BetaGapVerdict:
    passed: bool
    n_folds: int
    win_rate_vs_slow: float
    win_rate_vs_fast: float
    improvement_vs_slow_pct: float | None
    improvement_vs_fast_pct: float | None
    t_stat_vs_slow: float | None
    t_stat_vs_fast: float | None
    fold_results: list[FoldResult]
    reasons: list[str]


def build_beta_panel(weekly_frame: pd.DataFrame) -> pd.DataFrame:
    """Per (ticker, week): fast EW beta + SE proxy, slow beta, forward label.

    Everything trailing uses data through week t only; the label is strictly
    forward. NA whenever the window is short of its minimum.
    """

    pieces: list[pd.DataFrame] = []
    for ticker, group in weekly_frame.groupby("ticker", sort=True):
        ordered = reindex_contiguous_weeks(group)
        stock = pd.to_numeric(ordered["stock_log_ret"], errors="coerce").astype(float)
        gold = pd.to_numeric(ordered["gold_log_ret"], errors="coerce").astype(float)

        fast_beta, fast_se = _ew_beta_with_se(stock, gold)
        slow_beta = _rolling_beta(
            stock, gold, window=SLOW_WINDOW_WEEKS, min_periods=SLOW_MIN_PERIODS
        )
        forward_beta = (
            _rolling_beta(
                stock, gold, window=LABEL_WINDOW_WEEKS, min_periods=LABEL_MIN_PERIODS
            )
            .shift(-LABEL_WINDOW_WEEKS)
        )

        pieces.append(
            pd.DataFrame(
                {
                    "ticker": str(ticker),
                    "week_period": ordered["week_period"],
                    "fast_beta": fast_beta,
                    "fast_beta_se": fast_se,
                    "slow_beta": slow_beta,
                    "forward_beta": forward_beta,
                }
            )
        )
    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, ignore_index=True)


def apply_james_stein(panel: pd.DataFrame) -> pd.DataFrame:
    """Standardized heteroscedastic positive-part James-Stein, per week.

    Gaps are standardized by their own SEs before computing the shrink
    factor (c = max(0, 1-(k-2)/sum((gap/SE)^2))). With k <= 2 names or
    degenerate gaps, c = 0 (pure slow beta) — shrinking to the structural
    prior is the safe default.
    """

    working = panel.copy()
    working["beta_nowcast"] = np.nan
    for _, index in working.groupby("week_period").groups.items():
        rows = working.loc[index]
        valid = rows.dropna(subset=["fast_beta", "fast_beta_se", "slow_beta"])
        if valid.empty:
            continue
        gaps = (valid["fast_beta"] - valid["slow_beta"]).to_numpy(dtype=float)
        ses = valid["fast_beta_se"].to_numpy(dtype=float)
        k = len(gaps)
        # Standardized heteroscedastic positive-part JS: z_i = gap_i/SE_i,
        # c = max(0, 1 - (k-2)/sum(z^2)), nowcast_i = slow_i + c*gap_i.
        # The v1 homoscedastic form used mean(SE^2), which real SEs
        # (spanning 160x across names) inflated so badly the nowcast
        # collapsed to the slow baseline in ~half the weeks.
        # SE -> 0 means infinite precision: z -> inf, c -> 1, no shrink.
        safe_ses = np.maximum(ses, 1e-12)
        z = gaps / safe_ses
        z_energy = float(np.sum(z**2))
        if k > 2 and z_energy > 0:
            shrink = max(0.0, 1.0 - (k - 2) / z_energy)
        else:
            shrink = 0.0
        working.loc[valid.index, "beta_nowcast"] = (
            valid["slow_beta"].to_numpy(dtype=float) + shrink * gaps
        )
    return working


def run_experiment(panel_with_nowcast: pd.DataFrame) -> BetaGapVerdict:
    """Walk-forward evaluation of the nowcast vs both persistence baselines.

    NOTE: there is no fitting step — the nowcast is a deterministic formula —
    so 'train' weeks only establish that the fold respects the purge gap; all
    scoring happens strictly inside each test window.
    """

    scored = panel_with_nowcast.dropna(
        subset=["beta_nowcast", "slow_beta", "fast_beta", "forward_beta"]
    )
    grid = sorted(scored["week_period"].astype(str).unique())
    folds = generate_folds(
        grid,
        label_horizon_weeks=LABEL_WINDOW_WEEKS,
        min_train_weeks=int(EXPERIMENT_CONFIG["folds"]["min_train_weeks"]),
        test_weeks=int(EXPERIMENT_CONFIG["folds"]["test_weeks"]),
        # step = test + label horizon: adjacent folds' test LABEL windows
        # are disjoint, so per-fold MAE differences are not serially
        # correlated and the plain paired t is honest (the pre-registered
        # "episode-adjusted" requirement).
        step_weeks=int(EXPERIMENT_CONFIG["folds"]["step_weeks"]),
    )
    fold_results: list[FoldResult] = []
    for fold in folds:
        test_rows = scored[scored["week_period"].astype(str).isin(fold.test_periods)]
        if test_rows.empty:
            continue
        fold_results.append(
            FoldResult(
                fold_index=fold.fold_index,
                n_observations=int(len(test_rows)),
                mae_model=float((test_rows["beta_nowcast"] - test_rows["forward_beta"]).abs().mean()),
                mae_slow=float((test_rows["slow_beta"] - test_rows["forward_beta"]).abs().mean()),
                mae_fast=float((test_rows["fast_beta"] - test_rows["forward_beta"]).abs().mean()),
            )
        )

    reasons: list[str] = []
    if not fold_results:
        return BetaGapVerdict(
            passed=False,
            n_folds=0,
            win_rate_vs_slow=0.0,
            win_rate_vs_fast=0.0,
            improvement_vs_slow_pct=None,
            improvement_vs_fast_pct=None,
            t_stat_vs_slow=None,
            t_stat_vs_fast=None,
            fold_results=[],
            reasons=["No scorable folds — insufficient history."],
        )

    mae_model = float(np.mean([fold.mae_model for fold in fold_results]))
    mae_slow = float(np.mean([fold.mae_slow for fold in fold_results]))
    mae_fast = float(np.mean([fold.mae_fast for fold in fold_results]))
    improvement_slow = mae_improvement_pct(mae_model, mae_slow)
    improvement_fast = mae_improvement_pct(mae_model, mae_fast)
    win_slow = float(np.mean([fold.mae_model < fold.mae_slow for fold in fold_results]))
    win_fast = float(np.mean([fold.mae_model < fold.mae_fast for fold in fold_results]))
    t_slow = _paired_t(
        [fold.mae_slow - fold.mae_model for fold in fold_results]
    )
    t_fast = _paired_t(
        [fold.mae_fast - fold.mae_model for fold in fold_results]
    )

    checks = [
        (
            improvement_slow is not None
            and improvement_slow >= GATE_MIN_IMPROVEMENT_PCT,
            f"MAE improvement vs slow baseline {improvement_slow if improvement_slow is None else round(improvement_slow, 2)}% (need >= {GATE_MIN_IMPROVEMENT_PCT}%)",
        ),
        (
            improvement_fast is not None
            and improvement_fast >= GATE_MIN_IMPROVEMENT_PCT,
            f"MAE improvement vs fast baseline {improvement_fast if improvement_fast is None else round(improvement_fast, 2)}% (need >= {GATE_MIN_IMPROVEMENT_PCT}%)",
        ),
        (
            t_slow is not None and t_slow > GATE_MIN_T_STAT,
            f"t vs slow {t_slow if t_slow is None else round(t_slow, 2)} (need > {GATE_MIN_T_STAT})",
        ),
        (
            t_fast is not None and t_fast > GATE_MIN_T_STAT,
            f"t vs fast {t_fast if t_fast is None else round(t_fast, 2)} (need > {GATE_MIN_T_STAT})",
        ),
        (
            win_slow >= GATE_MIN_FOLD_WIN_RATE and win_fast >= GATE_MIN_FOLD_WIN_RATE,
            f"fold win rates slow={win_slow:.0%} fast={win_fast:.0%} (need >= {GATE_MIN_FOLD_WIN_RATE:.0%} both)",
        ),
    ]
    for passed, message in checks:
        reasons.append(("PASS: " if passed else "FAIL: ") + message)

    return BetaGapVerdict(
        passed=all(passed for passed, _ in checks),
        n_folds=len(fold_results),
        win_rate_vs_slow=win_slow,
        win_rate_vs_fast=win_fast,
        improvement_vs_slow_pct=improvement_slow,
        improvement_vs_fast_pct=improvement_fast,
        t_stat_vs_slow=t_slow,
        t_stat_vs_fast=t_fast,
        fold_results=fold_results,
        reasons=reasons,
    )


def _ew_beta_with_se(stock: pd.Series, gold: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Exponentially weighted beta and an OLS-style SE proxy.

    SE^2 ~ (1 - r^2) * var(stock) / (n_eff * var(gold)); n_eff is the
    standard EW equivalent sample size (1+lambda)/(1-lambda) for the chosen
    halflife — approximate, and used only as relative shrinkage weight.
    """

    ew = lambda s: s.ewm(halflife=FAST_HALFLIFE_WEEKS, min_periods=FAST_MIN_PERIODS)  # noqa: E731
    cov = ew(stock).cov(gold)
    var_gold = ew(gold).var()
    var_stock = ew(stock).var()
    beta = cov / var_gold
    corr_sq = (cov**2) / (var_gold * var_stock)
    lam = 2.0 ** (-1.0 / FAST_HALFLIFE_WEEKS)
    n_eff = (1 + lam) / (1 - lam)
    se_sq = (1 - corr_sq).clip(lower=0.0) * var_stock / (n_eff * var_gold)
    return beta, np.sqrt(se_sq)


def _rolling_beta(
    stock: pd.Series,
    gold: pd.Series,
    *,
    window: int,
    min_periods: int,
) -> pd.Series:
    cov = stock.rolling(window, min_periods=min_periods).cov(gold)
    var = gold.rolling(window, min_periods=min_periods).var()
    return cov / var


def _paired_t(differences: list[float]) -> float | None:
    if len(differences) < 2:
        return None
    std = float(np.std(differences, ddof=1))
    if std == 0:
        return None
    return float(np.mean(differences)) / (std / math.sqrt(len(differences)))
