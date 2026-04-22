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
    "open_usd",
    "high_usd",
    "low_usd",
    "close_usd",
    "adj_close_usd",
    "return_basis_usd",
    "volume",
    "source",
    "source_symbol",
    "fetched_at_utc",
    "normalization_status",
]


def normalize_equity_histories_to_usd(
    equity_histories: dict[str, pd.DataFrame],
    fx_histories: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    normalized: dict[str, pd.DataFrame] = {}
    for ticker, frame in equity_histories.items():
        if frame.empty:
            normalized[ticker] = normalize_equity_history_to_usd(
                frame=frame,
                fx_history=pd.DataFrame(),
            )
            continue

        normalized[ticker] = normalize_equity_history_to_usd(
            frame=frame,
            fx_history=fx_histories.get(_currency_from_equity_frame(frame), pd.DataFrame()),
        )
    return normalized


def normalize_equity_history_to_usd(
    frame: pd.DataFrame,
    fx_history: pd.DataFrame,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=USD_EQUITY_COLUMNS)

    normalized = frame.copy()
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
    normalized["normalization_status"] = normalized.apply(_equity_status, axis=1)

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


def _equity_status(row: pd.Series) -> str:
    if pd.isna(row.get("fx_rate_to_usd")):
        return "MISSING_FX"
    if _missing_or_non_positive(row.get("return_basis_local")):
        return "MISSING_RETURN_BASIS"
    return "OK"


def _multiply_if_present(left: pd.Series, right: pd.Series) -> pd.Series:
    return pd.to_numeric(left, errors="coerce") * pd.to_numeric(right, errors="coerce")


def _missing_or_non_positive(value: object) -> bool:
    if value is None or pd.isna(value):
        return True
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return True
