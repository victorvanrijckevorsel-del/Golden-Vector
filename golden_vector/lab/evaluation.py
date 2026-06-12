"""M1-2: evaluation metrics — industry-standard only, with a leakage alarm.

Metrics: per-date Spearman rank IC (mean + t-stat on the date series with
episode-adjusted N), MAE, hit rate, and top-minus-bottom quantile spread.
The t-stat divides by sqrt(effective_n) — overlapping h-week labels sampled
weekly are not independent observations.

The LEAKAGE ALARM is part of the contract, not a nicety: a mean |rank IC|
above ``LEAKAGE_IC_THRESHOLD`` is far beyond anything a real weekly miner
signal produces and marks the run inadmissible. The three CI canaries
(label-as-feature, shuffled labels, forward-shifted features) exercise it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from golden_vector.lab.walk_forward import effective_n

LEAKAGE_IC_THRESHOLD = 0.90
MIN_CROSS_SECTION = 5


@dataclass(frozen=True)
class EvaluationResult:
    n_dates: int
    n_observations: int
    effective_n_dates: float
    rank_ic_mean: float | None
    rank_ic_t_stat: float | None
    mae: float | None
    hit_rate: float | None
    quantile_spread: float | None
    leakage_alarm: bool
    notes: list[str] = field(default_factory=list)


def evaluate_predictions(
    frame: pd.DataFrame,
    *,
    label_horizon_weeks: int,
    prediction_column: str = "prediction",
    label_column: str = "label",
    date_column: str = "week_period",
    quantile: float = 0.2,
) -> EvaluationResult:
    """Score a long panel of (date, ticker, prediction, label) rows."""

    required = {date_column, prediction_column, label_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"evaluation frame missing columns: {sorted(missing)}")

    working = frame[[date_column, prediction_column, label_column]].copy()
    working[prediction_column] = pd.to_numeric(working[prediction_column], errors="coerce")
    working[label_column] = pd.to_numeric(working[label_column], errors="coerce")
    working = working.dropna()
    notes: list[str] = []

    daily_ic: list[float] = []
    spreads: list[float] = []
    hits: list[float] = []
    skipped_thin = 0
    for _, group in working.groupby(date_column, sort=True):
        if len(group) < MIN_CROSS_SECTION:
            skipped_thin += 1
            continue
        ic = _spearman(group[prediction_column], group[label_column])
        if ic is not None:
            daily_ic.append(ic)
        spread = _quantile_spread(group, prediction_column, label_column, quantile)
        if spread is not None:
            spreads.append(spread)
        hits.append(
            float((group[prediction_column] * group[label_column] > 0).mean())
        )
    if skipped_thin:
        notes.append(
            f"{skipped_thin} dates skipped: cross-section below {MIN_CROSS_SECTION}."
        )

    n_dates = len(daily_ic)
    eff_n = effective_n(n_dates, label_horizon_weeks=label_horizon_weeks)
    ic_mean = float(np.mean(daily_ic)) if daily_ic else None
    ic_t = _t_stat(daily_ic, eff_n)
    mae = (
        float((working[prediction_column] - working[label_column]).abs().mean())
        if not working.empty
        else None
    )
    leakage = ic_mean is not None and abs(ic_mean) > LEAKAGE_IC_THRESHOLD
    if leakage:
        notes.append(
            f"LEAKAGE ALARM: mean |rank IC| {abs(ic_mean):.3f} exceeds "
            f"{LEAKAGE_IC_THRESHOLD} — inadmissible, audit the feature pipeline."
        )

    return EvaluationResult(
        n_dates=n_dates,
        n_observations=int(len(working)),
        effective_n_dates=eff_n,
        rank_ic_mean=ic_mean,
        rank_ic_t_stat=ic_t,
        mae=mae,
        hit_rate=float(np.mean(hits)) if hits else None,
        quantile_spread=float(np.mean(spreads)) if spreads else None,
        leakage_alarm=leakage,
        notes=notes,
    )


def mae_improvement_pct(model_mae: float, baseline_mae: float) -> float | None:
    """Positive = model beats baseline; the flagship gate needs >= 10."""

    if baseline_mae <= 0:
        return None
    return (baseline_mae - model_mae) / baseline_mae * 100.0


def _spearman(left: pd.Series, right: pd.Series) -> float | None:
    left_rank = left.rank(method="average")
    right_rank = right.rank(method="average")
    if left_rank.nunique() < 2 or right_rank.nunique() < 2:
        return None
    correlation = float(np.corrcoef(left_rank, right_rank)[0, 1])
    if math.isnan(correlation):
        return None
    return correlation


def _quantile_spread(
    group: pd.DataFrame,
    prediction_column: str,
    label_column: str,
    quantile: float,
) -> float | None:
    if not 0 < quantile < 0.5:
        raise ValueError("quantile must be in (0, 0.5).")
    bucket = max(1, int(len(group) * quantile))
    ordered = group.sort_values(prediction_column)
    bottom = ordered.head(bucket)[label_column].mean()
    top = ordered.tail(bucket)[label_column].mean()
    if pd.isna(top) or pd.isna(bottom):
        return None
    return float(top - bottom)


def _t_stat(values: list[float], eff_n: float) -> float | None:
    if len(values) < 2 or eff_n < 2:
        return None
    std = float(np.std(values, ddof=1))
    if std == 0:
        return None
    return float(np.mean(values)) / (std / math.sqrt(eff_n))
