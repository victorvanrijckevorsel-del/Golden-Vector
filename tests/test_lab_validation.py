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


def _synthetic_panel_and_weekly(n_tickers=20, n_weeks=750, seed=5, panel_noise=0.1, windows=("6M", "12M", "3Y")):
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
            for w in windows:
                panel_rows.append(
                    {
                        "ticker": tk,
                        "as_of_date": str(periods[i].end_time.date()),
                        "window_id": w,
                        "window_status": "ELIGIBLE",
                        "structural_delta": beta + rng.normal(0, panel_noise),
                        "down_beta": beta + rng.normal(0, panel_noise),
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


# ------------------------------------------------- Codex-review hardening


def test_newey_west_hand_calculation():
    """Exact NW lag-1 t on a known 5-fold series (LOW-1: pin the convention)."""

    vals = [0.2, 0.1, 0.3, 0.2, 0.2]
    n = 5
    mean = np.mean(vals)
    r = np.array(vals) - mean
    g0 = np.sum(r**2) / n
    g1 = np.sum(r[1:] * r[:-1]) / n
    lrv = g0 + 2.0 * 0.5 * g1
    expected = mean / np.sqrt(lrv / n)
    assert v.newey_west_t(vals) == pytest.approx(expected)


def test_tercile_spread_deterministic_under_input_shuffle():
    """MED-1: ties on rank are broken by ticker, independent of input order."""

    ranks = pd.Series({f"T{i}": (i // 2) for i in range(12)})  # deliberate ties
    out = pd.Series({f"T{i}": float(i) for i in range(12)})
    base = v.tercile_portfolio_spread(ranks, out)
    shuffled_idx = list(ranks.index)[::-1]
    s2 = v.tercile_portfolio_spread(ranks.loc[shuffled_idx], out.loc[shuffled_idx])
    assert base == pytest.approx(s2)


def test_assert_publishable_refuses_contaminated_verdict():
    good = v.ExperimentVerdict(
        signal_id="x", claim="c", verdict="SUPPORTED", n_folds=10, mean_ic=0.3,
        nw_t=4.0, share_folds_directional=0.8, tercile_spread_mean=0.3,
        tercile_spread_t=3.0, median_ceiling=0.4, gate_results={},
    )
    v.assert_publishable([good])  # ok
    bad = v.ExperimentVerdict(
        signal_id="leak", claim="c", verdict="SUPPORTED", n_folds=10, mean_ic=1.0,
        nw_t=99.0, share_folds_directional=1.0, tercile_spread_mean=9.0,
        tercile_spread_t=9.0, median_ceiling=1.0, gate_results={}, contaminated=True,
    )
    with pytest.raises(ValueError, match="contaminated"):
        v.assert_publishable([good, bad])


def test_canary_time_reversal_contrast_proves_no_leak():
    """HIGH-3: a rank built from forward data must beat the honest PIT rank by
    >= 0.15 — if they are close, the honest path is leaking the future."""

    panel, weekly, wmap = _synthetic_panel_and_weekly(panel_noise=1.0, seed=11)
    grid = _test_grid(panel)
    honest, contaminated = v.time_reversal_ic_contrast(
        panel, weekly, grid, wmap, rank_column="structural_delta"
    )
    assert honest is not None and contaminated is not None
    # honest must be a moderate, non-leaking signal; contaminated is ~1.0.
    assert honest < 0.85
    assert contaminated - honest >= v.TIME_REVERSAL_MIN_CONTRAST
    assert contaminated > 0.95  # rank == future outcome


def test_baseline_line_fires_when_a_baseline_matches_the_core():
    """HIGH-2: when a baseline ranks as well as the core, the registered
    verbatim 'adds no measured edge' line must appear."""

    panel, weekly, wmap = _synthetic_panel_and_weekly(windows=("12M",))
    grid = _test_grid(panel)
    # Only 12M is eligible, so the weighted-median core EQUALS the 12M
    # single-window baseline exactly -> the core cannot beat it -> line fires.
    verdict, _ = v._validity_experiment(
        signal_id="t", claim="c", panel=panel, ticker_weekly=weekly, grid=grid,
        weight_map=wmap, rank_column="structural_delta",
        baselines=[
            v.BaselineSpec(
                label="single_12m_window",
                beaten_line="ADDS NO MEASURED EDGE",
                kind="single_window", window="12M",
            )
        ],
    )
    assert "ADDS NO MEASURED EDGE" in verdict.baseline_lines


def test_build_as_of_grid_step_param_changes_cadence():
    """MED-4: the 52-period grid must actually use the step param and yield a
    coarser cadence than the 26-period grid (exercises the real function)."""

    from golden_vector.app.paths import ProjectPaths

    paths = ProjectPaths.discover()
    if not paths.latest_tool_a_structural_metrics_path.exists():
        pytest.skip("no structural panel")
    panel = v._panel_with_periods(pd.read_parquet(paths.latest_tool_a_structural_metrics_path))
    g26 = v.build_as_of_grid(panel, step=26)
    g52 = v.build_as_of_grid(panel, step=52)
    assert len(g52) < len(g26)
    # consecutive 52-grid folds are ~52 periods apart
    if len(g52) >= 2:
        assert (g52[1] - g52[0]).n >= 40


def test_fixed_cohort_is_a_subset():
    panel, weekly, wmap = _synthetic_panel_and_weekly()
    cohort = v.fixed_cohort_panel(panel, before="2030-01-01")  # synthetic is 2012+
    assert cohort["ticker"].nunique() == panel["ticker"].nunique()
    empty = v.fixed_cohort_panel(panel, before="2000-01-01")  # before any data
    assert empty.empty


def test_lab_dial_corrupt_vs_missing_status(tmp_path):
    """MED-3: a corrupt artifact reports CORRUPT, a missing one MISSING."""

    from golden_vector.serve.lab_data import load_lab_dial_data

    class FakePaths:
        data_dir = tmp_path

    missing = load_lab_dial_data(FakePaths())  # type: ignore[arg-type]
    assert not missing.available and missing.error_status == "MISSING"
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "dial_table_13w_latest.parquet").write_text("not parquet", encoding="utf-8")
    corrupt = load_lab_dial_data(FakePaths())  # type: ignore[arg-type]
    assert not corrupt.available and corrupt.error_status == "CORRUPT"


def test_reconstruction_parity_against_live_artifact():
    """HIGH-1: PIT reconstruction at the latest period must reproduce the
    shipped tool_a_latest core columns exactly (the no-forked-math contract)."""

    import glob

    from golden_vector.app.config import load_app_config
    from golden_vector.app.paths import ProjectPaths

    paths = ProjectPaths.discover()
    panel_files = sorted(
        glob.glob(str(paths.data_dir / "intermediate" / "tool_a_structural" / "*latest*.parquet"))
    )
    if not panel_files or not paths.latest_tool_a_snapshot_parquet_path.exists():
        pytest.skip("no local structural panel / tool_a artifact")
    panel = v._panel_with_periods(pd.read_parquet(panel_files[0]))
    tool_a = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)
    if "structural_delta_core" not in tool_a.columns:
        pytest.skip("tool_a artifact lacks core columns")
    wmap = load_app_config(paths).app.scoring.structural_weight_map()

    period = pd.Period(str(pd.to_datetime(tool_a["as_of_date"]).max()), freq="W-FRI")
    recon = v.reconstruct_cores_at(panel, period, column="structural_delta", weight_map=wmap)
    live = tool_a.set_index("ticker")["structural_delta_core"].dropna()
    common = recon.index.intersection(live.index)
    assert len(common) >= 40
    for tk in common:
        assert recon[tk] == pytest.approx(float(live[tk]), abs=1e-6), tk


def test_ledger_constants_match_registered_gates():
    """MED-3: implementation gate constants must equal the registered ledger
    configs — the guardrail against post-hoc drift."""

    from golden_vector.app.paths import ProjectPaths
    from golden_vector.lab.ledger import load_ledger
    from golden_vector.lab.vintages import lab_dir

    records = load_ledger(lab_dir(ProjectPaths.discover()))
    by_id = {}
    for r in records:
        by_id[r.signal_id] = r.config  # last wins = latest registration
    if "validation_e3b" not in by_id:
        pytest.skip("validation variants not registered in this environment")
    e1a, e1b, e2 = by_id["validation_e1a"], by_id["validation_e1b"], by_id["validation_e2"]
    g1a, g1b, g2 = e1a["gates"], e1b["gates"], e2["gates"]
    assert g1a["mean_ic_min"] == v.E1A_MEAN_IC_GATE
    assert g1a["share_folds_ge_030"] == v.E1A_SHARE_GATE
    assert g1b["tercile_portfolio_spread_min"] == v.E1B_SPREAD_GATE
    assert g1b["mean_ic_gt0_nw_t"] == v.NW_T_GATE
    assert g1b["share_folds_pos"] == v.SHARE_DIRECTIONAL_GATE
    assert g1b["spread_t"] == v.SPREAD_T_GATE
    assert g2["tercile_portfolio_spread_min"] == v.E2_SPREAD_GATE
    # E3/E3b: orientation + gates pinned against the registry
    e3, e3b = by_id["validation_e3"], by_id["validation_e3b"]
    assert "< 0" in e3["direction"]  # downside score pinned NEGATIVE (most fragile)
    assert e3["gates"]["neg_mean_ic_nw_t"] == v.NW_T_GATE
    assert e3["gates"]["share_folds_neg"] == v.SHARE_DIRECTIONAL_GATE
    assert e3["gates"]["spread_neg_t"] == v.SPREAD_T_GATE
    assert "down_beta_core" in e3["baselines_paired_t2"][0]
    assert e3b["gates"]["mean_ic_nw_t"] == v.NW_T_GATE
    assert e3b["gates"]["share_folds"] == v.SHARE_DIRECTIONAL_GATE


# --------------------------------------------- E3/E3b (Tool C reconstruction)


def test_tool_c_reconstruction_parity_against_live_artifact():
    """E3 spec parity test: PIT Tool C reconstruction at the latest period must
    reproduce the shipped tool_c_latest downside AND upside scores exactly."""

    from golden_vector.app.paths import ProjectPaths

    paths = ProjectPaths.discover()
    if not paths.latest_tool_c_snapshot_parquet_path.exists():
        pytest.skip("no local tool_c artifact")
    live = pd.read_parquet(paths.latest_tool_c_snapshot_parquet_path)
    if "tool_c_downside_score" not in live.columns:
        pytest.skip("tool_c artifact lacks score columns")
    period = pd.Period(str(pd.to_datetime(live["as_of_date"]).max()), freq="W-FRI")
    ctx = v.build_tool_c_recon_context(paths)
    recon = v.reconstruct_tool_c_scores_at(period, ctx).set_index("ticker")
    livei = live.set_index("ticker")
    common = recon.index.intersection(livei.index)
    assert len(common) >= 40
    for col in ("tool_c_downside_score", "tool_c_upside_score"):
        r = pd.to_numeric(recon[col], errors="coerce").reindex(common)
        ll = pd.to_numeric(livei[col], errors="coerce").reindex(common)
        both = r.notna() & ll.notna()
        assert both.sum() >= 40
        assert float((r[both] - ll[both]).abs().max()) < 1e-6


def test_forward_capture_sign_canary():
    """E3 sign-convention canary: a synthetic always-RESILIENT ticker (beats GDX
    on every gold-down week) must produce a POSITIVE down-capture, and an
    always-fragile one a NEGATIVE one — pinning the orientation end to end."""

    periods = pd.period_range("2015-01-09", periods=60, freq="W-FRI")
    gold = np.where(np.arange(60) % 3 == 0, -0.03, 0.01)  # plenty of down weeks

    def frame(stock_minus_gdx):
        return v._ticker_weekly(
            pd.DataFrame(
                {
                    "ticker": "X",
                    "week_period": [str(p) for p in periods],
                    "stock_log_ret": 0.001 + stock_minus_gdx,
                    "gold_log_ret": gold,
                    "gdx_log_ret": 0.001,
                    "gdxj_log_ret": 0.001,
                }
            )
        )["X"]

    t = pd.Period(str(periods[5]), freq="W-FRI")
    resilient = v.forward_capture_vs_gdx(frame(0.01), t, gold_down_only=True)
    fragile = v.forward_capture_vs_gdx(frame(-0.01), t, gold_down_only=True)
    assert resilient is not None and resilient > 0
    assert fragile is not None and fragile < 0


def test_e3_orientation_negative_direction_stored_positive_when_working():
    """A perfectly fragile ranking (high score = worst down-capture) must yield
    a POSITIVE directed IC for E3 (direction=-1), confirming the orientation
    plumbing: a working tool reports positive, not negative."""

    # raw negative correlation (high rank -> low outcome) with direction=-1
    ranks = pd.Series({f"T{i}": float(i) for i in range(15)})
    outcome = pd.Series({f"T{i}": float(-i) for i in range(15)})
    raw = v.spearman_ic(ranks, outcome)
    assert raw == pytest.approx(-1.0)
    assert (-1) * raw == pytest.approx(1.0)  # stored direction
