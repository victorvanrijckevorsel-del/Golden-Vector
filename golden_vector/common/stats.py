"""Shared statistical primitives used across layers (common = lowest layer).

ONE copy of the weighted median: the model layer (``model/structural.py`` beta
aggregation, dict-keyed) and the Lab layer (``lab/statistics.py`` decay-weighted
alpha median, array-keyed) both delegate here so the algorithm can never fork.

Pure numpy/math — no scipy/statsmodels dependency.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None:
    """Lower weighted median: the smallest value whose cumulative weight reaches
    half of the total weight.

    Matches the long-standing behaviour of the model's beta aggregator: sort by
    value ascending, walk cumulative weight, return the first value at which the
    running weight is ``>=`` half the total. Non-finite values (and their weights)
    are dropped. Returns ``None`` when nothing usable remains.
    """

    v = np.asarray(list(values), dtype=float)
    w = np.asarray(list(weights), dtype=float)
    if v.size == 0 or v.size != w.size:
        return None
    mask = np.isfinite(v) & np.isfinite(w)
    v, w = v[mask], w[mask]
    if v.size == 0:
        return None
    order = np.argsort(v, kind="stable")
    v, w = v[order], w[order]
    cumulative = np.cumsum(w)
    total = float(cumulative[-1])
    cutoff = total / 2.0
    # First index where cumulative weight >= cutoff (== the old running>=cutoff loop).
    idx = int(np.searchsorted(cumulative, cutoff, side="left"))
    idx = min(idx, v.size - 1)
    return float(v[idx])
