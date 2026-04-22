from datetime import datetime, timezone

import pandas as pd

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
