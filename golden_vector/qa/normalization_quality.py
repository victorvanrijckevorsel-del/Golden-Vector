"""Normalization-stage quality checks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.contracts.data_models import QaCheckResult
from golden_vector.ingestion.registry import FoundationRegistry


@dataclass(frozen=True)
class NormalizationQaReport:
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


def evaluate_normalization_quality(
    app_config: object,
    registry: FoundationRegistry,
    usd_equity_histories: dict[str, pd.DataFrame],
    normalized_market_snapshots: pd.DataFrame,
) -> NormalizationQaReport:
    _ = app_config
    results: list[QaCheckResult] = []

    for target in registry.equity_targets:
        frame = usd_equity_histories.get(target.ticker, pd.DataFrame())
        results.extend(_equity_checks(target.ticker, frame))

    results.append(
        _market_snapshot_check(
            normalized_market_snapshots=normalized_market_snapshots,
            registry=registry,
        )
    )

    overall_status = "PASS"
    if any(result.status == "FAIL" for result in results):
        overall_status = "FAIL"
    elif any(result.status == "WARN" for result in results):
        overall_status = "WARN"

    return NormalizationQaReport(
        overall_status=overall_status,
        results=results,
    )


def _equity_checks(
    ticker: str,
    frame: pd.DataFrame,
) -> list[QaCheckResult]:
    if frame.empty:
        return [
            QaCheckResult(
                check_name="equity_usd_coverage",
                status="FAIL",
                dataset="usd_equities",
                entity=ticker,
                message="No normalized USD rows were produced for this ticker.",
            )
        ]

    statuses = frame["normalization_status"].fillna("UNKNOWN").astype(str)
    total_rows = len(frame.index)
    ok_rows = int((statuses == "OK").sum())
    missing_fx_rows = int((statuses == "MISSING_FX").sum())
    missing_return_basis_rows = int((statuses == "MISSING_RETURN_BASIS").sum())
    other_issue_rows = total_rows - ok_rows - missing_fx_rows - missing_return_basis_rows

    coverage_status = "PASS"
    if ok_rows == 0:
        coverage_status = "FAIL"
    elif ok_rows < total_rows:
        coverage_status = "WARN"

    message = (
        f"{ok_rows} of {total_rows} rows normalized successfully; "
        f"missing_fx={missing_fx_rows}, "
        f"missing_return_basis={missing_return_basis_rows}, "
        f"other_issues={other_issue_rows}."
    )

    return [
        QaCheckResult(
            check_name="equity_usd_coverage",
            status=coverage_status,
            dataset="usd_equities",
            entity=ticker,
            message=message,
        )
    ]


def _market_snapshot_check(
    normalized_market_snapshots: pd.DataFrame,
    registry: FoundationRegistry,
) -> QaCheckResult:
    expected = len(registry.market_snapshot_targets)
    if expected == 0:
        return QaCheckResult(
            check_name="market_snapshot_usd_coverage",
            status="PASS",
            dataset="normalized_market_snapshots",
            entity="tool-b",
            message="No Tool B market snapshots are expected for the current universe.",
        )

    if normalized_market_snapshots.empty:
        return QaCheckResult(
            check_name="market_snapshot_usd_coverage",
            status="WARN",
            dataset="normalized_market_snapshots",
            entity="tool-b",
            message=f"0 of {expected} Tool B market snapshots were normalized.",
        )

    statuses = normalized_market_snapshots["normalization_status"].fillna("UNKNOWN").astype(str)
    status_counts = statuses.value_counts().to_dict()
    ok_rows = int(status_counts.get("OK", 0))

    status = "PASS" if ok_rows == expected and len(normalized_market_snapshots.index) == expected else "WARN"
    breakdown = ", ".join(
        f"{name}={count}" for name, count in sorted(status_counts.items())
    )
    return QaCheckResult(
        check_name="market_snapshot_usd_coverage",
        status=status,
        dataset="normalized_market_snapshots",
        entity="tool-b",
        message=(
            f"{ok_rows} of {expected} Tool B market snapshots normalized successfully. "
            f"Status breakdown: {breakdown}."
        ),
    )
