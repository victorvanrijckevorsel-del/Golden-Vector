"""Fetch raw market snapshot inputs for Tool B."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from golden_vector.contracts.data_models import FetchStatusRecord
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
) -> tuple[pd.DataFrame, list[FetchStatusRecord]]:
    rows: list[dict[str, object]] = []
    statuses: list[FetchStatusRecord] = []

    for target in targets:
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
            rows.append(row)
            statuses.append(
                FetchStatusRecord(
                    dataset="market_snapshots",
                    entity=target.ticker,
                    source_symbol=target.yahoo_symbol,
                    status="PASS",
                    row_count=1,
                    started_at_utc=started_at,
                    completed_at_utc=datetime.now(timezone.utc),
                    message=None,
                )
            )
        except Exception as exc:
            statuses.append(
                FetchStatusRecord(
                    dataset="market_snapshots",
                    entity=target.ticker,
                    source_symbol=target.yahoo_symbol,
                    status="FAIL",
                    row_count=0,
                    started_at_utc=started_at,
                    completed_at_utc=datetime.now(timezone.utc),
                    message=str(exc),
                )
            )

    if not rows:
        return empty_market_snapshot_frame(), statuses
    return pd.DataFrame(rows), statuses
