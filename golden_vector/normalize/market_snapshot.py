"""Normalize Tool B market snapshots into USD terms."""

from __future__ import annotations

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
    "share_price_usd",
    "market_cap_usd",
    "shares_outstanding",
    "source",
    "source_run_id",
    "normalization_status",
]


def normalize_market_snapshots_to_usd(
    market_snapshots: pd.DataFrame,
    fx_histories: dict[str, pd.DataFrame],
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
        normalized["normalization_status"] = normalized.apply(
            _snapshot_status,
            axis=1,
        )
        normalized["snapshot_date"] = pd.to_datetime(normalized["snapshot_date"]).dt.date
        normalized["fx_source_date"] = pd.to_datetime(normalized["fx_source_date"]).dt.date
        normalized_groups.append(normalized[NORMALIZED_MARKET_SNAPSHOT_COLUMNS])

    return (
        pd.concat(normalized_groups, ignore_index=True)
        .sort_values(["ticker", "snapshot_date"])
        .reset_index(drop=True)
    )


def _snapshot_status(row: pd.Series) -> str:
    if pd.isna(row.get("fx_rate_to_usd")):
        return "MISSING_FX"
    if _missing_or_non_positive(row.get("share_price_local")):
        return "INVALID_SHARE_PRICE"
    if pd.isna(row.get("shares_outstanding")) or float(row["shares_outstanding"]) <= 0:
        return "MISSING_SHARES_OUTSTANDING"
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
