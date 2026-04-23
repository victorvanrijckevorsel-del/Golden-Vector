from datetime import date

import numpy as np
import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.model.pipeline import execute_tool_a_profile_pipeline
from tests.helpers import build_test_paths


def _gold_history(weeks: int = 180) -> pd.DataFrame:
    dates = pd.date_range("2022-01-07", periods=weeks, freq="W-FRI")
    gold_log_returns = np.array(
        [
            0.012 if index % 4 in (0, 1) else -0.008
            for index in range(weeks)
        ],
        dtype=float,
    )
    gold_basis = 1800.0 * np.exp(np.cumsum(gold_log_returns))
    return pd.DataFrame(
        {
            "date": dates.date,
            "close_usd": gold_basis,
            "adj_close_usd": gold_basis,
        }
    )


def _equity_history(
    *,
    ticker: str,
    gold_history: pd.DataFrame,
    positive_beta: float,
    negative_beta: float,
    alpha: float = 0.001,
) -> pd.DataFrame:
    gold_basis = pd.to_numeric(gold_history["adj_close_usd"], errors="coerce").to_numpy(dtype=float)
    gold_log_returns = np.log(gold_basis[1:] / gold_basis[:-1])
    stock_log_returns = np.where(
        gold_log_returns > 0,
        (positive_beta * gold_log_returns) + alpha,
        (negative_beta * gold_log_returns) + alpha,
    )
    stock_basis = np.empty(len(gold_basis), dtype=float)
    stock_basis[0] = 10.0
    stock_basis[1:] = stock_basis[0] * np.exp(np.cumsum(stock_log_returns))
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.to_datetime(gold_history["date"]).dt.date,
            "return_basis_usd": stock_basis,
            "normalization_status": "OK",
        }
    )


def test_tool_a_pipeline_ranks_structural_names_and_skips_inverse(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    gold_history = _gold_history()
    normalized_equity_histories = {
        "NEM": _equity_history(
            ticker="NEM",
            gold_history=gold_history,
            positive_beta=2.0,
            negative_beta=1.2,
        ),
        "GOLD": _equity_history(
            ticker="GOLD",
            gold_history=gold_history,
            positive_beta=0.7,
            negative_beta=0.7,
        ),
    }

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        snapshot_refresh_run_id="refresh-run",
    )

    assert result.overall_status == "PASS"
    latest_as_of_date = result.tool_a_outputs["as_of_date"].max()
    latest_rows = result.tool_a_outputs[
        result.tool_a_outputs["as_of_date"] == latest_as_of_date
    ].set_index("ticker")

    assert bool(latest_rows.loc["NEM", "score_eligible"]) is True
    assert int(latest_rows.loc["NEM", "tool_a_rank"]) == 1
    assert latest_rows.loc["NEM", "profile_label"] == "CONVEX"
    assert latest_rows.loc["NEM", "structural_gamma_core"] < 0
    assert pd.notna(latest_rows.loc["NEM", "total_volatility_52w"])
    assert pd.notna(latest_rows.loc["NEM", "residual_volatility_52w"])
    assert pd.notna(latest_rows.loc["NEM", "downside_volatility_52w"])
    assert bool(latest_rows.loc["GOLD", "score_eligible"]) is False
    assert latest_rows.loc["GOLD", "score_eligibility_reason"] == "LOW_LINKAGE_STRUCTURAL_SIGNAL"
    assert pd.isna(latest_rows.loc["GOLD", "tool_a_rank"])
    assert pd.notna(latest_rows.loc["GOLD", "total_volatility_52w"])


def test_tool_a_pipeline_marks_short_history_as_ineligible(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    gold_history = _gold_history(weeks=36)
    normalized_equity_histories = {
        "NEM": _equity_history(
            ticker="NEM",
            gold_history=gold_history,
            positive_beta=1.4,
            negative_beta=1.1,
        )
    }

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        snapshot_refresh_run_id="refresh-run",
    )

    latest_row = result.tool_a_outputs.sort_values("as_of_date").iloc[-1]
    assert bool(latest_row["score_eligible"]) is False
    assert latest_row["score_eligibility_reason"] in {
        "INSUFFICIENT_ELIGIBLE_STRUCTURAL_WINDOWS",
        "LOW_CONFIDENCE_STRUCTURAL_SIGNAL",
    }


def test_tool_a_pipeline_withholds_rows_when_normalization_is_blocked(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    gold_history = _gold_history()
    blocked_history = _equity_history(
        ticker="FRES.L",
        gold_history=gold_history,
        positive_beta=1.8,
        negative_beta=1.1,
    )
    blocked_history.loc[blocked_history.index[-30::5], "normalization_status"] = "STALE_FX"
    normalized_equity_histories = {"FRES.L": blocked_history}

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        snapshot_refresh_run_id="refresh-run",
    )

    latest_row = result.tool_a_outputs.sort_values("as_of_date").iloc[-1]
    assert bool(latest_row["score_eligible"]) is False
    assert latest_row["score_eligibility_reason"] == "UNACCEPTABLE_NORMALIZATION_STATUS"
    assert latest_row["confidence_label"] == "WITHHELD"
    assert latest_row["profile_label"] == "SCORE_WITHHELD"
    assert latest_row["normalization_issue_summary"] == "STALE_FX"
    assert "withheld" in str(latest_row["tool_a_summary_explanation"]).lower()


def test_tool_a_pipeline_fails_cleanly_on_empty_inputs(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=pd.DataFrame(),
        normalized_equity_histories={},
        snapshot_refresh_run_id="refresh-run",
    )

    assert result.overall_status == "FAIL"
    assert result.tool_a_outputs.empty
