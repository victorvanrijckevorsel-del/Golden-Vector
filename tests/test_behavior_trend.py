"""Phase 3 tests — the behaviour-change (trend) layer: beat + alpha, event-time."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.contracts.config_models import CaptureBehaviorConfig
from golden_vector.lab.behavior_engine import (
    BEHAVIOR_META_FILENAME,
    DIAL_EPISODES_FILENAME,
    TREND_COLUMNS,
    TREND_FILENAME,
    _beat_label,
    behavior_config_hash,
    build_and_save,
    compute_trend_table,
)
from golden_vector.lab.statistics import mde_proportion_pp


def _cell(ticker, bucket, beats, alphas=None, *, benchmark="GDX", h=1, anchor=True):
    """One synthetic cell: time-ordered episodes (oldest first) at horizon h."""
    n = len(beats)
    dates = pd.date_range("2015-01-02", periods=n, freq="W-FRI")
    if alphas is None:
        alphas = [0.05 if b else -0.05 for b in beats]
    return pd.DataFrame(
        {
            "ticker": [ticker] * n, "benchmark": [benchmark] * n, "horizon_weeks": [h] * n,
            "gold_bucket": [bucket] * n,
            "week_period": [str(p) for p in dates.to_period("W-FRI")],
            "week_date": [d.date().isoformat() for d in dates],
            "beat": [float(b) for b in beats], "alpha_simple": [float(a) for a in alphas],
            "is_nonoverlap_anchor": [anchor] * n,
        }
    )


def _trend(eps, *, config=None, benchmarks=("GDX",), horizons=(1,)):
    cfg = config or CaptureBehaviorConfig()
    chash = behavior_config_hash(cfg, spine_schema_version=4)
    table = compute_trend_table(
        eps, horizons=list(horizons), benchmarks=list(benchmarks), config=cfg, behavior_hash=chash
    )
    assert list(table.columns) == TREND_COLUMNS
    return table


def _row(table, ticker="FLIP"):
    sel = table[table["ticker"] == ticker]
    assert len(sel) == 1
    return sel.iloc[0]


# --- beat trend label ------------------------------------------------------

def test_clear_deterioration_labels_deteriorating() -> None:
    # Older anchors mostly beat, recent anchors mostly lag -> DETERIORATING (alone in its
    # scenario, so the FDR family is m=1 and the huge swing survives).
    eps = _cell("FLIP", "gold_down", [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0])
    row = _row(_trend(eps))
    assert row["trend_status"] == "OK"
    assert row["recent_p_beat_raw"] == 0.0 and row["older_p_beat_raw"] == 1.0
    assert row["trend_delta"] < -0.2 and row["trend_tau"] < 0
    assert row["trend_label"] == "DETERIORATING"


def test_clear_improvement_labels_improving() -> None:
    eps = _cell("FLIP", "gold_up", [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
    row = _row(_trend(eps))
    assert row["trend_delta"] > 0.2 and row["trend_tau"] > 0
    assert row["trend_label"] == "IMPROVING"


def test_flat_cell_is_stable() -> None:
    eps = _cell("FLIP", "gold_down", [1] * 12)
    row = _row(_trend(eps))
    assert row["trend_status"] == "OK" and row["trend_label"] == "NO_CHANGE_DETECTED"


def test_thin_recent_window_is_insufficient() -> None:
    # 8 anchors -> recent = round(8*0.5) = 4 < min_recent (6) -> THIN_RECENT, abstain.
    eps = _cell("FLIP", "gold_down", [1, 1, 1, 1, 0, 0, 0, 0])
    row = _row(_trend(eps))
    assert row["trend_status"] == "THIN_RECENT"
    assert row["trend_label"] == "INSUFFICIENT_EVIDENCE"


def test_event_time_split_counts() -> None:
    eps = _cell("FLIP", "gold_down", [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0])  # 14
    row = _row(_trend(eps))
    assert row["n_anchors"] == 14
    assert row["recent_anchor_n"] == 7 and row["older_anchor_n"] == 7


# --- alpha (size) trend, the leading indicator -----------------------------

def test_alpha_trend_deteriorates_while_beat_is_flat() -> None:
    # Beats all 1 (still winning) but the WIN SIZE shrinks monotonically -> the alpha
    # trend catches deterioration the beat rate can't.
    alphas = [0.30, 0.25, 0.20, 0.15, 0.10, 0.05, 0.0, -0.05, -0.10, -0.15, -0.20, -0.25]
    eps = _cell("FLIP", "gold_down", [1] * 12, alphas=alphas)
    row = _row(_trend(eps))
    assert row["trend_label"] == "NO_CHANGE_DETECTED"  # beat rate flat
    assert row["alpha_slope_per_year"] < 0
    assert row["alpha_trend_label"] == "ALPHA_DETERIORATING"


# --- window-matched peer shrinkage (research §2) ---------------------------

def test_recent_shrinks_to_peers_not_own_past() -> None:
    # FLIP flips 1->0; the peers beat ~ALWAYS (peer recent mean ~1.0). The recent window
    # shrinks toward the PEER mean, landing ABOVE 0.5 — an own-past prior (FLIP's own 0.5
    # all-history) could ONLY pull recent below 0.5. So this discriminates peer-shrinkage
    # from own-past-shrinkage, and the divergence still survives (DETERIORATING).
    cfg = CaptureBehaviorConfig(recent_prior_min_pool_tickers=2.0)
    peers = pd.concat(
        [_cell(t, "gold_down", [1] * 12) for t in ("P1", "P2", "P3")], ignore_index=True
    )
    eps = pd.concat([_cell("FLIP", "gold_down", [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]), peers], ignore_index=True)
    row = _row(_trend(eps, config=cfg))
    assert row["recent_prior_source"] == "cross_sectional"
    assert row["recent_p_beat_shrunk"] > 0.5  # pulled toward peers (~1.0), NOT own-past (0.5)
    assert row["trend_label"] == "DETERIORATING"  # divergence survives


def test_single_ticker_uses_neutral_prior_fallback() -> None:
    eps = _cell("FLIP", "gold_down", [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0])
    row = _row(_trend(eps))
    assert row["recent_prior_source"] == "neutral_0.5"  # no peers -> neutral


def test_missing_spine_column_fails_loud() -> None:
    eps = _cell("FLIP", "gold_down", [1, 0] * 6).drop(columns=["week_date"])
    with pytest.raises(ValueError) as exc:
        compute_trend_table(eps, horizons=[1], benchmarks=["GDX"], config=CaptureBehaviorConfig(), behavior_hash="h")
    assert "week_date" in str(exc.value)


# --- build_and_save persists the trend artifact ----------------------------

class _FakePaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


def test_build_and_save_writes_trend_artifact_and_meta(tmp_path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir(parents=True)
    # Full v4 spine at the default capture horizon (13) so build_and_save runs.
    dates = pd.date_range("2010-01-01", periods=80, freq="W-FRI")
    frames = []
    for bucket, gold, stock in (("gold_down", -0.10, -0.05), ("gold_up", 0.10, 0.25)):
        a = stock - gold
        frames.append(
            pd.DataFrame(
                {
                    "ticker": ["BIG"] * 80, "horizon_weeks": [13] * 80, "benchmark": ["GDX"] * 80,
                    "gold_bucket": [bucket] * 80,
                    "week_period": [str(p) for p in dates.to_period("W-FRI")],
                    "week_date": [d.date().isoformat() for d in dates],
                    "gold_fwd_simple": [gold] * 80, "stock_fwd_simple": [stock] * 80,
                    "alpha": [0.0] * 80, "alpha_simple": [a] * 80,
                    "beat": [1.0 if a > 0 else 0.0] * 80, "is_nonoverlap_anchor": [True] * 80,
                }
            )
        )
    pd.concat(frames, ignore_index=True).to_parquet(lab / DIAL_EPISODES_FILENAME, index=False)

    build_and_save(_FakePaths(tmp_path))
    trend = pd.read_parquet(lab / TREND_FILENAME)
    meta = json.loads((lab / BEHAVIOR_META_FILENAME).read_text())
    assert not trend.empty and list(trend.columns) == TREND_COLUMNS
    assert pd.read_parquet(lab / meta["run_stamped_artifacts"]["trend"]).equals(trend)
    assert meta["trend_rows"] == len(trend)
    assert "build_trend_seconds" in meta["stage_timings"]
    assert (trend["behavior_config_hash"] == meta["behavior_config_hash"]).all()


# --- FDR multiplicity gate (the load-bearing honesty control) --------------

def test_fdr_suppresses_borderline_movers_in_a_family() -> None:
    # One huge mover + 30 borderline movers in ONE scenario family. BH-FDR lets the huge
    # one through but suppresses the borderline ones to STABLE despite raw p <= 0.05 and a
    # large delta — the multiplicity gate working.
    frames = [_cell("MOVER", "gold_down", [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0])]
    # A few borderline movers (recent [1,1,1,0,0,0] vs older all-1 => raw p ~ 0.0455)...
    for i in range(4):
        frames.append(_cell(f"B{i:02d}", "gold_down", [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0]))
    # ...amid many flat cells that inflate the family size m so BH lifts the borderline q.
    for i in range(26):
        frames.append(_cell(f"F{i:02d}", "gold_down", [1] * 12))
    table = _trend(pd.concat(frames, ignore_index=True))
    mover = table[table["ticker"] == "MOVER"].iloc[0]
    assert mover["trend_q_value"] <= 0.10 and mover["trend_label"] == "DETERIORATING"
    borderline = table[table["ticker"].str.startswith("B")]
    suppressed = borderline[
        (borderline["trend_p_value"] <= 0.05) & (borderline["trend_q_value"] > 0.10)
    ]
    assert len(suppressed) >= 1  # raw-significant but FDR-corrected away...
    assert (suppressed["trend_label"] == "NO_CHANGE_DETECTED").all()  # ...so NOT labelled a mover


# --- joint gate: MK sign agreement -----------------------------------------

def test_beat_label_requires_mk_sign_agreement() -> None:
    cfg = CaptureBehaviorConfig()
    assert _beat_label(delta=0.30, tau=0.5, q_value=0.01, config=cfg) == "IMPROVING"
    assert _beat_label(delta=-0.30, tau=-0.5, q_value=0.01, config=cfg) == "DETERIORATING"
    assert _beat_label(delta=0.30, tau=-0.5, q_value=0.01, config=cfg) == "NO_CHANGE_DETECTED"  # signs disagree
    assert _beat_label(delta=0.30, tau=0.0, q_value=0.01, config=cfg) == "NO_CHANGE_DETECTED"  # tau == 0
    assert _beat_label(delta=0.30, tau=0.5, q_value=0.50, config=cfg) == "NO_CHANGE_DETECTED"  # q > q_fdr
    assert _beat_label(delta=0.10, tau=0.5, q_value=0.01, config=cfg) == "NO_CHANGE_DETECTED"  # |delta| < thr


# --- anchors-only windows + horizon deflation ------------------------------

def test_windows_use_anchors_only_and_deflate_by_horizon() -> None:
    n = 32
    dates = pd.date_range("2012-01-06", periods=n, freq="W-FRI")
    beats = [1] * 8 + [0] * 8 + [1] * 16  # first 16 are anchors; last 16 non-anchor 1s
    anchor = [True] * 16 + [False] * 16
    eps = pd.DataFrame(
        {
            "ticker": ["AZ"] * n, "benchmark": ["GDX"] * n, "horizon_weeks": [4] * n,
            "gold_bucket": ["gold_down"] * n,
            "week_period": [str(p) for p in dates.to_period("W-FRI")],
            "week_date": [d.date().isoformat() for d in dates],
            "beat": [float(b) for b in beats],
            "alpha_simple": [0.05 if b else -0.05 for b in beats],
            "is_nonoverlap_anchor": anchor,
        }
    )
    row = _row(_trend(eps, horizons=(4,)), "AZ")
    assert row["n_anchors"] == 16 and row["all_n_rows"] == 32
    assert math.isclose(row["all_effective_n"], 8.0)  # 32 rows / horizon 4
    # windows ignore the non-anchor rows: recent = last 8 anchors (all 0), not the 1s
    assert row["recent_p_beat_raw"] == 0.0 and row["older_p_beat_raw"] == 1.0


def test_nan_anchor_beat_is_dropped_not_inflating() -> None:
    eps = _cell("FLIP", "gold_down", [1, 1, 1, 1, 1, 1, float("nan"), 0, 0, 0, 0, 0, 0])
    row = _row(_trend(eps))
    assert row["n_anchors"] == 12  # the NaN anchor is dropped, never inflating the count
    assert row["recent_p_beat_raw"] == 0.0 and row["older_p_beat_raw"] == 1.0
    assert row["trend_delta"] is not None and row["trend_label"] == "DETERIORATING"


# --- decay / alpha / mde column wiring --------------------------------------

def test_decay_weights_recent_heaviest() -> None:
    flip = _row(_trend(_cell("D", "gold_down", [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0])), "D")
    assert flip["decay_p_beat_raw"] < flip["all_p_beat_raw"]  # newest (0s) weigh most
    assert flip["decay_effective_n"] is not None and flip["decay_effective_n"] > 0
    flat = _row(_trend(_cell("F", "gold_down", [1] * 12)), "F")
    assert math.isclose(flat["decay_p_beat_raw"], flat["all_p_beat_raw"])


def test_alpha_trend_improving_stable_insufficient() -> None:
    rising = [-0.25, -0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    imp = _row(_trend(_cell("UP", "gold_down", [1] * 12, alphas=rising)), "UP")
    assert imp["alpha_slope_per_year"] > 0 and imp["alpha_trend_label"] == "ALPHA_IMPROVING"
    stab = _row(_trend(_cell("ST", "gold_down", [1] * 12, alphas=[0.05] * 12)), "ST")
    assert stab["alpha_trend_label"] == "ALPHA_NO_CHANGE"
    thin = _row(_trend(_cell("TH", "gold_down", [1, 0, 1, 0, 1, 0])), "TH")  # na=6 < min_anchors
    assert thin["alpha_trend_label"] == "INSUFFICIENT"


def test_alpha_label_not_blanked_by_thin_beat_window() -> None:
    # 10 anchors: recent beat window (5) is below the beat floor (THIN_RECENT), but the
    # alpha trend over all 10 anchors must still be evaluated on its OWN power.
    falling = [0.30, 0.24, 0.18, 0.12, 0.06, 0.0, -0.06, -0.12, -0.18, -0.24]
    cfg = CaptureBehaviorConfig(min_anchors=8)
    row = _row(_trend(_cell("LEAD", "gold_down", [1] * 10, alphas=falling), config=cfg), "LEAD")
    assert row["trend_status"] == "THIN_RECENT"  # beat window thin
    assert row["alpha_trend_label"] == "ALPHA_DETERIORATING"  # alpha still leads


def test_mde_uses_per_side_anchor_counts() -> None:
    row = _row(_trend(_cell("M", "gold_down", [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0])), "M")
    expected = round(mde_proportion_pp(row["recent_anchor_n"], row["older_anchor_n"]), 2)
    assert math.isclose(row["mde_80pct_pp"], expected)


# --- FDR family scope stamping + alpha FDR ---------------------------------

def test_config_rejects_bad_domains() -> None:
    import pydantic

    for kwargs in (
        {"trend_window_basis": "calendar"},  # only event_time implemented
        {"min_recent_effective_n": -1.0},
        {"eb_prior_strength": -10.0},
        {"trend_delta_threshold": -0.2},
        {"decay_half_life_episodes": 0.0},  # zero half-life would crash decay_weights later
        {"recent_prior_min_pool_tickers": 0.0},
    ):
        with pytest.raises(pydantic.ValidationError):
            CaptureBehaviorConfig(**kwargs)


def test_fdr_scope_and_family_size_are_stamped() -> None:
    eps = pd.concat(
        [
            _cell("A", "gold_down", [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]),
            _cell("B", "gold_down", [1] * 12),
        ],
        ignore_index=True,
    )
    rows = _trend(eps)
    ok = rows[rows["trend_status"] == "OK"]
    assert (ok["trend_fdr_scope"] == "benchmark+horizon+gold_bucket").all()
    assert (ok["trend_fdr_family_size"] == 2).all()  # the scenario-local family size


def test_alpha_trend_is_fdr_corrected_and_stats_persisted() -> None:
    # A strong alpha mover amid flat-alpha cells: the mover survives BH (label set, q/tau/z
    # persisted); flat-alpha peers are not movers. Proves alpha is now FDR-gated, not raw.
    falling = [0.30, 0.25, 0.20, 0.15, 0.10, 0.05, 0.0, -0.05, -0.10, -0.15, -0.20, -0.25]
    frames = [_cell("MOVER", "gold_down", [1] * 12, alphas=falling)]
    for i in range(20):
        frames.append(_cell(f"F{i:02d}", "gold_down", [1] * 12, alphas=[0.05] * 12))
    table = _trend(pd.concat(frames, ignore_index=True))
    mover = table[table["ticker"] == "MOVER"].iloc[0]
    assert mover["alpha_trend_label"] == "ALPHA_DETERIORATING"
    assert mover["alpha_trend_q_value"] is not None and mover["alpha_trend_tau"] < 0
    flats = table[table["ticker"].str.startswith("F")]
    assert (flats["alpha_trend_label"] == "ALPHA_NO_CHANGE").all()
