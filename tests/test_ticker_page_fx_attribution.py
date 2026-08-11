"""Feature A: FX attribution producer acceptance tests (Codex plan §3)."""

from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.ticker_page import FX_ATTRIBUTION_COLUMNS
from golden_vector.model.ticker_page import (
    _fx_relationship,
    build_fx_attribution_series,
    build_performance_series,
)


@pytest.fixture()
def app_config():
    return load_app_config(ProjectPaths.discover()).app


def _history(
    *,
    ticker: str,
    currency: str,
    days: int,
    local_start: float,
    local_end: float,
    fx_start: float,
    fx_end: float,
    start: str = "2024-01-01",
) -> pd.DataFrame:
    """Normalized equity history whose local value and FX rate interpolate

    linearly from start to end — so window endpoints hit the exact targets.
    """
    dates = pd.bdate_range(start=start, periods=days)
    count = len(dates)
    rows = []
    for index, day in enumerate(dates):
        fraction = index / (count - 1)
        local = local_start + (local_end - local_start) * fraction
        fx = fx_start + (fx_end - fx_start) * fraction
        rows.append(
            {
                "ticker": ticker,
                "date": day,
                "currency": currency,
                "return_basis_local": local,
                "fx_rate_to_usd": fx,
                "fx_source_date": day,
                "fx_source_symbol": f"{currency}USD=X" if currency != "USD" else "USD",
                "return_basis_usd": local * fx,
                "normalization_status": "OK",
            }
        )
    return pd.DataFrame(rows)


def _one_year_row(frame: pd.DataFrame) -> pd.Series:
    row = frame[frame["horizon"] == "1Y"]
    assert len(row) == 1
    return row.iloc[0]


def test_fx_attribution_offset_matches_the_aar_style_case(app_config):
    """AUD strength offsets most of a local decline (the AAR 1Y shape)."""
    history = _history(
        ticker="AAR.AX", currency="AUD", days=200,
        local_start=10.0, local_end=9.12,     # -8.8% local
        fx_start=0.65, fx_end=0.7046,         # +8.4% FX
    )
    common_end = pd.Timestamp(history["date"].max())

    frame = build_fx_attribution_series(
        app_config=app_config, equity_history=history,
        ticker="AAR.AX", common_end=common_end,
    )
    row = _one_year_row(frame)

    assert list(frame.columns) == list(FX_ATTRIBUTION_COLUMNS)
    assert row["attribution_status"] == "OK"
    assert row["quote_currency"] == "AUD"
    assert row["local_return"] == pytest.approx(-0.088, abs=1e-6)
    assert row["fx_return"] == pytest.approx(0.084, abs=1e-6)
    # exact multiplicative reconciliation: (1+r_l)(1+r_fx)-1 == r_usd
    assert row["usd_return"] == pytest.approx(
        (1 + row["local_return"]) * (1 + row["fx_return"]) - 1, abs=1e-12
    )
    assert row["fx_contribution_pp"] == pytest.approx(
        (row["usd_return"] - row["local_return"]) * 100.0, abs=1e-9
    )
    assert row["relationship"] == "OFFSET"
    assert row["offset_of_local_move"] == pytest.approx(
        abs((row["usd_return"] - row["local_return"]) / row["local_return"]), abs=1e-9
    )
    assert row["share_of_usd_move"] is None or pd.isna(row["share_of_usd_move"])


def test_fx_attribution_same_direction_gain_and_loss(app_config):
    for local_end, fx_end in ((11.0, 0.70), (9.0, 0.60)):  # both legs up / both down
        history = _history(
            ticker="AAR.AX", currency="AUD", days=300,
            local_start=10.0, local_end=local_end,
            fx_start=0.65, fx_end=fx_end,
        )
        frame = build_fx_attribution_series(
            app_config=app_config, equity_history=history,
            ticker="AAR.AX", common_end=pd.Timestamp(history["date"].max()),
        )
        row = _one_year_row(frame)
        assert row["relationship"] == "SAME_DIRECTION"
        assert 0.0 <= row["share_of_usd_move"] <= 1.0


def test_fx_attribution_reversal(app_config):
    """FX more than offsets the local move and flips the USD sign."""
    history = _history(
        ticker="AAR.AX", currency="AUD", days=300,
        local_start=10.0, local_end=9.5,   # -5% local
        fx_start=0.65, fx_end=0.7150,      # +10% FX -> USD positive
    )
    frame = build_fx_attribution_series(
        app_config=app_config, equity_history=history,
        ticker="AAR.AX", common_end=pd.Timestamp(history["date"].max()),
    )
    row = _one_year_row(frame)
    assert row["relationship"] == "REVERSAL"
    assert row["usd_return"] > 0 > row["local_return"]
    # signed values stay visible; no forced percentage headline fields
    assert pd.isna(row["share_of_usd_move"]) and pd.isna(row["offset_of_local_move"])


def test_fx_attribution_near_zero_returns_never_explode():
    """Offsetting legs with a near-zero USD result must not produce a

    '-670%'-style share — the relationship logic caps and routes instead.
    """
    # direct unit test of the classification boundary
    relationship, share, offset = _fx_relationship(
        local_return=-0.088,
        fx_contribution=0.0877,
        usd_return=-0.0003,  # nearly fully offset
        near_zero=0.001,
    )
    assert relationship == "OFFSET"
    assert offset is not None and offset <= 1.0
    assert share is None

    # local flat
    relationship, share, offset = _fx_relationship(
        local_return=0.0002, fx_contribution=0.05, usd_return=0.0502, near_zero=0.001
    )
    assert relationship == "LOCAL_FLAT"


def test_fx_attribution_usd_listing_gets_explicit_na_rows(app_config):
    history = _history(
        ticker="NEM", currency="USD", days=300,
        local_start=40.0, local_end=44.0, fx_start=1.0, fx_end=1.0,
    )
    frame = build_fx_attribution_series(
        app_config=app_config, equity_history=history,
        ticker="NEM", common_end=pd.Timestamp(history["date"].max()),
    )
    assert set(frame["horizon"]) == set(app_config.ticker_page.chart.horizons)
    assert set(frame["relationship"]) == {"NOT_APPLICABLE_USD"}
    assert set(frame["attribution_status"]) == {"NOT_APPLICABLE_USD"}
    assert frame["usd_return"].isna().all()


def test_fx_attribution_missing_history_yields_reasoned_unavailable(app_config):
    frame = build_fx_attribution_series(
        app_config=app_config, equity_history=pd.DataFrame(),
        ticker="AAR.AX", common_end=None,
    )
    assert not frame.empty
    assert set(frame["attribution_status"]) == {"UNAVAILABLE"}
    assert frame["attribution_reason"].str.len().gt(0).all()


def test_fx_attribution_stale_normalized_rows_are_excluded(app_config):
    """A STALE_FX endpoint cannot silently become the attribution endpoint."""
    history = _history(
        ticker="AAR.AX", currency="AUD", days=300,
        local_start=10.0, local_end=9.12, fx_start=0.65, fx_end=0.7046,
    )
    # poison the final ten rows: they must be excluded, moving the endpoint back
    history.loc[history.index[-10:], "normalization_status"] = "STALE_FX"
    clean_last = pd.Timestamp(history.loc[history.index[-11], "date"])

    frame = build_fx_attribution_series(
        app_config=app_config, equity_history=history,
        ticker="AAR.AX", common_end=pd.Timestamp(history["date"].max()),
    )
    row = _one_year_row(frame)
    assert row["attribution_status"] == "OK"
    assert pd.Timestamp(row["end_date"]) == clean_last


def test_fx_attribution_reconciles_with_the_performance_chart_endpoints(app_config):
    """1Y/3Y/5Y: the attribution's endpoints and USD return must be exactly the

    stock chart's endpoints (same basis, same window rule, same common_end).
    """
    history = _history(
        ticker="AAR.AX", currency="AUD", days=1400,
        local_start=10.0, local_end=13.0, fx_start=0.60, fx_end=0.72,
    )
    gold = pd.DataFrame(
        {
            "date": history["date"],
            "adj_close_usd": [2000.0 + i for i in range(len(history))],
        }
    )
    common_end = pd.Timestamp(history["date"].max())

    performance = build_performance_series(
        app_config=app_config,
        equity_history=history,
        gold_history=gold,
        benchmark_histories={},
        ticker="AAR.AX",
        equity_as_of_date=common_end,
    )
    attribution = build_fx_attribution_series(
        app_config=app_config, equity_history=history,
        ticker="AAR.AX", common_end=common_end,
    )

    for horizon in app_config.ticker_page.chart.horizons:
        chart = performance[
            (performance["horizon"] == horizon)
            & (performance["series"] == "stock")
            & (performance["view"] == "price")
            & performance["value"].notna()
        ].sort_values("date")
        fx_row = attribution[attribution["horizon"] == horizon].iloc[0]
        assert fx_row["attribution_status"] == "OK", fx_row["attribution_reason"]
        assert pd.Timestamp(fx_row["start_date"]) == pd.Timestamp(chart["date"].iloc[0])
        assert pd.Timestamp(fx_row["end_date"]) == pd.Timestamp(chart["date"].iloc[-1])
        chart_return = float(chart["value"].iloc[-1]) / float(chart["value"].iloc[0]) - 1
        assert fx_row["usd_return"] == pytest.approx(chart_return, abs=1e-12)
        assert fx_row["price_basis"] == "return_basis_usd"


def test_fx_attribution_gbp_minor_unit_control(app_config):
    """GBp handling happens upstream at normalization; a GBP history with a

    valid rate attributes normally (the minor-unit control of the test list).
    """
    history = _history(
        ticker="THX.L", currency="GBP", days=200,
        local_start=2.50, local_end=2.75,  # +10% local (already GBP, not pence)
        fx_start=1.25, fx_end=1.30,        # +4% FX
    )
    frame = build_fx_attribution_series(
        app_config=app_config, equity_history=history,
        ticker="THX.L", common_end=pd.Timestamp(history["date"].max()),
    )
    row = _one_year_row(frame)
    assert row["attribution_status"] == "OK"
    assert row["quote_currency"] == "GBP"
    assert row["fx_source_symbol"] == "GBPUSD=X"
    assert row["local_return"] == pytest.approx(0.10, abs=1e-6)
    assert row["relationship"] == "SAME_DIRECTION"
