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


def test_numeric_expiration_evidence_outranks_the_message_text():
    """A post-threading manifest decides on the count, not the prose."""

    frame = build_option_availability(
        universe_tickers=["ZERO", "WINDOW", "MISLABELLED"],
        snapshot_records=[
            # Enumeration succeeded and returned zero expirations.
            {"ticker": "ZERO", "options_available": False, "row_count": 1,
             "message": NO_LISTED_OPTIONS_MESSAGE, "feature_status": "OK",
             "expiration_count_available": 0},
            # Expirations existed; the configured window filtered them away.
            {"ticker": "WINDOW", "options_available": False, "row_count": 1,
             "message": WINDOW_FILTERED_MESSAGE, "feature_status": "OK",
             "expiration_count_available": 14},
            # Message says "no listed options" but 9 expirations were enumerated:
            # the number wins, so the page never hides a name that has options.
            {"ticker": "MISLABELLED", "options_available": False, "row_count": 1,
             "message": NO_LISTED_OPTIONS_MESSAGE, "feature_status": "OK",
             "expiration_count_available": 9},
        ],
        capture_date="2026-08-10",
    ).set_index("ticker")

    assert frame.loc["ZERO", "availability_status"] == "NONE_LISTED"
    assert frame.loc["ZERO", "expirations_enumerated"] == 0
    assert frame.loc["WINDOW", "availability_status"] == "FILTERED_WINDOW_EMPTY"
    assert frame.loc["WINDOW", "expirations_enumerated"] == 14
    assert frame.loc["MISLABELLED", "availability_status"] == "FILTERED_WINDOW_EMPTY"
    assert frame.loc["MISLABELLED", "expirations_enumerated"] == 9


def test_legacy_manifests_without_the_field_keep_their_old_statuses():
    """Regression: the message mapping is unchanged for pre-threading entries."""

    legacy = build().set_index("ticker")
    assert legacy.loc["NOOPT", "availability_status"] == "NONE_LISTED"
    assert legacy.loc["FILT", "availability_status"] == "FILTERED_WINDOW_EMPTY"
    assert legacy.loc["BOOM", "availability_status"] == "FETCH_FAILED"
    # An explicit None is as legacy as an absent key.
    none_valued = build_option_availability(
        universe_tickers=["NOOPT"],
        snapshot_records=[
            {"ticker": "NOOPT", "options_available": False, "row_count": 1,
             "message": NO_LISTED_OPTIONS_MESSAGE, "feature_status": "OK",
             "expiration_count_available": None},
        ],
        capture_date="2026-08-10",
    )
    assert none_valued.iloc[0]["availability_status"] == "NONE_LISTED"


def test_a_failed_fetch_stays_fetch_failed_even_with_a_zero_count():
    """The ERROR path records a zero count; it must not read as NONE_LISTED."""

    frame = build_option_availability(
        universe_tickers=["BOOM"],
        snapshot_records=[
            {"ticker": "BOOM", "options_available": False, "row_count": 1,
             "message": "HTTPError: 500 from Yahoo", "feature_status": "ERROR",
             "expiration_count_available": 0},
        ],
        capture_date="2026-08-10",
    )
    assert frame.iloc[0]["availability_status"] == "FETCH_FAILED"


def test_lowercase_feature_status_error_still_routes_to_fetch_failed():
    """Case/whitespace must not decide whether an ERROR is honoured."""

    frame = build_option_availability(
        universe_tickers=["LOUD", "PADDED", "CTRL"],
        snapshot_records=[
            # A lowercase ERROR with a message that would otherwise be read as
            # "no listed options" and HIDE the page's options section.
            {"ticker": "LOUD", "options_available": False, "row_count": 0,
             "message": NO_LISTED_OPTIONS_MESSAGE, "feature_status": "error"},
            {"ticker": "PADDED", "options_available": False, "row_count": 0,
             "message": NO_LISTED_OPTIONS_MESSAGE, "feature_status": "  Error  "},
            # Control: a genuinely OK empty enumeration still says NONE_LISTED.
            {"ticker": "CTRL", "options_available": False, "row_count": 0,
             "message": NO_LISTED_OPTIONS_MESSAGE, "feature_status": "ok"},
        ],
        capture_date="2026-08-10",
    ).set_index("ticker")

    assert frame.loc["LOUD", "availability_status"] == "FETCH_FAILED"
    assert frame.loc["LOUD", "fetch_status"] == "ERROR"
    assert frame.loc["PADDED", "availability_status"] == "FETCH_FAILED"
    assert frame.loc["CTRL", "availability_status"] == "NONE_LISTED"


def test_carried_listed_snapshot_keeps_source_state_and_exposes_failed_attempt():
    frame = build_option_availability(
        universe_tickers=["AEM"],
        snapshot_records=[
            {
                "ticker": "AEM",
                "options_available": True,
                "row_count": 1200,
                "feature_status": "OK",
                "source_refresh_run_id": "prior-run",
                "source_as_of_date": "2026-08-07",
                "captured_at_utc": "2026-08-07T20:00:00Z",
                "carried_forward": True,
                "attempt_status": "ERROR",
                "attempt_message": "vendor timeout",
            }
        ],
        capture_date="2026-08-12",
    ).iloc[0]

    assert frame["availability_status"] == "LISTED"
    assert frame["fetch_status"] == "SUCCESS"
    assert frame["source_refresh_run_id"] == "prior-run"
    assert frame["source_as_of_date"] == "2026-08-07"
    assert bool(frame["carried_forward"]) is True
    assert frame["attempt_status"] == "ERROR"
    assert frame["attempt_message"] == "vendor timeout"
    assert frame["display_staleness_trading_days"] == 3
    assert frame["display_freshness_status"] == "STALE"
