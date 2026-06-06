"""Fetch raw equity history for the configured universe."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from golden_vector.contracts.data_models import FetchStatusRecord
from golden_vector.ingestion.collection_resilience import bounded_worker_count
from golden_vector.ingestion.registry import EquityFetchTarget
from golden_vector.ingestion.standardize import standardize_equity_history
from golden_vector.ingestion.yahoo_client import YahooClient


def fetch_equity_histories(
    client: YahooClient,
    targets: list[EquityFetchTarget],
    *,
    max_workers: int = 1,
) -> tuple[dict[str, pd.DataFrame], list[FetchStatusRecord]]:
    histories: dict[str, pd.DataFrame] = {}
    statuses: list[FetchStatusRecord] = []

    worker_count = bounded_worker_count(max_workers=max_workers, item_count=len(targets))
    if worker_count <= 1:
        results = [_fetch_equity_history(client, target) for target in targets]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(
                executor.map(
                    lambda target: _fetch_equity_history(client, target),
                    targets,
                )
            )

    for target, standardized, status in results:
        histories[target.ticker] = standardized
        statuses.append(status)

    return histories, statuses


def _fetch_equity_history(
    client: YahooClient,
    target: EquityFetchTarget,
) -> tuple[EquityFetchTarget, pd.DataFrame, FetchStatusRecord]:
    started_at = datetime.now(timezone.utc)
    try:
        raw_history = client.fetch_history(target.yahoo_symbol, period="max")
        fetched_at = datetime.now(timezone.utc)
        standardized = standardize_equity_history(
            ticker=target.ticker,
            exchange=target.exchange,
            currency=target.currency,
            source_symbol=target.yahoo_symbol,
            frame=raw_history,
            fetched_at=fetched_at,
        )
        status = "PASS" if not standardized.empty else "FAIL"
        message = None if status == "PASS" else "No equity history returned."
        return (
            target,
            standardized,
            FetchStatusRecord(
                dataset="equities",
                entity=target.ticker,
                source_symbol=target.yahoo_symbol,
                status=status,
                row_count=len(standardized),
                started_at_utc=started_at,
                completed_at_utc=fetched_at,
                message=message,
            ),
        )
    except Exception as exc:
        fetched_at = datetime.now(timezone.utc)
        return (
            target,
            standardize_equity_history(
                ticker=target.ticker,
                exchange=target.exchange,
                currency=target.currency,
                source_symbol=target.yahoo_symbol,
                frame=pd.DataFrame(),
                fetched_at=fetched_at,
            ),
            FetchStatusRecord(
                dataset="equities",
                entity=target.ticker,
                source_symbol=target.yahoo_symbol,
                status="FAIL",
                row_count=0,
                started_at_utc=started_at,
                completed_at_utc=fetched_at,
                message=str(exc),
            ),
        )
