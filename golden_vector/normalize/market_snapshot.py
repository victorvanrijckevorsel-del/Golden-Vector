"""Normalize Tool B market snapshots into USD terms."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from golden_vector.normalize.calendar import merge_fx_asof


NORMALIZED_MARKET_SNAPSHOT_COLUMNS = [
    "ticker",
    "snapshot_date",
    "currency",
    "share_price_local",
    "fx_rate_to_usd",
    "fx_source_date",
    "fx_source_symbol",
    "fx_staleness_days",
    "share_price_usd",
    "market_cap_usd",
    "shares_outstanding",
    "source",
    "source_run_id",
    "feed_currency",
    "price_scale_factor",
    "minor_unit_adjusted",
    "normalization_status",
]


def normalize_market_snapshots_to_usd(
    market_snapshots: pd.DataFrame,
    fx_histories: dict[str, pd.DataFrame],
    *,
    max_fx_staleness_days: int = 5,
) -> pd.DataFrame:
    if market_snapshots.empty:
        return pd.DataFrame(columns=NORMALIZED_MARKET_SNAPSHOT_COLUMNS)

    normalized_groups: list[pd.DataFrame] = []
    for currency, group in market_snapshots.groupby("currency", dropna=False):
        # Raw snapshot rows may already carry partially populated USD fields.
        # Normalized outputs are recalculated here from one canonical FX path.
        working = group.drop(
            columns=[
                column
                for column in (
                    "fx_rate_to_usd",
                    "fx_source_date",
                    "fx_source_symbol",
                    "share_price_usd",
                    "market_cap_usd",
                    "normalization_status",
                )
                if column in group.columns
            ]
        ).copy()
        currency_code = str(currency).upper()
        if currency_code == "USD":
            normalized = working
            normalized["snapshot_date"] = pd.to_datetime(normalized["snapshot_date"])
            normalized["fx_rate_to_usd"] = 1.0
            normalized["fx_source_date"] = normalized["snapshot_date"]
            normalized["fx_source_symbol"] = "USD"
        else:
            normalized = merge_fx_asof(
                working,
                date_column="snapshot_date",
                fx_history=fx_histories.get(currency_code, pd.DataFrame()),
            )

        normalized["share_price_usd"] = _multiply_if_present(
            normalized["share_price_local"],
            normalized["fx_rate_to_usd"],
        )
        normalized["market_cap_usd"] = _multiply_if_present(
            normalized["share_price_usd"],
            normalized["shares_outstanding"],
        )
        normalized["fx_staleness_days"] = _compute_fx_staleness_days(
            normalized["snapshot_date"],
            normalized["fx_source_date"],
        )
        normalized["normalization_status"] = _snapshot_statuses(
            normalized,
            max_fx_staleness_days=max_fx_staleness_days,
        )
        _ensure_price_unit_columns(normalized)
        normalized["snapshot_date"] = pd.to_datetime(normalized["snapshot_date"]).dt.date
        normalized["fx_source_date"] = pd.to_datetime(normalized["fx_source_date"]).dt.date
        normalized_groups.append(normalized[NORMALIZED_MARKET_SNAPSHOT_COLUMNS])

    return (
        pd.concat(normalized_groups, ignore_index=True)
        .sort_values(["ticker", "snapshot_date"])
        .reset_index(drop=True)
    )


def _snapshot_statuses(
    frame: pd.DataFrame,
    *,
    max_fx_staleness_days: int,
) -> pd.Series:
    statuses = pd.Series("OK", index=frame.index, dtype="object")
    missing_fx_mask = frame["fx_rate_to_usd"].isna()
    # C7: a present-but-invalid rate (zero/negative/non-finite) must never be OK.
    invalid_fx_mask = ~missing_fx_mask & frame["fx_rate_to_usd"].apply(_missing_or_non_positive)
    invalid_share_price_mask = frame["share_price_local"].apply(_missing_or_non_positive)
    shares_numeric = pd.to_numeric(frame["shares_outstanding"], errors="coerce")
    missing_shares_mask = (
        shares_numeric.isna() | ~np.isfinite(shares_numeric.fillna(0.0)) | (shares_numeric <= 0)
    )
    stale_fx_mask = (
        frame["fx_staleness_days"].notna()
        & (pd.to_numeric(frame["fx_staleness_days"], errors="coerce") > float(max_fx_staleness_days))
        & (~missing_fx_mask)
        & (~invalid_fx_mask)
    )

    statuses.loc[missing_fx_mask] = "MISSING_FX"
    statuses.loc[invalid_fx_mask] = "INVALID_FX"
    statuses.loc[
        ~missing_fx_mask
        & ~invalid_fx_mask
        & invalid_share_price_mask
    ] = "INVALID_SHARE_PRICE"
    statuses.loc[
        ~missing_fx_mask
        & ~invalid_fx_mask
        & ~invalid_share_price_mask
        & missing_shares_mask
    ] = "MISSING_SHARES_OUTSTANDING"
    statuses.loc[
        ~missing_fx_mask
        & ~invalid_fx_mask
        & ~invalid_share_price_mask
        & ~missing_shares_mask
        & stale_fx_mask
    ] = "STALE_FX"
    return statuses


def _ensure_price_unit_columns(frame: pd.DataFrame) -> None:
    if "feed_currency" not in frame.columns:
        frame["feed_currency"] = None
    if "price_scale_factor" not in frame.columns:
        frame["price_scale_factor"] = 1.0
    if "minor_unit_adjusted" not in frame.columns:
        frame["minor_unit_adjusted"] = False


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
        numeric = float(value)
    except (TypeError, ValueError):
        return True
    return not math.isfinite(numeric) or numeric <= 0
