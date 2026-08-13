"""Data + loader tests for the multi-horizon / multi-benchmark Lab artifacts.

The prize is the consistency invariant: the share of HIGHLIGHTED (scenario) dots
above zero equals the table's RAW p_beat, per benchmark — so the chart can never
disagree with the table. Plus GDXJ per-week degrade, marker cadence, the
schema-stale guard, and the 6-variant multiplicity hash check.
"""

from __future__ import annotations

import dataclasses
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
    DIAL_PROFILE_FILENAME,
    DIAL_RELSTRENGTH_FILENAME,
    DIAL_SCHEMA_VERSION,
    DIAL_SIGNAL_ID,
    build_dial_cells_from_episodes,
    build_dial_cells_wide,
    build_episode_artifact,
    build_episode_frame,
    build_profile_artifact,
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
    profile = build_profile_artifact(cells, horizons=horizons, benchmarks=benchmarks)
    lab = tmp_path / "lab"
    lab.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(lab / DIAL_CELLS_FILENAME, index=False)
    episodes.to_parquet(lab / DIAL_EPISODES_FILENAME, index=False)
    relstrength.to_parquet(lab / DIAL_RELSTRENGTH_FILENAME, index=False)
    profile.to_parquet(lab / DIAL_PROFILE_FILENAME, index=False)
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
    benchmark AND per horizon. A tie at exactly 0 must count as a MISS (beat is
    strictly > 0). Parametrized across the look-ahead set so a future
    forward_sum/anchor change can't break 4w/8w/26w undetected."""

    frame = parity_weekly_frame()
    horizons = [4, 8, 13]  # all yield usable cells on the synthetic frame at min_eff=2
    # Wide cells are GDX-anchored, so build both benchmarks together; check each
    # benchmark's own p_beat column against its episodes, per horizon.
    cells = build_dial_cells_wide(
        frame, horizons=horizons, benchmarks=["GDX", "GDXJ"], min_effective_n=2.0
    )
    checked = 0
    for horizon in horizons:
        hz_cells = cells[cells["horizon_weeks"] == horizon]
        for benchmark in ("GDX", "GDXJ"):
            insuff_col = f"{benchmark.lower()}_insufficient_history"
            usable = hz_cells[~hz_cells[insuff_col].fillna(True).astype(bool)]
            if usable.empty:
                continue
            episodes = build_episode_frame(frame, horizon_weeks=horizon, benchmark=benchmark)
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
                # p_beat is persisted rounded to 4 dp; invariant holds to that.
                assert abs(share - p_beat) < 1e-4, (
                    horizon, benchmark, cell["ticker"], cell["bucket"], share, p_beat
                )
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


def test_dial_horizon_set_is_pinned() -> None:
    """Pin the live look-ahead set so a silent revert to the empty-52w design is
    caught (the drift tests otherwise stamp arbitrary horizon lists)."""

    assert DIAL_HORIZONS_WEEKS == [4, 8, 13, 26]
    assert 52 not in DIAL_HORIZONS_WEEKS


def test_dial_config_hash_is_order_and_set_invariant() -> None:
    """Reordering the horizon/benchmark lists is a semantic no-op and must NOT
    change the config hash (else a current artifact false-flags STALE)."""

    assert dial_config_hash([4, 8, 13, 26], ["GDX", "GDXJ"]) == dial_config_hash(
        [26, 13, 8, 4], ["GDXJ", "GDX"]
    )
    assert dial_config_hash([4, 8, 13, 26], ["GDX", "GDXJ"]) != dial_config_hash(
        [4, 8, 13, 26, 52], ["GDX", "GDXJ"]
    )


def test_cumulative_rebased_does_not_bridge_interior_gaps() -> None:
    """An interior NaN must NA-propagate (post-gap excluded), not be bridged as a
    zero-return week — 'degraded data is EXCLUDED, not bridged'."""

    out = cumulative_rebased(pd.Series([0.1, float("nan"), 0.05]))
    assert abs(float(out.iloc[0]) - 100.0) < 1e-9
    assert pd.isna(out.iloc[1])  # the gap itself
    assert pd.isna(out.iloc[2])  # post-gap excluded, NOT exp(0.15)


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


def test_drilldown_profile_renders_across_scenarios_with_gaps() -> None:
    """v1 gold profile: 5 scenario slots in order, usable flags from the cells,
    rendered with the win-rate bar and an honest coverage basis line."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    curve = load_ticker_curve(
        paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )
    assert [p["bucket"] for p in curve.profile_points] == [
        "gold_down_big", "gold_down", "gold_flat", "gold_up", "gold_up_big"
    ]
    assert any(p["usable"] for p in curve.profile_points)
    # Non-usable buckets carry no number (honest gap), usable ones do.
    for p in curve.profile_points:
        if p["usable"]:
            assert p["p_beat_shrunk"] is not None
        else:
            assert p["p_beat_shrunk"] is None
    html = _render_lab_curve_page(curve)
    assert "lab-profile" in html and "winrate-bar" in html
    assert "usable down scenario" in html  # coverage basis line, not "whole spectrum"
    assert '<div class="terminal-density">' in html
    assert 'class="segmented-control"' in html
    assert 'aria-label="Benchmark"' in html
    assert html.count('aria-current="true"') == 1
    assert "benchmark-toggle" not in html


def test_profile_and_winrate_share_the_same_raw_basis() -> None:
    """HIGH fix: the profile dot and the win-rate bar must show the SAME number
    for the selected scenario (both the counted/raw rate), not shrunk vs raw."""

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    curve = load_ticker_curve(
        paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )
    if curve.cell is None or bool(curve.cell.get("gdx_insufficient_history")):
        return  # nothing to compare on this synthetic cell
    bar_raw = float(curve.cell["p_beat_gdx"])  # what the win-rate bar renders
    profile = {p["bucket"]: p for p in curve.profile_points}
    dot = profile["gold_down"]
    assert dot["usable"]
    assert abs(float(dot["p_beat_raw"]) - bar_raw) < 1e-12  # chart dot == bar


def test_profile_slope_wording_is_gated_on_an_adjacent_pair() -> None:
    """MED fix: only claim a 'down-then-up slope' when adjacent scenarios are both
    usable (a line is drawn); non-adjacent down+up says 'compare the dots'."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_profile

    def pt(bucket, usable, raw=0.6):
        return {
            "bucket": bucket, "label": bucket, "usable": usable,
            "p_beat_raw": raw if usable else None,
            "p_beat_shrunk": raw if usable else None,
            "median_alpha": 0.0 if usable else None, "effective_n": 9.0 if usable else None,
        }

    # down_big usable, then a gap, then up usable -> NON-adjacent (no connecting line).
    pts = [
        pt("gold_down_big", True), pt("gold_down", False), pt("gold_flat", False),
        pt("gold_up", True), pt("gold_up_big", False),
    ]
    curve = LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_down_big", scenario_label="Gold down more than 15%",
        profile_points=pts, profile_usable_down=1, profile_usable_up=1,
    )
    html = _render_profile(curve)
    assert "down-then-up slope" not in html
    assert "compare the down" in html


def test_profile_aria_label_names_the_real_benchmark() -> None:
    """MED fix: the profile SVG aria-label interpolates the benchmark (was a
    literal 'benchmark')."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    curve = load_ticker_curve(
        paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDXJ"
    )
    html = _render_lab_curve_page(curve)
    assert "aria-label=\"How often AAA beat GDXJ" in html
    assert "scenarios have countable history" in html  # coverage stated in the alt text


def test_bucket_short_labels_cover_all_buckets() -> None:
    """One-copy: the short-label map must stay in lock-step with BUCKET_LABELS, so
    a future 6th bucket forces an explicit update rather than a silent gap."""

    from golden_vector.lab.conditional_dial import BUCKET_LABELS, BUCKET_SHORT_LABELS

    assert set(BUCKET_SHORT_LABELS) == set(BUCKET_LABELS)


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


def _profile_pt(bucket, usable, *, raw=0.6, shrunk=None):
    """A hand-built profile point (lets render-level tests control raw vs shrunk)."""
    return {
        "bucket": bucket,
        "label": bucket,
        "usable": usable,
        "p_beat_raw": raw if usable else None,
        "p_beat_shrunk": (shrunk if shrunk is not None else raw) if usable else None,
        "median_alpha": 0.0 if usable else None,
        "effective_n": 9.0 if usable else None,
    }


def test_profile_render_shows_raw_not_shrunk_dot_and_bar() -> None:
    """HIGH-bug RENDER guard (Codex MED): with raw and shrunk deliberately
    DIFFERENT, the profile dot label AND the win-rate bar must show the RAW percent;
    the shrunk value may appear only in the hover <title>. Catches a regression
    where the SVG plots p_beat_shrunk again (the exact bug fixed in dfaf206)."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_profile, _render_winrate_bar

    cell = {  # raw 90% vs shrunk 70% — a swap would be plainly visible
        "p_beat_gdx": 0.90,
        "p_beat_gdx_shrunk": 0.70,
        "median_alpha_gdx": 0.05,
        "gdx_effective_n": 9.0,
        "gdx_insufficient_history": False,
    }
    pts = [
        _profile_pt("gold_down_big", False),
        _profile_pt("gold_down", True, raw=0.90, shrunk=0.70),
        _profile_pt("gold_flat", False),
        _profile_pt("gold_up", True, raw=0.40, shrunk=0.55),
        _profile_pt("gold_up_big", False),
    ]
    curve = LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%",
        profile_points=pts, profile_usable_down=1, profile_usable_up=1, cell=cell,
    )
    profile_html = _render_profile(curve)
    bar_html = _render_winrate_bar(curve)
    # The gold_down dot's printed label is the RAW 90%, not the shrunk 70%.
    assert ">90%<" in profile_html
    assert ">70%<" not in profile_html  # shrunk is never a plotted dot label
    assert "ranked/smoothed 70%" in profile_html  # it lives only in the hover title
    # The win-rate bar (selected gold_down scenario) also shows the RAW 90%.
    assert "90% of the time" in bar_html
    assert "70% of the time" not in bar_html


def test_profile_one_sided_up_does_not_claim_downside_resilience() -> None:
    """MED fix (Codex): a profile with ONLY up-side scenarios usable — even with an
    adjacent drawn segment — must not say it 'held up better when gold fell'; there
    is no down bucket to support that read."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_profile

    pts = [
        _profile_pt("gold_down_big", False), _profile_pt("gold_down", False),
        _profile_pt("gold_flat", False),
        _profile_pt("gold_up", True), _profile_pt("gold_up_big", True),  # adjacent
    ]
    curve = LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_up", scenario_label="Gold up 5% to 15%",
        profile_points=pts, profile_usable_down=0, profile_usable_up=2,
    )
    html = _render_profile(curve)
    assert "down-then-up slope" not in html
    assert "held up better when gold fell" not in html
    assert "Only up-side gold scenarios" in html


def test_profile_one_sided_down_does_not_claim_slope() -> None:
    """Symmetric one-sided guard: only down-side usable must say so, not imply a
    down-vs-up shape."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_profile

    pts = [
        _profile_pt("gold_down_big", True), _profile_pt("gold_down", True),  # adjacent
        _profile_pt("gold_flat", False),
        _profile_pt("gold_up", False), _profile_pt("gold_up_big", False),
    ]
    curve = LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%",
        profile_points=pts, profile_usable_down=2, profile_usable_up=0,
    )
    html = _render_profile(curve)
    assert "down-then-up slope" not in html
    assert "Only down-side gold scenarios" in html


def test_profile_svg_never_bridges_a_gap() -> None:
    """Visual-honesty pin (Codex MED): the profile SVG draws a connecting segment
    ONLY between two adjacent usable buckets; a non-usable bucket between two usable
    ones leaves a visible gap (no line spanning it)."""

    from golden_vector.serve.lab_curve_page import _build_profile_svg

    connector = "class=\"series-context\""  # the class used ONLY for the connecting line
    gapped = [  # usable, GAP, usable -> no adjacent usable pair -> zero connectors
        _profile_pt("gold_down_big", True), _profile_pt("gold_down", False),
        _profile_pt("gold_flat", True),
        _profile_pt("gold_up", False), _profile_pt("gold_up_big", False),
    ]
    svg_gapped = _build_profile_svg(gapped, ticker="ZZZ", benchmark="GDX", horizon=13)
    assert connector not in svg_gapped  # nothing bridges the gap
    adjacent = [  # positive control: two adjacent usable buckets DO get a connector
        _profile_pt("gold_down_big", True), _profile_pt("gold_down", True),
        _profile_pt("gold_flat", False),
        _profile_pt("gold_up", False), _profile_pt("gold_up_big", False),
    ]
    svg_adjacent = _build_profile_svg(adjacent, ticker="ZZZ", benchmark="GDX", horizon=13)
    assert connector in svg_adjacent


def test_down_up_bucket_partitions_are_derived_correctly() -> None:
    """One-copy partition pin (Codex NIT): DOWN/UP are derived from the bucket
    bounds; gold_flat belongs to neither and the two lists are disjoint."""

    from golden_vector.lab.conditional_dial import DOWN_BUCKETS, UP_BUCKETS

    assert set(DOWN_BUCKETS) == {"gold_down_big", "gold_down"}
    assert set(UP_BUCKETS) == {"gold_up", "gold_up_big"}
    assert "gold_flat" not in DOWN_BUCKETS and "gold_flat" not in UP_BUCKETS
    assert not (set(DOWN_BUCKETS) & set(UP_BUCKETS))  # disjoint


def test_drilldown_fails_loud_when_cells_artifact_is_bad() -> None:
    """Codex MED (fail-loud): a missing/corrupt/stale dial_cells artifact — while
    episodes exist — must surface a distinct CELLS_* status with a rebuild message,
    never masquerade as 'no countable cross-scenario history' (an evidence gap)."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    # MISSING: delete the cells artifact, keep episodes intact.
    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    (Path(paths.data_dir) / "lab" / DIAL_CELLS_FILENAME).unlink()
    curve = load_ticker_curve(paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert not curve.available
    assert curve.error_status == "CELLS_MISSING"
    html = _render_lab_curve_page(curve)
    assert "scenario-cells artifact is missing" in html
    assert "No countable cross-scenario history" not in html  # NOT the evidence-gap message

    # CORRUPT: overwrite cells with non-parquet bytes.
    paths2, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    (Path(paths2.data_dir) / "lab" / DIAL_CELLS_FILENAME).write_bytes(b"not a parquet file")
    curve2 = load_ticker_curve(paths2, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert not curve2.available
    assert curve2.error_status == "CELLS_CORRUPT"

    # STALE: cells present but missing required columns.
    paths3, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    pd.DataFrame({"ticker": ["AAA"]}).to_parquet(
        Path(paths3.data_dir) / "lab" / DIAL_CELLS_FILENAME, index=False
    )
    curve3 = load_ticker_curve(paths3, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert not curve3.available
    assert curve3.error_status == "CELLS_STALE"


def test_drilldown_distinguishes_bad_metadata_from_stale() -> None:
    """Codex LOW: a missing/corrupt dial_meta.json on the drill-down route must
    report META_MISSING/META_CORRUPT (mirroring the overview), not collapse to a
    misleading STALE."""

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    (Path(paths.data_dir) / "lab" / DIAL_ARTIFACT_META_FILENAME).unlink()
    curve = load_ticker_curve(paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert not curve.available
    assert curve.error_status == "META_MISSING"

    paths2, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    (Path(paths2.data_dir) / "lab" / DIAL_ARTIFACT_META_FILENAME).write_text("{not valid json")
    curve2 = load_ticker_curve(paths2, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert not curve2.available
    assert curve2.error_status == "META_CORRUPT"


def test_drilldown_unknown_scenario_is_flagged_not_thin_history() -> None:
    """Codex LOW: a mistyped ?scenario= must return UNKNOWN_SCENARIO with a clear
    message naming the bad value, not render as 'not enough history' (and no
    rebuild instruction, since a URL typo is not a build problem)."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    curve = load_ticker_curve(paths, ticker="AAA", scenario_bucket="gold_sideways", horizon=13, benchmark="GDX")
    assert not curve.available
    assert curve.error_status == "UNKNOWN_SCENARIO"
    html = _render_lab_curve_page(curve)
    assert "Unknown gold scenario" in html
    assert "gold_sideways" in html
    assert "python -m golden_vector.lab.conditional_dial" not in html


# ---- v2 gold-tilt label: loader reads the persisted artifact, render is honest --


def test_loader_reads_persisted_tilt_label() -> None:
    """The loader surfaces the build-computed label/status from dial_profile for the
    page (a pure read — serve never recomputes the tilt)."""

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    prof = pd.read_parquet(Path(paths.data_dir) / "lab" / DIAL_PROFILE_FILENAME)
    row = prof[(prof["benchmark"] == "GDX") & (prof["horizon_weeks"] == 13)].iloc[0]
    curve = load_ticker_curve(
        paths, ticker=str(row["ticker"]), scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )
    assert curve.profile_label_status == str(row["label_status"])
    if row["label_status"] == "OK":
        assert curve.profile_label == str(row["gold_tilt_label"])
        assert curve.profile_label in ("Defensive", "Steady", "Pro-cyclical")


def test_loader_usable_counts_match_persisted_profile_no_drift() -> None:
    """The serve usable-bucket count and the BUILD's persisted count come from the
    SAME cell_bucket_is_usable rule — they must never disagree."""

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    prof = pd.read_parquet(Path(paths.data_dir) / "lab" / DIAL_PROFILE_FILENAME)
    row = prof[(prof["benchmark"] == "GDX") & (prof["horizon_weeks"] == 13)].iloc[0]
    curve = load_ticker_curve(
        paths, ticker=str(row["ticker"]), scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )
    assert curve.profile_usable_down == int(row["usable_down_bucket_count"])
    assert curve.profile_usable_up == int(row["usable_up_bucket_count"])


def test_loader_flags_stale_when_gold_profile_threshold_changes(tmp_path) -> None:
    """Contract: editing a gold-profile threshold invalidates the artifact (the
    profile config is stamped into the dial config hash)."""

    from golden_vector.contracts.config_models import GoldProfileConfig

    frame = parity_weekly_frame()
    paths, _ = _write(tmp_path, frame, horizons=[13], benchmarks=["GDX", "GDXJ"])
    meta_path = tmp_path / "lab" / DIAL_ARTIFACT_META_FILENAME
    meta = json.loads(meta_path.read_text())
    meta["config_hash"] = dial_config_hash(
        DIAL_HORIZONS_WEEKS, DIAL_BENCHMARKS, GoldProfileConfig(tilt_threshold=0.25)
    )
    meta_path.write_text(json.dumps(meta))
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")
    assert not data.available
    assert data.error_status == "STALE"


def _labelled_curve(status, label, *, down=2, up=2):
    from golden_vector.serve.lab_curve_data import LabCurveData

    pts = [
        _profile_pt("gold_down_big", True, raw=0.9), _profile_pt("gold_down", True, raw=0.7),
        _profile_pt("gold_flat", False),
        _profile_pt("gold_up", True, raw=0.3), _profile_pt("gold_up_big", True, raw=0.1),
    ]
    return LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%",
        profile_points=pts, profile_usable_down=down, profile_usable_up=up,
        profile_basis_down=down, profile_basis_up=up,
        profile_down_mean=0.8, profile_up_mean=0.2, profile_tilt=0.6, profile_tilt_threshold=0.10,
        profile_label=label, profile_label_status=status,
        profile_caveat="counted history, survivor-only, exploratory — not a prediction.",
    )


def test_drilldown_renders_horizon_scoped_tilt_label_when_ok() -> None:
    """OK label is horizon-scoped, shows the numeric derivation + coverage basis +
    caveat, and never makes a bare 'this miner is defensive' identity claim."""

    from golden_vector.serve.lab_curve_page import _render_profile

    html = _render_profile(_labelled_curve("OK", "Defensive"))
    assert "13-week historical tilt: Defensive" in html
    assert "down-side beat rate 80% vs up-side 20% (tilt +0.60, threshold 0.10)" in html
    assert "based on 2 usable down scenario(s) and 2 usable up scenario(s) at 13w" in html
    assert "not a prediction" in html
    assert "is defensive" not in html.lower()  # never a horizon-free identity claim


def test_label_basis_uses_persisted_partition_count_not_structural() -> None:
    """M1 fix: the coverage basis renders the BUILD's persisted usable-bucket count
    (the tilt partition), not the structural chart count — so editing the config's
    down/up buckets can't desync the stated basis from the tilt's real coverage."""

    from golden_vector.serve.lab_curve_page import _render_profile

    # Structural count says 2 down; the persisted tilt partition counted 3 (e.g. a
    # config that folds gold_flat into the down side). The basis must show 3.
    curve = _labelled_curve("OK", "Defensive", down=2, up=2)
    curve = dataclasses.replace(curve, profile_basis_down=3, profile_basis_up=1)
    html = _render_profile(curve)
    assert "based on 3 usable down scenario(s) and 1 usable up scenario(s)" in html


def test_drilldown_insufficient_tilt_label_is_honest() -> None:
    from golden_vector.serve.lab_curve_page import _render_profile

    html = _render_profile(
        _labelled_curve("INSUFFICIENT_CROSS_SCENARIO_HISTORY", None, down=1, up=0)
    )
    assert "Not enough cross-scenario history to characterize" in html
    assert "historical tilt:" not in html  # no fabricated label


def test_drilldown_tilt_label_unavailable_degrades_to_chart() -> None:
    """A missing/stale profile artifact (UNAVAILABLE) hides the label but the chart
    still renders — optional enrichment, not a page failure."""

    from golden_vector.serve.lab_curve_page import _render_profile

    html = _render_profile(_labelled_curve("UNAVAILABLE", None))
    assert "historical tilt" not in html  # no label
    assert "lab-profile" in html  # the chart still renders


def test_serve_echoes_the_persisted_label_verbatim() -> None:
    """Serve renders EXACTLY the persisted gold_tilt_label string — it cannot be
    substituting its own category word. An odd persisted label appears verbatim,
    proving the word comes from the artifact, not a serve-side decision."""

    from golden_vector.serve.lab_curve_page import _render_profile

    html = _render_profile(_labelled_curve("OK", "Defensive-XYZ"))
    assert "13-week historical tilt: Defensive-XYZ" in html


def test_drilldown_profile_artifact_corrupt_or_short_degrades_to_unavailable() -> None:
    """A present-but-malformed dial_profile (corrupt bytes / missing a required
    column) degrades the LABEL to UNAVAILABLE; the chart + numbers still render (the
    tilt label is optional enrichment, not load-bearing like the cells)."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    (Path(paths.data_dir) / "lab" / DIAL_PROFILE_FILENAME).write_bytes(b"not a parquet")
    curve = load_ticker_curve(paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert curve.profile_label_status == "UNAVAILABLE"
    assert curve.available  # the page itself is unaffected
    html = _render_lab_curve_page(curve)
    assert "historical tilt" not in html  # label hidden
    assert "lab-profile" in html  # chart still renders

    paths2, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    pd.DataFrame({"ticker": ["AAA"]}).to_parquet(
        Path(paths2.data_dir) / "lab" / DIAL_PROFILE_FILENAME, index=False
    )
    curve2 = load_ticker_curve(paths2, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert curve2.profile_label_status == "UNAVAILABLE"
    assert curve2.available


def test_real_build_meta_registers_profile_artifact() -> None:
    """Guards build_and_save's manifest wiring for the profile artifact on REAL
    output: active once artifacts are built (e.g. after a rebuild), skipped in a
    dataless environment. A build that stops emitting dial_profile, or drops it from
    run_stamped_artifacts / latest_aliases, fails here."""

    from golden_vector.app.paths import ProjectPaths
    from golden_vector.lab.conditional_dial import PROFILE_COLUMNS
    from golden_vector.lab.vintages import lab_dir

    lab = lab_dir(ProjectPaths.discover())
    meta_path = lab / DIAL_ARTIFACT_META_FILENAME
    profile_path = lab / DIAL_PROFILE_FILENAME
    if not meta_path.exists() or not profile_path.exists():
        pytest.skip("real lab artifacts not built")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "profile" in meta.get("run_stamped_artifacts", {})
    assert meta.get("latest_aliases", {}).get("profile") == DIAL_PROFILE_FILENAME
    assert "profile_rows" in meta
    assert list(pd.read_parquet(profile_path).columns) == PROFILE_COLUMNS


# ---- v3: distribution strip (spread of scenario outcomes) + collapsed dots -----


def _strip_pt(date, a_simple, beat, *, scenario=True):
    """A hand-built drill-down point for the strip (carries alpha_simple, the
    simple-return per-week alpha the strip plots)."""
    return {
        "date": date, "alpha": None, "alpha_simple": a_simple, "beat": beat,
        "is_scenario": scenario, "is_anchor": False,
    }


def _strip_curve(points, cell, *, benchmark="GDX"):
    from golden_vector.serve.lab_curve_data import LabCurveData

    return LabCurveData(
        available=True, ticker="ZZZ", benchmark=benchmark, horizon=13,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%",
        points=points, cell=cell,
    )


def test_distribution_strip_persisted_median_and_shared_basis() -> None:
    """v3 fix (Codex/panel): ticks are plotted from alpha_simple and the marker from
    the PERSISTED cell median — SAME basis. The marker is NOT recomputed from the
    ticks (persisted median deliberately != median of the ticks), it shares the tick
    axis (sits within the tick range), and non-scenario weeks are excluded."""

    import re

    from golden_vector.serve.lab_curve_page import _render_distribution

    pts = [
        _strip_pt("2020-01-01", 0.50, True),
        _strip_pt("2020-02-01", -0.20, False),
        _strip_pt("2020-03-01", 0.10, True),
        _strip_pt("2020-04-01", 5.00, True, scenario=False),  # non-scenario -> excluded
    ]
    # Persisted median -0.07 != median([0.50,-0.20,0.10]) = 0.10, so a serve-side
    # recompute would print 'median +10%' instead of 'median -7%'.
    cell = {"median_alpha_gdx": -0.07, "gdx_insufficient_history": False, "p_beat_gdx": 0.66}
    html = _render_distribution(_strip_curve(pts, cell))
    assert "Spread of outcomes" in html and "lab-dist-svg" in html
    assert "median -7%" in html  # the PERSISTED cell median
    assert "median +10%" not in html  # NOT the recomputed tick median
    assert html.count("vs GDX</title>") == 3  # scenario-only ticks
    tick_xs = [float(x) for x in re.findall(r"<line x1=\"([\d.]+)\" y1=\"22.0\"", html)]
    marker_x = float(re.search(r"<path d=\"M ([\d.]+) ", html).group(1))
    assert len(tick_xs) == 3
    assert min(tick_xs) <= marker_x <= max(tick_xs)  # marker shares the ticks' axis/basis


def test_distribution_strip_clamps_out_of_range_median() -> None:
    """F2: a persisted median outside the tick range is clamped into the plot box,
    never drawn off-canvas where it would silently vanish (while aria still names it)."""

    import re

    from golden_vector.serve.lab_curve_page import _render_distribution

    pts = [_strip_pt("a", 0.05, True), _strip_pt("b", -0.03, False)]
    cell = {"median_alpha_gdx": 5.0, "gdx_insufficient_history": False, "p_beat_gdx": 0.5}
    html = _render_distribution(_strip_curve(pts, cell))
    marker_x = float(re.search(r"<path d=\"M ([\d.]+) ", html).group(1))
    assert 42.0 <= marker_x <= 742.0  # clamped into [left, width-right]
    # A1: a pinned marker must SAY it is off scale, not pose as the true position.
    assert "median +500% (off scale)" in html


def test_distribution_strip_absent_when_insufficient_or_all_nan() -> None:
    """No strip when the cell is insufficient, there are < 2 scenario weeks, or every
    scenario alpha is NaN (collapses to < 2 usable)."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_distribution

    assert _render_distribution(
        LabCurveData(available=True, ticker="ZZZ", benchmark="GDX", horizon=13, cell=None, points=[])
    ) == ""
    ok_cell = {"gdx_insufficient_history": False, "median_alpha_gdx": 0.0}
    assert _render_distribution(_strip_curve([_strip_pt("a", 0.1, True)], ok_cell)) == ""  # < 2
    all_nan = [_strip_pt("a", float("nan"), True), _strip_pt("b", float("nan"), False)]
    assert _render_distribution(_strip_curve(all_nan, ok_cell)) == ""  # all NaN -> < 2 usable


def test_distribution_strip_all_negative_keeps_zero_on_axis() -> None:
    """An all-lagged scenario still renders a valid strip with the zero baseline on
    the axis (the [*alphas, 0.0] guard) and lag-coloured ticks."""

    from golden_vector.serve.lab_curve_page import _LAG_CLASS, _render_distribution

    pts = [_strip_pt("a", -0.30, False), _strip_pt("b", -0.10, False), _strip_pt("c", -0.05, False)]
    cell = {"median_alpha_gdx": -0.10, "gdx_insufficient_history": False, "p_beat_gdx": 0.0}
    html = _render_distribution(_strip_curve(pts, cell))
    assert "lab-dist-svg" in html
    assert ">0</text>" in html  # zero baseline label present (stays on-axis)
    assert _LAG_CLASS in html  # ticks carry the lag series class


def test_distribution_strip_renders_for_gdxj() -> None:
    """The strip reads the BENCHMARK-specific persisted median (median_alpha_gdxj) and
    labels ticks 'vs GDXJ' — guards the per-column mapping that broke once."""

    from golden_vector.serve.lab_curve_page import _render_distribution

    pts = [_strip_pt("a", 0.20, True), _strip_pt("b", -0.05, False)]
    cell = {
        "median_alpha_gdxj": 0.04, "gdxj_insufficient_history": False, "p_beat_gdxj": 0.6,
        "median_alpha_gdx": 0.99, "gdx_insufficient_history": False,  # gdx values must NOT be used
    }
    html = _render_distribution(_strip_curve(pts, cell, benchmark="GDXJ"))
    assert html.count("vs GDXJ</title>") == 2
    assert "median +4%" in html  # the gdxj column
    assert "median +99%" not in html  # NOT the gdx column


def test_chart_a_week_by_week_is_collapsed_under_details() -> None:
    """v3: the dense week-by-week dot scatter is tucked under a collapsed <details>
    toggle (de-cluttered) but still fully present with its honesty captions."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    curve = load_ticker_curve(paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    html = _render_lab_curve_page(curve)
    assert "<details class=\"panel lab-curve-chart\">" in html  # collapsed, not a always-open section
    assert "When did it happen?" in html  # the summary toggle
    assert "lab-dots-svg" in html  # the dots chart is still there
    assert "hindsight grouping" in html  # honesty caption preserved
    # the new spread strip renders above it for this healthy scenario
    assert "Spread of outcomes" in html and "lab-dist-svg" in html


# ---- holistic-review fixes: one basis end-to-end + manifest-resolved reads ------


def _dots_pt(date, alpha, alpha_simple, beat, *, scenario=True):
    return {
        "date": date, "alpha": alpha, "alpha_simple": alpha_simple, "beat": beat,
        "is_scenario": scenario, "is_anchor": False,
    }


def test_dots_chart_plots_simple_return_not_log() -> None:
    """B1 (holistic): the week-by-week dots now plot alpha_simple (simple return) —
    the SAME basis as the strip/bar/label — not the raw log gap, so the whole page
    speaks one basis. Uses an episode where log (0.50) and simple (0.65) clearly
    diverge so a regression to log fails."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_chart_a

    pts = [
        _dots_pt("2020-01-01", 0.50, 0.65, True),
        _dots_pt("2020-02-01", -0.20, -0.18, False),
        _dots_pt("2020-03-01", 0.10, 0.105, True, scenario=False),
    ]
    curve = LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%", points=pts,
    )
    html = _render_chart_a(curve)
    assert "+65.0% vs GDX" in html  # simple-return alpha_simple
    assert "+50.0% vs GDX" not in html  # NOT the log gap
    assert "outperformance vs GDX" in html  # axis no longer says "alpha"


def test_full_page_dots_and_strip_agree_on_one_basis() -> None:
    """B1/B3 (holistic): on the full rendered page the dots and the distribution strip
    show the SAME magnitude for the same episode (one simple-return basis), and the log
    gap appears nowhere."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    pts = [
        _dots_pt("2020-01-01", 0.50, 0.65, True),
        _dots_pt("2020-02-01", -0.20, -0.18, False),
    ]
    cell = {
        "p_beat_gdx": 0.50, "p_beat_gdx_shrunk": 0.50, "median_alpha_gdx": 0.65,
        "gdx_effective_n": 9.0, "gdx_n_weeks": 18, "gdx_insufficient_history": False,
        "gdx_wilson_low": 0.3, "gdx_wilson_high": 0.7,
    }
    curve = LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%",
        points=pts, cell=cell,
    )
    html = _render_lab_curve_page(curve)
    assert "+65.0% vs GDX" in html  # dots tooltip (.1f), simple
    assert "+65% vs GDX" in html  # strip tooltip (.0f), simple — same magnitude
    assert "+50.0% vs GDX" not in html  # the log gap is shown nowhere on the page


def test_thin_ticker_degrades_across_all_surfaces() -> None:
    """B3: an insufficient cell suppresses the win-rate bar AND the spread strip while
    the page still renders honestly (no confident headline)."""

    from golden_vector.serve.lab_curve_data import LabCurveData
    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    pts = [_dots_pt("2020-01-01", 0.5, 0.65, True), _dots_pt("2020-02-01", -0.2, -0.18, False)]
    cell = {"gdx_insufficient_history": True, "median_alpha_gdx": None, "p_beat_gdx": None}
    curve = LabCurveData(
        available=True, ticker="ZZZ", benchmark="GDX", horizon=13,
        scenario_bucket="gold_down", scenario_label="Gold down 5% to 15%",
        points=pts, cell=cell,
    )
    html = _render_lab_curve_page(curve)
    assert "Spread of outcomes" not in html  # strip suppressed
    assert "winrate-bar" not in html  # win-rate bar suppressed
    assert "Not enough independent" in html  # honest degrade, no confident rate


def test_loader_reads_run_stamped_artifact_via_meta_not_mutable_latest() -> None:
    """B2 (holistic): serve resolves artifact paths through dial_meta.json's
    run_stamped_artifacts (the atomic pointer), so a torn mutable latest alias from a
    half-finished rebuild is never read — the loader serves the last COHERENT
    run-stamped set."""

    import shutil

    paths, _ = _write(tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"])
    lab = Path(paths.data_dir) / "lab"
    stamp = "20260101T000000Z"
    stamped: dict[str, str] = {}
    for key, latest in (
        ("cells", DIAL_CELLS_FILENAME),
        ("episodes", DIAL_EPISODES_FILENAME),
        ("relstrength", DIAL_RELSTRENGTH_FILENAME),
        ("profile", DIAL_PROFILE_FILENAME),
    ):
        name = latest.replace("_latest", f"_{stamp}")
        shutil.copy(lab / latest, lab / name)  # immutable run-stamped copy
        stamped[key] = name
    meta = json.loads((lab / DIAL_ARTIFACT_META_FILENAME).read_text())
    meta["run_stamped_artifacts"] = stamped
    (lab / DIAL_ARTIFACT_META_FILENAME).write_text(json.dumps(meta))
    # Simulate a half-finished rebuild: the mutable latest cells alias is torn/garbage.
    (lab / DIAL_CELLS_FILENAME).write_bytes(b"torn half-written rebuild, not parquet")

    curve = load_ticker_curve(paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX")
    assert curve.available  # served the coherent run-stamped cells, ignored the torn latest
    assert curve.error_status is None
    assert curve.cell is not None


def test_default_lab_horizon_comes_from_config(monkeypatch) -> None:
    """C3: the Lab default horizon is the config's default_profile_horizon, not a
    hardcoded 13 duplicated in the routes."""

    from golden_vector.contracts.config_models import GoldProfileConfig
    from golden_vector.serve import lab_curve_data as lcd

    monkeypatch.setattr(
        lcd,
        "default_gold_profile_config",
        lambda: GoldProfileConfig(default_profile_horizon=8),
    )
    assert lcd.default_lab_horizon() == 8


# A tmp dir for the loader-roundtrip tests that do not take the pytest fixture
# (keeps the assertion bodies flat and explicit).
def tmp_path_for() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="lab_curve_test_"))


@pytest.mark.parametrize(
    ("status", "expected_tone"),
    [
        ("CORRUPT", "notice-danger"),
        ("META_MISSING", "notice-danger"),
        ("META_CORRUPT", "notice-danger"),
        ("CELLS_MISSING", "notice-danger"),
        ("CELLS_CORRUPT", "notice-danger"),
        ("STALE", "notice-warning"),  # plan 10.5: stale = freshness warning
        ("CELLS_STALE", "notice-warning"),
        ("CELLS_EMPTY", "notice-warning"),
        ("EMPTY", "notice-warning"),
        ("UNKNOWN_SCENARIO", "notice-warning"),
        ("SOMETHING_NEW", "notice-warning"),  # unknown -> "no episodes" copy, never danger
    ],
)
def test_drilldown_unavailable_state_to_tone_mapping(status, expected_tone):
    """Codex Phases-3/4 finding 2: section-10.5 mapping at the drilldown call
    site — corrupt/unreadable stays danger, stale/empty/URL problems warn."""
    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    from golden_vector.serve.lab_curve_data import LabCurveData

    html = _render_lab_curve_page(
        LabCurveData(available=False, ticker="NEM", benchmark="GDX", error_status=status)
    )
    other = "notice-danger" if expected_tone == "notice-warning" else "notice-warning"
    assert expected_tone in html
    assert other not in html
    if status == "UNKNOWN_SCENARIO":
        assert "Rebuild:" not in html  # URL typo advice must not say rebuild


def test_overview_all_nan_horizons_reports_empty_not_available() -> None:
    """Cells rows exist but not one carries a horizon: nothing is selectable, so
    every downstream filter yields zero rows. Reporting available=True there
    renders an empty table as though the data were healthy."""

    paths, _ = _write(
        tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"]
    )
    cells_path = Path(paths.data_dir) / "lab" / DIAL_CELLS_FILENAME
    cells = pd.read_parquet(cells_path)
    assert not cells.empty  # the frame itself is NOT empty — only the horizons are
    cells["horizon_weeks"] = np.nan
    cells.to_parquet(cells_path, index=False)

    data = load_dial_cells(paths, horizon=13, bucket="gold_down")

    assert data.available is False
    assert data.error_status == "EMPTY"
    assert data.rows == [] or not data.rows


def test_overview_healthy_horizons_still_available() -> None:
    """Control for the all-NaN guard: untouched cells still report available."""

    paths, _ = _write(
        tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"]
    )

    data = load_dial_cells(paths, horizon=13, bucket="gold_down")

    assert data.available is True
    assert data.error_status is None
    assert data.rows


def test_chart_b_reports_empty_relstrength_artifact() -> None:
    """An EMPTY relstrength artifact is a broken build, not a thin ticker, so it
    must be as loud as MISSING/CORRUPT rather than drawing a blank line."""

    from golden_vector.serve.lab_curve_page import _render_lab_curve_page

    paths, _ = _write(
        tmp_path_for(), parity_weekly_frame(), horizons=[13], benchmarks=["GDX", "GDXJ"]
    )
    rel_path = Path(paths.data_dir) / "lab" / DIAL_RELSTRENGTH_FILENAME
    # Correct columns, zero rows: reads fine, carries nothing.
    pd.read_parquet(rel_path).iloc[0:0].to_parquet(rel_path, index=False)

    curve = load_ticker_curve(
        paths, ticker="AAA", scenario_bucket="gold_down", horizon=13, benchmark="GDX"
    )

    assert curve.relstrength_status == "EMPTY"
    html = _render_lab_curve_page(curve)
    assert "Relative-strength artifact is empty" in html
    # Chart A (the counted evidence) is unaffected.
    assert "lab-dots-svg" in html
