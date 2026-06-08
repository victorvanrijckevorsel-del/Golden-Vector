"""Shared small DataFrame lookup helpers."""

from __future__ import annotations

import pandas as pd


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
