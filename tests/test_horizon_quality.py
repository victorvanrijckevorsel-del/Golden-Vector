import pandas as pd

from golden_vector.qa.horizon_quality import evaluate_horizon_quality


def test_horizon_quality_fails_cleanly_when_no_rows_exist():
    report = evaluate_horizon_quality(
        tool_a_tickers=["NEM"],
        horizon_metrics=pd.DataFrame(),
    )

    assert report.overall_status == "FAIL"


def test_horizon_quality_warns_when_core_rows_are_not_officially_eligible():
    horizon_metrics = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "horizon_mode": "core",
                "coverage_flag": "PASS",
                "official_scoring_eligible": False,
            }
        ]
    )

    report = evaluate_horizon_quality(
        tool_a_tickers=["NEM"],
        horizon_metrics=horizon_metrics,
    )

    assert report.overall_status == "WARN"
    coverage_result = next(
        result for result in report.results if result.check_name == "core_horizon_coverage"
    )
    assert "0 rows are officially eligible" in coverage_result.message
