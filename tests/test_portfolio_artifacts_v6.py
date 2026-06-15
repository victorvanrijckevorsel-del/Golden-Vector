"""Increment 4: the v6 portfolio artifacts surface the schema-v2 fields —
quote/cost currency, backend GBP totals, provenance, and per-line FX issues —
and suppress position local P&L when the cost currency differs from the quote.
"""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from golden_vector.portfolio.models import PortfolioLot, TickerInfo
from golden_vector.portfolio.pipeline import (
    _combined_status,
    _lines_frame,
    _positions_frame,
    _summary_frame,
    _value_lot,
)


def _val(**lot_kw):
    """Value a lot against the standard AUD snapshot + GBP FX (override fx via _fx)."""
    fx = lot_kw.pop("fx_histories", None)
    return _value_lot(
        _lot(**lot_kw),
        ticker_info=_INFO,
        snapshot=_snapshot(),
        max_fx_staleness_days=5,
        fx_histories=_gbp_fx() if fx is None else fx,
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


# ---- Codex Checkpoint-1 review fixes ----------------------------------------


def test_same_currency_pnl_uses_cost_basis_total_not_shares_times_price():
    # cost_basis_total (75) != shares*buy_price (100*2=200): the canonical cost wins.
    line = _val(buy_currency="AUD", cost_currency="AUD", cost_basis_total=75.0, buy_price=2.0, shares=100.0)
    assert line.cost_local == pytest.approx(75.0)
    assert line.pnl_local == pytest.approx(30.0 - 75.0)          # value_local 100*0.30=30
    assert line.cost_usd_at_current_fx == pytest.approx(75.0 * 0.66)
    pos = _positions_frame([line], **_META).iloc[0]
    assert pos["cost_local"] == pytest.approx(75.0)
    assert pos["pnl_local"] == pytest.approx(-45.0)


def test_position_with_missing_cost_fx_publishes_no_aggregate_cost_or_pnl():
    ok = _val(id="a", buy_currency="AUD", cost_currency="AUD", cost_basis_total=100.0)
    bad = _val(id="b", buy_currency="AUD", cost_currency="CAD", cost_basis_total=100.0)  # no CAD FX
    assert bad.cost_usd_at_current_fx is None and "MISSING_COST_FX" in bad.status

    pos = _positions_frame([ok, bad], **_META).iloc[0]
    assert pd.isna(pos["cost_usd_at_current_fx"])   # not a partial sum
    assert pd.isna(pos["pnl_usd_at_current_fx"])     # no fake gain

    summary = _summary_frame([ok, bad], _positions_frame([ok, bad], **_META), **_META).iloc[0]
    assert pd.isna(summary["total_cost_usd_at_current_fx"])
    assert pd.isna(summary["total_pnl_usd_at_current_fx"])


def test_summary_gbp_totals_are_all_or_null():
    has_gbp = _val(id="a", buy_currency="AUD", cost_currency="AUD", cost_basis_total=100.0)
    no_gbp = _val(id="b", buy_currency="AUD", cost_currency="AUD", cost_basis_total=100.0, fx_histories={})
    summary = _summary_frame(
        [has_gbp, no_gbp], _positions_frame([has_gbp, no_gbp], **_META), **_META
    ).iloc[0]
    assert pd.isna(summary["total_value_gbp"])       # one line lacks GBP -> whole book GBP nulled


def test_combined_status_drops_ok_when_degraded():
    ok = _val(buy_currency="AUD", cost_currency="AUD", cost_basis_total=100.0)
    bad = _val(buy_currency="AUD", cost_currency="CAD", cost_basis_total=100.0)
    combined = _combined_status([ok, bad])
    assert "OK" not in combined.split("; ")
    assert "MISSING_COST_FX" in combined


# ---- money-audit fixes -------------------------------------------------------


def test_nan_cost_basis_does_not_fabricate_aggregate_gain():
    ok = _val(id="a", buy_currency="AUD", cost_currency="AUD", cost_basis_total=100.0)
    bad = _val(id="b", buy_currency="AUD", cost_currency="AUD", cost_basis_total=float("nan"))
    assert bad.cost_usd_at_current_fx is None and "INVALID_COST_BASIS" in bad.status

    pos = _positions_frame([ok, bad], **_META).iloc[0]
    assert pd.isna(pos["cost_usd_at_current_fx"])
    assert pd.isna(pos["pnl_usd_at_current_fx"])      # no fabricated gain from a dropped NaN cost

    summary = _summary_frame([ok, bad], _positions_frame([ok, bad], **_META), **_META).iloc[0]
    assert pd.isna(summary["total_pnl_usd_at_current_fx"])


def test_mixed_cost_currency_position_nulls_local_cost():
    gbp = _val(id="a", buy_currency="AUD", cost_currency="GBP", cost_basis_total=100.0)
    aud = _val(id="b", buy_currency="AUD", cost_currency="AUD", cost_basis_total=100.0)
    pos = _positions_frame([gbp, aud], **_META).iloc[0]
    assert pos["cost_currency"] == "MIXED"
    assert pd.isna(pos["cost_local"])                 # never sum GBP + AUD cost
    assert pd.isna(pos["avg_cost_local"])
