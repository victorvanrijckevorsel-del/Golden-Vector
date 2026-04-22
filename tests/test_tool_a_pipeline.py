from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.model.pipeline import execute_tool_a_profile_pipeline
from tests.helpers import build_test_paths


def _metric_row(
    *,
    ticker: str,
    horizon_id: str,
    gold_return: float,
    gold_delta: float,
    as_of_date: date = date(2026, 1, 31),
    official_scoring_eligible: bool = True,
    coverage_flag: str = "PASS",
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "horizon_id": horizon_id,
        "horizon_mode": "core",
        "horizon_unit": "D",
        "horizon_value": 5,
        "start_date": date(2026, 1, 1),
        "end_date": as_of_date,
        "equity_return": gold_delta * gold_return,
        "gold_return": gold_return,
        "gold_delta": gold_delta,
        "coverage_flag": coverage_flag,
        "coverage_reason": "OK" if coverage_flag == "PASS" else "INSUFFICIENT_HISTORY",
        "official_scoring_eligible": official_scoring_eligible,
    }


def test_tool_a_pipeline_ranks_positive_names_and_skips_inverse(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    horizon_metrics = pd.DataFrame(
        [
            _metric_row(ticker="NEM", horizon_id="5D", gold_return=0.01, gold_delta=1.10),
            _metric_row(ticker="NEM", horizon_id="10D", gold_return=0.02, gold_delta=1.20),
            _metric_row(ticker="NEM", horizon_id="15D", gold_return=0.03, gold_delta=1.30),
            _metric_row(ticker="NEM", horizon_id="1M", gold_return=0.04, gold_delta=1.40),
            _metric_row(ticker="NEM", horizon_id="3M", gold_return=0.05, gold_delta=1.50),
            _metric_row(ticker="GOLD", horizon_id="5D", gold_return=0.01, gold_delta=0.70),
            _metric_row(ticker="GOLD", horizon_id="10D", gold_return=0.02, gold_delta=0.75),
            _metric_row(ticker="GOLD", horizon_id="15D", gold_return=0.03, gold_delta=0.80),
            _metric_row(ticker="GOLD", horizon_id="1M", gold_return=0.04, gold_delta=0.85),
            _metric_row(ticker="GOLD", horizon_id="3M", gold_return=0.05, gold_delta=0.90),
            _metric_row(ticker="ANTI", horizon_id="5D", gold_return=0.01, gold_delta=-0.30),
            _metric_row(ticker="ANTI", horizon_id="10D", gold_return=0.02, gold_delta=-0.35),
            _metric_row(ticker="ANTI", horizon_id="15D", gold_return=0.03, gold_delta=-0.40),
            _metric_row(ticker="ANTI", horizon_id="1M", gold_return=0.04, gold_delta=-0.45),
            _metric_row(ticker="ANTI", horizon_id="3M", gold_return=0.05, gold_delta=-0.50),
        ]
    )

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        horizon_metrics=horizon_metrics,
    )

    assert result.overall_status == "PASS"
    output = result.tool_a_outputs.set_index("ticker")
    assert bool(output.loc["NEM", "score_eligible"]) is True
    assert int(output.loc["NEM", "tool_a_rank"]) == 1
    assert bool(output.loc["GOLD", "score_eligible"]) is True
    assert int(output.loc["GOLD", "tool_a_rank"]) == 2
    assert bool(output.loc["ANTI", "score_eligible"]) is False
    assert output.loc["ANTI", "score_eligibility_reason"] == "NON_POSITIVE_CORE_DELTA"
    assert pd.isna(output.loc["ANTI", "tool_a_rank"])


def test_tool_a_pipeline_marks_rows_ineligible_when_too_few_eligible_horizons(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    horizon_metrics = pd.DataFrame(
        [
            _metric_row(ticker="NEM", horizon_id="5D", gold_return=0.01, gold_delta=1.0),
            _metric_row(ticker="NEM", horizon_id="10D", gold_return=0.02, gold_delta=1.1),
            _metric_row(ticker="NEM", horizon_id="15D", gold_return=0.03, gold_delta=1.2),
            _metric_row(ticker="NEM", horizon_id="1M", gold_return=0.04, gold_delta=1.3),
            _metric_row(
                ticker="NEM",
                horizon_id="3M",
                gold_return=0.0,
                gold_delta=0.0,
                official_scoring_eligible=False,
            ),
        ]
    )

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        horizon_metrics=horizon_metrics,
    )

    assert result.overall_status == "WARN"
    row = result.tool_a_outputs.iloc[0]
    assert bool(row["score_eligible"]) is False
    assert row["score_eligibility_reason"] == "INSUFFICIENT_ELIGIBLE_HORIZONS"
    assert row["coverage_summary"] == "FAIL"


def test_tool_a_pipeline_keeps_scores_when_non_fail_core_horizon_is_not_officially_eligible(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    horizon_metrics = pd.DataFrame(
        [
            _metric_row(ticker="NEM", horizon_id="5D", gold_return=0.01, gold_delta=1.0),
            _metric_row(ticker="NEM", horizon_id="10D", gold_return=0.02, gold_delta=1.1),
            _metric_row(ticker="NEM", horizon_id="15D", gold_return=0.03, gold_delta=1.2),
            _metric_row(ticker="NEM", horizon_id="1M", gold_return=0.04, gold_delta=1.3),
            _metric_row(ticker="NEM", horizon_id="3M", gold_return=0.05, gold_delta=1.4),
            _metric_row(
                ticker="NEM",
                horizon_id="6M",
                gold_return=0.0,
                gold_delta=0.0,
                official_scoring_eligible=False,
                coverage_flag="PASS",
            ),
        ]
    )

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        horizon_metrics=horizon_metrics,
    )

    row = result.tool_a_outputs.iloc[0]
    assert result.overall_status == "PASS"
    assert row["coverage_summary"] == "PASS"
    assert bool(row["score_eligible"]) is True
    assert row["score_eligibility_reason"] == "OK"
    assert pd.notna(row["tool_a_score"])


def test_tool_a_pipeline_fails_cleanly_on_empty_horizon_metrics(tmp_path):
    paths = build_test_paths(tmp_path)
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
        horizon_metrics=pd.DataFrame(),
    )

    assert result.overall_status == "FAIL"
    assert result.tool_a_outputs.empty


def test_tool_a_pipeline_ranks_each_as_of_date_independently(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    date_one = date(2026, 1, 31)
    date_two = date(2026, 2, 1)
    horizon_metrics = pd.DataFrame(
        [
            _metric_row(ticker="NEM", horizon_id="5D", gold_return=0.01, gold_delta=1.30, as_of_date=date_one),
            _metric_row(ticker="NEM", horizon_id="10D", gold_return=0.02, gold_delta=1.35, as_of_date=date_one),
            _metric_row(ticker="NEM", horizon_id="15D", gold_return=0.03, gold_delta=1.40, as_of_date=date_one),
            _metric_row(ticker="NEM", horizon_id="1M", gold_return=0.04, gold_delta=1.45, as_of_date=date_one),
            _metric_row(ticker="NEM", horizon_id="3M", gold_return=0.05, gold_delta=1.50, as_of_date=date_one),
            _metric_row(ticker="GOLD", horizon_id="5D", gold_return=0.01, gold_delta=0.80, as_of_date=date_one),
            _metric_row(ticker="GOLD", horizon_id="10D", gold_return=0.02, gold_delta=0.85, as_of_date=date_one),
            _metric_row(ticker="GOLD", horizon_id="15D", gold_return=0.03, gold_delta=0.90, as_of_date=date_one),
            _metric_row(ticker="GOLD", horizon_id="1M", gold_return=0.04, gold_delta=0.95, as_of_date=date_one),
            _metric_row(ticker="GOLD", horizon_id="3M", gold_return=0.05, gold_delta=1.00, as_of_date=date_one),
            _metric_row(ticker="NEM", horizon_id="5D", gold_return=0.01, gold_delta=0.85, as_of_date=date_two),
            _metric_row(ticker="NEM", horizon_id="10D", gold_return=0.02, gold_delta=0.90, as_of_date=date_two),
            _metric_row(ticker="NEM", horizon_id="15D", gold_return=0.03, gold_delta=0.95, as_of_date=date_two),
            _metric_row(ticker="NEM", horizon_id="1M", gold_return=0.04, gold_delta=1.00, as_of_date=date_two),
            _metric_row(ticker="NEM", horizon_id="3M", gold_return=0.05, gold_delta=1.05, as_of_date=date_two),
            _metric_row(ticker="GOLD", horizon_id="5D", gold_return=0.01, gold_delta=1.35, as_of_date=date_two),
            _metric_row(ticker="GOLD", horizon_id="10D", gold_return=0.02, gold_delta=1.40, as_of_date=date_two),
            _metric_row(ticker="GOLD", horizon_id="15D", gold_return=0.03, gold_delta=1.45, as_of_date=date_two),
            _metric_row(ticker="GOLD", horizon_id="1M", gold_return=0.04, gold_delta=1.50, as_of_date=date_two),
            _metric_row(ticker="GOLD", horizon_id="3M", gold_return=0.05, gold_delta=1.55, as_of_date=date_two),
        ]
    )

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        horizon_metrics=horizon_metrics,
    )

    date_one_rows = result.tool_a_outputs[
        result.tool_a_outputs["as_of_date"] == date_one
    ].set_index("ticker")
    date_two_rows = result.tool_a_outputs[
        result.tool_a_outputs["as_of_date"] == date_two
    ].set_index("ticker")

    assert int(date_one_rows.loc["NEM", "tool_a_rank"]) == 1
    assert int(date_one_rows.loc["GOLD", "tool_a_rank"]) == 2
    assert int(date_two_rows.loc["GOLD", "tool_a_rank"]) == 1
    assert int(date_two_rows.loc["NEM", "tool_a_rank"]) == 2
