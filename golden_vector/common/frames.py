"""Shared small DataFrame lookup helpers."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.ticker_page import FINANCE_SOURCES


def select_finance_source_rows(
    frame: pd.DataFrame,
    *,
    finance_source: str,
    label: str,
) -> pd.DataFrame:
    """Return only rows explicitly labelled for one finance source.

    This is the shared read-boundary guard for artifacts whose row identity is
    ``(ticker, finance_source)``. A non-empty legacy/unlabelled frame fails loud:
    letting it pass would make a later ticker-only lookup choose a source by row
    order. An empty frame remains an honest empty input and needs no schema.
    """

    resolved_source = str(finance_source or "").strip().lower()
    if resolved_source not in FINANCE_SOURCES:
        raise ValueError(
            f"{label} requires a canonical finance source in {FINANCE_SOURCES}; "
            f"got {finance_source!r}."
        )
    if frame.empty:
        return frame.copy()
    if "finance_source" not in frame.columns:
        raise ValueError(
            f"{label} has rows but no 'finance_source' column; refusing to infer a source."
        )
    source_values = frame["finance_source"].astype("string").str.strip().str.lower()
    invalid_values = source_values.isna() | source_values.eq("") | ~source_values.isin(
        FINANCE_SOURCES
    )
    if invalid_values.any():
        invalid_count = int(invalid_values.sum())
        raise ValueError(
            f"{label} has {invalid_count} row(s) with null, blank, or non-canonical "
            f"'finance_source' values; expected one of {FINANCE_SOURCES}."
        )
    return frame.loc[source_values.eq(resolved_source)].copy()


def latest_records_by_key(
    frame: pd.DataFrame,
    key_column: str,
    *,
    sort_column: str | None = None,
    uppercase_keys: bool = True,
) -> dict[str, dict[str, object]]:
    """Return the last record for each key, optionally ordered by one sort column."""

    if frame.empty or key_column not in frame.columns:
        return {}
    working = frame.copy()
    lookup_key = "__gv_lookup_key"
    working[lookup_key] = working[key_column].map(_normalize_key if uppercase_keys else _clean_key)
    if sort_column and sort_column in working.columns:
        working[sort_column] = pd.to_datetime(working[sort_column], errors="coerce")
        working = working.sort_values([lookup_key, sort_column])
    records = {}
    for row in working.groupby(lookup_key, dropna=False).tail(1).to_dict(orient="records"):
        key = str(row.pop(lookup_key, "") or "").strip()
        if not key:
            continue
        records[key] = row
    return records


def _normalize_key(value: object) -> str:
    return _clean_key(value).upper()


def _clean_key(value: object) -> str:
    return str(value or "").strip()
