from datetime import datetime, timezone

import pandas as pd
import pytest

from golden_vector.normalize.market_snapshot import normalize_market_snapshots_to_usd


def _snapshot_frame(*, ticker: str, currency: str, date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "snapshot_date": date,
                "share_price_local": 10.0,
                "currency": currency,
                "fx_rate_to_usd": None,
                "share_price_usd": None,
                "market_cap_usd": None,
                "shares_outstanding": 100.0,
                "source": "yfinance",
                "source_run_id": "run-123",
            }
        ]
    )


def _fx_frame(*, currency: str, date: str, rate: float) -> pd.DataFrame:
    fetched_at = datetime(2026, 1, 4, tzinfo=timezone.utc)
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
                "fetched_at_utc": fetched_at,
            }
        ]
    )


def test_normalize_market_snapshots_uses_unity_fx_for_usd():
    snapshots = _snapshot_frame(ticker="NEM", currency="USD", date="2026-01-03")

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories={})

    assert normalized.loc[0, "fx_rate_to_usd"] == 1.0
    assert normalized.loc[0, "share_price_usd"] == 10.0
    assert normalized.loc[0, "market_cap_usd"] == 1000.0
    assert normalized.loc[0, "normalization_status"] == "OK"


def test_normalize_market_snapshots_converts_non_usd_and_derives_market_cap():
    snapshots = _snapshot_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    fx_histories = {"CAD": _fx_frame(currency="CAD", date="2026-01-03", rate=0.74)}

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories=fx_histories)

    assert normalized.loc[0, "fx_rate_to_usd"] == 0.74
    assert normalized.loc[0, "share_price_usd"] == 7.4
    assert normalized.loc[0, "market_cap_usd"] == 740.0
    assert normalized.loc[0, "fx_staleness_days"] == 0
    assert normalized.loc[0, "normalization_status"] == "OK"


def test_normalize_market_snapshots_flags_missing_fx():
    snapshots = _snapshot_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    fx_histories = {"CAD": _fx_frame(currency="CAD", date="2026-01-04", rate=0.74)}

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories=fx_histories)

    assert pd.isna(normalized.loc[0, "fx_rate_to_usd"])
    assert pd.isna(normalized.loc[0, "share_price_usd"])
    assert normalized.loc[0, "normalization_status"] == "MISSING_FX"


def test_normalize_market_snapshots_flags_stale_fx_when_threshold_is_exceeded():
    snapshots = _snapshot_frame(ticker="DPM.TO", currency="CAD", date="2026-01-10")
    fx_histories = {"CAD": _fx_frame(currency="CAD", date="2026-01-03", rate=0.74)}

    normalized = normalize_market_snapshots_to_usd(
        snapshots,
        fx_histories=fx_histories,
        max_fx_staleness_days=5,
    )

    assert normalized.loc[0, "fx_staleness_days"] == 7
    assert normalized.loc[0, "normalization_status"] == "STALE_FX"


def test_normalize_market_snapshots_flags_invalid_share_price():
    snapshots = _snapshot_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    snapshots.loc[0, "share_price_local"] = 0.0
    fx_histories = {"CAD": _fx_frame(currency="CAD", date="2026-01-03", rate=0.74)}

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories=fx_histories)

    assert normalized.loc[0, "normalization_status"] == "INVALID_SHARE_PRICE"


def test_normalize_market_snapshots_ignores_prefilled_usd_values_and_recomputes():
    snapshots = _snapshot_frame(ticker="DPM.TO", currency="CAD", date="2026-01-03")
    snapshots.loc[0, "share_price_usd"] = 999.0
    snapshots.loc[0, "market_cap_usd"] = 999999.0
    fx_histories = {"CAD": _fx_frame(currency="CAD", date="2026-01-03", rate=0.74)}

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories=fx_histories)

    assert normalized.loc[0, "share_price_usd"] == 7.4
    assert normalized.loc[0, "market_cap_usd"] == 740.0



@pytest.mark.parametrize(
    "bad_rate",
    [0.0, -2.0, float("nan"), float("inf"), float("-inf")],
    ids=["zero", "negative", "nan", "pos_inf", "neg_inf"],
)
def test_invalid_fx_rate_never_yields_ok_snapshot_row(bad_rate):
    """C7 snapshot side: invalid rates must never mark a normalized row OK."""
    snapshots = _snapshot_frame(ticker="AAR.AX", currency="AUD", date="2026-01-03")
    fx = _fx_frame(currency="AUD", date="2026-01-03", rate=bad_rate)

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories={"AUD": fx})

    assert normalized.loc[0, "normalization_status"] == "MISSING_FX"
    assert pd.isna(normalized.loc[0, "share_price_usd"])
    assert pd.isna(normalized.loc[0, "market_cap_usd"])


def test_snapshot_stale_but_valid_rate_is_stale_fx():
    snapshots = _snapshot_frame(ticker="AAR.AX", currency="AUD", date="2026-01-20")
    fx = _fx_frame(currency="AUD", date="2026-01-03", rate=0.65)

    normalized = normalize_market_snapshots_to_usd(
        snapshots, fx_histories={"AUD": fx}, max_fx_staleness_days=5
    )

    assert normalized.loc[0, "normalization_status"] == "STALE_FX"


def test_snapshot_valid_gbp_control_normalizes_ok():
    snapshots = _snapshot_frame(ticker="THX.L", currency="GBP", date="2026-01-03")
    fx = _fx_frame(currency="GBP", date="2026-01-03", rate=1.27)

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories={"GBP": fx})

    assert normalized.loc[0, "normalization_status"] == "OK"
    assert normalized.loc[0, "share_price_usd"] == pytest.approx(12.7)


def test_snapshot_non_finite_shares_outstanding_is_not_ok():
    """C7: infinite shares would fabricate an infinite market cap."""
    snapshots = _snapshot_frame(ticker="AAR.AX", currency="AUD", date="2026-01-03")
    snapshots.loc[0, "shares_outstanding"] = float("inf")
    fx = _fx_frame(currency="AUD", date="2026-01-03", rate=0.65)

    normalized = normalize_market_snapshots_to_usd(snapshots, fx_histories={"AUD": fx})

    assert normalized.loc[0, "normalization_status"] == "MISSING_SHARES_OUTSTANDING"
