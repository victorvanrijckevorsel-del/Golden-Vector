"""Fetch raw gold history."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from golden_vector.contracts.data_models import FetchStatusRecord
from golden_vector.ingestion.registry import GoldFetchTarget
from golden_vector.ingestion.standardize import standardize_gold_history
from golden_vector.ingestion.yahoo_client import YahooClient


def fetch_gold_history(
    client: YahooClient,
    target: GoldFetchTarget,
) -> tuple[pd.DataFrame, FetchStatusRecord]:
    started_at = datetime.now(timezone.utc)
    try:
        raw_history = client.fetch_history(target.yahoo_symbol, period="max")
        fetched_at = datetime.now(timezone.utc)
        standardized = standardize_gold_history(
            gold_symbol=target.yahoo_symbol,
            source_symbol=target.yahoo_symbol,
            frame=raw_history,
            fetched_at=fetched_at,
        )
        status = "PASS" if not standardized.empty else "FAIL"
        message = None if status == "PASS" else "No gold history returned."
        return standardized, FetchStatusRecord(
            dataset="gold",
            entity=target.yahoo_symbol,
            source_symbol=target.yahoo_symbol,
            status=status,
            row_count=len(standardized),
            started_at_utc=started_at,
            completed_at_utc=fetched_at,
            message=message,
        )
    except Exception as exc:
        empty = standardize_gold_history(
            gold_symbol=target.yahoo_symbol,
            source_symbol=target.yahoo_symbol,
            frame=pd.DataFrame(),
            fetched_at=datetime.now(timezone.utc),
        )
        return empty, FetchStatusRecord(
            dataset="gold",
            entity=target.yahoo_symbol,
            source_symbol=target.yahoo_symbol,
            status="FAIL",
            row_count=0,
            started_at_utc=started_at,
            completed_at_utc=datetime.now(timezone.utc),
            message=str(exc),
        )
