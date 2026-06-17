"""Unit tests for the shared Lab statistics primitives (Phase 0 foundation)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from golden_vector.common.stats import weighted_median as core_weighted_median
from golden_vector.lab.statistics import (
    benjamini_hochberg,
    decay_effective_n,
    decay_weights,
    eb_shrink,
    mann_kendall,
    mde_proportion_pp,
    peer_percentile,
    pooled_prior,
    theil_sen,
    two_proportion_p,
    weighted_median,
    wilson_interval,
)
from golden_vector.model.structural import weighted_median as model_weighted_median


# --- wilson_interval -------------------------------------------------------

def test_wilson_interval_brackets_p_and_widens_with_small_n() -> None:
    low, high = wilson_interval(0.8, 20)
    assert 0.0 <= low < 0.8 < high <= 1.0
    low_small, high_small = wilson_interval(0.8, 4)
    assert (high_small - low_small) > (high - low)  # thinner evidence => wider band
    assert wilson_interval(0.5, 0) == (0.0, 1.0)  # no evidence => uninformative


# --- eb_shrink -------------------------------------------------------------

def test_eb_shrink_pulls_toward_prior_and_respects_weight() -> None:
    # Thin cell is pulled hard toward the prior; strong cell barely moves.
    thin = eb_shrink(1.0, eff_n=1.0, prior=0.5, strength=10.0)
    strong = eb_shrink(1.0, eff_n=100.0, prior=0.5, strength=10.0)
    # Thin evidence is pulled HARD toward the prior (close to 0.5); strong evidence
    # barely moves off its raw 1.0 (far from the prior).
    assert abs(thin - 0.5) < abs(strong - 0.5)
    assert math.isclose(eb_shrink(0.9, 10.0, 0.5, 10.0), (0.9 * 10 + 0.5 * 10) / 20)
    assert eb_shrink(0.9, 0.0, 0.5, 0.0) == 0.5  # degenerate -> prior, no divide-by-zero


# --- pooled_prior ----------------------------------------------------------

def test_pooled_prior_equal_ticker_weight_and_leave_one_out() -> None:
    # AAA has many rows (all beat), BBB few (none beat). Equal ticker weight => 0.5,
    # NOT week-weighted (which AAA would dominate).
    episodes = pd.DataFrame(
        {
            "bucket": ["d"] * 7,
            "ticker": ["AAA", "AAA", "AAA", "AAA", "AAA", "BBB", "BBB"],
            "beat": [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0],
        }
    )
    assert math.isclose(pooled_prior(episodes, group_col="bucket")["d"], 0.5)
    # Leave-one-out AAA -> only BBB remains -> 0.0.
    assert math.isclose(
        pooled_prior(episodes, group_col="bucket", leave_out="AAA")["d"], 0.0
    )


# --- decay_weights / decay_effective_n -------------------------------------

def test_decay_weights_halve_each_half_life() -> None:
    w = decay_weights([0.0, 3.0, 6.0], half_life=3.0)
    assert np.allclose(w, [1.0, 0.5, 0.25])


def test_decay_effective_n_limit_checks() -> None:
    # Uniform weights -> n / horizon (recovers the unweighted overlap rule).
    assert math.isclose(
        decay_effective_n([1.0] * 26, label_horizon_weeks=13), 2.0
    )
    # horizon == 1 -> raw Kish size (no overlap to deflate).
    assert math.isclose(decay_effective_n([1.0, 1.0, 1.0, 1.0], label_horizon_weeks=1), 4.0)
    # Concentrated weight -> small effective size.
    assert decay_effective_n([10.0, 0.1, 0.1], label_horizon_weeks=1) < 1.5
    assert decay_effective_n([], label_horizon_weeks=4) == 0.0


# --- mann_kendall ----------------------------------------------------------

def test_mann_kendall_detects_monotone_and_stays_silent_on_flat() -> None:
    up = mann_kendall(list(range(12)))
    assert up["z"] > 0 and up["p_value"] < 0.01 and up["tau"] > 0.9
    down = mann_kendall(list(range(12, 0, -1)))
    assert down["z"] < 0 and down["p_value"] < 0.01 and down["tau"] < -0.9
    flat = mann_kendall([0.5] * 12)
    assert flat["z"] == 0.0 and flat["p_value"] == 1.0
    assert mann_kendall([1.0, 2.0])["p_value"] == 1.0  # n < 3 => no call


def test_mann_kendall_user_case_90_to_10() -> None:
    # The motivating example: a hit rate that collapses from mostly-1 to mostly-0.
    anchors = [1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    result = mann_kendall(anchors)
    assert result["z"] < 0 and result["tau"] < 0 and result["p_value"] < 0.05


# --- theil_sen -------------------------------------------------------------

def test_theil_sen_exact_slope_and_outlier_resistance() -> None:
    x = [0, 1, 2, 3, 4]
    assert math.isclose(theil_sen(x, [2 * xi + 1 for xi in x]), 2.0)
    # One wild outlier shouldn't swing the median-of-slopes much.
    y = [1.0, 3.0, 5.0, 7.0, 500.0]
    assert theil_sen(x, y) < 50.0
    assert theil_sen([1.0], [1.0]) is None


# --- benjamini_hochberg ----------------------------------------------------

def test_benjamini_hochberg_monotone_and_controls() -> None:
    rejected, q = benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05], q=0.05)
    assert rejected.all() and np.all(q <= 0.0501)
    # One strong signal among noise: only the tiny p survives.
    rej2, q2 = benjamini_hochberg([0.001, 0.5, 0.6, 0.7, 0.8], q=0.05)
    assert rej2[0] and not rej2[1:].any()
    # q-values are monotone in p order.
    order = np.argsort([0.001, 0.5, 0.6, 0.7, 0.8])
    assert np.all(np.diff(q2[order]) >= -1e-12)
    # NaN never rejected.
    rej3, q3 = benjamini_hochberg([np.nan, 0.001], q=0.05)
    assert not rej3[0] and q3[0] == 1.0


# --- peer_percentile -------------------------------------------------------

def test_peer_percentile_best_worst_ties_and_singleton() -> None:
    pct = peer_percentile([10.0, 20.0, 30.0, 40.0])
    assert math.isclose(pct[0], 0.0) and math.isclose(pct[3], 100.0)
    ties = peer_percentile([10.0, 10.0, 20.0])
    assert math.isclose(ties[2], 100.0) and math.isclose(ties[0], ties[1])
    assert np.isnan(peer_percentile([5.0])).all()  # no peers
    assert np.isnan(peer_percentile([np.nan, 1.0])[0])


# --- weighted_median (shared core + both wrappers) -------------------------

def test_weighted_median_core_and_robustness() -> None:
    assert core_weighted_median([1, 2, 3, 4], [1, 1, 1, 1]) == 2.0
    # Robust to a huge outlier (lower weighted median).
    assert core_weighted_median([1, 2, 3, 4, 1000], [1, 1, 1, 1, 1]) == 3.0
    # Weight pulls the median.
    assert core_weighted_median([1, 2, 3], [1, 1, 10]) == 3.0
    assert core_weighted_median([], []) is None


def test_lab_and_model_weighted_median_share_one_implementation() -> None:
    # Lab re-export is the same object as the common core.
    assert weighted_median is core_weighted_median
    # Model dict-wrapper agrees with the array core and drops missing values.
    assert model_weighted_median(
        {"a": 1.0, "b": 2.0, "c": 3.0, "d": None}, weights={"a": 1, "b": 1, "c": 1}
    ) == 2.0
    assert model_weighted_median({}, weights={}) is None


# --- two_proportion_p / mde_proportion_pp ----------------------------------

def test_two_proportion_p_detects_difference_and_handles_equal() -> None:
    # A big gap on a decent sample is significant; identical rates are not.
    assert two_proportion_p(0.9, 30, 0.2, 30) < 0.001
    assert two_proportion_p(0.5, 20, 0.5, 20) == 1.0
    assert two_proportion_p(0.9, 0, 0.2, 30) == 1.0  # empty side -> no evidence
    # On a thin sample even a large gap is not significant.
    assert two_proportion_p(0.8, 3, 0.2, 3) > 0.05


def test_mde_proportion_pp_shrinks_with_n() -> None:
    big = mde_proportion_pp(6, 6)
    small = mde_proportion_pp(60, 60)
    assert big > small > 0  # thinner sample -> larger minimum detectable effect
    assert mde_proportion_pp(0, 10) is None
    # At ~6 effective per side only a very large gap is detectable.
    assert big > 50.0


def test_stats_edge_branches() -> None:
    # Partial ties hit the tie-corrected variance path (distinct from strictly monotone).
    mk = mann_kendall([1, 1, 2, 2, 3, 3, 3])
    assert mk["tau"] > 0 and mk["var_s"] > 0
    # decay_effective_n drops a non-finite weight (Kish over the finite ones; h=1 => no /h).
    assert math.isclose(decay_effective_n([1.0, float("nan"), 1.0, 1.0], label_horizon_weeks=1), 3.0)
    # two_proportion_p is symmetric under swapping the two groups.
    assert math.isclose(two_proportion_p(0.8, 12, 0.3, 10), two_proportion_p(0.3, 10, 0.8, 12))
    # Benjamini-Hochberg on an all-NaN family: nothing rejected, all q == 1.
    rejected, q_values = benjamini_hochberg([float("nan"), float("nan")], q=0.10)
    assert not rejected.any() and (q_values == 1.0).all()
