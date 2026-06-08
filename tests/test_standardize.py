from datetime import datetime, timezone

import pandas as pd
import pytest

from golden_vector.ingestion.standardize import (
    empty_market_snapshot_frame,
    standardize_equity_history,
    standardize_fx_history,
    standardize_gold_history,
    standardize_market_snapshot,
)


def test_standardize_equity_history_maps_price_columns_and_metadata():
    fetched_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {
            "Date": ["2026-01-30"],
            "Open": [10.0],
            "High": [11.0],
            "Low": [9.0],
            "Close": [10.5],
            "Adj Close": [10.4],
            "Volume": [1_000_000],
        }
    )

    standardized = standardize_equity_history(
        ticker="NEM",
        exchange="NYSE",
        currency="USD",
        source_symbol="NEM",
        frame=frame,
        fetched_at=fetched_at,
    )

    row = standardized.iloc[0]
    assert row["ticker"] == "NEM"
    assert str(row["date"]) == "2026-01-30"
    assert row["adj_close_local"] == 10.4
    assert row["exchange"] == "NYSE"
    assert row["source"] == "yfinance"
    assert row["price_scale_factor"] == 1.0
    assert bool(row["minor_unit_adjusted"]) is False


def test_standardize_equity_history_converts_lse_pence_to_pounds():
    fetched_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {
            "Date": ["2026-01-30"],
            "Open": [38.0],
            "High": [40.0],
            "Low": [37.5],
            "Close": [39.0],
            "Adj Close": [39.0],
            "Volume": [1_000_000],
        }
    )

    standardized = standardize_equity_history(
        ticker="PAF.L",
        exchange="LSE",
        currency="GBP",
        source_symbol="PAF.L",
        frame=frame,
        fetched_at=fetched_at,
        feed_currency="GBp",
    )

    row = standardized.iloc[0]
    assert row["open_local"] == pytest.approx(0.38)
    assert row["close_local"] == pytest.approx(0.39)
    assert row["adj_close_local"] == pytest.approx(0.39)
    assert row["currency"] == "GBP"
    assert row["feed_currency"] == "GBp"
    assert row["price_scale_factor"] == pytest.approx(0.01)
    assert bool(row["minor_unit_adjusted"]) is True


def test_standardize_fx_and_gold_history_map_expected_fields():
    fetched_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {
            "Date": ["2026-01-30"],
            "Close": [0.72],
            "Adj Close": [3010.0],
        }
    )

    fx = standardize_fx_history(
        base_currency="AUD",
        source_symbol="AUDUSD=X",
        frame=frame[["Date", "Close"]],
        fetched_at=fetched_at,
    )
    gold = standardize_gold_history(
        gold_symbol="GC=F",
        source_symbol="GC=F",
        frame=frame,
        fetched_at=fetched_at,
    )

    assert fx.iloc[0]["fx_pair"] == "AUDUSD"
    assert fx.iloc[0]["fx_rate_to_usd"] == 0.72
    assert gold.iloc[0]["close_usd"] == 0.72
    assert gold.iloc[0]["adj_close_usd"] == 3010.0


def test_standardize_market_snapshot_populates_usd_fields_for_usd_names():
    frame = pd.DataFrame({"Date": ["2026-02-01"], "Close": [60.0]})

    snapshot = standardize_market_snapshot(
        ticker="NEM",
        currency="USD",
        frame=frame,
        fast_info={"marketCap": 48_000_000_000.0, "sharesOutstanding": 800_000_000.0},
        source_run_id="run-1",
    )

    assert snapshot["share_price_local"] == 60.0
    assert snapshot["fx_rate_to_usd"] == 1.0
    assert snapshot["share_price_usd"] == 60.0
    assert snapshot["market_cap_usd"] == 48_000_000_000.0


def test_standardize_market_snapshot_leaves_non_usd_conversion_for_later():
    frame = pd.DataFrame({"Date": ["2026-02-01"], "Close": [25.0]})

    snapshot = standardize_market_snapshot(
        ticker="DPM.TO",
        currency="CAD",
        frame=frame,
        fast_info={"marketCap": 3_000_000_000.0, "sharesOutstanding": 120_000_000.0},
        source_run_id="run-1",
    )

    assert snapshot["currency"] == "CAD"
    assert snapshot["fx_rate_to_usd"] is None
    assert snapshot["share_price_usd"] is None
    assert snapshot["market_cap_usd"] is None


def test_standardize_market_snapshot_converts_lse_pence_to_pounds():
    # Yahoo serves LSE prices in pence (currency tag "GBp"); they must be /100
    # to pounds so the later local->USD step isn't ~100x too large.
    frame = pd.DataFrame({"Date": ["2026-02-01"], "Close": [39.0]})

    snapshot = standardize_market_snapshot(
        ticker="PAF.L",
        currency="GBP",
        frame=frame,
        fast_info={"currency": "GBp", "sharesOutstanding": 2_000_000_000.0},
        source_run_id="run-1",
    )

    assert snapshot["share_price_local"] == pytest.approx(0.39)
    assert snapshot["currency"] == "GBP"


def test_standardize_market_snapshot_keeps_genuine_pound_quote_unchanged():
    # Case-sensitive: a real GBP (pounds) quote must NOT be divided by 100.
    frame = pd.DataFrame({"Date": ["2026-02-01"], "Close": [12.5]})

    snapshot = standardize_market_snapshot(
        ticker="FRES.L",
        currency="GBP",
        frame=frame,
        fast_info={"currency": "GBP", "sharesOutstanding": 700_000_000.0},
        source_run_id="run-1",
    )

    assert snapshot["share_price_local"] == 12.5


def test_standardize_market_snapshot_falls_back_to_fast_info_price_when_close_is_missing():
    frame = pd.DataFrame({"Date": ["2026-02-01"], "Close": [None], "Adj Close": [None]})

    snapshot = standardize_market_snapshot(
        ticker="NEM",
        currency="USD",
        frame=frame,
        fast_info={"currentPrice": 61.5, "sharesOutstanding": 800_000_000.0},
        source_run_id="run-1",
    )

    assert snapshot["share_price_local"] == 61.5


def test_standardize_market_snapshot_rejects_invalid_share_price_cleanly():
    frame = pd.DataFrame({"Date": ["2026-02-01"], "Close": [None]})

    with pytest.raises(ValueError, match="no valid positive share price"):
        standardize_market_snapshot(
            ticker="NEM",
            currency="USD",
            frame=frame,
            fast_info={},
            source_run_id="run-1",
        )


def test_standardize_market_snapshot_rejects_missing_date_cleanly():
    frame = pd.DataFrame({"Close": [60.0]})

    with pytest.raises(ValueError, match="missing Date"):
        standardize_market_snapshot(
            ticker="NEM",
            currency="USD",
            frame=frame,
            fast_info={},
            source_run_id="run-1",
        )


def test_standardize_market_snapshot_rejects_empty_recent_history():
    with pytest.raises(ValueError, match="No recent history returned for market snapshot"):
        standardize_market_snapshot(
            ticker="NEM",
            currency="USD",
            frame=pd.DataFrame(),
            fast_info={},
            source_run_id="run-1",
        )


def test_empty_market_snapshot_frame_has_expected_columns():
    frame = empty_market_snapshot_frame()

    assert list(frame.columns) == [
        "ticker",
        "snapshot_date",
        "share_price_local",
        "currency",
        "fx_rate_to_usd",
        "share_price_usd",
        "market_cap_usd",
        "shares_outstanding",
        "source",
        "source_run_id",
        "feed_currency",
        "price_scale_factor",
        "minor_unit_adjusted",
    ]
