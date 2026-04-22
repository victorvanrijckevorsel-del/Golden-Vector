"""Phase 3 horizon-return quality checks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.contracts.data_models import QaCheckResult


@dataclass(frozen=True)
class HorizonQaReport:
    overall_status: str
    results: list[QaCheckResult]

    def summary(self) -> dict[str, object]:
        fail_count = sum(1 for result in self.results if result.status == "FAIL")
        warn_count = sum(1 for result in self.results if result.status == "WARN")
        pass_count = sum(1 for result in self.results if result.status == "PASS")
        return {
            "overall_status": self.overall_status,
            "pass_count": pass_count,
            "warn_count": warn_count,
            "fail_count": fail_count,
        }


def evaluate_horizon_quality(
    *,
    tool_a_tickers: list[str],
    horizon_metrics: pd.DataFrame,
) -> HorizonQaReport:
    results: list[QaCheckResult] = []
    working = horizon_metrics.copy()

    if working.empty:
        working = pd.DataFrame(
            columns=[
                "ticker",
                "horizon_mode",
                "coverage_flag",
                "official_scoring_eligible",
            ]
        )
        results.append(
            QaCheckResult(
                check_name="horizon_table_presence",
                status="FAIL",
                dataset="horizon_metrics",
                entity="tool-a",
                message="No horizon rows were produced.",
            )
        )
    else:
        results.append(
            QaCheckResult(
                check_name="horizon_table_presence",
                status="PASS",
                dataset="horizon_metrics",
                entity="tool-a",
                message=f"{len(working.index)} horizon rows were produced.",
            )
        )

    for ticker in tool_a_tickers:
        ticker_rows = working[working["ticker"] == ticker]
        if ticker_rows.empty:
            results.append(
                QaCheckResult(
                    check_name="horizon_rows_by_ticker",
                    status="FAIL",
                    dataset="horizon_metrics",
                    entity=ticker,
                    message="No horizon rows were produced for this ticker.",
                )
            )
            continue

        core_rows = ticker_rows[ticker_rows["horizon_mode"] == "core"]
        pass_core_rows = core_rows[core_rows["coverage_flag"] == "PASS"]
        eligible_core_rows = core_rows[
            core_rows["official_scoring_eligible"].fillna(False).astype(bool)
        ]

        status = "PASS"
        if pass_core_rows.empty:
            status = "WARN"
        elif eligible_core_rows.empty:
            status = "WARN"
        message = (
            f"{len(pass_core_rows.index)} passing core horizon rows out of "
            f"{len(core_rows.index)} core rows; "
            f"{len(eligible_core_rows.index)} rows are officially eligible."
        )

        results.append(
            QaCheckResult(
                check_name="core_horizon_coverage",
                status=status,
                dataset="horizon_metrics",
                entity=ticker,
                message=message,
            )
        )

    overall_status = "PASS"
    if any(result.status == "FAIL" for result in results):
        overall_status = "FAIL"
    elif any(result.status == "WARN" for result in results):
        overall_status = "WARN"

    return HorizonQaReport(
        overall_status=overall_status,
        results=results,
    )
