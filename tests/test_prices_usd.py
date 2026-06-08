from datetime import datetime, timezone

import pandas as pd
import pytest

from golden_vector.normalize.prices_usd import normalize_equity_history_to_usd


def _fetched_at() -> datetime:
    return datetime(2026, 1, 4, tzinfo=timezone.utc)


def _equity_frame(*, ticker: str, currency: str, date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "date": date,
                "open_local": 9.0,
                "high_local": 11.0,
                "low_local": 8.0,
                "close_local": 10.0,
                "adj_close_local": 9.5,
                "volume": 1000.0,
                "currency": currency,
                "exchange": "TEST",
                "source": "yfinance",
                "source_symbol": ticker,
                "fetched_at_utc": _fetched_at(),
            }
        ]
    )


def _fx_frame(*, currency: str, date: str, rate: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "base_currency": currency,
                "quote_currency": "USD",
                "date": date,
                "fx_pair": f"{currency}USD",
                "fx_rate_to_usd": rate,
                "source": "yfinance",
                "source_symbol": f"{currency}USD=X",
                "fetched_at_utc": _fetched_at(),
            }
        ]
    )


def test_normalize_equity_history_uses_unity_fx_for_usd_tickers():
    frame = _equity_frame(ticker="NEM", currency="USD", date="2026-01-03")

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=pd.DataFrame())

    assert normalized.loc[0, "fx_rate_to_usd"] == 1.0
    assert normalized.loc[0, "close_usd"] == 10.0
    assert normalized.loc[0, "return_basis_usd"] == 9.5
    assert normalized.loc[0, "normalization_status"] == "OK"


def test_normalize_equity_history_converts_non_usd_values():
    frame = _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    fx_history = _fx_frame(currency="CAD", date="2026-01-03", rate=0.74)

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=fx_history)

    assert normalized.loc[0, "fx_rate_to_usd"] == 0.74
    assert normalized.loc[0, "close_usd"] == 7.4
    assert normalized.loc[0, "adj_close_usd"] == 7.03
    assert normalized.loc[0, "fx_source_date"].isoformat() == "2026-01-03"
    assert normalized.loc[0, "normalization_status"] == "OK"


def test_normalize_equity_history_carries_price_unit_audit_fields():
    frame = _equity_frame(ticker="PAF.L", currency="GBP", date="2026-01-03")
    frame["feed_currency"] = "GBp"
    frame["price_scale_factor"] = 0.01
    frame["minor_unit_adjusted"] = True
    fx_history = _fx_frame(currency="GBP", date="2026-01-03", rate=1.25)

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=fx_history)

    assert normalized.loc[0, "feed_currency"] == "GBp"
    assert normalized.loc[0, "price_scale_factor"] == pytest.approx(0.01)
    assert bool(normalized.loc[0, "minor_unit_adjusted"]) is True


def test_normalize_equity_history_falls_back_to_close_when_adj_close_missing():
    frame = _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    frame.loc[0, "adj_close_local"] = None
    fx_history = _fx_frame(currency="CAD", date="2026-01-03", rate=0.74)

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=fx_history)

    assert normalized.loc[0, "return_basis_local"] == 10.0
    assert normalized.loc[0, "return_basis_usd"] == 7.4
    assert normalized.loc[0, "normalization_status"] == "OK"


def test_normalize_equity_history_forward_fills_fx_only():
    frame = _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    fx_history = _fx_frame(currency="CAD", date="2026-01-02", rate=0.75)

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=fx_history)

    assert normalized.loc[0, "fx_rate_to_usd"] == 0.75
    assert normalized.loc[0, "fx_source_date"].isoformat() == "2026-01-02"
    assert normalized.loc[0, "normalization_status"] == "OK"
    assert int(normalized.loc[0, "fx_staleness_days"]) == 1


def test_normalize_equity_history_flags_stale_fx_when_threshold_is_exceeded():
    frame = _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-10")
    fx_history = _fx_frame(currency="CAD", date="2026-01-03", rate=0.75)

    normalized = normalize_equity_history_to_usd(
        frame=frame,
        fx_history=fx_history,
        max_fx_staleness_days=5,
    )

    assert int(normalized.loc[0, "fx_staleness_days"]) == 7
    assert normalized.loc[0, "normalization_status"] == "STALE_FX"


def test_normalize_equity_history_flags_missing_fx():
    frame = _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    fx_history = _fx_frame(currency="CAD", date="2026-01-04", rate=0.75)

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=fx_history)

    assert pd.isna(normalized.loc[0, "fx_rate_to_usd"])
    assert pd.isna(normalized.loc[0, "close_usd"])
    assert normalized.loc[0, "normalization_status"] == "MISSING_FX"


def test_normalize_equity_history_sets_status_per_row_with_partial_fx_coverage():
    frame = pd.DataFrame(
        [
            _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-01").iloc[0].to_dict(),
            _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-02").iloc[0].to_dict(),
            _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03").iloc[0].to_dict(),
        ]
    )
    fx_history = _fx_frame(currency="CAD", date="2026-01-02", rate=0.75)

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=fx_history)

    assert normalized["normalization_status"].tolist() == [
        "MISSING_FX",
        "OK",
        "OK",
    ]
    assert pd.isna(normalized.loc[0, "fx_rate_to_usd"])
    assert normalized.loc[1, "fx_rate_to_usd"] == 0.75
    assert normalized.loc[2, "fx_source_date"].isoformat() == "2026-01-02"


def test_normalize_equity_history_flags_missing_return_basis():
    frame = _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    frame.loc[0, "close_local"] = None
    frame.loc[0, "adj_close_local"] = None
    fx_history = _fx_frame(currency="CAD", date="2026-01-03", rate=0.75)

    normalized = normalize_equity_history_to_usd(frame=frame, fx_history=fx_history)

    assert pd.isna(normalized.loc[0, "return_basis_usd"])
    assert normalized.loc[0, "normalization_status"] == "MISSING_RETURN_BASIS"


def test_normalize_equity_history_rejects_mixed_currency_frame():
    frame = pd.DataFrame(
        [
            _equity_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03").iloc[0].to_dict(),
            _equity_frame(ticker="DPM.TO", currency="USD", date="2026-01-04").iloc[0].to_dict(),
        ]
    )

    with pytest.raises(ValueError, match="exactly one currency"):
        normalize_equity_history_to_usd(frame=frame, fx_history=pd.DataFrame())
