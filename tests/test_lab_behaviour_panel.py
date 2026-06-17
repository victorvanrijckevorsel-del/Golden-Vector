"""Phase 4 — the /lab/dial Behaviour panel: renderer (render-only) + loader selection."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from golden_vector.lab.behavior_engine import (
    BEHAVIOR_META_FILENAME,
    CAPTURE_COLUMNS,
    CAPTURE_FILENAME,
    PEER_COLUMNS,
    PEER_FILENAME,
    TREND_COLUMNS,
    TREND_FILENAME,
    behavior_config_hash,
    default_capture_behavior_config,
)
from golden_vector.lab.conditional_dial import DIAL_SCHEMA_VERSION
from golden_vector.serve.lab_curve_data import (
    DIAL_ARTIFACT_META_FILENAME,
    LabCurveData,
    _load_behaviour,
)
from golden_vector.serve.lab_curve_page import _render_behaviour


# --- renderer (pure) -------------------------------------------------------

def _curve(**kw) -> LabCurveData:
    base = dict(
        available=True, ticker="AEM", benchmark="GDX", horizon=8,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%",
        behavior_status=None, capture_horizon=13,
    )
    base.update(kw)
    return LabCurveData(**base)


def test_panel_renders_capture_peer_trend_with_correct_placement() -> None:
    curve = _curve(
        capture={
            "archetype": "CONVEX", "archetype_all_rows": "CONVEX",
            "archetype_confidence": "confirmed", "capture_status": "OK",
            "down_capture_mean": 0.5, "up_capture_mean": 2.0, "convexity": 1.5,
        },
        peer_down={
            "direction": "down", "peer_status": "OK", "peer_percentile_median": 70.0,
            "top_quartile_rate": 0.4, "peer_event_n": 80, "peer_effective_n": 6.2,
        },
        peer_up={
            "direction": "up", "peer_status": "OK", "peer_percentile_median": 55.0,
            "top_quartile_rate": 0.2, "peer_event_n": 390, "peer_effective_n": 30.0,
        },
        behavior_trend={
            "trend_status": "OK", "trend_label": "DETERIORATING",
            "recent_p_beat_raw": 0.2, "older_p_beat_raw": 0.8, "mde_80pct_pp": 40.0,
            "alpha_trend_label": "ALPHA_DETERIORATING",
        },
    )
    html = _render_behaviour(curve)
    assert "<strong>CONVEX</strong>" in html
    # POSITIONAL: down-capture is the FALL, up-capture is the RISE (a swap must fail)
    assert "<strong>0.50×</strong> of gold's <em>fall</em>" in html
    assert "<strong>2.00×</strong> of its <em>rise</em>" in html
    assert "convexity <strong>+1.50</strong>" in html  # signed gap, no '×'
    # POSITIONAL peers: 70% on the "fell" line, 55% on the "rose" line
    assert "When gold fell: typically better than <strong>70%</strong>" in html
    assert "When gold rose: typically better than <strong>55%</strong>" in html
    assert "independent episodes" in html  # effective N, not the raw event count
    assert "DETERIORATING" in html and "ALPHA_DETERIORATING" in html
    assert "13-week" in html and "not a forecast" in html


def test_panel_nan_archetype_never_renders_as_confirmed() -> None:
    # Regression for the Parquet None->float-nan round-trip: a null archetype must NOT
    # render as a bold "nan" box; it falls to the not-confirmed / not-enough-history branch.
    curve = _curve(
        capture={
            "archetype": float("nan"), "archetype_all_rows": float("nan"),
            "archetype_confidence": float("nan"), "capture_status": "THIN_DOWN",
            "down_capture_mean": 0.61, "up_capture_mean": 1.45, "convexity": 0.84,
        },
    )
    html = _render_behaviour(curve)
    assert "<strong>nan</strong>" not in html
    assert "not enough independent history" in html  # honest abstain branch
    assert "too thin or invalid" in html  # THIN status surfaced as a caveat


def test_panel_unconfirmed_archetype_shows_raw_label_flagged() -> None:
    curve = _curve(
        capture={
            "archetype": None, "archetype_all_rows": "TORQUE",
            "archetype_confidence": "unconfirmed_disagrees", "capture_status": "OK",
            "down_capture_mean": 2.5, "up_capture_mean": 2.6, "convexity": 0.1,
        },
    )
    html = _render_behaviour(curve)
    assert "TORQUE" in html and "not confirmed" in html


def test_panel_degrades_for_missing_stale_corrupt() -> None:
    miss = _render_behaviour(LabCurveData(available=True, ticker="AEM", behavior_status="MISSING"))
    assert "behavior_engine" in miss  # rebuild command for MISSING
    for status in ("STALE", "CORRUPT"):
        html = _render_behaviour(LabCurveData(available=True, ticker="AEM", behavior_status=status))
        assert "Behaviour" in html and "ebuild" in html  # distinct rebuild message, no crash


def test_panel_thin_peer_and_insufficient_trend() -> None:
    curve = _curve(
        capture=None,
        peer_down={"direction": "down", "peer_status": "THIN_PEER_POOL"},
        peer_up=None,
        behavior_trend={"trend_status": "THIN_RECENT"},
    )
    html = _render_behaviour(curve)
    assert "too few independent episodes" in html and "honest default" in html


# --- loader (selection + staleness) ----------------------------------------

class _FakePaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


def _row(columns, **vals) -> pd.DataFrame:
    base = {c: None for c in columns}
    base.update(vals)
    return pd.DataFrame([base])


def _write_behaviour(
    lab: Path, *, behavior_hash: str, source_episodes: str | None = None
) -> None:
    lab.mkdir(parents=True, exist_ok=True)
    # capture at horizon 13 (the default), plus an 8w row that must NOT be picked for the box
    cap = pd.concat(
        [
            _row(CAPTURE_COLUMNS, ticker="AEM", horizon_weeks=13, archetype="CONVEX",
                 archetype_all_rows="CONVEX", capture_status="OK",
                 down_capture_mean=0.5, up_capture_mean=2.0, convexity=1.5),
            _row(CAPTURE_COLUMNS, ticker="AEM", horizon_weeks=8, archetype="HEDGE",
                 archetype_all_rows="HEDGE", capture_status="OK"),
        ],
        ignore_index=True,
    )
    cap.to_parquet(lab / CAPTURE_FILENAME, index=False)
    # peer rows at BOTH 8w and 13w — peer follows the PAGE look-ahead, so the values differ
    # per horizon to prove the selection picks the page horizon.
    peer = pd.concat(
        [
            _row(PEER_COLUMNS, ticker="AEM", horizon_weeks=8, direction="down",
                 peer_status="OK", peer_percentile_median=70.0, peer_effective_n=6.2),
            _row(PEER_COLUMNS, ticker="AEM", horizon_weeks=8, direction="up",
                 peer_status="OK", peer_percentile_median=55.0, peer_effective_n=30.0),
            _row(PEER_COLUMNS, ticker="AEM", horizon_weeks=13, direction="down",
                 peer_status="OK", peer_percentile_median=41.0, peer_effective_n=9.0),
            _row(PEER_COLUMNS, ticker="AEM", horizon_weeks=13, direction="up",
                 peer_status="OK", peer_percentile_median=46.0, peer_effective_n=40.0),
        ],
        ignore_index=True,
    )
    peer.to_parquet(lab / PEER_FILENAME, index=False)
    # trend rows at BOTH 8w (the locked default) and 13w with DIFFERENT labels — the loader
    # must pin the trend card to 8w regardless of the page horizon.
    trend = pd.concat(
        [
            _row(TREND_COLUMNS, ticker="AEM", horizon_weeks=8, benchmark="GDX",
                 gold_bucket="gold_down", trend_status="OK", trend_label="DETERIORATING",
                 alpha_trend_label="ALPHA_DETERIORATING"),
            _row(TREND_COLUMNS, ticker="AEM", horizon_weeks=13, benchmark="GDX",
                 gold_bucket="gold_down", trend_status="OK", trend_label="IMPROVING",
                 alpha_trend_label="ALPHA_IMPROVING"),
        ],
        ignore_index=True,
    )
    trend.to_parquet(lab / TREND_FILENAME, index=False)
    meta = {
        "schema_version": 1,
        "behavior_config_hash": behavior_hash,
        "spine_schema_version": DIAL_SCHEMA_VERSION,
    }
    if source_episodes is not None:
        meta["source_spine"] = {"episodes_artifact": source_episodes}
    (lab / BEHAVIOR_META_FILENAME).write_text(json.dumps(meta), encoding="utf-8")


def _write_dial_meta(lab: Path, *, episodes: str) -> None:
    """Minimal live dial_meta.json so the loader can cross-check the behaviour source-spine."""
    lab.mkdir(parents=True, exist_ok=True)
    (lab / DIAL_ARTIFACT_META_FILENAME).write_text(
        json.dumps({"run_stamped_artifacts": {"episodes": episodes}}), encoding="utf-8"
    )


def _live_hash() -> str:
    return behavior_config_hash(
        default_capture_behavior_config(), spine_schema_version=DIAL_SCHEMA_VERSION
    )


def test_loader_selects_capture_at_default_horizon_peer_trend_at_page_horizon(tmp_path) -> None:
    lab = tmp_path / "lab"
    _write_behaviour(lab, behavior_hash=_live_hash())
    out = _load_behaviour(
        _FakePaths(tmp_path), ticker="AEM", horizon=8, benchmark="GDX", scenario_bucket="gold_down"
    )
    assert out["behavior_status"] is None
    assert out["capture_horizon"] == 13
    assert out["capture"]["archetype"] == "CONVEX"  # the 13w row, NOT the 8w HEDGE row
    assert out["peer_down"]["peer_percentile_median"] == 70.0
    assert out["peer_up"]["peer_percentile_median"] == 55.0
    assert out["behavior_trend"]["trend_label"] == "DETERIORATING"


def test_loader_stale_hash_fails_closed(tmp_path) -> None:
    lab = tmp_path / "lab"
    _write_behaviour(lab, behavior_hash="not-the-live-hash")
    out = _load_behaviour(
        _FakePaths(tmp_path), ticker="AEM", horizon=8, benchmark="GDX", scenario_bucket="gold_down"
    )
    assert out["behavior_status"] == "STALE"  # mismatched hash -> degrade, never serve stale


def test_loader_missing_meta(tmp_path) -> None:
    (tmp_path / "lab").mkdir(parents=True)
    out = _load_behaviour(
        _FakePaths(tmp_path), ticker="AEM", horizon=8, benchmark="GDX", scenario_bucket="gold_down"
    )
    assert out["behavior_status"] == "MISSING"


def test_loader_corrupt_frame_under_valid_meta_degrades(tmp_path) -> None:
    lab = tmp_path / "lab"
    _write_behaviour(lab, behavior_hash=_live_hash())
    (lab / CAPTURE_FILENAME).write_text("not a parquet", encoding="utf-8")  # corrupt one frame
    out = _load_behaviour(
        _FakePaths(tmp_path), ticker="AEM", horizon=8, benchmark="GDX", scenario_bucket="gold_down"
    )
    # An artifact-level failure must read as CORRUPT (rebuild), NOT as a "no history" gap.
    assert out["behavior_status"] == "CORRUPT"


def test_loader_pins_trend_to_default_horizon_independent_of_page(tmp_path) -> None:
    lab = tmp_path / "lab"
    _write_behaviour(lab, behavior_hash=_live_hash())
    # Page look-ahead is 13w, but the trend card is LOCKED to the 8w default.
    out = _load_behaviour(
        _FakePaths(tmp_path), ticker="AEM", horizon=13, benchmark="GDX", scenario_bucket="gold_down"
    )
    assert out["behavior_status"] is None
    assert out["trend_horizon"] == 8
    # trend is the 8w DETERIORATING row, NOT the 13w IMPROVING row at the page horizon
    assert out["behavior_trend"]["trend_label"] == "DETERIORATING"
    assert out["behavior_trend"]["horizon_weeks"] == 8
    # peer DOES follow the page look-ahead (13w), proving the two are decoupled
    assert out["peer_down"]["peer_percentile_median"] == 41.0
    assert out["peer_up"]["peer_percentile_median"] == 46.0


def test_loader_source_spine_mismatch_fails_closed(tmp_path) -> None:
    lab = tmp_path / "lab"
    # Behaviour built from an OLD spine run; the dial has since been rebuilt (NEW episodes).
    _write_behaviour(lab, behavior_hash=_live_hash(), source_episodes="dial_episodes_OLD.parquet")
    _write_dial_meta(lab, episodes="dial_episodes_NEW.parquet")
    out = _load_behaviour(
        _FakePaths(tmp_path), ticker="AEM", horizon=8, benchmark="GDX", scenario_bucket="gold_down"
    )
    # Config hash is current, but the spine moved underneath — must degrade, never serve stale.
    assert out["behavior_status"] == "STALE"


def test_loader_source_spine_match_serves(tmp_path) -> None:
    lab = tmp_path / "lab"
    _write_behaviour(lab, behavior_hash=_live_hash(), source_episodes="dial_episodes_SAME.parquet")
    _write_dial_meta(lab, episodes="dial_episodes_SAME.parquet")
    out = _load_behaviour(
        _FakePaths(tmp_path), ticker="AEM", horizon=8, benchmark="GDX", scenario_bucket="gold_down"
    )
    # Spine pointers agree -> the panel serves normally (the cross-check is not over-strict).
    assert out["behavior_status"] is None
    assert out["capture"]["archetype"] == "CONVEX"
