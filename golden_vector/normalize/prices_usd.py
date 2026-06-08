"""Convert raw equity histories into USD-normalized daily prices."""

from __future__ import annotations

import pandas as pd

from golden_vector.normalize.calendar import merge_fx_asof


USD_EQUITY_COLUMNS = [
    "ticker",
    "date",
    "currency",
    "exchange",
    "open_local",
    "high_local",
    "low_local",
    "close_local",
    "adj_close_local",
    "return_basis_local",
    "fx_rate_to_usd",
    "fx_source_date",
    "fx_source_symbol",
    "fx_staleness_days",
    "open_usd",
    "high_usd",
    "low_usd",
    "close_usd",
    "adj_close_usd",
    "return_basis_usd",
    "volume",
    "source",
    "source_symbol",
    "feed_currency",
    "price_scale_factor",
    "minor_unit_adjusted",
    "fetched_at_utc",
    "normalization_status",
]


def normalize_equity_histories_to_usd(
    equity_histories: dict[str, pd.DataFrame],
    fx_histories: dict[str, pd.DataFrame],
    *,
    max_fx_staleness_days: int = 5,
) -> dict[str, pd.DataFrame]:
    normalized: dict[str, pd.DataFrame] = {}
    for ticker, frame in equity_histories.items():
        if frame.empty:
            normalized[ticker] = normalize_equity_history_to_usd(
                frame=frame,
                fx_history=pd.DataFrame(),
                max_fx_staleness_days=max_fx_staleness_days,
            )
            continue

        normalized[ticker] = normalize_equity_history_to_usd(
            frame=frame,
            fx_history=fx_histories.get(_currency_from_equity_frame(frame), pd.DataFrame()),
            max_fx_staleness_days=max_fx_staleness_days,
        )
    return normalized


def normalize_equity_history_to_usd(
    frame: pd.DataFrame,
    fx_history: pd.DataFrame,
    *,
    max_fx_staleness_days: int = 5,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=USD_EQUITY_COLUMNS)

    normalized = frame.copy()
    _ensure_price_unit_columns(normalized)
    normalized["date"] = pd.to_datetime(normalized["date"])
    normalized["return_basis_local"] = normalized["adj_close_local"].where(
        normalized["adj_close_local"].notna(),
        normalized["close_local"],
    )

    currency = _currency_from_equity_frame(frame)
    if currency == "USD":
        normalized["fx_rate_to_usd"] = 1.0
        normalized["fx_source_date"] = normalized["date"]
        normalized["fx_source_symbol"] = "USD"
    else:
        normalized = merge_fx_asof(
            normalized,
            date_column="date",
            fx_history=fx_history,
        )

    normalized["open_usd"] = _multiply_if_present(
        normalized["open_local"],
        normalized["fx_rate_to_usd"],
    )
    normalized["high_usd"] = _multiply_if_present(
        normalized["high_local"],
        normalized["fx_rate_to_usd"],
    )
    normalized["low_usd"] = _multiply_if_present(
        normalized["low_local"],
        normalized["fx_rate_to_usd"],
    )
    normalized["close_usd"] = _multiply_if_present(
        normalized["close_local"],
        normalized["fx_rate_to_usd"],
    )
    normalized["adj_close_usd"] = _multiply_if_present(
        normalized["adj_close_local"],
        normalized["fx_rate_to_usd"],
    )
    normalized["return_basis_usd"] = _multiply_if_present(
        normalized["return_basis_local"],
        normalized["fx_rate_to_usd"],
    )
    normalized["fx_staleness_days"] = _compute_fx_staleness_days(
        normalized["date"],
        normalized["fx_source_date"],
    )
    normalized["normalization_status"] = _equity_statuses(
        normalized,
        max_fx_staleness_days=max_fx_staleness_days,
    )

    normalized["date"] = normalized["date"].dt.date
    normalized["fx_source_date"] = pd.to_datetime(normalized["fx_source_date"]).dt.date
    return normalized[USD_EQUITY_COLUMNS].reset_index(drop=True)


def _currency_from_equity_frame(frame: pd.DataFrame) -> str:
    if frame.empty:
        raise ValueError("Equity history frame is empty.")
    if "currency" not in frame.columns:
        raise ValueError("Equity history frame is missing the currency column.")

    currencies = sorted(
        {
            str(value).upper()
            for value in frame["currency"].dropna().unique()
        }
    )
    if len(currencies) != 1:
        raise ValueError(
            "Equity history frame must contain exactly one currency value."
        )
    return currencies[0]


def _ensure_price_unit_columns(frame: pd.DataFrame) -> None:
    if "feed_currency" not in frame.columns:
        frame["feed_currency"] = None
    if "price_scale_factor" not in frame.columns:
        frame["price_scale_factor"] = 1.0
    if "minor_unit_adjusted" not in frame.columns:
        frame["minor_unit_adjusted"] = False


def _equity_statuses(
    frame: pd.DataFrame,
    *,
    max_fx_staleness_days: int,
) -> pd.Series:
    statuses = pd.Series("OK", index=frame.index, dtype="object")
    missing_fx_mask = frame["fx_rate_to_usd"].isna()
    missing_return_basis_mask = frame["return_basis_local"].apply(_missing_or_non_positive)
    stale_fx_mask = (
        frame["fx_staleness_days"].notna()
        & (pd.to_numeric(frame["fx_staleness_days"], errors="coerce") > float(max_fx_staleness_days))
        & (~missing_fx_mask)
    )

    statuses.loc[missing_fx_mask] = "MISSING_FX"
    statuses.loc[~missing_fx_mask & missing_return_basis_mask] = "MISSING_RETURN_BASIS"
    statuses.loc[
        ~missing_fx_mask
        & ~missing_return_basis_mask
        & stale_fx_mask
    ] = "STALE_FX"
    return statuses


def _multiply_if_present(left: pd.Series, right: pd.Series) -> pd.Series:
    return pd.to_numeric(left, errors="coerce") * pd.to_numeric(right, errors="coerce")


def _compute_fx_staleness_days(
    observation_dates: pd.Series,
    fx_source_dates: pd.Series,
) -> pd.Series:
    observation_ts = pd.to_datetime(observation_dates, errors="coerce")
    fx_source_ts = pd.to_datetime(fx_source_dates, errors="coerce")
    return (observation_ts - fx_source_ts).dt.days.astype("Int64")


def _missing_or_non_positive(value: object) -> bool:
    if value is None or pd.isna(value):
        return True
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return True
