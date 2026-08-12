"""Authoritative schema and row-identity contract for Tool D artifacts.

Tool D schema v4 changes the persisted identity from ticker-only to the
composite ``(ticker, finance_source)`` key.  The model owns calculations; this
module owns the shape that producers persist and readers may trust.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from golden_vector.common.frames import select_finance_source_rows
from golden_vector.contracts.ticker_page import (
    FINANCE_SOURCES,
    canonical_finance_source,
    validate_frame_schema,
)

TOOL_D_SCHEMA_VERSION = 4

TOOL_D_KEY_COLUMNS: tuple[str, ...] = ("ticker", "finance_source")

# A non-OK resilience row is an explicit evidence/status row, not a ranked
# observation.  Keeping this list beside the schema makes the fail-closed rule
# reusable at every producer boundary.
TOOL_D_RANKING_OUTPUT_COLUMNS: tuple[str, ...] = (
    "cost_curve_aisc_percentile",
    "survival_distance_component",
    "cost_curve_resilience_component",
    "fragility_resilience_component",
    "balance_sheet_resilience_component",
    "tool_d_quality_score",
    "tool_d_quality_rank",
)

TOOL_D_SOURCE_PAIR_CONTEXT_COLUMNS: tuple[str, ...] = (
    "as_of_date",
    "gold_price_used",
    "spot_gold_usd",
    "spot_gold_date",
)

# Kept central during the v3 -> v4 migration so readers never invent a
# different explanation or silently borrow Our View data for Yahoo.
YAHOO_TOOL_D_UNAVAILABLE_REASON = "resilience is computed on Our View inputs"
# W10: this string is shown VERBATIM on the ticker page during the real v3->v4
# window, so it is written for the reader — no schema version, no tool codename,
# and no invented promise about when the refresh happens. Still truthful: the
# data genuinely is absent until the next dual-source build is published.
YAHOO_TOOL_D_REBUILD_REQUIRED_REASON = (
    "Corporate Resilience for Yahoo Fundamentals is not available yet — the data "
    "needs one refresh in the new dual-source format"
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


# ---------------------------------------------------------------------------
# Read boundary: selecting ONE finance source out of a persisted Tool D frame.
#
# Lives beside the schema contract (not in the serve layer) because every
# reader must apply the same guards: the serve pages, the Candidate Finder,
# the Portfolio analytics and the Lab vintage recorder (W3).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDSourceSelection:
    """Exact-source Tool D rows plus an honest reason when none are usable."""

    frame: pd.DataFrame
    reason: str | None = None


def select_tool_d_source_rows(
    frame: pd.DataFrame,
    *,
    finance_source: str,
    label: str,
    ticker: str | None = None,
) -> ToolDSourceSelection:
    """Select one Tool D finance source, optionally narrowed to one ticker.

    A pre-v4 artifact already labels its rows ``our`` but cannot contain Yahoo
    rows. That migration state gets the contract-owned rebuild reason; every
    other missing key gets a source-specific absence reason. No caller may
    borrow the alternate source to make an empty selection look complete.
    """

    # Keep the same fail-loud request contract as the shared selector even
    # when schema metadata is malformed; invalid caller input is not a
    # data-degradation state. The empty probe validates without inspecting
    # stored rows before their schema generation is known.
    select_finance_source_rows(
        frame.iloc[0:0].copy(),
        finance_source=finance_source,
        label=label,
    )
    # Resolve aliases through the ONE shared table BEFORE any source-specific
    # branch below (W4): a request for the legacy `official` token must take the
    # Yahoo path, not fall through to Our View. The probe above already rejected
    # anything unrecognized, so this is never None here.
    normalized_source = canonical_finance_source(finance_source) or "our"
    schema_state = _tool_d_schema_state(frame)
    if schema_state == "malformed":
        return ToolDSourceSelection(
            frame=frame.iloc[0:0].copy(),
            reason=(
                "Corporate Resilience artifact has malformed Tool D schema-version "
                "metadata; selected-source data is unavailable."
            ),
        )

    # Legacy v3 is an explicitly Our-View-only compatibility state. Validate
    # every stored source before deciding whether Yahoo needs a rebuild so a
    # malformed v3 Yahoo row can never be served as if it were legitimate.
    selection_source = normalized_source
    if schema_state == "legacy_our":
        legacy_our = select_finance_source_rows(
            frame,
            finance_source="our",
            label=label,
        )
        if len(legacy_our.index) != len(frame.index):
            return ToolDSourceSelection(
                frame=frame.iloc[0:0].copy(),
                reason=(
                    "Corporate Resilience legacy Tool D artifact contains a non-Our-View "
                    "source; selected-source data is unavailable."
                ),
            )
        if normalized_source == "yahoo":
            return ToolDSourceSelection(
                frame=frame.iloc[0:0].copy(),
                reason=YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
            )
        selection_source = "our"

    selected = select_finance_source_rows(
        frame,
        finance_source=selection_source,
        label=label,
    )
    if "ticker" in selected.columns:
        selected_tickers = selected["ticker"].astype(str).str.strip().str.upper()
        duplicate_tickers = selected_tickers.loc[
            selected_tickers.ne("") & selected_tickers.duplicated(keep=False)
        ]
        if not duplicate_tickers.empty:
            sample = ", ".join(sorted(set(duplicate_tickers.tolist()))[:5])
            raise ValueError(
                f"{label} has duplicate persisted (ticker, finance_source) rows "
                f"for {finance_source!r} (e.g. {sample}); refusing row-order selection."
            )
    normalized_ticker = str(ticker or "").strip().upper()
    if normalized_ticker:
        if "ticker" not in selected.columns and not selected.empty:
            raise ValueError(f"{label} has rows but no 'ticker' column.")
        if "ticker" in selected.columns:
            selected = selected.loc[
                selected["ticker"].astype(str).str.strip().str.upper().eq(normalized_ticker)
            ].copy()
    if not selected.empty:
        return ToolDSourceSelection(frame=selected)

    source_label = "Yahoo Fundamentals" if normalized_source == "yahoo" else "Our View"
    return ToolDSourceSelection(
        frame=selected,
        reason=(
            f"No persisted {source_label} Corporate Resilience data is available "
            f"for {label}."
        ),
    )


def _tool_d_schema_state(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "empty"
    if "tool_d_schema_version" not in frame.columns:
        return "malformed"
    versions = pd.to_numeric(frame["tool_d_schema_version"], errors="coerce")
    if versions.isna().any():
        return "malformed"
    if bool(versions.eq(float(TOOL_D_SCHEMA_VERSION)).all()):
        return "v4"
    # Pre-v4 artifacts were Our-View-only. Integer schema generations remain
    # readable for that source so their existing field-level migration notices
    # (for example the v1 FCF rebuild notice) can render honestly. Yahoo stays
    # unavailable until a dual-source v4 refresh is published.
    legacy_versions = versions.ge(1.0) & versions.lt(float(TOOL_D_SCHEMA_VERSION))
    integral_versions = versions.eq(versions.round())
    if bool((legacy_versions & integral_versions).all()) and versions.nunique() == 1:
        return "legacy_our"
    return "malformed"


def validate_tool_d_output_frame(
    frame: pd.DataFrame,
    *,
    expected_tickers: Iterable[str] | None = None,
    require_complete_sources: bool = True,
    expected_source_run_id: str | None = None,
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
    violations.extend(_normalized_key_violations(frame))

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
        parsed_dates = pd.to_datetime(frame["as_of_date"], errors="coerce")
        invalid_dates = int((frame["as_of_date"].notna() & parsed_dates.isna()).sum())
        if invalid_dates:
            violations.append(f"invalid as_of_date values: {invalid_dates} row(s)")

    violations.extend(
        _single_generation_identity_violations(
            frame,
            "source_run_id",
            expected_value=expected_source_run_id,
        )
    )
    violations.extend(
        _single_generation_identity_violations(
            frame,
            "snapshot_refresh_run_id",
        )
    )
    for column in ("gold_price_used", "spot_gold_usd", "spot_gold_date"):
        violations.extend(_single_generation_context_violations(frame, column))

    for column in ("gold_price_used", "spot_gold_usd"):
        if column not in frame.columns:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        invalid = numeric.isna() | ~numeric.map(_is_finite_positive)
        count = int(invalid.sum())
        if count:
            violations.append(
                f"{column} must be finite and positive: {count} row(s) invalid"
            )

    if "spot_gold_date" in frame.columns:
        nonblank = _nonblank(frame, "spot_gold_date")
        parsed_spot_dates = pd.to_datetime(frame["spot_gold_date"], errors="coerce")
        invalid_spot_dates = int((nonblank & parsed_spot_dates.isna()).sum())
        if invalid_spot_dates:
            violations.append(
                f"invalid spot_gold_date values: {invalid_spot_dates} row(s)"
            )

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
        ticker_text = frame["ticker"].astype("string")
        canonical_tickers = ticker_text.str.strip().str.upper()
        blank_tickers = int(canonical_tickers.fillna("").eq("").sum())
        if blank_tickers:
            violations.append(f"blank ticker values: {blank_tickers} row(s)")
        noncanonical = ticker_text.notna() & ticker_text.ne(canonical_tickers)
        count = int(noncanonical.sum())
        if count:
            violations.append(
                "ticker values must be stored uppercase and stripped: "
                f"{count} row(s) non-canonical"
            )

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
        non_ok = ~statuses.astype("string").eq("OK").fillna(False)
        populated_outputs: list[str] = []
        for column in TOOL_D_RANKING_OUTPUT_COLUMNS:
            if column not in frame.columns:
                continue
            count = int(frame.loc[non_ok, column].notna().sum())
            if count:
                populated_outputs.append(f"{column}={count}")
        if populated_outputs:
            violations.append(
                "non-OK rows must keep ranking/score/percentile outputs null: "
                + ", ".join(populated_outputs)
            )

    violations.extend(_source_pair_context_violations(frame))

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


def canonicalize_tool_d_tickers(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy whose non-null ticker keys are stripped uppercase values.

    Validation remains pure and reports non-canonical inputs.  Persistence uses
    this one boundary normalizer before validation, so stored keys are stable
    while normalized collisions still fail loud instead of last-row-wins.
    """

    normalized = frame.copy()
    normalized.attrs.update(frame.attrs)
    if "ticker" in normalized.columns:
        normalized["ticker"] = normalized["ticker"].map(_canonical_ticker_value)
    return normalized


def _canonical_tickers(values: Iterable[str]) -> set[str]:
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _nonblank(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[column]
    return values.notna() & values.astype(str).str.strip().ne("")


def _normalized_key_violations(frame: pd.DataFrame) -> list[str]:
    if not all(column in frame.columns for column in TOOL_D_KEY_COLUMNS):
        return []
    keys = frame.loc[:, list(TOOL_D_KEY_COLUMNS)].copy()
    keys["ticker"] = keys["ticker"].map(_canonical_ticker_value)
    keys["finance_source"] = keys["finance_source"].map(_canonical_source_value)
    duplicate_count = int(keys.duplicated(subset=list(TOOL_D_KEY_COLUMNS)).sum())
    if not duplicate_count:
        return []
    return [
        "duplicate normalized keys on (ticker, finance_source): "
        f"{duplicate_count} row(s)"
    ]


def _single_generation_identity_violations(
    frame: pd.DataFrame,
    column: str,
    *,
    expected_value: str | None = None,
) -> list[str]:
    if column not in frame.columns:
        return []
    values = frame[column]
    text = values.astype("string").str.strip()
    blank = values.isna() | text.fillna("").eq("")
    violations: list[str] = []
    blank_count = int(blank.sum())
    if blank_count:
        violations.append(f"blank {column} values: {blank_count} row(s)")
    distinct = sorted(set(text.loc[~blank].astype(str).tolist()))
    if len(distinct) != 1:
        violations.append(
            f"{column} must contain exactly one nonblank generation value; "
            f"observed={distinct}"
        )
    if expected_value is not None:
        expected = str(expected_value).strip()
        if not expected or distinct != [expected]:
            violations.append(
                f"{column} must match persistence run_context {expected!r}; "
                f"observed={distinct}"
            )
    return violations


def _source_pair_context_violations(frame: pd.DataFrame) -> list[str]:
    required = {"ticker", "finance_source", *TOOL_D_SOURCE_PAIR_CONTEXT_COLUMNS}
    if not required.issubset(frame.columns):
        return []
    working = frame.loc[:, list(required)].copy()
    working["_canonical_ticker"] = working["ticker"].map(_canonical_ticker_value)
    working["_canonical_source"] = working["finance_source"].map(
        _canonical_source_value
    )
    working = working[
        working["_canonical_ticker"].notna()
        & working["_canonical_ticker"].ne("")
        & working["_canonical_source"].isin(FINANCE_SOURCES)
    ]

    mismatches: dict[str, list[str]] = {
        column: [] for column in TOOL_D_SOURCE_PAIR_CONTEXT_COLUMNS
    }
    for ticker, pair in working.groupby("_canonical_ticker", sort=True):
        if not set(FINANCE_SOURCES).issubset(pair["_canonical_source"]):
            continue
        for column in TOOL_D_SOURCE_PAIR_CONTEXT_COLUMNS:
            tokens = {
                _context_comparison_token(column, value)
                for value in pair[column].tolist()
            }
            if len(tokens) != 1:
                mismatches[column].append(str(ticker))

    return [
        f"source-pair {column} values differ for ticker(s): " + ", ".join(tickers)
        for column, tickers in mismatches.items()
        if tickers
    ]


def _single_generation_context_violations(
    frame: pd.DataFrame,
    column: str,
) -> list[str]:
    if column not in frame.columns:
        return []
    tokens = {
        _context_comparison_token(column, value)
        for value in frame[column].tolist()
    }
    if len(tokens) == 1:
        return []
    return [
        f"{column} must contain one coherent generation-wide value; "
        f"observed {len(tokens)} distinct normalized values"
    ]


def _context_comparison_token(column: str, value: Any) -> tuple[str, object]:
    if _is_missing(value):
        return ("missing", "")
    if column in {"as_of_date", "spot_gold_date"}:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return ("invalid-date", str(value).strip())
        return ("date", pd.Timestamp(parsed).date().isoformat())
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ("invalid-number", str(value).strip())
    return ("number", float(numeric))


def _canonical_ticker_value(value: Any) -> Any:
    return value if _is_missing(value) else str(value).strip().upper()


def _canonical_source_value(value: Any) -> Any:
    return value if _is_missing(value) else str(value).strip().lower()


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_finite_positive(value: Any) -> bool:
    if _is_missing(value):
        return False
    numeric = float(value)
    return numeric > 0 and math.isfinite(numeric)
