"""Lab workspace page: render-level behavior + serve-purity guardrail."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from golden_vector.lab.conditional_dial import (
    DIAL_ARTIFACT_META_FILENAME,
    DIAL_BENCHMARKS,
    DIAL_CELLS_FILENAME,
    DIAL_EPISODES_FILENAME,
    DIAL_HORIZONS_WEEKS,
    DIAL_SCHEMA_VERSION,
    build_dial_cells_wide,
    build_episode_artifact,
    dial_config_hash,
)
from golden_vector.serve.lab_curve_data import load_dial_cells
from golden_vector.serve.overview_lab import _render_dial_row, _render_lab_overview_page


class _FakePaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


def _dial_frame() -> pd.DataFrame:
    """200 weeks; gold alternates down/up regimes; WIN always beats GDX, LOSE
    always trails (matches the experiments fixture)."""

    grid = [str(p) for p in pd.period_range("2010-01-08", periods=200, freq="W-FRI")]
    gold = [-0.012 if i % 26 < 13 else 0.012 for i in range(200)]
    rows = []
    for ticker, edge in (("WIN", 0.004), ("LOSE", -0.004)):
        for i in range(200):
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


def _write_artifacts(
    tmp_path: Path,
    *,
    frame: pd.DataFrame | None = None,
    horizons: list[int] | None = None,
    min_eff: float = 2.0,
    schema_version: int = DIAL_SCHEMA_VERSION,
) -> _FakePaths:
    frame = _dial_frame() if frame is None else frame
    horizons = horizons or [13]
    benchmarks = ["GDX", "GDXJ"]
    cells = build_dial_cells_wide(
        frame, horizons=horizons, benchmarks=benchmarks, min_effective_n=min_eff
    )
    episodes = build_episode_artifact(frame, horizons=horizons, benchmarks=benchmarks)
    lab = tmp_path / "lab"
    lab.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(lab / DIAL_CELLS_FILENAME, index=False)
    episodes.to_parquet(lab / DIAL_EPISODES_FILENAME, index=False)

    availability: dict[str, dict[str, int]] = {}
    if not cells.empty:
        insufficient = cells["gdx_insufficient_history"].fillna(True).astype(bool)
        for horizon in horizons:
            hz_mask = cells["horizon_weeks"] == int(horizon)
            per_bucket: dict[str, int] = {}
            for bucket_name in cells.loc[hz_mask, "bucket"].unique():
                per_bucket[str(bucket_name)] = int(
                    (hz_mask & (cells["bucket"] == bucket_name) & (~insufficient)).sum()
                )
            availability[str(int(horizon))] = per_bucket
    meta = {
        "schema_version": schema_version,
        # Loader checks config_hash vs the LIVE config; stamp the live-default hash
        # (fixture builds a horizon subset for speed; tests query within it).
        "config_hash": dial_config_hash(DIAL_HORIZONS_WEEKS, DIAL_BENCHMARKS),
        "horizons_weeks": [int(h) for h in horizons],
        "benchmarks": benchmarks,
        "usable_gdx_cells_by_horizon_bucket": availability,
        "caveat": "Exploratory, survivor-only universe.",
        "built_at_utc": "2026-06-13T00:00:00+00:00",
    }
    (lab / DIAL_ARTIFACT_META_FILENAME).write_text(json.dumps(meta))
    return _FakePaths(tmp_path)


def test_lab_page_renders_ranked_rows_caveat_and_gdxj(tmp_path) -> None:
    paths = _write_artifacts(tmp_path)
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")  # type: ignore[arg-type]
    assert data.available
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    # Backend rank order: WIN before LOSE.
    assert html.index(">WIN<") < html.index(">LOSE<")
    assert "Exploratory, survivor-only universe." in html
    assert "Gold down 5% to 15%" in html
    assert "episode-adjusted" in html
    # GDXJ comparison column + horizon selector present.
    assert "P(beat GDXJ)" in html
    assert "26w" in html or "Look-ahead" in html
    # Ticker links to the drill-down carrying scenario + horizon + benchmark
    # (& is HTML-escaped to &amp; in the rendered attribute).
    assert "/lab/dial/WIN?scenario=gold_down&amp;horizon=13&amp;benchmark=GDX" in html


def test_lab_page_all_insufficient_shows_table_with_banner_and_no_links(tmp_path) -> None:
    """When no miner has history, the TABLE still renders (every miner listed),
    a banner explains why, and the no-data rows are greyed + non-clickable."""

    paths = _write_artifacts(tmp_path, min_eff=999.0)  # forces every cell insufficient
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")  # type: ignore[arg-type]
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    # Table is always shown (no full-page takeover), with a slim explanatory banner.
    assert 'id="lab-dial-table"' in html
    assert "No miner has countable history" in html
    assert "insufficient history" in html
    # The miners are listed (greyed, with a non-colour "(no data)" cue) but NOT
    # clickable (no drill-down links for no-data rows).
    assert 'lab-no-data">WIN ' in html and 'lab-no-data">LOSE ' in html
    assert "(no data)" in html
    assert "/lab/dial/WIN" not in html
    assert "lab-row-insufficient" in html


def test_banner_derives_from_rows_not_meta(tmp_path) -> None:
    """The banner's usable count comes from the SAME rows the table renders, not
    from meta — so a stale/empty meta can't claim 'no countable history' above
    ranked, clickable miners (the two-truths bug)."""

    paths = _write_artifacts(tmp_path, min_eff=2.0)  # healthy, clickable rows
    # Wipe meta's availability map (simulate stale/partial meta) — must NOT matter.
    meta_path = tmp_path / "lab" / DIAL_ARTIFACT_META_FILENAME
    meta = json.loads(meta_path.read_text())
    meta["usable_gdx_cells_by_horizon_bucket"] = {}
    meta_path.write_text(json.dumps(meta))
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")  # type: ignore[arg-type]
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    assert "No miner has countable history" not in html  # would fire off stale meta (the bug)
    assert "/lab/dial/WIN" in html  # ranked + clickable, as the rows say


def test_insufficient_row_numeric_cells_sort_last(tmp_path) -> None:
    """Greyed (insufficient) rows must carry the sort-last sentinel on numeric
    cells so they never interleave with ranked rows; the episodes cell carries a
    real numeric sort key."""

    from golden_vector.serve.format_helpers import _MISSING_SORT_SENTINEL
    from golden_vector.serve.overview_lab import _render_dial_row

    insufficient = {
        "ticker": "SPARSE",
        "bucket": "gold_down",
        "horizon_weeks": 13,
        "gdx_insufficient_history": True,
        "rank_in_bucket": None,
        "gdx_n_weeks": 40,
        "gdx_effective_n": 3.1,
    }
    html = _render_dial_row(insufficient, selected_bucket="gold_down", horizon=13)
    # rank + 4 numeric stat columns all carry the sentinel (>=5 occurrences).
    assert html.count(f'data-order="{_MISSING_SORT_SENTINEL}"') >= 4
    # The episodes column sorts by effective N, not as NaN.
    assert 'data-order="3.1"' in html


def test_lab_page_degrades_when_artifact_missing(tmp_path) -> None:
    data = load_dial_cells(_FakePaths(tmp_path), bucket=None)  # type: ignore[arg-type]
    assert not data.available
    assert data.error_status == "MISSING"
    html = _render_lab_overview_page(data, selected_bucket="")
    assert "Lab artifacts are not built yet" in html


def test_lab_loader_defaults_to_normal_downside_bucket(tmp_path) -> None:
    paths = _write_artifacts(tmp_path)
    data = load_dial_cells(paths, horizon=13, bucket=None)  # type: ignore[arg-type]
    assert data.available
    assert data.rows
    assert {row["bucket"] for row in data.rows} == {"gold_down"}


def test_lab_page_flags_stale_schema(tmp_path) -> None:
    paths = _write_artifacts(tmp_path, schema_version=DIAL_SCHEMA_VERSION - 1)
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")  # type: ignore[arg-type]
    assert not data.available
    assert data.error_status == "STALE"
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    assert "out of date" in html


def test_lab_page_flags_missing_metadata_distinctly(tmp_path) -> None:
    """Intact cells + a missing meta sidecar -> a metadata message, NOT the
    'older schema / missing columns' stale message."""

    paths = _write_artifacts(tmp_path)
    (tmp_path / "lab" / DIAL_ARTIFACT_META_FILENAME).unlink()  # remove meta only
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")  # type: ignore[arg-type]
    assert not data.available
    assert data.error_status == "META_MISSING"
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    assert "metadata is missing or unreadable" in html
    assert "out of date" not in html  # not misdiagnosed as stale


def test_lab_page_flags_empty_universe_distinctly(tmp_path) -> None:
    """A built-but-empty cells parquet -> EMPTY (not 'not built yet')."""

    import pandas as pd

    from golden_vector.lab.conditional_dial import CELLS_COLUMNS

    lab = tmp_path / "lab"
    lab.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=CELLS_COLUMNS).to_parquet(lab / DIAL_CELLS_FILENAME, index=False)
    data = load_dial_cells(_FakePaths(tmp_path), bucket="gold_down")  # type: ignore[arg-type]
    assert not data.available
    assert data.error_status == "EMPTY"
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    assert "empty universe" in html


def test_lab_route_serves_table_and_drilldown(tmp_path) -> None:
    from tests.helpers import build_test_paths
    from tests.test_workspace_app import _call_wsgi_app, _repo_app_config

    from golden_vector.serve.workspace import create_workspace_app

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_artifacts(Path(paths.data_dir))

    app = create_workspace_app(
        paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"]
    )
    response = _call_wsgi_app(app, method="GET", path="/lab?bucket=not_a_bucket&horizon=13")
    assert str(response["status"]).startswith("200")
    body = str(response["body"])
    assert "Gold Scenario Analogs" in body
    assert ">WIN<" in body
    assert ">Lab</a>" in body

    drill = _call_wsgi_app(
        app, method="GET", path="/lab/dial/WIN?scenario=gold_down&horizon=13&benchmark=GDX"
    )
    assert str(drill["status"]).startswith("200")
    drill_body = str(drill["body"])
    assert "relative performance vs GDX" in drill_body
    assert "benchmark=GDXJ" in drill_body  # toggle link
    assert "hindsight grouping" in drill_body


def test_lab_route_default_horizon_comes_from_config(tmp_path, monkeypatch) -> None:
    """C3 (Codex LOW): with no ?horizon=, the /lab route defaults to the config's
    default_profile_horizon (set here to 8), not a hardcoded 13. Proves the config
    knob is actually wired into the route."""
    import yaml

    from tests.helpers import build_test_paths
    from tests.test_lab_dial_panel_parity import parity_weekly_frame
    from tests.test_workspace_app import _call_wsgi_app, _repo_app_config

    from golden_vector.app.paths import ProjectPaths
    from golden_vector.serve.workspace import create_workspace_app

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    # Point the config loader at this workspace's config and set the default to 8.
    yaml_path = paths.config_path("lab_gold_profile.yaml")
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["default_profile_horizon"] = 8
    yaml_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(ProjectPaths, "discover", classmethod(lambda cls: paths))

    _write_artifacts(Path(paths.data_dir), frame=parity_weekly_frame(), horizons=[8, 13])
    app = create_workspace_app(paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/lab")  # no ?horizon=
    assert str(response["status"]).startswith("200")
    assert "value=\"8\" selected" in str(response["body"])  # 8w is the default-selected horizon


def test_lab_serve_layer_has_no_dial_arithmetic() -> None:
    """The Lab pages render backend-resolved columns only: no counting,
    shrinkage, interval math, rebasing, or rank decisions in serve — and the
    gold-tilt LABEL is read from the persisted artifact, never re-decided here (the
    category words must not appear as serve literals, nor any tilt aggregation)."""

    for module in ("overview_lab.py", "lab_curve_data.py", "lab_curve_page.py"):
        source = Path(f"golden_vector/serve/{module}").read_text(encoding="utf-8")
        for forbidden in (
            "_wilson_interval",
            "build_dial_table",
            "build_episode_frame",
            "build_forward_return_panel",
            "build_profile_artifact",  # the tilt/label is build-computed, never in serve
            "_assign_bucket",
            "_is_above(",  # beat decision must be read from the persisted column
            ".mean(",
            ".median(",
            ".quantile(",
            ".groupby(",
            ".fillna(",
            ".cumsum(",
            "forward_sum",
            "effective_n(",
            "np.exp",
            "math.exp",
            "EB_PRIOR",
            "cumcount",
            ".rank(",
            # The Defensive/Steady/Pro-cyclical label is DECIDED in the build; serve
            # only echoes the persisted gold_tilt_label string. Forbid the bare
            # category words in ANY form (quote-style independent) so a single-quoted
            # or dynamically-built serve-side decision can't evade the scan — serve
            # never needs these words in source (it renders curve.profile_label).
            "Defensive",
            "Pro-cyclical",
            "Steady",
            "_gold_tilt_label(",  # the threshold->label decision helper is build-only
            # Hand-rolled aggregation smells (a mean computed in serve). min()/max()
            # for axis geometry stay allowed; a recomputed median/quantile is caught
            # behaviorally by the distribution-strip persisted-median test.
            "/ len(",
            "/len(",
            # Behaviour layer (Phase 4): serve renders the persisted capture / peer /
            # trend columns + labels; it must NEVER re-derive them. Forbid every
            # behaviour COMPUTE entry point (the archetype/label decision needs the
            # cutoffs + these helpers, none of which belong in serve). Column NAMES and
            # the echoed enum strings are allowed — only the computation is banned.
            "compute_capture_table",
            "compute_peer_points",
            "compute_peer_snapshot",
            "compute_trend_table",
            "build_capture",
            "_archetype(",
            "_capture_side(",
            "_beat_label(",
            "_alpha_label(",
            "_trend_record(",
            "mann_kendall(",
            "theil_sen(",
            "benjamini_hochberg(",
            "two_proportion_p(",
            "mde_proportion_pp(",
            "peer_percentile(",
            "decay_weights(",
            "decay_effective_n(",
        ):
            assert forbidden not in source, f"{module}: {forbidden}"


def test_dial_rows_have_one_cell_per_header_column() -> None:
    """DataTables counts <td> cells — every row type must emit exactly 10 (the
    new GDXJ comparison column makes it 10, not 9)."""

    import re

    healthy = {
        "ticker": "AEM",
        "bucket": "gold_down",
        "horizon_weeks": 13,
        "gdx_insufficient_history": False,
        "rank_in_bucket": 1,
        "p_beat_gdx_shrunk": 0.7,
        "p_beat_gdx": 0.8,
        "p_beat_gdxj_shrunk": 0.65,
        "gdxj_insufficient_history": False,
        "gdx_wilson_low": 0.5,
        "gdx_wilson_high": 0.9,
        "median_alpha_gdx": 0.1,
        "alpha_q10_gdx": -0.1,
        "alpha_q90_gdx": 0.3,
        "gdx_n_weeks": 150,
        "gdx_effective_n": 11.5,
    }
    insufficient = {
        "ticker": "SPARSE",
        "bucket": "gold_down",
        "horizon_weeks": 13,
        "gdx_insufficient_history": True,
        "rank_in_bucket": None,
        "gdx_n_weeks": 40,
        "gdx_effective_n": 3.1,
    }
    for row in (healthy, insufficient):
        html = _render_dial_row(row, selected_bucket="gold_down", horizon=13)
        assert len(re.findall(r"<td", html)) == 10
        assert "colspan" not in html
