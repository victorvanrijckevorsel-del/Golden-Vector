"""Shared option-candidate availability rules + the `option_availability` artifact."""

from __future__ import annotations

from typing import Any

import pandas as pd

from golden_vector.common.numeric import optional_int
from golden_vector.common.strings import clean_string, normalize_ticker
from golden_vector.contracts.option_artifacts import (
    OPTION_AVAILABILITY_COLUMNS,
    OPTION_AVAILABILITY_SCHEMA_VERSION,
)


def has_usable_option_slots(slots: object) -> bool:
    """Return True when any candidate slot contains a tradable selected contract."""

    return any(
        getattr(getattr(slot, "candidate", None), "liquidity_tier", None) == "tradable"
        for slot in slots or []
    )


# --- option_availability artifact (plan §8) --------------------------------
# DORMANT: not yet published or read. The active option schema version stays 3.

AVAILABILITY_LISTED = "LISTED"
AVAILABILITY_NONE_LISTED = "NONE_LISTED"
AVAILABILITY_FETCH_FAILED = "FETCH_FAILED"
AVAILABILITY_FILTERED_WINDOW_EMPTY = "FILTERED_WINDOW_EMPTY"
AVAILABILITY_UNKNOWN = "UNKNOWN"

FETCH_STATUS_SUCCESS = "SUCCESS"
FETCH_STATUS_EMPTY = "EMPTY"
FETCH_STATUS_ERROR = "ERROR"
FETCH_STATUS_ABSENT = "ABSENT"

# The manifest snapshot entries do NOT carry the fetch status enum — only
# ticker / options_available / row_count / message / feature_status. The one
# signal that distinguishes "the enumeration succeeded and returned ZERO
# expirations" from "expirations existed but the configured window filtered them
# away" is fetch_options' verbatim empty-reason MESSAGE, mirrored here.
NO_LISTED_OPTIONS_MESSAGE = "No listed options returned by Yahoo."
WINDOW_FILTERED_MESSAGE = "No listed options matched the configured expiry fetch mode."
NO_ROWS_MESSAGE = "Yahoo returned expirations but no option rows."


def build_option_availability(
    *,
    universe_tickers: list[str],
    snapshot_records: list[dict[str, Any]],
    capture_date: str,
    provider: str = "yahoo",
) -> pd.DataFrame:
    """Return one availability row per universe ticker (plan §8).

    ``snapshot_records`` are the options manifest's ``snapshots`` entries
    (``OptionsSnapshotRecord.manifest_entry`` dicts). Only ``NONE_LISTED`` is
    written when the expiration enumeration itself succeeded and returned zero
    expirations — it is the sole status that may hide the page's options section,
    so every ambiguous case degrades to a louder status instead.
    """

    by_ticker: dict[str, dict[str, Any]] = {}
    for record in snapshot_records or []:
        ticker = normalize_ticker(record.get("ticker"))
        if ticker:
            by_ticker[ticker] = record

    rows: list[dict[str, Any]] = []
    for raw_ticker in universe_tickers:
        ticker = normalize_ticker(raw_ticker)
        if not ticker:
            continue
        record = by_ticker.get(ticker)
        rows.append(_availability_row(ticker=ticker, record=record))

    frame = pd.DataFrame(rows, columns=[
        column for column in OPTION_AVAILABILITY_COLUMNS
        if column not in {"provider", "capture_date", "schema_version"}
    ])
    frame["provider"] = str(provider)
    frame["capture_date"] = str(capture_date)
    frame["schema_version"] = OPTION_AVAILABILITY_SCHEMA_VERSION
    return frame.loc[:, list(OPTION_AVAILABILITY_COLUMNS)].reset_index(drop=True)


def _availability_row(*, ticker: str, record: dict[str, Any] | None) -> dict[str, Any]:
    if record is None:
        # A universe ticker the options stage never touched: not evidence of
        # absence.
        return {
            "ticker": ticker,
            "availability_status": AVAILABILITY_UNKNOWN,
            "expirations_enumerated": None,
            "fetch_status": FETCH_STATUS_ABSENT,
            "fetch_message": "No options manifest entry for this ticker.",
            }

    message = clean_string(record.get("message"))
    row_count = optional_int(record.get("row_count")) or 0
    options_available = bool(record.get("options_available"))
    feature_status = clean_string(record.get("feature_status")) or "OK"

    if options_available and row_count > 0:
        status = AVAILABILITY_LISTED
        fetch_status = FETCH_STATUS_SUCCESS
        expirations = None
    elif feature_status == FETCH_STATUS_ERROR or message is None:
        # feature computation failed, or an empty capture with no recorded
        # reason — never claim "no options" without the evidence.
        status = AVAILABILITY_FETCH_FAILED
        fetch_status = FETCH_STATUS_ERROR
        expirations = None
    elif (expiration_count := optional_int(record.get("expiration_count_available"))) is not None:
        # Numeric evidence beats prose. Present only on manifests written after
        # the field was threaded through; legacy entries fall through to the
        # message mapping below and keep their historical statuses.
        if expiration_count == 0:
            status = AVAILABILITY_NONE_LISTED
            fetch_status = FETCH_STATUS_EMPTY
            expirations = 0
        else:
            status = AVAILABILITY_FILTERED_WINDOW_EMPTY
            fetch_status = FETCH_STATUS_EMPTY
            expirations = expiration_count
    elif message == NO_LISTED_OPTIONS_MESSAGE:
        status = AVAILABILITY_NONE_LISTED
        fetch_status = FETCH_STATUS_EMPTY
        expirations = 0
    elif message in {WINDOW_FILTERED_MESSAGE, NO_ROWS_MESSAGE}:
        status = AVAILABILITY_FILTERED_WINDOW_EMPTY
        fetch_status = FETCH_STATUS_EMPTY
        expirations = None
    else:
        status = AVAILABILITY_FETCH_FAILED
        fetch_status = FETCH_STATUS_ERROR
        expirations = None

    return {
        "ticker": ticker,
        "availability_status": status,
        "expirations_enumerated": expirations,
        "fetch_status": fetch_status,
        "fetch_message": message,
    }
