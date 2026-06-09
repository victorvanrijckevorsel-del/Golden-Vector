"""Shared string normalization helpers."""

from __future__ import annotations


import pandas as pd


def clean_string(value: object) -> str | None:
    """Return a stripped string, treating blank and NaN-like values as missing."""

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def normalize_ticker(value: object) -> str | None:
    """Return an uppercase ticker symbol, or None for missing/blank values."""

    text = clean_string(value)
    return text.upper() if text else None


def normalize_ticker_series(series: pd.Series) -> pd.Series:
    """Normalize a pandas Series of ticker symbols to uppercase nullable strings."""

    return series.map(normalize_ticker)


def unique_strings(frame: pd.DataFrame, column: str) -> list[str]:
    """Return sorted unique non-empty, non-NaN strings from a DataFrame column."""

    if frame.empty or column not in frame.columns:
        return []
    values: set[str] = set()
    for value in frame[column].dropna().unique():
        normalized = clean_string(value)
        if normalized:
            values.add(normalized)
    return sorted(values)
