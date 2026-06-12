"""Lab workspace page: render-level behavior + serve-purity guardrail."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from golden_vector.lab.conditional_dial import (
    DIAL_META_FILENAME,
    DIAL_TABLE_FILENAME,
    build_dial_table,
)
from golden_vector.serve.lab_data import load_lab_dial_data
from golden_vector.serve.overview_lab import _render_lab_overview_page


class _FakePaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


def _write_dial_artifact(tmp_path: Path) -> _FakePaths:
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
    table = build_dial_table(
        pd.DataFrame(rows), horizon_weeks=13, min_effective_n=2.0
    )
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir(parents=True)
    table.to_parquet(lab_dir / DIAL_TABLE_FILENAME, index=False)
    (lab_dir / DIAL_META_FILENAME).write_text(
        json.dumps(
            {
                "built_at_utc": "2026-06-12T10:00:00+00:00",
                "caveat": "Exploratory, survivor-only universe.",
            }
        )
    )
    return _FakePaths(tmp_path)


def test_lab_page_renders_ranked_rows_and_caveat(tmp_path) -> None:
    paths = _write_dial_artifact(tmp_path)
    data = load_lab_dial_data(paths, bucket="gold_down")  # type: ignore[arg-type]
    assert data.available
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    # Backend rank order: WIN must appear before LOSE in the rendered body.
    assert html.index(">WIN<") < html.index(">LOSE<")
    assert "Exploratory, survivor-only universe." in html
    assert "Gold down 5% to 15%" in html
    assert "episode-adjusted" in html


def test_lab_page_insufficient_cells_show_no_numbers(tmp_path) -> None:
    paths = _write_dial_artifact(tmp_path)
    # Force every cell insufficient by reloading with a tougher artifact.
    lab_dir = tmp_path / "lab"
    frame = pd.read_parquet(lab_dir / DIAL_TABLE_FILENAME)
    frame["insufficient_history"] = True
    for column in (
        "p_beat_gdx",
        "p_beat_gdx_shrunk",
        "wilson_low",
        "wilson_high",
        "median_alpha",
        "alpha_q10",
        "alpha_q90",
    ):
        frame[column] = None
    frame.to_parquet(lab_dir / DIAL_TABLE_FILENAME, index=False)
    data = load_lab_dial_data(paths, bucket="gold_down")  # type: ignore[arg-type]
    html = _render_lab_overview_page(data, selected_bucket="gold_down")
    assert "insufficient history" in html
    assert "%" not in html.split("<tbody>")[1].split("</tbody>")[0]


def test_lab_page_degrades_when_artifact_missing(tmp_path) -> None:
    data = load_lab_dial_data(_FakePaths(tmp_path), bucket=None)  # type: ignore[arg-type]
    assert not data.available
    html = _render_lab_overview_page(data, selected_bucket="")
    assert "Lab artifacts are not built yet" in html


def test_lab_route_serves_table_and_falls_back_on_unknown_bucket(tmp_path) -> None:
    from tests.helpers import build_test_paths
    from tests.test_workspace_app import _call_wsgi_app, _repo_app_config

    from golden_vector.serve.workspace import create_workspace_app

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_dial_artifact(Path(paths.data_dir))

    app = create_workspace_app(
        paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"]
    )
    response = _call_wsgi_app(app, method="GET", path="/lab?bucket=not_a_bucket")
    assert str(response["status"]).startswith("200")
    body = str(response["body"])
    # Unknown bucket falls back to the first bucket rather than erroring.
    assert "Gold Scenario Analogs" in body
    assert ">WIN<" in body
    # Nav tab present on the shell.
    assert ">Lab</a>" in body


def test_lab_serve_layer_has_no_dial_arithmetic() -> None:
    """The Lab page renders backend-resolved columns only: no counting,
    shrinkage, interval math, or rank decisions may creep into serve."""

    for module in ("overview_lab.py", "lab_data.py"):
        source = Path(f"golden_vector/serve/{module}").read_text(encoding="utf-8")
        for forbidden in (
            "_wilson_interval",
            "build_dial_table",
            ".mean(",
            ".median(",
            ".quantile(",
            ".groupby(",
            "effective_n(",
            "np.exp",
            "math.exp",
            "EB_PRIOR",
            "cumcount",
            ".rank(",
        ):
            assert forbidden not in source, f"{module}: {forbidden}"
        # Sorting only on the ONE backend-provided rank column.
        if "sort_values" in source:
            assert source.count("sort_values") == 1
            assert 'sort_values("rank_in_bucket")' in source
