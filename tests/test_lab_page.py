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
    html = _render_lab_overview_page(data, selected_bucket="gold_down", selected_horizon=13)
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


def test_lab_page_empty_state_when_all_cells_insufficient(tmp_path) -> None:
    paths = _write_artifacts(tmp_path, min_eff=999.0)  # forces every cell insufficient
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")  # type: ignore[arg-type]
    html = _render_lab_overview_page(data, selected_bucket="gold_down", selected_horizon=13)
    # Evidence-collapse view: explanation, no sortable ranking table.
    assert "No countable history" in html
    assert 'id="lab-dial-table"' not in html
    assert "out-of-sample" in html


def test_lab_page_degrades_when_artifact_missing(tmp_path) -> None:
    data = load_dial_cells(_FakePaths(tmp_path), bucket=None)  # type: ignore[arg-type]
    assert not data.available
    assert data.error_status == "MISSING"
    html = _render_lab_overview_page(data, selected_bucket="", selected_horizon=13)
    assert "Lab artifacts are not built yet" in html


def test_lab_page_flags_stale_schema(tmp_path) -> None:
    paths = _write_artifacts(tmp_path, schema_version=DIAL_SCHEMA_VERSION - 1)
    data = load_dial_cells(paths, horizon=13, bucket="gold_down")  # type: ignore[arg-type]
    assert not data.available
    assert data.error_status == "STALE"
    html = _render_lab_overview_page(data, selected_bucket="gold_down", selected_horizon=13)
    assert "older version" in html


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


def test_lab_serve_layer_has_no_dial_arithmetic() -> None:
    """The Lab pages render backend-resolved columns only: no counting,
    shrinkage, interval math, rebasing, or rank decisions in serve."""

    for module in ("overview_lab.py", "lab_curve_data.py", "lab_curve_page.py"):
        source = Path(f"golden_vector/serve/{module}").read_text(encoding="utf-8")
        for forbidden in (
            "_wilson_interval",
            "build_dial_table",
            "build_episode_frame",
            "build_forward_return_panel",
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
