"""Raw-data quality checks for the foundation pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.contracts.config_models import AppConfig
from golden_vector.contracts.data_models import FetchStatusRecord, QaCheckResult
from golden_vector.ingestion.collection_resilience import (
    failed_fetch_entities,
    fetch_dataset_outage_status,
)
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
    failed_equity_tickers = failed_fetch_entities(fetch_statuses, dataset="equities")
    blocking_vendor_outage = _is_blocking_vendor_outage(fetch_statuses)

    results.append(_currency_map_check(app_config, registry))
    results.append(_vendor_outage_check(fetch_statuses))
    results.extend(
        _status_results(
            fetch_statuses,
            blocking_vendor_outage=blocking_vendor_outage,
        )
    )

    for ticker, frame in equity_histories.items():
        if ticker in failed_equity_tickers and not blocking_vendor_outage:
            results.append(
                QaCheckResult(
                    check_name="history_presence",
                    status="WARN",
                    dataset="equities",
                    entity=ticker,
                    message=(
                        "No rows available because the Yahoo fetch failed for this "
                        "ticker. The failure is carried as a visible per-ticker "
                        "data issue; the refresh can continue for other names."
                    ),
                )
            )
            continue
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


def _status_results(
    fetch_statuses: list[FetchStatusRecord],
    *,
    blocking_vendor_outage: bool,
) -> list[QaCheckResult]:
    results: list[QaCheckResult] = []
    for status in fetch_statuses:
        mapped_status = status.status
        if (
            status.dataset in {"equities", "market_snapshots"}
            and status.status == "FAIL"
            and not blocking_vendor_outage
        ):
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


def _vendor_outage_check(fetch_statuses: list[FetchStatusRecord]) -> QaCheckResult:
    if not fetch_statuses:
        return QaCheckResult(
            check_name="vendor_outage_policy",
            status="PASS",
            dataset="market_data",
            entity="yahoo",
            message="No Yahoo-backed fetches were requested.",
        )
    fail_count = sum(
        1 for status in fetch_statuses if str(status.status).upper() == "FAIL"
    )
    total_count = len(fetch_statuses)
    if fail_count == total_count:
        return QaCheckResult(
            check_name="vendor_outage_policy",
            status="FAIL",
            dataset="market_data",
            entity="yahoo",
            message=(
                f"Yahoo full outage: all {total_count} requested fetches failed. "
                "The latest published state must be left unchanged."
            ),
        )
    if fetch_dataset_outage_status(fetch_statuses, dataset="equities") == "FULL_OUTAGE":
        equity_count = sum(1 for status in fetch_statuses if status.dataset == "equities")
        return QaCheckResult(
            check_name="vendor_outage_policy",
            status="FAIL",
            dataset="market_data",
            entity="yahoo",
            message=(
                f"Yahoo equity outage: all {equity_count} equity fetches failed. "
                "The latest published state must be left unchanged."
            ),
        )
    if fail_count:
        return QaCheckResult(
            check_name="vendor_outage_policy",
            status="WARN",
            dataset="market_data",
            entity="yahoo",
            message=(
                f"Yahoo per-ticker outage: {fail_count} of {total_count} fetches "
                "failed and remain visible as data issues."
            ),
        )
    return QaCheckResult(
        check_name="vendor_outage_policy",
        status="PASS",
        dataset="market_data",
        entity="yahoo",
        message=f"Yahoo fetches completed for all {total_count} requested inputs.",
    )


def _is_blocking_vendor_outage(fetch_statuses: list[FetchStatusRecord]) -> bool:
    if fetch_dataset_outage_status(fetch_statuses, dataset="equities") == "FULL_OUTAGE":
        return True
    return bool(fetch_statuses) and all(
        str(status.status).upper() == "FAIL"
        for status in fetch_statuses
    )


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
