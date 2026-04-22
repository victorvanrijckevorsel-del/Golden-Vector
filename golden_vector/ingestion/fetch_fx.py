"""Fetch raw FX history for configured currencies."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from golden_vector.contracts.data_models import FetchStatusRecord
from golden_vector.ingestion.registry import FxFetchTarget
from golden_vector.ingestion.standardize import standardize_fx_history
from golden_vector.ingestion.yahoo_client import YahooClient


def fetch_fx_histories(
    client: YahooClient,
    targets: list[FxFetchTarget],
) -> tuple[dict[str, pd.DataFrame], list[FetchStatusRecord]]:
    histories: dict[str, pd.DataFrame] = {}
    statuses: list[FetchStatusRecord] = []

    for target in targets:
        started_at = datetime.now(timezone.utc)
        try:
            raw_history = client.fetch_history(target.yahoo_symbol, period="max")
            fetched_at = datetime.now(timezone.utc)
            standardized = standardize_fx_history(
                base_currency=target.base_currency,
                source_symbol=target.yahoo_symbol,
                frame=raw_history,
                fetched_at=fetched_at,
            )
            histories[target.base_currency] = standardized
            status = "PASS" if not standardized.empty else "FAIL"
            message = None if status == "PASS" else "No FX history returned."
            statuses.append(
                FetchStatusRecord(
                    dataset="fx",
                    entity=target.base_currency,
                    source_symbol=target.yahoo_symbol,
                    status=status,
                    row_count=len(standardized),
                    started_at_utc=started_at,
                    completed_at_utc=fetched_at,
                    message=message,
                )
            )
        except Exception as exc:
            statuses.append(
                FetchStatusRecord(
                    dataset="fx",
                    entity=target.base_currency,
                    source_symbol=target.yahoo_symbol,
                    status="FAIL",
                    row_count=0,
                    started_at_utc=started_at,
                    completed_at_utc=datetime.now(timezone.utc),
                    message=str(exc),
                )
            )
            histories[target.base_currency] = standardize_fx_history(
                base_currency=target.base_currency,
                source_symbol=target.yahoo_symbol,
                frame=pd.DataFrame(),
                fetched_at=datetime.now(timezone.utc),
            )

    return histories, statuses
