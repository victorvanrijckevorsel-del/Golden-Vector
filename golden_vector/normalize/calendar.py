"""Calendar and FX-alignment helpers for normalization."""

from __future__ import annotations

import pandas as pd


FX_LOOKUP_COLUMNS = ["fx_source_date", "fx_rate_to_usd", "fx_source_symbol"]


def build_fx_lookup(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FX_LOOKUP_COLUMNS)

    prepared = frame.copy()
    prepared["fx_source_date"] = pd.to_datetime(prepared["date"])
    prepared = prepared.sort_values("fx_source_date")
    prepared = prepared.rename(columns={"source_symbol": "fx_source_symbol"})

    lookup = prepared[["fx_source_date", "fx_rate_to_usd", "fx_source_symbol"]]
    lookup = lookup.dropna(subset=["fx_rate_to_usd"])
    lookup = lookup.drop_duplicates(subset=["fx_source_date"], keep="last")
    return lookup.reset_index(drop=True)


def merge_fx_asof(
    frame: pd.DataFrame,
    *,
    date_column: str,
    fx_history: pd.DataFrame,
) -> pd.DataFrame:
    aligned = frame.copy()
    aligned[date_column] = pd.to_datetime(aligned[date_column])

    fx_lookup = build_fx_lookup(fx_history)
    if fx_lookup.empty:
        aligned["fx_source_date"] = pd.NaT
        aligned["fx_rate_to_usd"] = pd.NA
        aligned["fx_source_symbol"] = pd.NA
        return aligned.sort_values(date_column).reset_index(drop=True)

    merged = pd.merge_asof(
        aligned.sort_values(date_column),
        fx_lookup.sort_values("fx_source_date"),
        left_on=date_column,
        right_on="fx_source_date",
        direction="backward",
    )
    return merged.reset_index(drop=True)
