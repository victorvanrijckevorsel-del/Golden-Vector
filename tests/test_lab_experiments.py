"""Conditional Dial analog table + beta-gap experiment machinery."""

from __future__ import annotations

import numpy as np
import pandas as pd

from golden_vector.lab.beta_gap import (
    apply_james_stein,
    build_beta_panel,
    run_experiment,
)
from golden_vector.lab.conditional_dial import (
    DEFAULT_BUCKETS,
    _assign_bucket,
    _wilson_interval,
    build_dial_table,
)


def _grid(n: int) -> list[str]:
    return [str(p) for p in pd.period_range("2010-01-08", periods=n, freq="W-FRI")]


# ---------------------------------------------------------------- dial


def _dial_weekly_frame() -> pd.DataFrame:
    """200 weeks; gold alternates down/up regimes; WIN always beats GDX,
    LOSE always trails, by construction."""

    n = 200
    grid = _grid(n)
    gold = np.where(np.arange(n) % 26 < 13, -0.012, 0.012)  # 13w down, 13w up
    rows = []
    for ticker, edge in (("WIN", 0.004), ("LOSE", -0.004)):
        for i in range(n):
            rows.append(
                {
                    "ticker": ticker,
                    "week_period": grid[i],
                    "stock_log_ret": 0.001 + edge,
                    "gold_log_ret": gold[i],
                    "gdx_log_ret": 0.001,
                    "gdxj_log_ret": 0.001,
                }
            )
    return pd.DataFrame(rows)


def test_dial_table_counts_deterministic_outcomes() -> None:
    table = build_dial_table(_dial_weekly_frame(), horizon_weeks=13, min_effective_n=2.0)
    assert not table.empty
    win_rows = table[(table["ticker"] == "WIN") & (~table["insufficient_history"])]
    lose_rows = table[(table["ticker"] == "LOSE") & (~table["insufficient_history"])]
    assert not win_rows.empty and not lose_rows.empty
    assert (win_rows["p_beat_gdx"] == 1.0).all()
    assert (lose_rows["p_beat_gdx"] == 0.0).all()
    # EB shrinkage pulls toward the pooled rate (0.5 here), never past raw.
    assert (win_rows["p_beat_gdx_shrunk"] < 1.0).all()
    assert (win_rows["p_beat_gdx_shrunk"] > 0.5).all()
    # Wilson bounds bracket the raw rate.
    assert (win_rows["wilson_low"] <= win_rows["p_beat_gdx"]).all()
    assert (win_rows["wilson_high"] >= win_rows["p_beat_gdx"]).all()
    assert (win_rows["median_alpha"] > 0).all()


def test_dial_table_insufficient_history_carries_no_numbers() -> None:
    table = build_dial_table(_dial_weekly_frame(), horizon_weeks=13, min_effective_n=999.0)
    assert not table.empty
    assert table["insufficient_history"].all()
    for column in ("p_beat_gdx", "median_alpha", "wilson_low", "alpha_q90"):
        assert table[column].isna().all()
    # Raw + effective N still shown so the user sees WHY the cell is blank.
    assert (table["n_weeks"] > 0).all()


def test_bucket_assignment_edges() -> None:
    assert _assign_bucket(-0.20, DEFAULT_BUCKETS) == "gold_down_big"
    assert _assign_bucket(-0.15, DEFAULT_BUCKETS) == "gold_down"
    assert _assign_bucket(0.0, DEFAULT_BUCKETS) == "gold_flat"
    assert _assign_bucket(0.05, DEFAULT_BUCKETS) == "gold_up"
    assert _assign_bucket(0.40, DEFAULT_BUCKETS) == "gold_up_big"


def test_wilson_interval_sane() -> None:
    low, high = _wilson_interval(0.8, 20)
    assert 0.0 <= low < 0.8 < high <= 1.0
    low_small, high_small = _wilson_interval(0.8, 4)
    assert high_small - low_small > high - low  # less data, wider interval


# ------------------------------------------------------------ beta gap


def _beta_weekly_frame(beta_first: float, beta_second: float, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    gold = rng.normal(0.002, 0.02, n)
    betas = np.where(np.arange(n) < n // 2, beta_first, beta_second)
    stock = betas * gold + rng.normal(0, 0.001, n)
    return pd.DataFrame(
        {
            "ticker": "AEM",
            "week_period": _grid(n),
            "stock_log_ret": stock,
            "gold_log_ret": gold,
            "gdx_log_ret": 0.0,
            "gdxj_log_ret": 0.0,
        }
    )


def test_beta_panel_recovers_constant_beta() -> None:
    panel = build_beta_panel(_beta_weekly_frame(2.0, 2.0))
    settled = panel.dropna(subset=["fast_beta", "slow_beta", "forward_beta"])
    assert not settled.empty
    assert settled["fast_beta"].sub(2.0).abs().mean() < 0.1
    assert settled["slow_beta"].sub(2.0).abs().mean() < 0.05
    assert settled["forward_beta"].sub(2.0).abs().mean() < 0.05


def test_fast_beta_adapts_faster_than_slow_after_regime_change() -> None:
    panel = build_beta_panel(_beta_weekly_frame(1.0, 3.0))
    # 30 weeks after the break, fast should be much closer to 3 than slow.
    after_break = panel.iloc[230:240].dropna(subset=["fast_beta", "slow_beta"])
    assert not after_break.empty
    assert (after_break["fast_beta"] - 3.0).abs().mean() < (
        after_break["slow_beta"] - 3.0
    ).abs().mean()


def test_james_stein_limits() -> None:
    grid = _grid(1)
    base = pd.DataFrame(
        {
            "ticker": [f"T{i}" for i in range(10)],
            "week_period": grid * 10,
            "fast_beta": np.linspace(1.0, 3.0, 10),
            "slow_beta": 2.0,
            "forward_beta": 2.0,
        }
    )
    zero_se = base.assign(fast_beta_se=0.0)
    out = apply_james_stein(zero_se)
    assert np.allclose(out["beta_nowcast"], out["fast_beta"])  # no shrink
    huge_se = base.assign(fast_beta_se=100.0)
    out = apply_james_stein(huge_se)
    assert np.allclose(out["beta_nowcast"], out["slow_beta"])  # full shrink


def test_run_experiment_passes_on_rigged_skillful_nowcast() -> None:
    """Structure check: a nowcast almost exactly equal to the label, with
    both baselines far off, must clear every gate."""

    n, tickers = 500, 8
    rng = np.random.default_rng(9)
    rows = []
    for t_index, period in enumerate(_grid(n)):
        for i in range(tickers):
            truth = 2.0 + 0.3 * np.sin(t_index / 17) + 0.05 * i
            rows.append(
                {
                    "ticker": f"T{i}",
                    "week_period": period,
                    "beta_nowcast": truth + rng.normal(0, 0.01),
                    "slow_beta": truth + 0.8 + rng.normal(0, 0.05),
                    "fast_beta": truth - 0.7 + rng.normal(0, 0.05),
                    "forward_beta": truth,
                }
            )
    verdict = run_experiment(pd.DataFrame(rows))
    assert verdict.n_folds >= 3
    assert verdict.passed, verdict.reasons
    assert verdict.win_rate_vs_slow == 1.0 and verdict.win_rate_vs_fast == 1.0


def test_run_experiment_fails_on_no_skill() -> None:
    """A nowcast identical to the slow baseline cannot pass — and the verdict
    must say so rather than erroring."""

    n, tickers = 300, 8
    rng = np.random.default_rng(10)
    rows = []
    for t_index, period in enumerate(_grid(n)):
        for i in range(tickers):
            truth = 2.0 + 0.05 * i
            slow = truth + rng.normal(0, 0.3)
            rows.append(
                {
                    "ticker": f"T{i}",
                    "week_period": period,
                    "beta_nowcast": slow,
                    "slow_beta": slow,
                    "fast_beta": truth + rng.normal(0, 0.3),
                    "forward_beta": truth,
                }
            )
    verdict = run_experiment(pd.DataFrame(rows))
    assert not verdict.passed
    assert any(reason.startswith("FAIL") for reason in verdict.reasons)


def test_rank_in_bucket_ties_na_and_insufficient_ordering() -> None:
    """The ONE rank column the /lab page sorts on: deliberate tie broken by
    ticker, insufficient-history rows rank last, ranks dense 1..N."""

    grid = _grid(200)
    gold = np.where(np.arange(200) % 26 < 13, -0.012, 0.012)
    rows = []
    # TWIN_A / TWIN_B: identical returns -> exact tie on p_beat_gdx_shrunk.
    # WEAK: clearly worse. SPARSE: too few weeks -> insufficient history.
    for ticker, edge, n in (
        ("TWIN_A", 0.004, 200),
        ("TWIN_B", 0.004, 200),
        ("WEAK", -0.004, 200),
        ("SPARSE", 0.004, 40),
    ):
        for i in range(n):
            rows.append(
                {
                    "ticker": ticker,
                    "week_period": grid[i],
                    "stock_log_ret": 0.001 + edge,
                    "gold_log_ret": gold[i],
                    "gdx_log_ret": 0.001,
                    "gdxj_log_ret": 0.001,
                }
            )
    table = build_dial_table(
        pd.DataFrame(rows), horizon_weeks=13, min_effective_n=4.0
    )
    down = table[table["bucket"] == "gold_down"].sort_values("rank_in_bucket")
    order = list(down["ticker"])
    # Tie broken alphabetically; weak after the twins; sparse (insufficient) last.
    assert order.index("TWIN_A") < order.index("TWIN_B")
    assert order.index("TWIN_B") < order.index("WEAK")
    assert order[-1] == "SPARSE"
    assert bool(down.iloc[-1]["insufficient_history"])
    measured = down[~down["insufficient_history"]]
    assert list(measured["rank_in_bucket"]) == list(range(1, len(measured) + 1))
    # Degraded cells carry NA rank (house rule), never a displayable number.
    assert down[down["insufficient_history"]]["rank_in_bucket"].isna().all()


def test_config_sentinel_structural_invariants() -> None:
    """Literal-minimum sentinels: most tests derive expectations from the
    same config the code reads, so a catastrophic config edit reshapes both
    sides in lockstep. These literals do not."""

    from golden_vector.app.config import load_app_config
    from golden_vector.app.paths import ProjectPaths

    loaded = load_app_config(ProjectPaths.discover())
    app = loaded.app
    active = [t for t in app.universe.tickers if getattr(t, "active", True)]
    assert len(active) >= 30  # literal floor, not derived
    hedge = app.hedge_readiness
    assert len(hedge.target_horizons_days) >= 2
    assert sorted(hedge.target_horizons_days) == list(hedge.target_horizons_days)
    assert hedge.option_signal_horizon_days in hedge.target_horizons_days
