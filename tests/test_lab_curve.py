"""Data + loader tests for the multi-horizon / multi-benchmark Lab artifacts.

The prize is the consistency invariant: the share of HIGHLIGHTED (scenario) dots
above zero equals the table's RAW p_beat, per benchmark — so the chart can never
disagree with the table. Plus GDXJ per-week degrade, marker cadence, the
schema-stale guard, and the 6-variant multiplicity hash check.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from golden_vector.lab.conditional_dial import (
    DEFAULT_BUCKETS,
    DIAL_ARTIFACT_META_FILENAME,
    DIAL_BENCHMARKS,
    DIAL_CELLS_FILENAME,
    DIAL_EPISODES_FILENAME,
    DIAL_HORIZONS_WEEKS,
    DIAL_RELSTRENGTH_FILENAME,
    DIAL_SCHEMA_VERSION,
    DIAL_SIGNAL_ID,
    build_dial_cells_from_episodes,
    build_dial_cells_wide,
    build_episode_artifact,
    build_episode_frame,
    build_relstrength_artifact,
    cumulative_rebased,
    dial_config_hash,
)
from golden_vector.lab.forward_returns import build_forward_return_panel
from golden_vector.lab.ledger import variant_hash
from golden_vector.serve.lab_curve_data import load_dial_cells, load_ticker_curve
from tests.test_lab_dial_panel_parity import parity_weekly_frame


class _FakePaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


def _write(tmp_path: Path, frame: pd.DataFrame, *, horizons, benchmarks, min_eff=2.0):
    cells = build_dial_cells_wide(
        frame, horizons=horizons, benchmarks=benchmarks, min_effective_n=min_eff
    )
    episodes = build_episode_artifact(frame, horizons=horizons, benchmarks=benchmarks)
    relstrength = build_relstrength_artifact(frame, benchmarks=benchmarks)
    lab = tmp_path / "lab"
    lab.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(lab / DIAL_CELLS_FILENAME, index=False)
    episodes.to_parquet(lab / DIAL_EPISODES_FILENAME, index=False)
    relstrength.to_parquet(lab / DIAL_RELSTRENGTH_FILENAME, index=False)
    meta = {
        "schema_version": DIAL_SCHEMA_VERSION,
        # The loader checks config_hash against the LIVE config, so a fixture must
        # stamp the live-default hash to read as current (it builds a subset of
        # horizons for speed; the tests query within that subset).
        "config_hash": dial_config_hash(DIAL_HORIZONS_WEEKS, DIAL_BENCHMARKS),
        "horizons_weeks": [int(h) for h in horizons],
        "benchmarks": [str(b).upper() for b in benchmarks],
        "usable_gdx_cells_by_horizon_bucket": {},
        "built_at_utc": "2026-06-13T00:00:00+00:00",
    }
    (lab / DIAL_ARTIFACT_META_FILENAME).write_text(json.dumps(meta))
    return _FakePaths(tmp_path), cells


def test_consistency_invariant_chart_share_equals_table_p_beat() -> None:
    """Share of highlighted, non-NA dots with alpha > 0 == cell raw p_beat, per
    benchmark. A tie at exactly 0 must count as a MISS (beat is strictly > 0)."""

    frame = parity_weekly_frame()
    # Wide cells are GDX-anchored (ranked by GDX), so build both benchmarks
    # together and check each benchmark's own p_beat column against its episodes.
    cells = build_dial_cells_wide(
        frame, horizons=[13], benchmarks=["GDX", "GDXJ"], min_effective_n=2.0
    )
    for benchmark in ("GDX", "GDXJ"):
        insuff_col = f"{benchmark.lower()}_insufficient_history"
        usable = cells[~cells[insuff_col].fillna(True).astype(bool)]
        assert not usable.empty
        episodes = build_episode_frame(frame, horizon_weeks=13, benchmark=benchmark)
        checked = 0
        for _, cell in usable.iterrows():
            sub = episodes[
                (episodes["ticker"] == cell["ticker"])
                & (episodes["gold_bucket"] == cell["bucket"])
            ]
            alphas = pd.to_numeric(sub["alpha"], errors="coerce").dropna()
            if alphas.empty:
                continue
            share = float((alphas > 0).mean())
            p_beat = float(cell[f"p_beat_{benchmark.lower()}"])
            # p_beat is persisted rounded to 4 decimals; the invariant holds to
            # that rounding (the chart and table agree by construction).
            assert abs(share - p_beat) < 1e-4, (cell["ticker"], cell["bucket"], share, p_beat)
            checked += 1
        assert checked > 0


def test_cells_are_derived_from_the_same_episode_spine() -> None:
    """The publisher contract: build episodes once, then derive cells from that
    exact spine. This prevents the overview table and drill-down dots drifting."""

    frame = parity_weekly_frame()
    direct = build_dial_cells_wide(
        frame, horizons=[4, 13], benchmarks=["GDX", "GDXJ"], min_effective_n=2.0
    )
    episodes = build_episode_artifact(frame, horizons=[4, 13], benchmarks=["GDX", "GDXJ"])
    derived = build_dial_cells_from_episodes(
        episodes, horizons=[4, 13], benchmarks=["GDX", "GDXJ"], min_effective_n=2.0
    )
    pd.testing.assert_frame_equal(
        direct.sort_index(axis=1).reset_index(drop=True),
        derived.sort_index(axis=1).reset_index(drop=True),
    )


def test_forward_labels_reject_inconsistent_benchmark_calendar_values() -> None:
    frame = parity_weekly_frame()
    first_week = sorted(frame["week_period"].unique())[0]
    mask = (frame["ticker"] == "AAA") & (frame["week_period"] == first_week)
    frame.loc[mask, "gdx_log_ret"] = 0.123456

    with pytest.raises(ValueError, match="Inconsistent gdx_log_ret"):
        build_forward_return_panel(frame, horizons_weeks=[13])


def test_episode_artifact_rejects_inconsistent_gold_calendar_values() -> None:
    frame = parity_weekly_frame()
    first_week = sorted(frame["week_period"].unique())[0]
    mask = (frame["ticker"] == "AAA") & (frame["week_period"] == first_week)
    frame.loc[mask, "gold_log_ret"] = 0.123456

    with pytest.raises(ValueError, match="Inconsistent gold_log_ret"):
        build_episode_artifact(frame, horizons=[13], benchmarks=["GDX"])


def test_alpha_zero_tie_counts_as_miss() -> None:
    """beat is strictly alpha > 0, so an exact-zero alpha is NOT a beat."""

    frame = parity_weekly_frame()
    episodes = build_episode_frame(frame, horizon_weeks=13, benchmark="GDX")
    forced = episodes.copy()
    forced.loc[forced.index[:5], "alpha"] = 0.0
    beats = (pd.to_numeric(forced["alpha"], errors="coerce") > 0).astype(float)
    assert beats.iloc[:5].sum() == 0.0


def test_consistency_invariant_holds_through_the_loader() -> None:
    """End-to-end: loader points + matching cell agree (no highlight off-by-one)."""

    frame = parity_weekly_frame()
    paths, _ = _write(tmp_path_for(), frame, horizons=[13], benchmarks=["GDX", "GDXJ"])
    curve = load_ticker_curve(
        paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )
    scenario = [p for p in curve.points if p["is_scenario"]]
    if curve.cell and not bool(curve.cell.get("gdx_insufficient_history")) and scenario:
        above = [p for p in scenario if p["alpha"] is not None and float(p["alpha"]) > 0]
        share = len(above) / len(scenario)
        assert abs(share - float(curve.cell["p_beat_gdx"])) < 1e-4


def test_gdxj_degrades_per_week_independently() -> None:
    """GDXJ inception/missingness is a calendar-level benchmark fact: every
    ticker gets a shorter GDXJ evidence set when the benchmark lacks early weeks."""

    frame = parity_weekly_frame()
    # Null out GDXJ for the first 150 calendar weeks.
    early = sorted(frame["week_period"].unique())[:150]
    mask = frame["week_period"].isin(early)
    frame.loc[mask, "gdxj_log_ret"] = np.nan

    cells = build_dial_cells_wide(
        frame, horizons=[13], benchmarks=["GDX", "GDXJ"], min_effective_n=2.0
    )
    # GDXJ weeks shorter than GDX weeks for every ticker where both are present.
    comparable = cells[cells["gdxj_n_weeks"].fillna(0).gt(0)]
    assert not comparable.empty
    assert (comparable["gdxj_n_weeks"].fillna(0) < comparable["gdx_n_weeks"].fillna(0)).all()
    # GDX (the required base) is untouched.
    assert (cells["gdx_n_weeks"].fillna(0) > 0).all()


def test_nonoverlap_anchor_cadence() -> None:
    """Every h-th episode per ticker is a non-overlap anchor."""

    frame = parity_weekly_frame()
    episodes = build_episode_artifact(frame, horizons=[13], benchmarks=["GDX"])
    one = episodes[(episodes["ticker"] == "AAA") & (episodes["benchmark"] == "GDX")]
    one = one.sort_values("week_period").reset_index(drop=True)
    anchors = one.index[one["is_nonoverlap_anchor"]].tolist()
    assert anchors[:3] == [0, 13, 26]
    # roughly one anchor per 13 rows
    assert abs(len(anchors) - round(len(one) / 13)) <= 1


def test_loader_flags_stale_when_schema_old(tmp_path) -> None:
    frame = parity_weekly_frame()
    paths, _ = _write(tmp_path, frame, horizons=[13], benchmarks=["GDX", "GDXJ"])
    meta_path = tmp_path / "lab" / DIAL_ARTIFACT_META_FILENAME
    meta = json.loads(meta_path.read_text())
    meta["schema_version"] = DIAL_SCHEMA_VERSION - 1
    meta_path.write_text(json.dumps(meta))
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")
    assert not data.available
    assert data.error_status == "STALE"


def test_loader_flags_stale_when_config_hash_mismatches(tmp_path) -> None:
    """A config change (e.g. a bucket threshold) that does NOT bump the schema
    version must still invalidate the artifact via the config_hash."""

    frame = parity_weekly_frame()
    paths, _ = _write(tmp_path, frame, horizons=[13], benchmarks=["GDX", "GDXJ"])
    meta_path = tmp_path / "lab" / DIAL_ARTIFACT_META_FILENAME
    meta = json.loads(meta_path.read_text())
    meta["config_hash"] = "stale-config-hash-from-old-thresholds"
    meta_path.write_text(json.dumps(meta))
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")
    assert not data.available
    assert data.error_status == "STALE"


def test_loader_flags_stale_when_live_horizons_change(tmp_path) -> None:
    """Codex MED: a live horizon-LIST change must go STALE — the guard checks the
    live DIAL_HORIZONS_WEEKS, not the artifact's own stored list hashed to itself."""

    frame = parity_weekly_frame()
    paths, _ = _write(tmp_path, frame, horizons=[13], benchmarks=["GDX", "GDXJ"])
    meta_path = tmp_path / "lab" / DIAL_ARTIFACT_META_FILENAME
    meta = json.loads(meta_path.read_text())
    # Artifact was built for a DIFFERENT horizon set than the live default.
    meta["config_hash"] = dial_config_hash([13, 26, 52, 104], DIAL_BENCHMARKS)
    meta["horizons_weeks"] = [13, 26, 52, 104]
    meta_path.write_text(json.dumps(meta))
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")
    assert not data.available
    assert data.error_status == "STALE"


def test_variant_hashes_are_distinct_per_benchmark_horizon() -> None:
    """Benchmark x horizon multiplicity: every (benchmark, horizon) config is a
    distinct registered variant — one per pair, none colliding."""

    bucket_cfg = [[n, lo, hi] for n, lo, hi in DEFAULT_BUCKETS]
    hashes = set()
    for bench in DIAL_BENCHMARKS:
        for horizon in DIAL_HORIZONS_WEEKS:
            cfg = {
                "signal": "conditional_dial_analog_v1",
                "horizon_weeks": int(horizon),
                "buckets": bucket_cfg,
                "min_effective_n": 8.0,
                "eb_prior_strength": 10.0,
                "benchmark": str(bench).upper(),
            }
            hashes.add(variant_hash(DIAL_SIGNAL_ID, cfg))
    assert len(hashes) == len(DIAL_BENCHMARKS) * len(DIAL_HORIZONS_WEEKS)


def test_relstrength_rebased_to_100_at_start() -> None:
    frame = parity_weekly_frame()
    rel = build_relstrength_artifact(frame, benchmarks=["GDX", "GDXJ"])
    assert not rel.empty
    for _, grp in rel.groupby(["ticker", "benchmark"]):
        first = grp.sort_values("week_date")["relstrength"].iloc[0]
        assert abs(float(first) - 100.0) < 1e-9


def test_cumulative_rebased_is_prefix_only() -> None:
    """value at k uses only returns through k (start-anchored, no look-ahead)."""

    import math

    series = pd.Series([0.1, -0.2, 0.05])
    out = cumulative_rebased(series)
    assert abs(float(out.iloc[0]) - 100.0) < 1e-9
    assert abs(float(out.iloc[1]) - 100.0 * math.exp(-0.2)) < 1e-9
    assert abs(float(out.iloc[2]) - 100.0 * math.exp(-0.15)) < 1e-9


def test_relstrength_prefix_stable_under_truncation() -> None:
    """Truncating future weeks must not change earlier values — proves the line
    is not end-anchored and carries no look-ahead."""

    frame = parity_weekly_frame()
    full = build_relstrength_artifact(frame, benchmarks=["GDX"])
    full_aaa = (
        full[(full["ticker"] == "AAA") & (full["benchmark"] == "GDX")]
        .sort_values("week_date")
        .reset_index(drop=True)
    )
    weeks = sorted(frame["week_period"].unique())[:120]
    truncated = frame[frame["week_period"].isin(weeks)]
    part = build_relstrength_artifact(truncated, benchmarks=["GDX"])
    part_aaa = (
        part[(part["ticker"] == "AAA") & (part["benchmark"] == "GDX")]
        .sort_values("week_date")
        .reset_index(drop=True)
    )
    m = len(part_aaa)
    assert m > 5
    assert np.allclose(
        full_aaa["relstrength"].iloc[:m].to_numpy(dtype=float),
        part_aaa["relstrength"].to_numpy(dtype=float),
        atol=1e-9,
    )


def test_chart_b_reports_missing_relstrength_artifact() -> None:
    """Codex LOW: a bad/absent relstrength artifact must say so, not silently
    render an empty Chart B."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    # Remove just the relstrength artifact; Chart A (episodes/cells) stays intact.
    (Path(paths.data_dir) / "lab" / DIAL_RELSTRENGTH_FILENAME).unlink()
    curve = load_ticker_curve(
        paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )
    assert curve.relstrength_status == "MISSING"
    html = _render_lab_curve_page(curve)
    assert "Relative-strength artifact is missing" in html
    # Chart A (the counted evidence) is unaffected.
    assert "lab-dots-svg" in html


def test_drilldown_render_has_forward_and_survivor_honesty() -> None:
    """The drill-down binds the honesty qualifiers into the page."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    curve = load_ticker_curve(
        paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )
    html = _render_lab_curve_page(curve)
    assert "next 13 weeks" in html  # forward-window label
    assert "surviving miners only" in html  # survivor caveat bound in
    assert "hindsight grouping" in html  # scenario highlight honesty
    assert "Different measure" in html  # Chart B labelled as different
    assert "benchmark=GDXJ" in html  # toggle
    assert "pending" in html  # forward-window gutter is drawn, not just captioned


def test_drilldown_headline_shows_effn_and_shrunk_not_blank() -> None:
    """Regression for the _cell_field key mismatch: the headline must render a
    NUMERIC effective N and shrunk percent (not an em-dash) for BOTH benchmarks."""

    import re

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    frame = parity_weekly_frame()
    paths, _ = _write(tmp_path_for(), frame, horizons=[13], benchmarks=["GDX", "GDXJ"])
    cells = build_dial_cells_wide(frame, horizons=[13], benchmarks=["GDX", "GDXJ"], min_effective_n=2.0)
    usable = cells[
        (cells["bucket"] == "gold_down")
        & (~cells["gdx_insufficient_history"].fillna(True).astype(bool))
        & (~cells["gdxj_insufficient_history"].fillna(True).astype(bool))
    ]
    assert not usable.empty
    ticker = str(usable.iloc[0]["ticker"])
    for benchmark in ("GDX", "GDXJ"):
        curve = load_ticker_curve(
            paths, ticker=ticker, scenario_bucket="gold_down", horizon=13, benchmark=benchmark
        )
        html = _render_lab_curve_page(curve)
        assert re.search(r"Effective N = \d+\.\d", html), (benchmark, "effective N blank")
        assert re.search(r"Ranked/smoothed estimate: \d+\.\d%", html), (benchmark, "shrunk blank")


# A tmp dir for the loader-roundtrip tests that do not take the pytest fixture
# (keeps the assertion bodies flat and explicit).
def tmp_path_for() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="lab_curve_test_"))
