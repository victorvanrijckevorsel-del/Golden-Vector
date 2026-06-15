"""Calendar and FX-alignment helpers for normalization."""

from __future__ import annotations

import math

import pandas as pd


FX_LOOKUP_COLUMNS = ["fx_source_date", "fx_rate_to_usd", "fx_source_symbol"]
FX_RAW_REQUIRED_COLUMNS = ["base_currency", "date", "fx_rate_to_usd", "source_symbol"]


def split_fx_histories_by_base_currency(raw_fx: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a standardized raw-FX frame into one history per base currency.

    Each value retains the ``date`` / ``fx_rate_to_usd`` / ``source_symbol``
    columns that ``build_fx_lookup`` / ``merge_fx_asof`` expect, so a caller can
    do ``merge_fx_asof(frame, date_column=..., fx_history=histories[ccy])``.

    USD has no row here by construction (it is the quote side of every ``*USD``
    pair) — callers treat a missing currency as rate 1.0 for USD and must
    fail/degrade for any other missing currency rather than assume 1.0.
    """

    if raw_fx is None or raw_fx.empty:
        return {}
    missing = [column for column in FX_RAW_REQUIRED_COLUMNS if column not in raw_fx.columns]
    if missing:
        raise ValueError("raw FX frame is missing required columns: " + ", ".join(missing))
    # Normalize the currency code BEFORE grouping so harmless casing differences
    # (e.g. "gbp" vs "GBP") collapse into one key instead of grouping apart and
    # then overwriting each other under the upper-cased key.
    working = raw_fx.copy()
    working["_base_currency_key"] = working["base_currency"].astype("string").str.strip().str.upper()
    histories: dict[str, pd.DataFrame] = {}
    for key, group in working.groupby("_base_currency_key"):
        normalized = str(key).strip()
        if not normalized or normalized.lower() == "nan":
            continue
        histories[normalized] = group.drop(columns=["_base_currency_key"]).reset_index(drop=True)
    return histories


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


def fx_rate_to_usd_asof(
    fx_history: pd.DataFrame | None,
    as_of: object,
    *,
    max_staleness_days: float | None = None,
) -> float | None:
    """Resolve one currency's ``->USD`` rate as of a date (backward, like
    ``merge_fx_asof``): the latest row on or before ``as_of``.

    Returns None when the history is empty, unparseable, has no row on/before the
    date, the rate is non-positive/non-finite, OR (when ``max_staleness_days`` is
    given) the chosen row is older than that bound — so a stale-but-present rate
    degrades instead of silently valuing the cost leg. USD has no FX history by
    construction, so the caller must treat USD as rate 1.0 before calling this.
    """

    if fx_history is None or fx_history.empty:
        return None
    lookup = build_fx_lookup(fx_history)
    if lookup.empty:
        return None
    target = pd.to_datetime(as_of, errors="coerce")
    if pd.isna(target):
        return None
    eligible = lookup[lookup["fx_source_date"] <= target]
    if eligible.empty:
        return None
    chosen = eligible.sort_values("fx_source_date").iloc[-1]
    if max_staleness_days is not None:
        age_days = (target - chosen["fx_source_date"]).days
        if age_days > max_staleness_days:
            return None
    try:
        rate = float(chosen["fx_rate_to_usd"])
    except (TypeError, ValueError):
        return None
    return rate if math.isfinite(rate) and rate > 0 else None


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
