"""Shared Lab statistics primitives — ONE copy of the counting / shrinkage / trend math.

Extracted from ``conditional_dial._dial_cells`` (``wilson_interval``, ``eb_shrink``,
``pooled_prior``) so there is a single shrink/prior/interval implementation, plus the
new pure-numpy primitives the Capture & Behaviour engine needs:

- ``decay_weights`` / ``decay_effective_n`` — recency weighting + the overlap-deflated
  (Kish / horizon) honest sample size for weighted, overlapping weekly labels.
- ``mann_kendall`` / ``theil_sen`` — distribution-free monotone-trend test + robust
  slope, run ONLY on independent (non-overlap anchor) samples by the callers.
- ``benjamini_hochberg`` — step-up FDR control across the tested family.
- ``peer_percentile`` — cross-sectional rank (100 = best, 0 = worst).
- ``weighted_median`` — re-exported from ``common.stats`` (one copy, shared with model).

scipy / statsmodels / sklearn are NOT installed; everything here is numpy/math only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from golden_vector.common.stats import weighted_median
from golden_vector.lab.walk_forward import effective_n

__all__ = [
    "wilson_interval",
    "eb_shrink",
    "pooled_prior",
    "decay_weights",
    "decay_effective_n",
    "mann_kendall",
    "theil_sen",
    "benjamini_hochberg",
    "peer_percentile",
    "two_proportion_p",
    "mde_proportion_pp",
    "weighted_median",
]

# Standard-normal quantiles for the default two-sided alpha=0.05 / power=0.80 MDE.
_Z_ALPHA_TWO_SIDED_95 = 1.959963985
_Z_POWER_80 = 0.841621234


def wilson_interval(p: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion ``p`` on (effective) sample ``n``.

    Feed the EFFECTIVE sample size, never the raw weekly count — overlapping weekly
    labels are not independent. ``n <= 0`` returns the uninformative ``(0, 1)``.
    """

    if n <= 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


def eb_shrink(p_raw: float, eff_n: float, prior: float, strength: float) -> float:
    """Empirical-Bayes shrink of a rate toward ``prior`` with ``strength`` pseudo-counts.

    ``(p_raw*eff_n + prior*strength) / (eff_n + strength)`` — the exact rule the dial
    has always used, on EFFECTIVE n so a thin cell is pulled harder toward the prior.
    """

    denom = eff_n + strength
    if denom <= 0:
        return prior
    return (p_raw * eff_n + prior * strength) / denom


def pooled_prior(
    episodes: pd.DataFrame,
    *,
    group_col: str,
    value_col: str = "beat",
    ticker_col: str = "ticker",
    leave_out: str | None = None,
) -> dict[str, float]:
    """Per-``group_col`` prior = mean of PER-TICKER means (equal ticker weight).

    Equal ticker weight (not week-weighted) so a long-history miner can't dominate
    the prior. ``leave_out`` excludes one ticker from the pool (leave-one-out), so a
    stock is never partly shrunk toward itself — used by the windowed peer priors.
    """

    frame = episodes
    if leave_out is not None:
        frame = frame[frame[ticker_col] != leave_out]
    if frame.empty:
        return {}
    return (
        frame.groupby([group_col, ticker_col])[value_col]
        .mean()
        .groupby(group_col)
        .mean()
        .to_dict()
    )


def decay_weights(ages: Sequence[float], half_life: float) -> np.ndarray:
    """Exponential recency weights: ``0.5 ** (age / half_life)``.

    ``ages`` is generic — calendar years OR event-time rank back from the latest
    independent anchor (the engine uses event time so decay is paced by evidence,
    not by how long gold sat still). An age of one half-life weighs 0.5, two 0.25.
    """

    if half_life <= 0:
        raise ValueError("half_life must be positive.")
    return 0.5 ** (np.asarray(ages, dtype=float) / float(half_life))


def decay_effective_n(weights: Sequence[float], *, label_horizon_weeks: int) -> float:
    """Honest sample size for DECAY-WEIGHTED, OVERLAPPING weekly labels.

    Composes the two corrections that multiply: the Kish effective size for unequal
    weights ``(Σw)² / Σ(w²)`` AND the overlap deflation ``/ horizon`` (reusing
    ``walk_forward.effective_n``). Limit checks: uniform weights -> ``n / horizon``;
    ``horizon == 1`` -> the raw Kish size.
    """

    w = np.asarray(list(weights), dtype=float)
    w = w[np.isfinite(w)]
    denom = float((w**2).sum())
    if w.size == 0 or denom <= 0:
        return 0.0
    kish = float(w.sum() ** 2) / denom
    return effective_n(kish, label_horizon_weeks=label_horizon_weeks)


def mann_kendall(values: Sequence[float]) -> dict[str, float]:
    """Mann-Kendall monotone-trend test (continuity-corrected, tie-aware).

    Distribution-free; run it on the INDEPENDENT (non-overlap anchor) sample only —
    running it over overlapping weekly rows manufactures significance. Returns
    ``n, s, var_s, z, tau, p_value`` (two-sided normal approximation via ``erfc``).
    ``n < 3`` -> ``z = 0, p_value = 1`` (no call). ``tau`` is Kendall tau-a
    ``S / (n(n-1)/2)`` — a signed effect size in [-1, 1].
    """

    x = np.asarray(list(values), dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    result = {"n": float(n), "s": 0.0, "var_s": 0.0, "z": 0.0, "tau": 0.0, "p_value": 1.0}
    if n < 3:
        return result
    # S = sum over i<j of sign(x_j - x_i).
    diff = np.subtract.outer(x, x)  # diff[j, i] = x[j] - x[i]
    s = float(np.sign(diff[np.triu_indices(n, k=1)[::-1]]).sum())
    # Tie-corrected variance of S.
    _, counts = np.unique(x, return_counts=True)
    tie_term = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var_s <= 0:
        result["s"] = s
        return result
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    tau = s / (0.5 * n * (n - 1))
    p_value = math.erfc(abs(z) / math.sqrt(2.0))
    result.update({"s": s, "var_s": var_s, "z": z, "tau": tau, "p_value": p_value})
    return result


def theil_sen(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Theil-Sen robust slope: the median of all pairwise slopes ``Δy/Δx``.

    ~29% breakdown point, so it ignores the heavy alpha tail. Run on the independent
    anchor sample. Returns ``None`` if fewer than two points share distinct ``x``.
    """

    xa = np.asarray(list(x), dtype=float)
    ya = np.asarray(list(y), dtype=float)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    n = xa.size
    if n < 2:
        return None
    slopes: list[float] = []
    for i in range(n - 1):
        dx = xa[i + 1 :] - xa[i]
        dy = ya[i + 1 :] - ya[i]
        valid = dx != 0
        slopes.extend((dy[valid] / dx[valid]).tolist())
    if not slopes:
        return None
    return float(np.median(slopes))


def benjamini_hochberg(
    p_values: Sequence[float], q: float
) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg step-up FDR control at level ``q``.

    Returns ``(rejected, q_values)`` aligned to the input order. ``q_values`` are the
    monotone BH-adjusted p-values (clipped to [0, 1]); ``rejected = q_values <= q``.
    NaN inputs get ``q_value = 1`` and are never rejected.
    """

    p = np.asarray(list(p_values), dtype=float)
    n = p.size
    q_values = np.ones(n, dtype=float)
    rejected = np.zeros(n, dtype=bool)
    finite = np.isfinite(p)
    if not finite.any():
        return rejected, q_values
    idx = np.where(finite)[0]
    pv = p[idx]
    order = np.argsort(pv, kind="stable")
    ranked = pv[order]
    m = ranked.size
    raw = ranked * m / np.arange(1, m + 1)
    # Enforce monotonicity from the largest p downward, then clip.
    monotone = np.minimum.accumulate(raw[::-1])[::-1]
    monotone = np.clip(monotone, 0.0, 1.0)
    adjusted = np.empty(m, dtype=float)
    adjusted[order] = monotone
    q_values[idx] = adjusted
    rejected[idx] = adjusted <= q
    return rejected, q_values


def two_proportion_p(p1: float, n1: float, p2: float, n2: float) -> float:
    """Two-sided two-proportion z-test p-value (pooled SE), on EFFECTIVE sample sizes.

    Feed effective N (independent episode counts), never the raw weekly count. Returns
    1.0 (no evidence of a difference) when either side is empty or the pooled SE is zero.
    """

    if n1 <= 0 or n2 <= 0:
        return 1.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return 1.0
    z = (p1 - p2) / se
    return math.erfc(abs(z) / math.sqrt(2.0))


def mde_proportion_pp(
    n1: float,
    n2: float,
    *,
    p: float = 0.5,
    z_alpha: float = _Z_ALPHA_TWO_SIDED_95,
    z_power: float = _Z_POWER_80,
) -> float | None:
    """Minimum detectable difference between two proportions, in PERCENTAGE POINTS.

    The smallest recent-vs-older gap this cell could catch at the given power (default
    80%) and two-sided alpha (default 5%). Uses ``p=0.5`` (max variance => conservative)
    and the smaller (effective) side. ``None`` if either side is empty. This is the
    honesty number that lets the UI say "could only have caught a change bigger than X".
    """

    n = min(float(n1), float(n2))
    if n <= 0:
        return None
    return 100.0 * (z_alpha + z_power) * math.sqrt(2.0 * p * (1.0 - p) / n)


def peer_percentile(values: Sequence[float]) -> np.ndarray:
    """Cross-sectional percentile of each value within the pool: 100 = best (highest),
    0 = worst. Average ranks for ties. Pools of < 2 valid values -> all NaN (a single
    name has no peers to rank against). NaN inputs stay NaN.
    """

    series = pd.Series(np.asarray(list(values), dtype=float))
    valid = series.notna()
    n = int(valid.sum())
    out = np.full(series.size, np.nan, dtype=float)
    if n < 2:
        return out
    ranks = series.rank(method="average")  # 1..n ascending; highest value -> rank n
    out = (100.0 * (ranks - 1.0) / (n - 1.0)).to_numpy(dtype=float)
    return out
