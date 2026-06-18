"""Phase 1 tests — the symmetric Capture & Behaviour engine (gold frame)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.contracts.config_models import CaptureBehaviorConfig
from golden_vector.lab.behavior_engine import (
    BEHAVIOR_META_FILENAME,
    CAPTURE_CAVEAT,
    CAPTURE_COLUMNS,
    CAPTURE_FILENAME,
    _warn_cutoff_drift,
    behavior_config_hash,
    build_and_save,
    build_capture,
    capture_distribution,
    compute_capture_table,
)
from golden_vector.lab.conditional_dial import (
    DIAL_ARTIFACT_META_FILENAME,
    DIAL_EPISODES_FILENAME,
    DIAL_SCHEMA_VERSION,
)

# Cutoffs + floors chosen so the synthetic ratios below classify unambiguously.
# default_capture_horizon=1 so the synthetic h=1 cells receive an archetype (archetypes
# are only emitted at the default capture horizon).
_CFG = CaptureBehaviorConfig(
    hedge_down_capture_max=1.0,
    torque_up_capture_min=1.5,
    min_direction_effective_n=1.0,
    min_anchor_episodes=6,
    default_capture_horizon=1,
)


def _rows(ticker, bucket, gold, stock, *, n, anchor=True, benchmark="GDX", h=1):
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "horizon_weeks": [h] * n,
            "benchmark": [benchmark] * n,
            "gold_bucket": [bucket] * n,
            "gold_fwd_simple": [gold] * n,
            "stock_fwd_simple": [stock] * n,
            "is_nonoverlap_anchor": [anchor] * n,
        }
    )


def _episodes(*frames) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True)


def _row_for(table, ticker=None, h=1):
    sel = table[table["horizon_weeks"] == h]
    if ticker is not None:
        sel = sel[sel["ticker"] == ticker]
    assert len(sel) == 1, f"expected exactly one row for {ticker or '*'}@{h}w"
    return sel.iloc[0]


def _build(episodes, *, horizons=(1,), config=_CFG):
    table = build_capture(episodes, horizons=list(horizons), config=config)
    assert list(table.columns) == CAPTURE_COLUMNS
    return table


# --- archetype correctness -------------------------------------------------

def test_convex_miner_is_cushioned_down_and_explosive_up() -> None:
    # r = 0.5*g down (takes only half the drop), r = 2*g up. Confirmed by anchors.
    eps = _episodes(
        _rows("CVX", "gold_down", -0.10, -0.05, n=8),
        _rows("CVX", "gold_up", 0.10, 0.20, n=8),
    )
    row = _row_for(_build(eps))
    assert math.isclose(row["down_capture_mean"], 0.5, abs_tol=1e-9)
    assert math.isclose(row["up_capture_mean"], 2.0, abs_tol=1e-9)
    assert math.isclose(row["convexity"], 1.5, abs_tol=1e-9)
    assert row["capture_status"] == "OK" and row["archetype"] == "CONVEX"
    assert row["archetype_confidence"] == "confirmed"
    # Component means persisted "so serve never divides", plus the provenance caveat.
    assert math.isclose(row["down_stock_mean"], -0.05) and math.isclose(row["down_gold_mean"], -0.10)
    assert math.isclose(row["up_stock_mean"], 0.20) and math.isclose(row["up_gold_mean"], 0.10)
    assert math.isclose(row["down_capture_mean"], round(row["down_stock_mean"] / row["down_gold_mean"], 6))
    assert row["caveat"] == CAPTURE_CAVEAT


def test_four_archetypes_partition_the_plane() -> None:
    eps = _episodes(
        _rows("HDG", "gold_down", -0.10, -0.05, n=8),
        _rows("HDG", "gold_up", 0.10, 0.10, n=8),
        _rows("TRQ", "gold_down", -0.10, -0.20, n=8),
        _rows("TRQ", "gold_up", 0.10, 0.20, n=8),
        _rows("DED", "gold_down", -0.10, -0.20, n=8),
        _rows("DED", "gold_up", 0.10, 0.10, n=8),
    )
    table = _build(eps)
    assert _row_for(table, "HDG")["archetype"] == "HEDGE"
    assert _row_for(table, "TRQ")["archetype"] == "TORQUE"
    assert _row_for(table, "DED")["archetype"] == "DEAD_WEIGHT"


def test_negative_down_capture_is_the_best_hedge() -> None:
    eps = _episodes(
        _rows("ANTI", "gold_down", -0.10, 0.03, n=8),  # rises when gold falls
        _rows("ANTI", "gold_up", 0.10, 0.10, n=8),
    )
    row = _row_for(_build(eps))
    assert row["down_capture_mean"] < 0 and row["archetype"] == "HEDGE"


# --- abstention / floors ---------------------------------------------------

def test_zero_rows_side_abstains() -> None:
    row = _row_for(_build(_rows("THN", "gold_up", 0.10, 0.20, n=8)))
    assert row["capture_status"] == "THIN_DOWN"
    assert row["archetype"] is None and row["down_capture_mean"] is None


def test_effective_n_floor_bites_on_data_below_it() -> None:
    # floor 2.0, one down row at h=1 -> effective_n 1.0 < 2.0 -> THIN_DOWN, but the
    # capture number is still computed (status gates the label, not the numbers).
    cfg = CaptureBehaviorConfig(hedge_down_capture_max=1.0, torque_up_capture_min=1.5, min_direction_effective_n=2.0)
    eps = _episodes(
        _rows("LO", "gold_down", -0.10, -0.05, n=1),
        _rows("LO", "gold_up", 0.10, 0.20, n=8),
    )
    row = _row_for(_build(eps, config=cfg))
    assert row["capture_status"] == "THIN_DOWN" and row["archetype"] is None
    assert math.isclose(row["down_capture_mean"], 0.5)  # number kept, label withheld


def test_horizon_deflation_is_real_not_h1_coincidence() -> None:
    # 4 down weeks at h=4 -> effective_n = 4/4 = 1.0 < floor 2.0 -> THIN_DOWN.
    cfg = CaptureBehaviorConfig(hedge_down_capture_max=1.0, torque_up_capture_min=1.5, min_direction_effective_n=2.0)
    eps = _episodes(
        _rows("H4", "gold_down", -0.10, -0.05, n=4, h=4),
        _rows("H4", "gold_up", 0.10, 0.20, n=40, h=4),  # 40/4 = 10 >= floor
    )
    row = _row_for(_build(eps, horizons=(4,), config=cfg), h=4)
    assert math.isclose(row["down_effective_n"], 1.0)
    assert math.isclose(row["up_effective_n"], 10.0)
    assert row["capture_status"] == "THIN_DOWN"


def test_thin_both_when_both_sides_below_floor() -> None:
    cfg = CaptureBehaviorConfig(hedge_down_capture_max=1.0, torque_up_capture_min=1.5, min_direction_effective_n=6.0)
    eps = _episodes(
        _rows("TB", "gold_down", -0.10, -0.05, n=2),
        _rows("TB", "gold_up", 0.10, 0.20, n=2),
    )
    row = _row_for(_build(eps, config=cfg))
    assert row["capture_status"] == "THIN_BOTH" and row["archetype"] is None
    # Numbers stay populated; only the label is withheld.
    assert row["down_capture_mean"] is not None and row["up_capture_mean"] is not None


# --- gold_flat exclusion ---------------------------------------------------

def test_gold_flat_excluded_from_both_sides() -> None:
    healthy = _episodes(
        _rows("FLT", "gold_down", -0.10, -0.05, n=8),
        _rows("FLT", "gold_up", 0.10, 0.20, n=8),
    )
    contaminated = _episodes(healthy, _rows("FLT", "gold_flat", 0.0, 5.0, n=50))
    base = _row_for(_build(healthy))
    row = _row_for(_build(contaminated))
    assert row["down_n_weeks"] == 8 and row["up_n_weeks"] == 8  # flat rows not counted
    assert row["down_capture_mean"] == base["down_capture_mean"]
    assert row["up_capture_mean"] == base["up_capture_mean"]


# --- NaN / degraded data ---------------------------------------------------

def test_all_nan_side_abstains_never_mislabels() -> None:
    eps = _episodes(
        _rows("NAN", "gold_down", -0.10, float("nan"), n=8),  # no valid down obs
        _rows("NAN", "gold_up", 0.10, 0.20, n=8),
    )
    row = _row_for(_build(eps))
    assert row["down_n_weeks"] == 0 and row["down_capture_mean"] is None
    assert row["capture_status"] == "THIN_DOWN" and row["archetype"] is None


def test_partial_nan_counts_only_valid_rows() -> None:
    eps = _episodes(
        _rows("PN", "gold_down", -0.10, -0.05, n=5),
        _rows("PN", "gold_down", -0.10, float("nan"), n=3),  # dropped from evidence
        _rows("PN", "gold_up", 0.10, 0.20, n=8),
    )
    row = _row_for(_build(eps))
    assert row["down_n_weeks"] == 5  # NOT 8 — inflated count would overstate evidence
    assert math.isclose(row["down_capture_mean"], 0.5)


# --- anchor cross-check is a DIAGNOSTIC, not a veto ------------------------

def test_anchor_disagreement_flags_unconfirmed_not_abstains() -> None:
    # All-rows down-capture is hedgey (~0.85) but the (well-powered) anchors say 2.0.
    # Demoted gate: archetype still ships, flagged unconfirmed_disagrees.
    eps = _episodes(
        _rows("UNS", "gold_down", -0.10, -0.05, n=30, anchor=False),  # ratio 0.5 dominates all-rows
        _rows("UNS", "gold_down", -0.10, -0.20, n=6, anchor=True),  # ratio 2.0, n>=6 anchors
        _rows("UNS", "gold_up", 0.10, 0.20, n=8, anchor=True),
    )
    row = _row_for(_build(eps))
    # All-rows down-capture 0.75 (hedgey) -> CONVEX; anchors-only 2.0 (not hedgey) -> TORQUE.
    assert row["down_capture_mean"] <= _CFG.hedge_down_capture_max
    assert row["down_capture_anchor"] > _CFG.hedge_down_capture_max
    assert row["capture_status"] == "OK"
    # The raw label is kept under archetype_all_rows; the confirmed `archetype` is NULL
    # because the independent anchors disagree (display-safe — UI can't show it as settled).
    assert row["archetype_all_rows"] == "CONVEX" and row["archetype"] is None
    assert row["archetype_confidence"] == "unconfirmed_disagrees"
    assert bool(row["archetype_anchor_agrees"]) is False


def test_no_anchor_is_unconfirmed_and_archetype_withheld() -> None:
    eps = _episodes(
        _rows("NOA", "gold_down", -0.10, -0.05, n=8, anchor=False),
        _rows("NOA", "gold_up", 0.10, 0.20, n=8, anchor=False),
    )
    row = _row_for(_build(eps))
    assert row["capture_status"] == "OK"
    assert row["archetype_all_rows"] == "CONVEX" and row["archetype"] is None
    assert row["archetype_confidence"] == "unconfirmed_thin_anchor"
    assert row["archetype_anchor"] is None and row["archetype_anchor_agrees"] is None


def test_few_anchors_below_bar_are_unconfirmed() -> None:
    # Anchors agree but there are only 3 (< min_anchor_episodes=6): not confirmable.
    eps = _episodes(
        _rows("FA", "gold_down", -0.10, -0.05, n=8, anchor=False),
        _rows("FA", "gold_down", -0.10, -0.05, n=3, anchor=True),
        _rows("FA", "gold_up", 0.10, 0.20, n=8, anchor=True),
    )
    row = _row_for(_build(eps))
    assert row["archetype_confidence"] == "unconfirmed_thin_anchor"


# --- robustness / benchmark independence -----------------------------------

def test_capture_median_resists_a_tail_outlier() -> None:
    eps = _episodes(
        _rows("TL", "gold_down", -0.10, -0.05, n=10),
        _rows("TL", "gold_down", -0.10, -5.0, n=1),  # one wild row
        _rows("TL", "gold_up", 0.10, 0.20, n=8),
    )
    row = _row_for(_build(eps))
    assert abs(row["down_capture_median"] - 0.5) < abs(row["down_capture_mean"] - 0.5)


def test_capture_is_benchmark_independent() -> None:
    gdx = _episodes(
        _rows("BI", "gold_down", -0.10, -0.05, n=8, benchmark="GDX"),
        _rows("BI", "gold_up", 0.10, 0.20, n=8, benchmark="GDX"),
    )
    with_gdxj = _episodes(
        gdx,
        _rows("BI", "gold_down", -0.10, -0.05, n=8, benchmark="GDXJ"),
        _rows("BI", "gold_up", 0.10, 0.20, n=8, benchmark="GDXJ"),
    )
    only = _row_for(_build(gdx))
    both = _row_for(_build(with_gdxj))
    assert both["down_capture_mean"] == only["down_capture_mean"]
    assert both["up_capture_mean"] == only["up_capture_mean"]
    assert (build_capture(with_gdxj, horizons=[1], config=_CFG)["ticker"] == "BI").sum() == 1


def test_rounding_to_six_digits() -> None:
    eps = _episodes(
        _rows("RND", "gold_down", -0.30, -0.10, n=8),  # 1/3 = 0.3333...
        _rows("RND", "gold_up", 0.10, 0.20, n=8),
    )
    row = _row_for(_build(eps))
    assert row["down_capture_mean"] == round(1.0 / 3.0, 6)


def test_horizon_filter_does_not_pool_across_horizons() -> None:
    eps = _episodes(
        _rows("HZ", "gold_down", -0.10, -0.05, n=8, h=1),
        _rows("HZ", "gold_up", 0.10, 0.20, n=8, h=1),
        _rows("HZ", "gold_down", -0.10, -0.50, n=8, h=4),  # different returns at h=4
        _rows("HZ", "gold_up", 0.10, 0.05, n=8, h=4),
    )
    table = _build(eps, horizons=(1, 4))
    assert math.isclose(_row_for(table, "HZ", h=1)["down_capture_mean"], 0.5)
    assert math.isclose(_row_for(table, "HZ", h=4)["down_capture_mean"], 5.0)


# --- fail-loud / config hash ----------------------------------------------

@pytest.mark.parametrize(
    "column",
    ["ticker", "horizon_weeks", "benchmark", "gold_bucket", "stock_fwd_simple", "gold_fwd_simple", "is_nonoverlap_anchor"],
)
def test_missing_spine_column_fails_loud(column) -> None:
    eps = _episodes(
        _rows("X", "gold_down", -0.1, -0.05, n=4),
        _rows("X", "gold_up", 0.1, 0.2, n=4),
    ).drop(columns=[column])
    with pytest.raises(ValueError) as exc:
        compute_capture_table(eps, horizons=[1], config=_CFG, behavior_hash="h")
    assert column in str(exc.value) and "v4" in str(exc.value)


def test_behavior_hash_tracks_config_spine_and_buckets() -> None:
    base = behavior_config_hash(_CFG, spine_schema_version=4)
    assert base == behavior_config_hash(_CFG, spine_schema_version=4)  # deterministic
    assert base != behavior_config_hash(_CFG, spine_schema_version=5)  # spine bump
    assert base != behavior_config_hash(_CFG, spine_schema_version=4, buckets=[["x", None, 0.0]])
    for field in ("hedge_down_capture_max", "torque_up_capture_min", "min_direction_effective_n"):
        other = _CFG.model_copy(update={field: getattr(_CFG, field) + 0.5})
        assert base != behavior_config_hash(other, spine_schema_version=4), field


# --- capture_distribution (grounding evidence) -----------------------------

def test_capture_distribution_values_and_provenance_quantiles() -> None:
    eps = _episodes(
        _rows("A", "gold_down", -0.10, -0.05, n=8),  # 0.5
        _rows("A", "gold_up", 0.10, 0.20, n=8),  # 2.0
        _rows("B", "gold_down", -0.10, -0.20, n=8),  # 2.0
        _rows("B", "gold_up", 0.10, 0.10, n=8),  # 1.0
    )
    dist = capture_distribution(_build(eps), horizon=1)
    assert dist["down_capture_mean"]["n"] == 2.0
    assert math.isclose(dist["down_capture_mean"]["p50"], 1.25)  # mean of {0.5, 2.0}
    # p33/p67 are emitted so the grounded cutoffs are auditable from the artifact.
    assert "p33" in dist["down_capture_mean"] and "p67" in dist["up_capture_mean"]
    assert "convexity" in dist


def test_capture_distribution_empty_table_is_safe() -> None:
    dist = capture_distribution(pd.DataFrame(columns=CAPTURE_COLUMNS), horizon=13)
    assert dist["down_capture_mean"]["n"] == 0.0


# --- build_and_save (compute -> persist) -----------------------------------

def _write_spine(lab: Path) -> None:
    # Full v4 spine (capture + peer + trend all read it): horizon 13, enough rows for capture.
    dates = pd.date_range("2010-01-01", periods=80, freq="W-FRI")
    frames = []
    for bucket, gold, stock in (("gold_down", -0.10, -0.05), ("gold_up", 0.10, 0.25)):
        alpha_simple = stock - gold
        frames.append(
            pd.DataFrame(
                {
                    "ticker": ["BIG"] * 80, "horizon_weeks": [13] * 80, "benchmark": ["GDX"] * 80,
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
    _write_dial_meta(lab, episodes=DIAL_EPISODES_FILENAME)


def _write_dial_meta(lab: Path, *, episodes: str) -> None:
    """The behaviour build now REQUIRES the dial manifest + its immutable episodes
    pointer (Codex F1) — write a minimal one beside the spine fixture."""
    (lab / DIAL_ARTIFACT_META_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": DIAL_SCHEMA_VERSION,
                "config_hash": "test-dial-config-hash",
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "run_stamped_artifacts": {"episodes": episodes},
            }
        ),
        encoding="utf-8",
    )


class _FakePaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


def test_build_and_save_persists_artifact_and_meta(tmp_path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir(parents=True)
    _write_spine(lab)
    paths = _FakePaths(tmp_path)

    table = build_and_save(paths)
    assert not table.empty

    latest = pd.read_parquet(lab / CAPTURE_FILENAME)
    meta = json.loads((lab / BEHAVIOR_META_FILENAME).read_text())
    stamped = pd.read_parquet(lab / meta["run_stamped_artifacts"]["capture"])
    # latest alias is byte-identical to the run-stamped artifact.
    pd.testing.assert_frame_equal(latest, stamped)
    assert meta["spine_schema_version"] == 4
    assert meta["source_benchmark"] == "GDX"
    assert meta["rows"] == len(table)
    assert meta["behavior_config_hash"] == table["behavior_config_hash"].iloc[0]
    # the grounded distribution at the default horizon carries the p33/p67 provenance.
    assert "p33" in meta["capture_distribution_default_horizon"]["down_capture_mean"]


def test_build_and_save_missing_spine_fails_loud(tmp_path) -> None:
    (tmp_path / "lab").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        build_and_save(_FakePaths(tmp_path))


def test_build_and_save_off_list_default_horizon_fails_loud(tmp_path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir(parents=True)
    _write_spine(lab)
    # default_capture_horizon (13, from disk config) is not in [4] -> loud failure.
    with pytest.raises(ValueError):
        build_and_save(_FakePaths(tmp_path), horizons=[4])


def test_build_and_save_dial_meta_without_episodes_pointer_fails_loud(tmp_path) -> None:
    """Codex F1: the behaviour build must bind to the IMMUTABLE run-stamped episodes — a
    manifest with no episodes pointer is a malformed spine, fail loud (never alias-fallback)."""
    lab = tmp_path / "lab"
    lab.mkdir(parents=True)
    _write_spine(lab)
    (lab / DIAL_ARTIFACT_META_FILENAME).write_text(
        json.dumps({"schema_version": DIAL_SCHEMA_VERSION, "run_stamped_artifacts": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        build_and_save(_FakePaths(tmp_path))


def test_warn_cutoff_drift_warns_above_tolerance_and_silent_within(capsys) -> None:
    """Codex F13: the build re-confirms the archetype cutoffs against the live p33/p67 and
    warns loudly on drift beyond tolerance, silent within."""
    dist = {"down_capture_mean": {"p33": 1.50}, "up_capture_mean": {"p67": 2.00}}
    # down cutoff drifts 0.50 from the live p33 -> warn naming the cutoff.
    _warn_cutoff_drift(
        CaptureBehaviorConfig(hedge_down_capture_max=1.00, torque_up_capture_min=2.00), dist
    )
    out = capsys.readouterr().out
    assert "hedge_down_capture_max" in out and "drift" in out.lower()
    # both cutoffs within tolerance -> silent.
    _warn_cutoff_drift(
        CaptureBehaviorConfig(hedge_down_capture_max=1.51, torque_up_capture_min=2.00), dist
    )
    assert capsys.readouterr().out == ""


def test_build_and_save_invokes_cutoff_drift_check(tmp_path, monkeypatch) -> None:
    """Codex F13: prove the drift check runs on EVERY behaviour build (not just in main())."""
    import golden_vector.lab.behavior_engine as be

    lab = tmp_path / "lab"
    lab.mkdir(parents=True)
    _write_spine(lab)
    seen: dict[str, bool] = {}
    monkeypatch.setattr(be, "_warn_cutoff_drift", lambda cfg, dist: seen.setdefault("called", True))
    be.build_and_save(_FakePaths(tmp_path))
    assert seen.get("called") is True


def test_archetype_only_emitted_at_default_capture_horizon() -> None:
    # _CFG.default_capture_horizon == 1, so an h=4 cell keeps its NUMBERS but gets no box
    # (the cutoffs are only grounded at the default horizon).
    eps = _episodes(
        _rows("CVX4", "gold_down", -0.10, -0.05, n=8, h=4),
        _rows("CVX4", "gold_up", 0.10, 0.20, n=8, h=4),
    )
    row = _row_for(_build(eps, horizons=(4,)), "CVX4", h=4)
    assert row["capture_status"] == "OK"
    assert math.isclose(row["down_capture_mean"], 0.5)  # numbers present at every horizon
    assert row["archetype"] is None and row["archetype_all_rows"] is None  # no box off-default


def test_invalid_gold_denominator_abstains() -> None:
    # A "down" side whose gold returns average to ~0 (corrupt/custom data) has no capture;
    # status flags it explicitly instead of shipping OK with a null archetype.
    down = pd.DataFrame(
        {
            "ticker": ["BAD"] * 8, "horizon_weeks": [1] * 8, "benchmark": ["GDX"] * 8,
            "gold_bucket": ["gold_down"] * 8,
            "gold_fwd_simple": [0.10, -0.10] * 4,  # mean 0 -> invalid denominator
            "stock_fwd_simple": [-0.05] * 8, "is_nonoverlap_anchor": [True] * 8,
        }
    )
    eps = _episodes(down, _rows("BAD", "gold_up", 0.10, 0.20, n=8))
    row = _row_for(_build(eps), "BAD")
    assert row["capture_status"] == "INVALID_DOWN_DENOMINATOR"
    assert row["down_capture_mean"] is None and row["archetype"] is None
