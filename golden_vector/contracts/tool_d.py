"""Authoritative schema and row-identity contract for Tool D artifacts.

Tool D schema v4 changes the persisted identity from ticker-only to the
composite ``(ticker, finance_source)`` key.  The model owns calculations; this
module owns the shape that producers persist and readers may trust.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from golden_vector.contracts.ticker_page import FINANCE_SOURCES, validate_frame_schema

TOOL_D_SCHEMA_VERSION = 4

TOOL_D_KEY_COLUMNS: tuple[str, ...] = ("ticker", "finance_source")

# Kept central during the v3 -> v4 migration so readers never invent a
# different explanation or silently borrow Our View data for Yahoo.
YAHOO_TOOL_D_UNAVAILABLE_REASON = "resilience is computed on Our View inputs"
YAHOO_TOOL_D_REBUILD_REQUIRED_REASON = (
    "Yahoo resilience data requires a Tool D schema v4 rebuild"
)

TOOL_D_OUTPUT_COLUMNS: list[str] = [
    "ticker",
    "tool_d_schema_version",
    "as_of_date",
    "source_run_id",
    "finance_source",
    "source_tool_b_run_id",
    "snapshot_refresh_run_id",
    "gold_price_used",
    "spot_gold_usd",
    "spot_gold_date",
    "gold_price_delta_vs_spot_pct",
    "market_cap_musd",
    "screening_verdict",
    "confidence",
    "aisc_margin_yield_at_g",
    "aisc_margin_yield_at_spot",
    "reserve_life_years",
    "cash_cost_usd_per_oz",
    "production_oz",
    "aisc_usd_per_oz",
    "sustaining_capex_musd",
    "interest_expense_musd",
    "net_debt_musd",
    "forward_ebitda_musd_at_g",
    "forward_ebitda_musd_at_spot",
    "margin_per_oz_at_g",
    "margin_per_oz_at_spot",
    "margin_per_oz_delta_vs_spot",
    "headroom_to_breakeven_pct_at_g",
    "headroom_to_breakeven_pct_at_spot",
    "headroom_delta_vs_spot",
    "breaks_even_at_gold_usd",
    "interest_cover_gold_usd",
    "debt_stress_gold_usd",
    "survival_distance_to_interest_cover_pct",
    "cost_curve_aisc_percentile",
    "fragility_ebitda_pct_per_10pct_gold",
    "leverage_stressed_at_g",
    "leverage_stressed_at_spot",
    "leverage_delta_vs_spot",
    "ev_ebitda_at_g",
    "ebitda_pct_change_vs_spot",
    "survival_order_ladder",
    "resilience_flip_flags",
    "resilience_data_status",
    "survival_distance_component",
    "cost_curve_resilience_component",
    "fragility_resilience_component",
    "balance_sheet_resilience_component",
    "tool_d_quality_score",
    "tool_d_quality_rank",
    "tool_d_tags",
    "tool_d_explanation",
    "missing_inputs",
]


def validate_tool_d_output_frame(
    frame: pd.DataFrame,
    *,
    expected_tickers: Iterable[str] | None = None,
    require_complete_sources: bool = True,
) -> list[str]:
    """Return all Tool D v4 contract violations without mutating ``frame``.

    A healthy generation has one explicit row for every active ticker and both
    canonical finance sources.  A source with incomplete inputs still occupies
    its key with a non-OK status and an explanation; it never disappears.
    ``expected_tickers`` lets the producer prove completeness against its active
    universe.  When omitted, completeness is checked across tickers present in
    the frame, which is still sufficient to detect a half-published source.
    """

    violations = validate_frame_schema(
        frame,
        columns=tuple(TOOL_D_OUTPUT_COLUMNS),
        key_columns=TOOL_D_KEY_COLUMNS,
    )

    if "tool_d_schema_version" in frame.columns:
        versions = pd.to_numeric(frame["tool_d_schema_version"], errors="coerce")
        invalid_versions = int(versions.ne(TOOL_D_SCHEMA_VERSION).sum())
        if invalid_versions:
            violations.append(
                "tool_d_schema_version must equal "
                f"{TOOL_D_SCHEMA_VERSION}: {invalid_versions} row(s) differ"
            )

    if "as_of_date" in frame.columns:
        null_dates = int(frame["as_of_date"].isna().sum())
        if null_dates:
            violations.append(f"null as_of_date values: {null_dates} row(s)")

    if "finance_source" in frame.columns:
        present_sources = {
            str(value) for value in frame["finance_source"].dropna().tolist()
        }
        invalid_sources = sorted(present_sources.difference(FINANCE_SOURCES))
        if invalid_sources:
            violations.append(
                "non-canonical finance_source values: " + ", ".join(invalid_sources)
            )

    if "ticker" in frame.columns:
        blank_tickers = int(frame["ticker"].fillna("").astype(str).str.strip().eq("").sum())
        if blank_tickers:
            violations.append(f"blank ticker values: {blank_tickers} row(s)")

    if "resilience_data_status" in frame.columns:
        statuses = frame["resilience_data_status"]
        null_statuses = int(statuses.isna().sum())
        if null_statuses:
            violations.append(
                f"null resilience_data_status values: {null_statuses} row(s)"
            )
        degraded = statuses.notna() & statuses.astype(str).ne("OK")
        if degraded.any():
            explanation = _nonblank(frame, "tool_d_explanation")
            missing_inputs = _nonblank(frame, "missing_inputs")
            missing_reason = degraded & ~explanation & ~missing_inputs
            count = int(missing_reason.sum())
            if count:
                violations.append(
                    "degraded rows without tool_d_explanation or missing_inputs: "
                    f"{count} row(s)"
                )

    if require_complete_sources and all(
        column in frame.columns for column in TOOL_D_KEY_COLUMNS
    ):
        actual_tickers = {
            str(value).strip().upper()
            for value in frame["ticker"].dropna().tolist()
            if str(value).strip()
        }
        required_tickers = (
            _canonical_tickers(expected_tickers)
            if expected_tickers is not None
            else actual_tickers
        )
        actual_keys = {
            (str(ticker).strip().upper(), str(source))
            for ticker, source in frame.loc[:, list(TOOL_D_KEY_COLUMNS)].itertuples(
                index=False, name=None
            )
            if pd.notna(ticker) and pd.notna(source) and str(ticker).strip()
        }
        required_keys = {
            (ticker, source)
            for ticker in required_tickers
            for source in FINANCE_SOURCES
        }
        missing_keys = sorted(required_keys.difference(actual_keys))
        if missing_keys:
            violations.append(
                "missing expected (ticker, finance_source) keys: "
                + ", ".join(f"({ticker}, {source})" for ticker, source in missing_keys)
            )
        if expected_tickers is not None:
            unexpected_tickers = sorted(actual_tickers.difference(required_tickers))
            if unexpected_tickers:
                violations.append(
                    "unexpected tickers: " + ", ".join(unexpected_tickers)
                )

    return violations


def _canonical_tickers(values: Iterable[str]) -> set[str]:
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _nonblank(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[column]
    return values.notna() & values.astype(str).str.strip().ne("")
