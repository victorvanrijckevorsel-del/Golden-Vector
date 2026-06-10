"""Resolve official-vs-our-view fundamental values."""

from __future__ import annotations

import pandas as pd

from golden_vector.fundamentals.artifacts import validate_fetched_fundamentals_frame
from golden_vector.screening.manual_store import (
    FINANCIAL_DUAL_SOURCE_FIELDS,
    OPERATIONAL_SINGLE_SOURCE_FIELDS,
)

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
            official_value = _official_value(official_row)
            official_status = _official_status(official_row)
            manual_value = _manual_value(company_row, field_name)
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
                    "official_source": "official",
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


def _official_status(row: object | None) -> str:
    if row is None:
        return "MISSING"
    value = str(getattr(row, "value_status", "MISSING") or "MISSING").upper().strip()
    return value or "MISSING"
