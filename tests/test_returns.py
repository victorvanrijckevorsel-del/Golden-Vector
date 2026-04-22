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
