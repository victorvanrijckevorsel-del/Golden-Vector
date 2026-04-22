"""Raw-data quality checks for the foundation pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.contracts.config_models import AppConfig
from golden_vector.contracts.data_models import FetchStatusRecord, QaCheckResult
from golden_vector.ingestion.registry import FoundationRegistry, missing_fx_currencies


@dataclass(frozen=True)
class RawQaReport:
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


def evaluate_raw_quality(
    app_config: AppConfig,
    registry: FoundationRegistry,
    equity_histories: dict[str, pd.DataFrame],
    fx_histories: dict[str, pd.DataFrame],
    gold_history: pd.DataFrame,
    market_snapshots: pd.DataFrame,
    fetch_statuses: list[FetchStatusRecord],
) -> RawQaReport:
    results: list[QaCheckResult] = []

    results.append(_currency_map_check(app_config, registry))
    results.extend(_status_results(fetch_statuses))

    for ticker, frame in equity_histories.items():
        results.extend(
            _history_checks(
                dataset="equities",
                entity=ticker,
                frame=frame,
                min_rows=app_config.qa.minimum_equity_history_days,
                duplicate_subset=["ticker", "date"],
                block_on_short_history=True,
                warn_on_duplicates=app_config.qa.warn_on_duplicate_rows,
            )
        )

    for currency, frame in fx_histories.items():
        results.extend(
            _history_checks(
                dataset="fx",
                entity=currency,
                frame=frame,
                min_rows=app_config.qa.minimum_fx_history_days,
                duplicate_subset=["base_currency", "date"],
                block_on_short_history=app_config.qa.block_on_missing_fx_history,
                warn_on_duplicates=app_config.qa.warn_on_duplicate_rows,
            )
        )

    results.extend(
        _history_checks(
            dataset="gold",
            entity=registry.gold_target.yahoo_symbol,
            frame=gold_history,
            min_rows=app_config.qa.minimum_gold_history_days,
            duplicate_subset=["date"],
            block_on_short_history=app_config.qa.block_on_missing_gold_history,
            warn_on_duplicates=app_config.qa.warn_on_duplicate_rows,
        )
    )

    results.append(_market_snapshot_coverage_check(market_snapshots, registry))
    results.extend(_market_snapshot_field_checks(market_snapshots))

    overall_status = "PASS"
    if any(result.status == "FAIL" for result in results):
        overall_status = "FAIL"
    elif any(result.status == "WARN" for result in results):
        overall_status = "WARN"

    return RawQaReport(overall_status=overall_status, results=results)


def _status_results(fetch_statuses: list[FetchStatusRecord]) -> list[QaCheckResult]:
    results: list[QaCheckResult] = []
    for status in fetch_statuses:
        mapped_status = status.status
        if status.dataset == "market_snapshots" and status.status == "FAIL":
            mapped_status = "WARN"
        message = status.message or f"{status.dataset} fetch returned {status.row_count} rows."
        results.append(
            QaCheckResult(
                check_name="fetch_status",
                status=mapped_status,
                dataset=status.dataset,
                entity=status.entity,
                message=message,
            )
        )
    return results


def _currency_map_check(
    app_config: AppConfig,
    registry: FoundationRegistry,
) -> QaCheckResult:
    missing = missing_fx_currencies(app_config.universe)
    status = "PASS"
    message = "FX mappings are available for all active non-USD currencies."

    if missing:
        status = "FAIL" if app_config.qa.block_on_missing_currency_map else "WARN"
        message = "Missing FX mappings for: " + ", ".join(missing)
    elif not registry.fx_targets:
        message = "No active non-USD currencies require FX mappings."

    return QaCheckResult(
        check_name="currency_map_coverage",
        status=status,
        dataset="fx",
        entity="currency_map",
        message=message,
    )


def _history_checks(
    dataset: str,
    entity: str,
    frame: pd.DataFrame,
    min_rows: int,
    duplicate_subset: list[str],
    block_on_short_history: bool,
    warn_on_duplicates: bool,
) -> list[QaCheckResult]:
    if frame.empty:
        return [
            QaCheckResult(
                check_name="history_presence",
                status="FAIL" if block_on_short_history else "WARN",
                dataset=dataset,
                entity=entity,
                message="No rows available after fetch.",
            )
        ]

    results: list[QaCheckResult] = [
        QaCheckResult(
            check_name="history_minimum_rows",
            status="PASS" if len(frame) >= min_rows else ("FAIL" if block_on_short_history else "WARN"),
            dataset=dataset,
            entity=entity,
            message=f"{len(frame)} rows available; minimum expected is {min_rows}.",
        )
    ]

    duplicate_count = int(frame.duplicated(subset=duplicate_subset).sum())
    duplicate_status = "WARN" if duplicate_count > 0 and warn_on_duplicates else "PASS"
    duplicate_message = f"{duplicate_count} duplicate rows found."
    if duplicate_count > 0 and not warn_on_duplicates:
        duplicate_message += " Duplicate warnings are disabled in QA config."
    results.append(
        QaCheckResult(
            check_name="duplicate_rows",
            status=duplicate_status,
            dataset=dataset,
            entity=entity,
            message=duplicate_message,
        )
    )
    return results


def _market_snapshot_coverage_check(
    market_snapshots: pd.DataFrame,
    registry: FoundationRegistry,
) -> QaCheckResult:
    expected = len(registry.market_snapshot_targets)
    actual = len(market_snapshots.index)
    status = "PASS" if actual == expected else "WARN"
    return QaCheckResult(
        check_name="market_snapshot_coverage",
        status=status,
        dataset="market_snapshots",
        entity="tool-b",
        message=f"{actual} market snapshots available for {expected} expected Tool B tickers.",
    )


def _market_snapshot_field_checks(
    market_snapshots: pd.DataFrame,
) -> list[QaCheckResult]:
    if market_snapshots.empty:
        return []

    invalid_price_tickers = sorted(
        {
            str(row["ticker"])
            for _, row in market_snapshots.iterrows()
            if _missing_or_non_positive(row.get("share_price_local"))
        }
    )
    missing_shares_tickers = sorted(
        {
            str(row["ticker"])
            for _, row in market_snapshots.iterrows()
            if _missing_or_non_positive(row.get("shares_outstanding"))
        }
    )

    return [
        QaCheckResult(
            check_name="market_snapshot_share_price",
            status="WARN" if invalid_price_tickers else "PASS",
            dataset="market_snapshots",
            entity="tool-b",
            message=_snapshot_message(
                invalid_price_tickers,
                "share_price_local is missing or non-positive for: ",
                "share_price_local is populated for all fetched market snapshots.",
            ),
        ),
        QaCheckResult(
            check_name="market_snapshot_shares_outstanding",
            status="WARN" if missing_shares_tickers else "PASS",
            dataset="market_snapshots",
            entity="tool-b",
            message=_snapshot_message(
                missing_shares_tickers,
                "shares_outstanding is missing or non-positive for: ",
                "shares_outstanding is populated for all fetched market snapshots.",
            ),
        ),
    ]


def _missing_or_non_positive(value: object) -> bool:
    if value is None or pd.isna(value):
        return True
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return True


def _snapshot_message(
    tickers: list[str],
    failure_prefix: str,
    success_message: str,
) -> str:
    if not tickers:
        return success_message
    return failure_prefix + ", ".join(tickers)
