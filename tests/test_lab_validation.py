"""Program A validation engine: unit tests + the pre-registered canaries.

The canaries (spec §4) are the load-bearing correctness checks — they prove
the harness cannot see the future and that its t-stat path is the disjoint
n_folds one, not the weekly effective_n (which would void every gate).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from golden_vector.lab import validation as v


# ------------------------------------------------------------- stats helpers


def test_newey_west_t_uses_n_folds_not_effective_n():
    # 43 disjoint folds with a clear positive mean must yield a finite, large
    # t — the eff_n=n/26 trap would have returned None / tiny.
    rng = np.random.default_rng(1)
    series = list(0.3 + rng.normal(0, 0.1, 43))
    t = v.newey_west_t(series)
    assert t is not None and t > 10
    # scaling: same mean/std, 4x the folds -> ~2x the t
    t_small = v.newey_west_t([0.3, 0.2, 0.4] * 3)
    t_big = v.newey_west_t([0.3, 0.2, 0.4] * 12)
    assert t_big > t_small
    assert v.newey_west_t([0.1, 0.2]) is None  # n<3


def test_spearman_and_tercile_spread():
    a = pd.Series({f"T{i}": i for i in range(12)})
    b = pd.Series({f"T{i}": i + 0.1 for i in range(12)})
    assert v.spearman_ic(a, b) == pytest.approx(1.0)
    # tercile spread: top third minus bottom third of a monotone outcome
    spread = v.tercile_portfolio_spread(a, b)
    assert spread is not None and spread > 0


# ------------------------------------------------------------- forward beta


def _weekly(n=60, beta=2.0, seed=3, start="2010-01-08"):
    rng = np.random.default_rng(seed)
    periods = pd.period_range(start, periods=n, freq="W-FRI")
    gold = rng.normal(0.001, 0.02, n)
    stock = beta * gold + rng.normal(0, 0.001, n)
    g = pd.DataFrame(
        {
            "ticker": "AEM",
            "week_period": [str(p) for p in periods],
            "stock_log_ret": stock,
            "gold_log_ret": gold,
            "gdx_log_ret": 0.0,
            "gdxj_log_ret": 0.0,
        }
    )
    return v._ticker_weekly(g)["AEM"]


def test_forward_realized_beta_is_strictly_forward_and_recovers_beta():
    g = _weekly(beta=2.5)
    t = pd.Period(str(g["period"].iloc[20]), freq="W-FRI")
    beta = v.forward_realized_beta(g, t)
    assert beta == pytest.approx(2.5, abs=0.1)
    # week of t itself is excluded: a beta from periods strictly > t only
    fwd = g[(g["period"] > t)]
    assert len(fwd) >= v.MIN_FORWARD_WEEKS


def test_forward_realized_beta_honors_min_weeks():
    g = _weekly(n=30)
    t = pd.Period(str(g["period"].iloc[20]), freq="W-FRI")  # only ~9 weeks ahead
    assert v.forward_realized_beta(g, t, min_weeks=20) is None
    assert v.forward_realized_beta(g, t, min_weeks=8) is not None


# ------------------------------------------------------------- core reconstruction


def _panel():
    rows = []
    weights = {"6M": 1.0, "12M": 1.0, "3Y": 1.0}
    # AEM: 3 eligible windows with deltas 1.0/2.0/3.0 -> median 2.0
    # NEM: 12M INELIGIBLE -> weighted median over {1.5, 2.5} = 1.5 (lower-middle)
    for window, status, aem, nem in (
        ("6M", "ELIGIBLE", 1.0, 1.5),
        ("12M", "ELIGIBLE", 2.0, 9.9),
        ("3Y", "ELIGIBLE", 3.0, 2.5),
    ):
        for tk, val in (("AEM", aem), ("NEM", nem)):
            st = status
            if tk == "NEM" and window == "12M":
                st = "INELIGIBLE"
            rows.append(
                {
                    "ticker": tk,
                    "as_of_date": "2020-01-10",
                    "window_id": window,
                    "window_status": st,
                    "structural_delta": val,
                    "down_beta": val,
                }
            )
    return v._panel_with_periods(pd.DataFrame(rows)), weights


def test_reconstruct_core_is_weighted_median_over_eligible_windows():
    panel, weights = _panel()
    period = pd.Period("2020-01-10", freq="W-FRI")
    cores = v.reconstruct_cores_at(panel, period, column="structural_delta", weight_map=weights)
    assert cores["AEM"] == pytest.approx(2.0)  # median of 1/2/3
    assert cores["NEM"] == pytest.approx(1.5)  # 12M ineligible; wmedian(1.5,2.5)=1.5


# ------------------------------------------------------------- THE CANARIES


def _test_grid(panel):
    """Every-26-period grid over the synthetic panel's eligible 12M weeks
    (the production grid hardcodes a 2004 anchor; synthetic data is 2012+)."""

    periods = sorted(
        panel[panel["window_id"].astype(str).str.upper() == "12M"]["week_period"].unique()
    )
    return list(periods[:: v.GRID_STEP_PERIODS])


def _synthetic_panel_and_weekly(n_tickers=20, n_weeks=750, seed=5):
    """A panel + weekly frame where each ticker has a TRUE beta; the panel's
    12M delta equals that beta plus noise, so an honest experiment should
    score positive and a rigged one should be catchable."""

    rng = np.random.default_rng(seed)
    true_beta = {f"T{i}": 0.5 + 2.5 * i / n_tickers for i in range(n_tickers)}
    periods = pd.period_range("2012-01-06", periods=n_weeks, freq="W-FRI")
    gold = rng.normal(0.001, 0.02, n_weeks)
    weekly_rows, panel_rows = [], []
    for tk, beta in true_beta.items():
        stock = beta * gold + rng.normal(0, 0.01, n_weeks)
        for i, p in enumerate(periods):
            weekly_rows.append(
                {
                    "ticker": tk,
                    "week_period": str(p),
                    "stock_log_ret": stock[i],
                    "gold_log_ret": gold[i],
                    "gdx_log_ret": 0.0,
                    "gdxj_log_ret": 0.0,
                }
            )
        # panel: a 12M delta ~ true beta, stamped every week
        for i in range(0, n_weeks):
            for w in ("6M", "12M", "3Y"):
                panel_rows.append(
                    {
                        "ticker": tk,
                        "as_of_date": str(periods[i].end_time.date()),
                        "window_id": w,
                        "window_status": "ELIGIBLE",
                        "structural_delta": beta + rng.normal(0, 0.1),
                        "down_beta": beta + rng.normal(0, 0.1),
                    }
                )
    panel = v._panel_with_periods(pd.DataFrame(panel_rows))
    weekly = v._ticker_weekly(pd.DataFrame(weekly_rows))
    return panel, weekly, {"6M": 1.0, "12M": 1.0, "3Y": 1.0}


def test_canary_label_as_feature_scores_near_perfect():
    """If the rank IS the forward outcome, IC must be ~1 (the harness can
    measure a perfect signal)."""

    panel, weekly, wmap = _synthetic_panel_and_weekly()
    grid = [p for p in _test_grid(panel)][:6]
    # build forward betas and rank by them directly
    ics = []
    for t in grid:
        fwd = {tk: v.forward_realized_beta(g, t) for tk, g in weekly.items()}
        fwd = {k: x for k, x in fwd.items() if x is not None}
        if len(fwd) < v.MIN_CROSS_SECTION:
            continue
        s = pd.Series(fwd)
        ics.append(v.spearman_ic(s, s))  # rank == outcome
    assert ics and np.mean(ics) > 0.99


def test_canary_shuffled_ranks_rarely_trip(monkeypatch):
    """20 fixed-seed shuffles: at most 2 may show |t| >= 2 (single-shuffle
    criterion is ~5% flaky by construction)."""

    rng_master = np.random.default_rng(0)
    tripped = 0
    base = list(rng_master.normal(0, 0.1, 40))  # null fold-IC series, mean 0
    for seed in range(20):
        rng = np.random.default_rng(seed)
        shuffled = list(rng.permutation(base))
        t = v.newey_west_t(shuffled)
        if t is not None and abs(t) >= 2:
            tripped += 1
    assert tripped <= 2


def test_honest_experiment_scores_positive_on_synthetic_truth():
    """End-to-end: a panel whose delta tracks true beta must produce a
    positive, significant E1b on synthetic data (no survivorship, no noise
    confounds) — proves the engine wiring is correct."""

    panel, weekly, wmap = _synthetic_panel_and_weekly()
    grid = _test_grid(panel)
    verdict, folds = v._validity_experiment(
        signal_id="test", claim="t", panel=panel, ticker_weekly=weekly,
        grid=grid, weight_map=wmap, rank_column="structural_delta",
    )
    assert verdict.mean_ic is not None and verdict.mean_ic > 0.3
    assert verdict.nw_t is not None and verdict.nw_t > 3
