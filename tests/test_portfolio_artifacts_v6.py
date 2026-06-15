"""Increment 4: the v6 portfolio artifacts surface the schema-v2 fields —
quote/cost currency, backend GBP totals, provenance, and per-line FX issues —
and suppress position local P&L when the cost currency differs from the quote.
"""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from golden_vector.portfolio.models import PortfolioLot, TickerInfo
from golden_vector.portfolio.pipeline import (
    _lines_frame,
    _positions_frame,
    _summary_frame,
    _value_lot,
)

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
_INFO = {"AAR.AX": TickerInfo(ticker="AAR.AX", currency="AUD", active=True)}
_META = dict(source_run_id="run", snapshot_refresh_run_id="snap", source_hash=None, portfolio_source_version="v")


def _lot(**kw) -> PortfolioLot:
    base = dict(
        id="lot-1", ticker="AAR.AX", shares=100.0, buy_price=2.0, buy_currency="AUD",
        buy_date=date(2020, 1, 1), note=None, created_at=_NOW, updated_at=_NOW,
        cost_currency="GBP", cost_basis_total=136.0, raw_broker_symbol="AAR",
        source_name="snowball", source_file="Snowball Holdings.csv",
        cost_basis_as_of_date=date(2026, 6, 15),
    )
    base.update(kw)
    return PortfolioLot(**base)


def _snapshot() -> dict[str, object]:
    return {
        "share_price_local": 0.30, "fx_rate_to_usd": 0.66, "currency": "AUD",
        "snapshot_date": "2026-06-05", "normalization_status": "OK",
        "fx_staleness_days": 0.0, "price_scale_factor": 1.0, "minor_unit_adjusted": False,
    }


def _gbp_fx() -> dict[str, pd.DataFrame]:
    return {
        "GBP": pd.DataFrame(
            [{"base_currency": "GBP", "date": date(2026, 6, 1), "fx_rate_to_usd": 1.27, "source_symbol": "GBPUSD=X"}]
        )
    }


def _distinct_line():
    return _value_lot(_lot(), ticker_info=_INFO, snapshot=_snapshot(), max_fx_staleness_days=5, fx_histories=_gbp_fx())


def test_line_frame_surfaces_v2_columns():
    frame = _lines_frame([_distinct_line()], **_META)
    for col in [
        "quote_currency", "cost_currency", "cost_basis_total", "raw_broker_symbol",
        "source_name", "cost_basis_as_of_date", "value_gbp", "cost_gbp_at_current_fx",
        "pnl_gbp_at_current_fx", "fx_issues_json",
    ]:
        assert col in frame.columns
    row = frame.iloc[0]
    assert row["quote_currency"] == "AUD"
    assert row["cost_currency"] == "GBP"
    assert row["cost_basis_total"] == pytest.approx(136.0)
    assert row["raw_broker_symbol"] == "AAR"
    assert row["source_name"] == "snowball"
    assert "[]" == row["fx_issues_json"]   # both legs resolved -> no issues


def test_position_frame_marks_distinct_cost_and_suppresses_local_pnl():
    frame = _positions_frame([_distinct_line()], **_META)
    row = frame.iloc[0]
    assert row["quote_currency"] == "AUD"
    assert row["cost_currency"] == "GBP"
    assert row["pnl_local"] is None or pd.isna(row["pnl_local"])   # currencies differ
    assert row["value_gbp"] is not None
    assert row["cost_gbp_at_current_fx"] == pytest.approx(136.0)


def test_summary_frame_has_gbp_totals():
    line = _distinct_line()
    positions = _positions_frame([line], **_META)
    summary = _summary_frame([line], positions, **_META)
    row = summary.iloc[0]
    for col in ["total_value_gbp", "total_cost_gbp_at_current_fx", "total_pnl_gbp_at_current_fx"]:
        assert col in summary.columns
    assert row["total_cost_gbp_at_current_fx"] == pytest.approx(136.0)
    assert row["total_value_gbp"] is not None
