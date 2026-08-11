"""option_availability artifact (plan §8) — all five enum values."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.option_artifacts import (
    OPTION_AVAILABILITY_COLUMNS,
    OPTION_AVAILABILITY_SCHEMA_VERSION,
)
from golden_vector.hedge.option_availability import (
    NO_LISTED_OPTIONS_MESSAGE,
    WINDOW_FILTERED_MESSAGE,
    build_option_availability,
)

# One fixture manifest covering every enum value at once.
SNAPSHOTS = [
    # healthy listed control
    {"ticker": "AEM", "options_available": True, "row_count": 1200, "message": None,
     "feature_status": "OK"},
    # enumeration SUCCEEDED and returned zero expirations -> the only status
    # that may hide the page section
    {"ticker": "NOOPT", "options_available": False, "row_count": 1,
     "message": NO_LISTED_OPTIONS_MESSAGE, "feature_status": "OK"},
    # expirations existed but the configured window filtered them away
    {"ticker": "FILT", "options_available": False, "row_count": 1,
     "message": WINDOW_FILTERED_MESSAGE, "feature_status": "OK"},
    # vendor error
    {"ticker": "BOOM", "options_available": False, "row_count": 1,
     "message": "HTTPError: 500 from Yahoo", "feature_status": "ERROR"},
    # 'MISSING' is deliberately absent from the manifest -> UNKNOWN
]

UNIVERSE = ["AEM", "NOOPT", "FILT", "BOOM", "MISSING"]


def build():
    return build_option_availability(
        universe_tickers=UNIVERSE,
        snapshot_records=SNAPSHOTS,
        capture_date="2026-08-10",
    )


def test_every_enum_value_is_produced_with_its_evidence():
    frame = build().set_index("ticker")
    assert frame.loc["AEM", "availability_status"] == "LISTED"
    assert frame.loc["NOOPT", "availability_status"] == "NONE_LISTED"
    assert frame.loc["FILT", "availability_status"] == "FILTERED_WINDOW_EMPTY"
    assert frame.loc["BOOM", "availability_status"] == "FETCH_FAILED"
    assert frame.loc["MISSING", "availability_status"] == "UNKNOWN"

    # Only the successful zero-expiration enumeration claims a count of 0.
    assert frame.loc["NOOPT", "expirations_enumerated"] == 0
    for ticker in ("AEM", "FILT", "BOOM", "MISSING"):
        assert pd.isna(frame.loc[ticker, "expirations_enumerated"])

    assert frame.loc["BOOM", "fetch_status"] == "ERROR"
    assert frame.loc["BOOM", "fetch_message"] == "HTTPError: 500 from Yahoo"
    assert frame.loc["MISSING", "fetch_status"] == "ABSENT"


def test_shape_is_universe_complete_and_stamped():
    frame = build()
    assert list(frame.columns) == list(OPTION_AVAILABILITY_COLUMNS)
    assert list(frame["ticker"]) == UNIVERSE
    assert set(frame["provider"]) == {"yahoo"}
    assert set(frame["capture_date"]) == {"2026-08-10"}
    assert set(frame["schema_version"]) == {OPTION_AVAILABILITY_SCHEMA_VERSION}


def test_empty_capture_without_a_recorded_reason_never_claims_no_options():
    frame = build_option_availability(
        universe_tickers=["QUIET"],
        snapshot_records=[
            {"ticker": "QUIET", "options_available": False, "row_count": 1,
             "message": None, "feature_status": "OK"}
        ],
        capture_date="2026-08-10",
    )
    assert frame.iloc[0]["availability_status"] == "FETCH_FAILED"


def test_no_snapshots_at_all_gives_unknown_for_everyone():
    frame = build_option_availability(
        universe_tickers=["AEM", "NEM"],
        snapshot_records=[],
        capture_date="2026-08-10",
    )
    assert set(frame["availability_status"]) == {"UNKNOWN"}
