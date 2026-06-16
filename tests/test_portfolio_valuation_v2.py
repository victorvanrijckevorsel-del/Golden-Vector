"""Increment 3b: multi-currency valuation.

Cost is converted via its OWN currency's FX (not the quote FX); local P&L is
suppressed when cost currency != quote currency; GBP presentation is computed in
the backend; FX gaps are reported leg-by-leg (cost FX degrades, presentation FX
does not).
"""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from golden_vector.portfolio.models import PortfolioLot, TickerInfo
from golden_vector.portfolio.pipeline import _value_lot

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _lot(**overrides) -> PortfolioLot:
    base = dict(
        id="lot-1",
        ticker="AAR.AX",
        shares=100.0,
        buy_price=2.0,
        buy_currency="AUD",
        buy_date=date(2020, 1, 1),
        note=None,
        created_at=_NOW,
        updated_at=_NOW,
        cost_currency="AUD",
        cost_basis_total=200.0,
        raw_broker_symbol="AAR",
        source_name="manual",
        source_file=None,
        cost_basis_as_of_date=date(2020, 1, 1),
    )
    base.update(overrides)
    return PortfolioLot(**base)


def _snapshot(*, currency: str, price: float, fx: float) -> dict[str, object]:
    return {
        "share_price_local": price,
        "fx_rate_to_usd": fx,
        "currency": currency,
        "snapshot_date": "2026-06-05",
        "normalization_status": "OK",
        "fx_staleness_days": 0.0,
        "price_scale_factor": 1.0,
        "minor_unit_adjusted": False,
    }


def _fx(currency: str, rate: float) -> pd.DataFrame:
    return pd.DataFrame(
        [{"base_currency": currency, "date": date(2026, 6, 1), "fx_rate_to_usd": rate, "source_symbol": f"{currency}USD=X"}]
    )


_INFO = {"AAR.AX": TickerInfo(ticker="AAR.AX", currency="AUD", active=True)}


def test_same_currency_lot_preserves_local_pnl_and_uses_quote_fx():
    lot = _lot(buy_currency="AUD", cost_currency="AUD", cost_basis_total=200.0, buy_price=2.0)
    line = _value_lot(
        lot,
        ticker_info=_INFO,
        snapshot=_snapshot(currency="AUD", price=3.0, fx=0.66),
        max_fx_staleness_days=5,
        fx_histories={"GBP": _fx("GBP", 1.27)},
    )
    assert line.value_local == pytest.approx(300.0)        # 100 * 3
    assert line.cost_usd_at_current_fx == pytest.approx(132.0)   # 200 cost * 0.66 (quote FX)
    assert line.pnl_local == pytest.approx(100.0)          # 300 - 200, same currency
    assert line.status == "OK"
    assert line.fx_issues == ()
    # GBP presentation via GBPUSD=1.27: value_usd 198 / 1.27
    assert line.value_gbp == pytest.approx(198.0 / 1.27)


def test_distinct_cost_currency_uses_cost_fx_and_suppresses_local_pnl():
    # GBP cost on an AUD-quoted ticker (the Snowball case).
    lot = _lot(buy_currency="AUD", cost_currency="GBP", cost_basis_total=136.0)
    line = _value_lot(
        lot,
        ticker_info=_INFO,
        snapshot=_snapshot(currency="AUD", price=0.30, fx=0.66),
        max_fx_staleness_days=5,
        fx_histories={"GBP": _fx("GBP", 1.27)},
    )
    assert line.quote_currency == "AUD"
    assert line.cost_currency == "GBP"
    assert line.cost_usd_at_current_fx == pytest.approx(136.0 * 1.27)   # cost via GBP FX, not AUD
    assert line.pnl_local is None                                        # currencies differ
    assert line.pnl_fraction_local is None
    assert line.cost_gbp_at_current_fx == pytest.approx(136.0)          # back to GBP
    assert line.status == "OK"
    assert line.fx_issues == ()


def test_position_frame_exposes_gbp_cost_and_pnl_for_distinct_cost_currency():
    # GBP-cost / AUD-quote position: local cost/P&L are NA, so the position frame must
    # surface avg_cost_gbp + pnl_fraction_gbp (+ cost/pnl in GBP) for the page to render
    # them instead of a dash.
    from golden_vector.portfolio.pipeline import _positions_frame

    lot = _lot(buy_currency="AUD", cost_currency="GBP", cost_basis_total=136.0, shares=100.0)
    line = _value_lot(
        lot,
        ticker_info=_INFO,
        snapshot=_snapshot(currency="AUD", price=0.30, fx=0.66),
        max_fx_staleness_days=5,
        fx_histories={"GBP": _fx("GBP", 1.27)},
    )
    pos = _positions_frame(
        [line],
        source_run_id="r",
        snapshot_refresh_run_id="s",
        source_hash=None,
        portfolio_source_version="v",
    )
    row = pos.iloc[0]
    assert pd.isna(row["pnl_local"])  # local P&L NA when cost currency != quote currency
    assert pd.isna(row["avg_cost_local"])
    assert row["avg_cost_gbp"] == pytest.approx(136.0 / 100.0)  # GBP cost per share
    assert row["cost_gbp_at_current_fx"] == pytest.approx(136.0)
    value_gbp = (100 * 0.30 * 0.66) / 1.27
    assert row["pnl_gbp_at_current_fx"] == pytest.approx(value_gbp - 136.0)
    assert row["pnl_fraction_gbp"] == pytest.approx((value_gbp - 136.0) / 136.0)


def test_missing_cost_fx_degrades_line():
    lot = _lot(buy_currency="AUD", cost_currency="CAD", cost_basis_total=100.0)
    line = _value_lot(
        lot,
        ticker_info=_INFO,
        snapshot=_snapshot(currency="AUD", price=3.0, fx=0.66),
        max_fx_staleness_days=5,
        fx_histories={"GBP": _fx("GBP", 1.27)},  # no CAD
    )
    assert line.cost_usd_at_current_fx is None
    assert line.pnl_usd_at_current_fx is None
    assert "MISSING_COST_FX" in line.status
    assert "cost_fx" in line.fx_issues
    assert line.value_usd == pytest.approx(198.0)   # value leg still valid


def test_stale_quote_fx_excludes_usd_and_gbp_pnl():
    # A non-USD line whose QUOTE FX is stale must exclude USD/GBP value & P&L,
    # not just flag it — local figures remain.
    snap = _snapshot(currency="AUD", price=3.0, fx=0.66)
    snap["fx_staleness_days"] = 40.0  # > max 5
    line = _value_lot(
        _lot(buy_currency="AUD", cost_currency="AUD", cost_basis_total=200.0),
        ticker_info=_INFO,
        snapshot=snap,
        max_fx_staleness_days=5,
        fx_histories={"GBP": _fx("GBP", 1.27)},
    )
    assert "STALE_FX" in line.status
    assert line.value_usd is None
    assert line.cost_usd_at_current_fx is None     # same-ccy cost used the stale quote FX
    assert line.pnl_usd_at_current_fx is None
    assert line.value_gbp is None
    assert line.value_local is not None            # local value survives


def test_stale_cost_fx_degrades_line():
    # GBP cost history's latest bar is ~40 days before the snapshot (max 5) -> stale.
    stale_gbp = {
        "GBP": pd.DataFrame(
            [{"base_currency": "GBP", "date": date(2026, 4, 26), "fx_rate_to_usd": 1.27, "source_symbol": "GBPUSD=X"}]
        )
    }
    lot = _lot(buy_currency="AUD", cost_currency="GBP", cost_basis_total=136.0)
    line = _value_lot(
        lot,
        ticker_info=_INFO,
        snapshot=_snapshot(currency="AUD", price=0.30, fx=0.66),
        max_fx_staleness_days=5,
        fx_histories=stale_gbp,
    )
    assert line.cost_usd_at_current_fx is None        # stale cost FX excluded, not used
    assert "MISSING_COST_FX" in line.status
    assert line.value_usd is not None                 # value leg stays valid


def test_missing_gbp_presentation_fx_does_not_degrade_usd():
    lot = _lot(buy_currency="AUD", cost_currency="AUD", cost_basis_total=200.0)
    line = _value_lot(
        lot,
        ticker_info=_INFO,
        snapshot=_snapshot(currency="AUD", price=3.0, fx=0.66),
        max_fx_staleness_days=5,
        fx_histories={},  # no GBP history
    )
    assert line.value_gbp is None
    assert "gbp_presentation_fx" in line.fx_issues
    assert line.status == "OK"                       # presentation-only gap must not degrade
    assert line.cost_usd_at_current_fx == pytest.approx(132.0)
    assert line.pnl_local == pytest.approx(100.0)
