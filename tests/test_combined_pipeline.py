from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.run_context import RunContext
from golden_vector.app.paths import ProjectPaths
from golden_vector.combined.join import join_tool_outputs
from golden_vector.combined.ranking import rank_combined_outputs
from golden_vector.combined.pipeline import execute_combined_pipeline
from tests.helpers import build_test_paths


def test_combined_pipeline_scores_complete_rows_and_ranks_them(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="combined",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )
    as_of_date = date(2026, 2, 1)
    tool_a_outputs = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": as_of_date,
                "core_delta": 1.3,
                "regime_tag": "BULLISH",
                "tool_a_score": 82.0,
                "tool_a_rank": 1,
                "coverage_summary": "PASS",
                "source_run_id": "tool-a-run",
            },
            {
                "ticker": "GOLD",
                "as_of_date": as_of_date,
                "core_delta": 0.9,
                "regime_tag": "BULLISH",
                "tool_a_score": 68.0,
                "tool_a_rank": 2,
                "coverage_summary": "PASS",
                "source_run_id": "tool-a-run",
            },
        ]
    )
    tool_b_outputs = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": as_of_date,
                "gold_price_assumption": 4000.0,
                "screening_verdict": "STRONG_CANDIDATE",
                "confidence": "VERIFIED",
                "tool_b_score": 90.0,
                "tool_b_rank": 1,
                "best_upside_pct": 0.55,
                "forward_pe": 7.5,
                "fcf_yield": 0.18,
                "source_run_id": "tool-b-run",
            },
            {
                "ticker": "GOLD",
                "as_of_date": as_of_date,
                "gold_price_assumption": 4000.0,
                "screening_verdict": "WATCHLIST",
                "confidence": "ESTIMATED",
                "tool_b_score": 70.0,
                "tool_b_rank": 2,
                "best_upside_pct": 0.20,
                "forward_pe": 9.5,
                "fcf_yield": 0.11,
                "source_run_id": "tool-b-run",
            },
        ]
    )

    result = execute_combined_pipeline(
        paths=paths,
        run_context=run_context,
        scoring_config=app_config.scoring,
        tool_a_outputs=tool_a_outputs,
        tool_b_outputs=tool_b_outputs,
        gold_price_assumption=4000.0,
    )

    assert result.overall_status == "PASS"
    output = result.combined_outputs.set_index("ticker")
    assert output.loc["NEM", "join_status"] == "COMPLETE"
    assert output.loc["NEM", "combined_score"] == 86.0
    assert output.loc["NEM", "combined_verdict"] == "HIGH_CONVICTION"
    assert int(output.loc["NEM", "combined_rank"]) == 1
    assert int(output.loc["GOLD", "combined_rank"]) == 2


def test_combined_pipeline_keeps_partial_rows_when_only_tool_a_exists(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="combined",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )
    as_of_date = date(2026, 2, 1)
    tool_a_outputs = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": as_of_date,
                "core_delta": 1.1,
                "regime_tag": "BULLISH",
                "tool_a_score": 75.0,
                "tool_a_rank": 1,
                "coverage_summary": "PASS",
                "source_run_id": "tool-a-run",
            }
        ]
    )

    result = execute_combined_pipeline(
        paths=paths,
        run_context=run_context,
        scoring_config=app_config.scoring,
        tool_a_outputs=tool_a_outputs,
        tool_b_outputs=pd.DataFrame(),
        gold_price_assumption=4000.0,
    )

    assert result.overall_status == "WARN"
    row = result.combined_outputs.iloc[0]
    assert row["join_status"] == "PARTIAL"
    assert pd.isna(row["combined_score"])
    assert row["combined_verdict"] == "TOOL_A_ONLY"


def test_combined_join_rejects_duplicate_keys():
    tool_a_outputs = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 2, 1),
                "core_delta": 1.1,
                "regime_tag": "BULLISH",
                "tool_a_score": 75.0,
                "tool_a_rank": 1,
                "coverage_summary": "PASS",
                "source_run_id": "tool-a-run",
            },
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 2, 1),
                "core_delta": 1.0,
                "regime_tag": "BULLISH",
                "tool_a_score": 74.0,
                "tool_a_rank": 2,
                "coverage_summary": "PASS",
                "source_run_id": "tool-a-run",
            },
        ]
    )

    try:
        join_tool_outputs(
            tool_a_outputs=tool_a_outputs,
            tool_b_outputs=pd.DataFrame(),
            gold_price_assumption=4000.0,
        )
    except ValueError as exc:
        assert "duplicate combined join keys" in str(exc)
    else:
        raise AssertionError("Expected duplicate join keys to fail fast.")


def test_combined_ranking_resets_by_gold_price_scenario():
    frame = pd.DataFrame(
        [
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 3000.0, "combined_score": 80.0},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 3000.0, "combined_score": 70.0},
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "combined_score": 60.0},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "combined_score": 90.0},
        ]
    )

    ranked = rank_combined_outputs(frame).set_index(["ticker", "gold_price_assumption"])

    assert int(ranked.loc[("NEM", 3000.0), "combined_rank"]) == 1
    assert int(ranked.loc[("GOLD", 3000.0), "combined_rank"]) == 2
    assert int(ranked.loc[("GOLD", 4000.0), "combined_rank"]) == 1
    assert int(ranked.loc[("NEM", 4000.0), "combined_rank"]) == 2
