"""Phase 2 tests — point-in-time, benchmark-independent peer ranking."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.contracts.config_models import CaptureBehaviorConfig
from golden_vector.lab.behavior_engine import (
    BEHAVIOR_META_FILENAME,
    PEER_CAVEAT,
    PEER_COLUMNS,
    PEER_FILENAME,
    PEER_POINT_COLUMNS,
    PEER_POINTS_FILENAME,
    behavior_config_hash,
    build_and_save,
    compute_peer_points,
    compute_peer_snapshot,
)
from golden_vector.lab.conditional_dial import (
    DIAL_ARTIFACT_META_FILENAME,
    DIAL_EPISODES_FILENAME,
    DIAL_SCHEMA_VERSION,
)

_CFG = CaptureBehaviorConfig(min_peer_count=2, min_direction_effective_n=1.0)
_HASH = behavior_config_hash(_CFG, spine_schema_version=4)


def _peer_rows(week, bucket, returns, *, h=1, benchmark="GDX"):
    """One episode row per ticker for a single (week, bucket, horizon)."""
    tickers = list(returns)
    return pd.DataFrame(
        {
            "ticker": tickers,
            "horizon_weeks": [h] * len(tickers),
            "benchmark": [benchmark] * len(tickers),
            "gold_bucket": [bucket] * len(tickers),
            "week_period": [week] * len(tickers),
            "stock_fwd_simple": [returns[t] for t in tickers],
        }
    )


def _pt(points, ticker, week="W1"):
    sel = points[(points["ticker"] == ticker) & (points["week_period"] == week)]
    assert len(sel) == 1
    return sel.iloc[0]


# --- per-episode peer points ----------------------------------------------

def test_peer_percentile_best_worst_and_rank() -> None:
    eps = _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05, "C": -0.10})
    pts = compute_peer_points(eps, behavior_hash=_HASH)
    assert list(pts.columns) == PEER_POINT_COLUMNS
    assert math.isclose(_pt(pts, "A")["peer_percentile"], 100.0)  # least down = best
    assert math.isclose(_pt(pts, "C")["peer_percentile"], 0.0)  # most down = worst
    assert math.isclose(_pt(pts, "B")["peer_percentile"], 50.0)
    assert _pt(pts, "A")["peer_rank_1_best"] == 1.0 and _pt(pts, "C")["peer_rank_1_best"] == 3.0
    assert (pts["peer_count"] == 3).all() and (pts["point_status"] == "OK").all()


def test_peer_rank_is_point_in_time() -> None:
    # C is absent in W2 -> that week's pool is only {A, B}, not today's full universe.
    eps = pd.concat(
        [
            _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05, "C": -0.10}),
            _peer_rows("W2", "gold_down", {"A": -0.02, "B": -0.05}),
        ],
        ignore_index=True,
    )
    pts = compute_peer_points(eps, behavior_hash=_HASH)
    assert _pt(pts, "A", "W2")["peer_count"] == 2
    assert math.isclose(_pt(pts, "A", "W2")["peer_percentile"], 100.0)
    assert math.isclose(_pt(pts, "B", "W2")["peer_percentile"], 0.0)


def test_peer_rank_is_benchmark_independent() -> None:
    gdx = _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05, "C": -0.10}, benchmark="GDX")
    with_gdxj = pd.concat(
        [gdx, _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05, "C": -0.10}, benchmark="GDXJ")],
        ignore_index=True,
    )
    only = compute_peer_points(gdx, behavior_hash=_HASH)
    both = compute_peer_points(with_gdxj, behavior_hash=_HASH)
    # One ranked row per (ticker, week) — never two benchmark-scoped percentiles.
    assert len(both) == len(only) == 3
    assert _pt(both, "A")["peer_percentile"] == _pt(only, "A")["peer_percentile"]


def test_singleton_pool_has_no_percentile() -> None:
    eps = _peer_rows("W1", "gold_down", {"SOLO": -0.05})
    pts = compute_peer_points(eps, behavior_hash=_HASH)
    row = _pt(pts, "SOLO")
    assert row["peer_count"] == 1 and pd.isna(row["peer_percentile"])
    assert pd.isna(row["peer_rank_1_best"])  # no peer pool -> uniform abstain on BOTH columns
    assert row["point_status"] == "SINGLETON"


def test_flat_gold_excluded_from_peer_points() -> None:
    eps = pd.concat(
        [
            _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05}),
            _peer_rows("W1", "gold_flat", {"A": 0.5, "B": -0.5}),  # must be ignored
        ],
        ignore_index=True,
    )
    pts = compute_peer_points(eps, behavior_hash=_HASH)
    assert (pts["gold_bucket"] == "gold_down").all()


def test_raw_percentile_not_nulled_by_min_peer_count() -> None:
    # 3-ticker pool, but config min_peer_count=20: the RAW point keeps its percentile;
    # only the snapshot drops the under-pooled event.
    eps = _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05, "C": -0.10})
    pts = compute_peer_points(eps, behavior_hash=_HASH)
    assert not pd.isna(_pt(pts, "A")["peer_percentile"])
    strict = CaptureBehaviorConfig(min_peer_count=20, min_direction_effective_n=1.0)
    snap = compute_peer_snapshot(pts, behavior_hash=_HASH, config=strict)
    assert (snap["peer_status"] == "THIN_PEER_POOL").all()
    assert snap[snap["direction"] == "down"].iloc[0]["peer_event_n"] == 0


def test_missing_spine_column_fails_loud() -> None:
    eps = _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05}).drop(columns=["week_period"])
    with pytest.raises(ValueError) as exc:
        compute_peer_points(eps, behavior_hash=_HASH)
    assert "week_period" in str(exc.value)


# --- per-direction snapshot ------------------------------------------------

def _eight_weeks(ticker_best=True):
    frames = []
    for i in range(8):
        a = -0.01 if ticker_best else -0.20  # A best (or worst) each week
        frames.append(_peer_rows(f"W{i}", "gold_down", {"A": a, "B": -0.05, "C": -0.10}))
    return pd.concat(frames, ignore_index=True)


def test_snapshot_median_and_quartile_rates() -> None:
    pts = compute_peer_points(_eight_weeks(ticker_best=True), behavior_hash=_HASH)
    snap = compute_peer_snapshot(pts, behavior_hash=_HASH, config=_CFG)
    assert list(snap.columns) == PEER_COLUMNS
    row = snap[(snap["ticker"] == "A") & (snap["direction"] == "down")].iloc[0]
    assert row["peer_event_n"] == 8 and math.isclose(row["peer_effective_n"], 8.0)
    assert math.isclose(row["peer_percentile_median"], 100.0)  # best every week
    assert math.isclose(row["top_quartile_rate"], 1.0)
    assert math.isclose(row["bottom_quartile_rate"], 0.0)
    assert row["peer_status"] == "OK" and bool(row["survivor_universe"]) is True
    assert row["caveat"] == PEER_CAVEAT and "survivor" in row["caveat"]


def test_snapshot_direction_mapping() -> None:
    eps = pd.concat(
        [
            _peer_rows("W1", "gold_down_big", {"A": -0.02, "B": -0.05, "C": -0.10}),
            _peer_rows("W1", "gold_up_big", {"A": 0.30, "B": 0.10, "C": 0.05}),
        ],
        ignore_index=True,
    )
    snap = compute_peer_snapshot(compute_peer_points(eps, behavior_hash=_HASH), behavior_hash=_HASH, config=_CFG)
    assert set(snap["direction"]) == {"down", "up"}


def test_snapshot_thin_when_below_effective_floor() -> None:
    cfg = CaptureBehaviorConfig(min_peer_count=2, min_peer_effective_n=20.0)
    snap = compute_peer_snapshot(
        compute_peer_points(_eight_weeks(), behavior_hash=_HASH), behavior_hash=_HASH, config=cfg
    )
    row = snap[(snap["ticker"] == "A") & (snap["direction"] == "down")].iloc[0]
    # 8 events / h=1 = 8 effective < 20 floor -> flagged, but the numbers stay populated.
    assert row["peer_status"] == "THIN_PEER_POOL"
    assert row["peer_percentile_median"] is not None


# --- build_and_save persists the peer artifacts ----------------------------

class _FakePaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


def _multi_ticker_spine(lab: Path) -> None:
    # Full v4 spine with 3 peers sharing weeks (peer + capture + trend all read it).
    dates = pd.date_range("2010-01-01", periods=80, freq="W-FRI")
    frames = []
    for i, ticker in enumerate(("AAA", "BBB", "CCC")):
        for bucket, gold, stock0 in (("gold_down", -0.10, -0.05), ("gold_up", 0.10, 0.20)):
            stock = stock0 * (1 + i * 0.1)
            alpha_simple = stock - gold
            frames.append(
                pd.DataFrame(
                    {
                        "ticker": [ticker] * 80, "horizon_weeks": [13] * 80, "benchmark": ["GDX"] * 80,
                        "gold_bucket": [bucket] * 80,
                        "week_period": [str(p) for p in dates.to_period("W-FRI")],
                        "week_date": [d.date().isoformat() for d in dates],
                        "gold_fwd_simple": [gold] * 80, "stock_fwd_simple": [stock] * 80,
                        "alpha": [0.0] * 80, "alpha_simple": [alpha_simple] * 80,
                        "beat": [1.0 if alpha_simple > 0 else 0.0] * 80,
                        "is_nonoverlap_anchor": [True] * 80,
                    }
                )
            )
    pd.concat(frames, ignore_index=True).to_parquet(lab / DIAL_EPISODES_FILENAME, index=False)
    (lab / DIAL_ARTIFACT_META_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": DIAL_SCHEMA_VERSION,
                "config_hash": "test",
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "run_stamped_artifacts": {"episodes": DIAL_EPISODES_FILENAME},
            }
        ),
        encoding="utf-8",
    )


def test_build_and_save_writes_peer_artifacts_and_meta(tmp_path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir(parents=True)
    _multi_ticker_spine(lab)
    build_and_save(_FakePaths(tmp_path))

    points = pd.read_parquet(lab / PEER_POINTS_FILENAME)
    snap = pd.read_parquet(lab / PEER_FILENAME)
    meta = json.loads((lab / BEHAVIOR_META_FILENAME).read_text())
    assert not points.empty and not snap.empty
    assert list(points.columns) == PEER_POINT_COLUMNS
    assert list(snap.columns) == PEER_COLUMNS
    # latest aliases match the run-stamped artifacts.
    assert pd.read_parquet(lab / meta["run_stamped_artifacts"]["peer_points"]).equals(points)
    assert pd.read_parquet(lab / meta["run_stamped_artifacts"]["peer"]).equals(snap)
    assert meta["peer_points_rows"] == len(points) and meta["peer_rows"] == len(snap)
    assert "build_peer_seconds" in meta["stage_timings"]


# --- benchmark-independence (orphan), deflation, hash, boundaries -----------

def test_pool_includes_benchmark_orphan_ticker() -> None:
    # C appears ONLY on a GDXJ row; the union cross-section must still rank it (a
    # GDX-only filter would silently drop it and under-count peers).
    eps = pd.concat(
        [
            _peer_rows("W1", "gold_down", {"A": -0.02, "B": -0.05}, benchmark="GDX"),
            _peer_rows("W1", "gold_down", {"C": -0.10}, benchmark="GDXJ"),
        ],
        ignore_index=True,
    )
    pts = compute_peer_points(eps, behavior_hash=_HASH)
    assert set(pts["ticker"]) == {"A", "B", "C"}
    assert (pts["peer_count"] == 3).all()
    assert math.isclose(_pt(pts, "C")["peer_percentile"], 0.0)  # orphan ranked, worst
    assert math.isclose(_pt(pts, "A")["peer_percentile"], 100.0)


def test_snapshot_effective_n_deflates_by_horizon() -> None:
    # 26 weekly down-events at h=13 -> peer_effective_n = 2.0 (NOT raw 26).
    frames = [
        _peer_rows(f"W{i}", "gold_down", {"A": -0.01, "B": -0.05, "C": -0.10}, h=13)
        for i in range(26)
    ]
    pts = compute_peer_points(pd.concat(frames, ignore_index=True), behavior_hash=_HASH)
    snap = compute_peer_snapshot(pts, behavior_hash=_HASH, config=_CFG)
    row = snap[(snap["ticker"] == "A") & (snap["direction"] == "down")].iloc[0]
    assert row["peer_event_n"] == 26 and math.isclose(row["peer_effective_n"], 2.0)


def test_behavior_hash_is_stamped_on_peer_rows() -> None:
    pts = compute_peer_points(_eight_weeks(), behavior_hash=_HASH)
    snap = compute_peer_snapshot(pts, behavior_hash=_HASH, config=_CFG)
    assert (pts["behavior_config_hash"] == _HASH).all()
    assert (snap["behavior_config_hash"] == _HASH).all()


def test_snapshot_quartile_boundaries_and_na_exclusion() -> None:
    # Hand-built points: percentiles exactly on the 75/25 boundaries (inclusive), plus a
    # singleton event AND a count>=min-but-NaN event that must both be excluded.
    def _point(week, peer_count, pct, rank):
        return {
            "schema_version": 1, "behavior_config_hash": _HASH, "ticker": "Q",
            "horizon_weeks": 1, "gold_bucket": "gold_down", "week_period": week,
            "peer_count": peer_count, "peer_rank_1_best": rank,
            "peer_percentile": pct, "point_status": "OK" if peer_count >= 2 else "SINGLETON",
        }
    rows = [
        _point("W0", 5, 80.0, 1.0), _point("W1", 5, 75.0, 2.0), _point("W2", 5, 50.0, 3.0),
        _point("W3", 5, 25.0, 4.0), _point("W4", 5, 10.0, 5.0),
        _point("Wsingle", 1, float("nan"), pd.NA),  # under-pooled -> excluded
        _point("Wnan", 5, float("nan"), 1.0),  # count ok but NaN pct -> excluded by notna()
    ]
    points = pd.DataFrame(rows, columns=PEER_POINT_COLUMNS)
    snap = compute_peer_snapshot(points, behavior_hash=_HASH, config=_CFG)
    row = snap[snap["direction"] == "down"].iloc[0]
    assert row["peer_event_n"] == 5  # both bad events dropped
    assert math.isclose(row["peer_percentile_median"], 50.0)
    assert math.isclose(row["top_quartile_rate"], 0.4)  # 80 & 75 are >= 75
    assert math.isclose(row["bottom_quartile_rate"], 0.4)  # 25 & 10 are <= 25
