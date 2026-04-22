from datetime import datetime, timezone

import pandas as pd

from golden_vector.features.horizons import parse_horizon_id
from golden_vector.features.returns import compute_horizon_returns_for_ticker


def _usd_equity_history() -> pd.DataFrame:
    fetched_at = datetime(2026, 1, 6, tzinfo=timezone.utc)
    return pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "date": "2026-01-01",
                "return_basis_usd": 100.0,
                "normalization_status": "OK",
                "fetched_at_utc": fetched_at,
            },
            {
                "ticker": "NEM",
                "date": "2026-01-02",
                "return_basis_usd": 101.0,
                "normalization_status": "OK",
                "fetched_at_utc": fetched_at,
            },
            {
                "ticker": "NEM",
                "date": "2026-01-03",
                "return_basis_usd": 102.0,
                "normalization_status": "OK",
                "fetched_at_utc": fetched_at,
            },
            {
                "ticker": "NEM",
                "date": "2026-01-04",
                "return_basis_usd": 103.0,
                "normalization_status": "OK",
                "fetched_at_utc": fetched_at,
            },
            {
                "ticker": "NEM",
                "date": "2026-01-05",
                "return_basis_usd": 104.0,
                "normalization_status": "OK",
                "fetched_at_utc": fetched_at,
            },
            {
                "ticker": "NEM",
                "date": "2026-01-06",
                "return_basis_usd": 120.0,
                "normalization_status": "OK",
                "fetched_at_utc": fetched_at,
            },
        ]
    )


def _gold_history(*, final_price: float = 110.0) -> pd.DataFrame:
    fetched_at = datetime(2026, 1, 6, tzinfo=timezone.utc)
    return pd.DataFrame(
        [
            {"date": "2026-01-01", "close_usd": 100.0, "adj_close_usd": 100.0, "fetched_at_utc": fetched_at},
            {"date": "2026-01-02", "close_usd": 101.0, "adj_close_usd": 101.0, "fetched_at_utc": fetched_at},
            {"date": "2026-01-03", "close_usd": 102.0, "adj_close_usd": 102.0, "fetched_at_utc": fetched_at},
            {"date": "2026-01-04", "close_usd": 103.0, "adj_close_usd": 103.0, "fetched_at_utc": fetched_at},
            {"date": "2026-01-05", "close_usd": 104.0, "adj_close_usd": 104.0, "fetched_at_utc": fetched_at},
            {"date": "2026-01-06", "close_usd": final_price, "adj_close_usd": final_price, "fetched_at_utc": fetched_at},
        ]
    )


def test_compute_horizon_returns_for_core_horizon():
    horizons = [parse_horizon_id("5D", core_horizon_ids={"5D"})]

    result = compute_horizon_returns_for_ticker(
        usd_equity_history=_usd_equity_history(),
        gold_history=_gold_history(),
        horizons=horizons,
        near_zero_gold_return_threshold=0.005,
    )

    row = result[
        (result["as_of_date"].astype(str) == "2026-01-06")
        & (result["horizon_id"] == "5D")
    ].iloc[0]

    assert row["coverage_flag"] == "PASS"
    assert round(float(row["equity_return"]), 6) == 0.2
    assert round(float(row["gold_return"]), 6) == 0.1
    assert round(float(row["gold_delta"]), 6) == 2.0
    assert bool(row["official_scoring_eligible"]) is True


def test_compute_horizon_returns_flags_near_zero_gold_return():
    horizons = [parse_horizon_id("5D", core_horizon_ids={"5D"})]

    result = compute_horizon_returns_for_ticker(
        usd_equity_history=_usd_equity_history(),
        gold_history=_gold_history(final_price=100.3),
        horizons=horizons,
        near_zero_gold_return_threshold=0.005,
    )

    row = result[
        (result["as_of_date"].astype(str) == "2026-01-06")
        & (result["horizon_id"] == "5D")
    ].iloc[0]

    assert row["coverage_flag"] == "PASS"
    assert row["coverage_reason"] == "NEAR_ZERO_GOLD_RETURN"
    assert pd.isna(row["gold_delta"])
    assert bool(row["official_scoring_eligible"]) is False


def test_compute_horizon_returns_marks_custom_horizons_not_official():
    horizons = [parse_horizon_id("45D", core_horizon_ids={"5D"})]

    result = compute_horizon_returns_for_ticker(
        usd_equity_history=_usd_equity_history(),
        gold_history=_gold_history(),
        horizons=horizons,
        near_zero_gold_return_threshold=0.005,
    )

    row = result.iloc[0]

    assert row["horizon_mode"] == "custom"
    assert bool(row["official_scoring_eligible"]) is False


def test_compute_horizon_returns_emits_rows_for_each_date_and_marks_insufficient_history():
    horizons = [parse_horizon_id("5D", core_horizon_ids={"5D"})]

    result = compute_horizon_returns_for_ticker(
        usd_equity_history=_usd_equity_history(),
        gold_history=_gold_history(),
        horizons=horizons,
        near_zero_gold_return_threshold=0.005,
    )

    assert len(result.index) == 6
    insufficient_rows = result[result["coverage_reason"] == "INSUFFICIENT_HISTORY"]
    assert len(insufficient_rows.index) == 5
    assert insufficient_rows["start_date"].isna().all()


def test_compute_horizon_returns_uses_calendar_horizon_start_dates():
    fetched_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    usd_equity_history = pd.DataFrame(
        [
            {"ticker": "NEM", "date": "2026-01-30", "return_basis_usd": 100.0, "normalization_status": "OK", "fetched_at_utc": fetched_at},
            {"ticker": "NEM", "date": "2026-02-02", "return_basis_usd": 101.0, "normalization_status": "OK", "fetched_at_utc": fetched_at},
            {"ticker": "NEM", "date": "2026-02-27", "return_basis_usd": 110.0, "normalization_status": "OK", "fetched_at_utc": fetched_at},
            {"ticker": "NEM", "date": "2026-03-02", "return_basis_usd": 111.0, "normalization_status": "OK", "fetched_at_utc": fetched_at},
            {"ticker": "NEM", "date": "2026-03-31", "return_basis_usd": 121.0, "normalization_status": "OK", "fetched_at_utc": fetched_at},
        ]
    )
    gold_history = pd.DataFrame(
        [
            {"date": "2026-01-30", "close_usd": 200.0, "adj_close_usd": 200.0, "fetched_at_utc": fetched_at},
            {"date": "2026-02-02", "close_usd": 202.0, "adj_close_usd": 202.0, "fetched_at_utc": fetched_at},
            {"date": "2026-02-27", "close_usd": 220.0, "adj_close_usd": 220.0, "fetched_at_utc": fetched_at},
            {"date": "2026-03-02", "close_usd": 221.0, "adj_close_usd": 221.0, "fetched_at_utc": fetched_at},
            {"date": "2026-03-31", "close_usd": 242.0, "adj_close_usd": 242.0, "fetched_at_utc": fetched_at},
        ]
    )
    horizons = [parse_horizon_id("1M", core_horizon_ids={"1M"})]

    result = compute_horizon_returns_for_ticker(
        usd_equity_history=usd_equity_history,
        gold_history=gold_history,
        horizons=horizons,
        near_zero_gold_return_threshold=0.005,
    )

    row = result[result["as_of_date"].astype(str) == "2026-03-31"].iloc[0]

    assert str(row["start_date"]) == "2026-02-27"
    assert row["coverage_flag"] == "PASS"
    assert round(float(row["gold_delta"]), 6) == 1.0
