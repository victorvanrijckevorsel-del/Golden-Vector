"""Fetch raw market snapshot inputs for Tool B."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from golden_vector.contracts.data_models import FetchStatusRecord
from golden_vector.ingestion.collection_resilience import bounded_worker_count
from golden_vector.ingestion.registry import MarketSnapshotTarget
from golden_vector.ingestion.standardize import (
    empty_market_snapshot_frame,
    standardize_market_snapshot,
)
from golden_vector.ingestion.yahoo_client import YahooClient


def fetch_market_snapshots(
    client: YahooClient,
    targets: list[MarketSnapshotTarget],
    source_run_id: str,
    *,
    max_workers: int = 1,
) -> tuple[pd.DataFrame, list[FetchStatusRecord]]:
    rows: list[dict[str, object]] = []
    statuses: list[FetchStatusRecord] = []

    worker_count = bounded_worker_count(max_workers=max_workers, item_count=len(targets))
    if worker_count <= 1:
        results = [
            _fetch_market_snapshot(client, target, source_run_id)
            for target in targets
        ]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(
                executor.map(
                    lambda target: _fetch_market_snapshot(
                        client,
                        target,
                        source_run_id,
                    ),
                    targets,
                )
            )

    for row, status in results:
        if row is not None:
            rows.append(row)
        statuses.append(status)

    if not rows:
        return empty_market_snapshot_frame(), statuses
    return pd.DataFrame(rows), statuses


def _fetch_market_snapshot(
    client: YahooClient,
    target: MarketSnapshotTarget,
    source_run_id: str,
) -> tuple[dict[str, object] | None, FetchStatusRecord]:
    started_at = datetime.now(timezone.utc)
    try:
        recent_history = client.fetch_history(target.yahoo_symbol, period="5d")
        fast_info = dict(client.fetch_fast_info(target.yahoo_symbol))
        row = standardize_market_snapshot(
            ticker=target.ticker,
            currency=target.currency,
            frame=recent_history,
            fast_info=fast_info,
            source_run_id=source_run_id,
        )
        return (
            row,
            FetchStatusRecord(
                dataset="market_snapshots",
                entity=target.ticker,
                source_symbol=target.yahoo_symbol,
                status="PASS",
                row_count=1,
                started_at_utc=started_at,
                completed_at_utc=datetime.now(timezone.utc),
                message=None,
            ),
        )
    except Exception as exc:
        return (
            None,
            FetchStatusRecord(
                dataset="market_snapshots",
                entity=target.ticker,
                source_symbol=target.yahoo_symbol,
                status="FAIL",
                row_count=0,
                started_at_utc=started_at,
                completed_at_utc=datetime.now(timezone.utc),
                message=str(exc),
            ),
        )
