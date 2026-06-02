"""Small shared helpers for hedge-readiness modules."""

from __future__ import annotations

from typing import Any

import pandas as pd


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


def _row_value(row: pd.Series | dict[str, Any] | None, column: str) -> object:
    if row is None:
        return None
    if isinstance(row, pd.Series):
        return row[column] if column in row.index else None
    return row.get(column)


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
