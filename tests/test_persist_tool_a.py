from datetime import date

import numpy as np
import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import (
    persist_tool_a_outputs,
)
from golden_vector.model.pipeline import execute_tool_a_profile_pipeline
from tests.helpers import build_test_paths


def test_persist_tool_a_outputs_writes_full_and_latest_exports(tmp_path):
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    tool_a_outputs = pd.DataFrame(
        [
            {"ticker": "GOLD", "as_of_date": date(2026, 1, 31), "tool_a_rank": 2},
            {"ticker": "NEM", "as_of_date": date(2026, 1, 31), "tool_a_rank": 1},
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "tool_a_rank": 2},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "tool_a_rank": 1},
        ]
    )

    written_paths = persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=tool_a_outputs,
    )

    assert len(written_paths) == 7
    latest_csv_path = next(path for path in written_paths if path.name.endswith("latest_" + run_context.run_id + ".csv"))
    latest_parquet_path = next(path for path in written_paths if path.name.endswith("latest_" + run_context.run_id + ".parquet"))
    latest_csv = pd.read_csv(latest_csv_path)
    latest_parquet = pd.read_parquet(latest_parquet_path)
    stable_latest = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)

    assert list(latest_csv["ticker"]) == ["GOLD", "NEM"]
    assert len(latest_csv.index) == 2
    assert len(latest_parquet.index) == 2
    assert list(stable_latest["ticker"]) == ["GOLD", "NEM"]


def test_persist_tool_a_outputs_round_trips_display_window_columns(tmp_path):
    """Schema/persist lock for the Phase-2 display windows: the 16 2Y/5Y columns must
    survive the parquet round-trip with their values, and weeks_* must stay integer."""
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths, command="tool-a", parameters={}, config_hash="hash",
    )
    display_cols = {
        "structural_delta_2y": 1.6, "structural_delta_5y": 1.4,
        "gamma_2y": 0.05, "gamma_5y": -0.02,
        "up_beta_2y": 1.31, "down_beta_2y": 1.02,
        "up_beta_5y": 1.45, "down_beta_5y": 1.10,
        "asymmetry_ratio_2y": 1.28, "asymmetry_ratio_5y": 1.10,
        "r_squared_2y": 0.41, "r_squared_5y": 0.33,
        "weeks_2y": 104, "weeks_5y": 143,
        "window_status_2y": "ELIGIBLE", "window_status_5y": "LOW_OBSERVATION",
    }
    tool_a_outputs = pd.DataFrame(
        [{"ticker": "NEM", "as_of_date": date(2026, 1, 31), "tool_a_rank": 1, **display_cols}]
    )

    persist_tool_a_outputs(
        paths=paths, run_context=run_context, tool_a_outputs=tool_a_outputs,
    )

    stable = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)
    row = stable[stable["ticker"] == "NEM"].iloc[0]
    for col, expected in display_cols.items():
        if isinstance(expected, str):
            assert row[col] == expected, col
        else:
            assert abs(float(row[col]) - expected) < 1e-9, col
    # weeks columns must persist as an integer dtype, not float
    assert pd.api.types.is_integer_dtype(stable["weeks_2y"])
    assert pd.api.types.is_integer_dtype(stable["weeks_5y"])


def test_persist_tool_a_outputs_can_preserve_previous_stable_latest_alias_on_empty_run(tmp_path):
    paths = build_test_paths(tmp_path)
    initial_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=initial_context,
        tool_a_outputs=pd.DataFrame(
            [
                {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "tool_a_rank": 1},
            ]
        ),
    )

    empty_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=empty_context,
        tool_a_outputs=pd.DataFrame(columns=["ticker", "as_of_date", "tool_a_rank"]),
        publish_latest_aliases=False,
    )

    stable_latest = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)
    assert list(stable_latest["ticker"]) == ["NEM"]


def test_persist_tool_a_outputs_latest_is_per_ticker_not_global_max_date(tmp_path):
    """Regression guard for the VAU.AX-style trust bug: if one ticker's
    latest structural row is a week behind the rest of the universe
    (because its last complete weekly bar lagged), the "latest" snapshot
    must still include that ticker's most recent row, not drop it.

    Per-ticker latest → Emanuel never sees a silent missing ticker
    between the active universe and the Tool A latest view.
    """
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths, command="tool-a", parameters={}, config_hash="hash",
    )
    tool_a_outputs = pd.DataFrame(
        [
            # Two tickers at the global max date.
            {"ticker": "NEM", "as_of_date": date(2026, 4, 24), "tool_a_rank": 1},
            {"ticker": "AEM", "as_of_date": date(2026, 4, 24), "tool_a_rank": 2},
            # VAU.AX-style lagged ticker: its last row is a week earlier.
            {"ticker": "VAU.AX", "as_of_date": date(2026, 4, 17), "tool_a_rank": 3},
            # VAU.AX history also has older rows that must NOT appear in latest.
            {"ticker": "VAU.AX", "as_of_date": date(2026, 4, 10), "tool_a_rank": 3},
        ]
    )

    persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=tool_a_outputs,
    )

    stable_latest = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)

    # All three active tickers must be present, including the lagged one.
    assert set(stable_latest["ticker"]) == {"NEM", "AEM", "VAU.AX"}
    # VAU.AX should be represented by its MOST RECENT row, not an older one.
    vau_rows = stable_latest[stable_latest["ticker"] == "VAU.AX"]
    assert len(vau_rows) == 1
    assert vau_rows.iloc[0]["as_of_date"] == date(2026, 4, 17)


def test_persist_tool_a_structural_metrics_carries_source_run_id(tmp_path):
    """Phase 1A / v3 §1: every structural-window-metric row must carry the producing
    Tool A run id so the workspace can detect when the structural-history file is out
    of sync with the published Tool A row.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )

    weeks = 180
    dates = pd.date_range("2022-01-07", periods=weeks, freq="W-FRI")
    gold_log_returns = np.array(
        [0.012 if i % 4 in (0, 1) else -0.008 for i in range(weeks)],
        dtype=float,
    )
    gold_basis = 1800.0 * np.exp(np.cumsum(gold_log_returns))
    gold_history = pd.DataFrame(
        {"date": dates.date, "close_usd": gold_basis, "adj_close_usd": gold_basis}
    )
    stock_log_returns = np.where(gold_log_returns > 0, 2.0 * gold_log_returns + 0.001, 1.2 * gold_log_returns + 0.001)
    stock_basis = np.empty(weeks, dtype=float)
    stock_basis[0] = 10.0
    stock_basis[1:] = stock_basis[0] * np.exp(np.cumsum(stock_log_returns[:-1]))
    equity_history = pd.DataFrame(
        {
            "ticker": "NEM",
            "date": pd.to_datetime(gold_history["date"]).dt.date,
            "return_basis_usd": stock_basis,
            "normalization_status": "OK",
        }
    )

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=gold_history,
        normalized_equity_histories={"NEM": equity_history},
        snapshot_refresh_run_id="refresh-run",
    )

    assert "source_run_id" in result.structural_window_metrics.columns
    assert (result.structural_window_metrics["source_run_id"] == run_context.run_id).all()

    persisted = pd.read_parquet(paths.latest_tool_a_structural_metrics_path)
    assert "source_run_id" in persisted.columns
    assert (persisted["source_run_id"] == run_context.run_id).all()
