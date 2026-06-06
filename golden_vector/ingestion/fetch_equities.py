"""Fetch raw equity history for the configured universe."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from golden_vector.contracts.data_models import FetchStatusRecord
from golden_vector.ingestion.collection_resilience import map_with_bounded_workers
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

    results = map_with_bounded_workers(
        targets,
        max_workers=max_workers,
        func=lambda target: _fetch_equity_history(client, target),
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
