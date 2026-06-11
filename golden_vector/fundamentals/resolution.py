"""Resolve official-vs-our-view fundamental values."""

from __future__ import annotations

import pandas as pd

from golden_vector.fundamentals.artifacts import validate_fetched_fundamentals_frame
from golden_vector.screening.manual_store import (
    FINANCIAL_DUAL_SOURCE_FIELDS,
    OPERATIONAL_SINGLE_SOURCE_FIELDS,
)

MANUAL_ONLY_FINANCIAL_FIELDS = frozenset({"tax_rate"})
MONEY_DUAL_SOURCE_FIELDS = FINANCIAL_DUAL_SOURCE_FIELDS - MANUAL_ONLY_FINANCIAL_FIELDS

RESOLVED_FUNDAMENTALS_COLUMNS: tuple[str, ...] = (
    "ticker",
    "field_name",
    "official_value",
    "official_status",
    "official_source",
    "our_view_value",
    "our_view_status",
    "our_view_source",
)


def resolve_fundamental_layers(
    *,
    company_inputs: pd.DataFrame,
    official_fundamentals: pd.DataFrame,
    snapshot_feed_currencies: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Resolve Official and Our-view values without mutating the manual store."""

    company = _normalize_company_inputs(company_inputs)
    official = validate_fetched_fundamentals_frame(official_fundamentals)
    company_lookup = {
        str(row.ticker): row
        for row in company.itertuples(index=False)
    }
    official_lookup = {
        (str(row.ticker), str(row.field_name)): row
        for row in official.itertuples(index=False)
    }
    feed_currency_lookup = _feed_currency_lookup(snapshot_feed_currencies)
    tickers = sorted(set(company_lookup) | set(official["ticker"].dropna().astype(str)))
    rows: list[dict[str, object]] = []
    for ticker in tickers:
        company_row = company_lookup.get(ticker)
        for field_name in sorted(OPERATIONAL_SINGLE_SOURCE_FIELDS):
            value = _manual_value(company_row, field_name)
            status = "OK" if pd.notna(value) else "MISSING"
            rows.append(
                {
                    "ticker": ticker,
                    "field_name": field_name,
                    "official_value": value,
                    "official_status": status,
                    "official_source": "manual_single_source",
                    "our_view_value": value,
                    "our_view_status": status,
                    "our_view_source": "manual_single_source",
                }
            )
        for field_name in sorted(FINANCIAL_DUAL_SOURCE_FIELDS):
            official_row = official_lookup.get((ticker, field_name))
            manual_value = _manual_value(company_row, field_name)
            if field_name in MANUAL_ONLY_FINANCIAL_FIELDS:
                official_value = manual_value
                official_status = "OK" if pd.notna(manual_value) else "MISSING"
                official_source = "manual_single_source"
            else:
                official_value = _official_value(official_row)
                official_status = _official_status(
                    official_row,
                    field_name=field_name,
                    feed_currency=feed_currency_lookup.get(ticker),
                )
                official_source = "official"
            if pd.notna(manual_value):
                our_value = manual_value
                our_status = "OK"
                our_source = "manual"
            else:
                our_value = official_value
                our_status = official_status
                our_source = "official"
            rows.append(
                {
                    "ticker": ticker,
                    "field_name": field_name,
                    "official_value": official_value,
                    "official_status": official_status,
                    "official_source": official_source,
                    "our_view_value": our_value,
                    "our_view_status": our_status,
                    "our_view_source": our_source,
                }
            )
    return pd.DataFrame(rows, columns=RESOLVED_FUNDAMENTALS_COLUMNS)


def _normalize_company_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    company = frame.copy()
    if "ticker" not in company.columns:
        return pd.DataFrame(columns=["ticker"])
    company["ticker"] = company["ticker"].fillna("").astype(str).str.upper().str.strip()
    company = company[company["ticker"] != ""].copy()
    company = company.drop_duplicates(subset=["ticker"], keep="last")
    return company.reset_index(drop=True)


def _manual_value(row: object | None, field_name: str) -> object:
    if row is None:
        return pd.NA
    return getattr(row, field_name, pd.NA)


def _official_value(row: object | None) -> object:
    if row is None:
        return pd.NA
    return getattr(row, "value", pd.NA)


def _feed_currency_lookup(frame: pd.DataFrame | None) -> dict[str, str]:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return {}
    working = frame.copy()
    if "feed_currency" not in working.columns:
        return {}
    working["ticker"] = working["ticker"].fillna("").astype(str).str.upper().str.strip()
    working["feed_currency"] = working["feed_currency"].map(_clean_currency)
    working = working[(working["ticker"] != "") & (working["feed_currency"] != "")]
    if working.empty:
        return {}
    working = working.drop_duplicates(subset=["ticker"], keep="last")
    return dict(zip(working["ticker"], working["feed_currency"]))


def _official_status(
    row: object | None,
    *,
    field_name: str,
    feed_currency: str | None,
) -> str:
    if row is None:
        return "MISSING"
    raw_value = getattr(row, "value_status", "MISSING")
    if pd.isna(raw_value):
        return "MISSING"
    value = str(raw_value).upper().strip()
    if not value:
        return "MISSING"
    if value != "OK":
        return value
    if field_name in MONEY_DUAL_SOURCE_FIELDS and _has_currency_basis_mismatch(
        row,
        feed_currency=feed_currency,
    ):
        return "CURRENCY_BASIS_MISMATCH"
    return value


def _has_currency_basis_mismatch(row: object, *, feed_currency: str | None) -> bool:
    statement_currency = _clean_currency(getattr(row, "statement_currency", None))
    feed = _clean_currency(feed_currency)
    if not statement_currency or not feed:
        return False
    return statement_currency != feed


def _clean_currency(value: object | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).upper().strip()
