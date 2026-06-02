"""Small shared helpers for hedge-readiness modules."""

from __future__ import annotations

from typing import Any

import pandas as pd

OPTIONABLE_TIERS = {"directly_hedgeable", "thin"}


def as_float(value: object) -> float | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def row_float(row: pd.Series | dict[str, Any] | None, column: str) -> float | None:
    value = _row_value(row, column)
    if value is None:
        return None
    return as_float(value)


def row_string(row: pd.Series | dict[str, Any] | None, column: str) -> str | None:
    value = _row_value(row, column)
    if value is None or pd.isna(value):
        return None
    return str(value)


def rows_by_ticker_dict(
    frame: pd.DataFrame,
    *,
    strip: bool = False,
    require_string: bool = False,
) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    frame = _sorted_by_as_of_date(frame)
    result: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        ticker = _normalized_ticker(
            row.get("ticker"),
            strip=strip,
            require_string=require_string,
        )
        if ticker is not None:
            result[ticker] = row.to_dict()
    return result


def rows_by_ticker_series(
    frame: pd.DataFrame,
    *,
    strip: bool = False,
    require_string: bool = False,
) -> dict[str, pd.Series]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    frame = _sorted_by_as_of_date(frame)
    result: dict[str, pd.Series] = {}
    for _, row in frame.iterrows():
        ticker = _normalized_ticker(
            row.get("ticker"),
            strip=strip,
            require_string=require_string,
        )
        if ticker is not None:
            result[ticker] = row
    return result


def latest_row_dict(
    frame: pd.DataFrame,
    *,
    fallback_ticker: str | None = None,
) -> dict[str, Any]:
    if frame.empty:
        return {"ticker": fallback_ticker} if fallback_ticker is not None else {}
    sorted_frame = _sorted_by_as_of_date(frame)
    row = sorted_frame.iloc[-1].to_dict()
    if fallback_ticker is not None:
        row.setdefault("ticker", fallback_ticker)
    return row


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def optionability_tier(value: object) -> str:
    """Normalize missing/blank optionability values to the non-optionable tier."""

    if value is None:
        return "none"
    try:
        if pd.isna(value):
            return "none"
    except (TypeError, ValueError):
        pass
    normalized = str(value).strip().lower()
    if normalized in {"", "none", "nan", "null", "<na>"}:
        return "none"
    return normalized


def is_optionable_tier(value: object) -> bool:
    return optionability_tier(value) in OPTIONABLE_TIERS


def _row_value(row: pd.Series | dict[str, Any] | None, column: str) -> object:
    if row is None:
        return None
    if isinstance(row, pd.Series):
        return row[column] if column in row.index else None
    return row.get(column)


def _sorted_by_as_of_date(frame: pd.DataFrame) -> pd.DataFrame:
    if "as_of_date" not in frame.columns:
        return frame
    sorted_frame = frame.copy()
    sorted_frame["_as_of_date_sort"] = pd.to_datetime(
        sorted_frame["as_of_date"],
        errors="coerce",
    )
    return sorted_frame.sort_values(
        "_as_of_date_sort",
        kind="stable",
        na_position="first",
    ).drop(columns=["_as_of_date_sort"])


def _normalized_ticker(
    value: object,
    *,
    strip: bool,
    require_string: bool,
) -> str | None:
    if require_string and not isinstance(value, str):
        return None
    if pd.isna(value):
        return None
    ticker = str(value)
    if strip:
        ticker = ticker.strip()
    if not ticker:
        return None
    return ticker.upper()
