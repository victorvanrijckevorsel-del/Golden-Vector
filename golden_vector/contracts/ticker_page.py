"""Ticker-page artifact schemas (mirrors plan §5.6 exactly, 1:1).

M1a contract only: constants + a pure schema-validation helper. Producers land
in M1b; model-state / manifest wiring lands with them.
"""

from __future__ import annotations

import pandas as pd

TICKER_PAGE_SCHEMA_VERSIONS: dict[str, int] = {
    "gold_response": 1,
    "percentiles": 1,
    "performance": 1,
    "research_series": 1,
}

# Provenance columns carried by every ticker-page artifact (§5.6 "Common columns").
TICKER_PAGE_PROVENANCE_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "parent_refresh_id",
    "config_hash",
)

# --- enums -----------------------------------------------------------------

GOLD_RESPONSE_STATUSES: tuple[str, ...] = (
    "OK",
    "DEGRADED_NONLINEAR",
    "DEGRADED_INPUTS",
)
PERFORMANCE_SERIES: tuple[str, ...] = ("stock", "gold", "gdx", "gdxj")
PERFORMANCE_VIEWS: tuple[str, ...] = ("price", "rebased")
PERFORMANCE_HORIZONS: tuple[str, ...] = ("1Y", "3Y", "5Y")
PERFORMANCE_SERIES_STATUSES: tuple[str, ...] = ("OK", "STALE_OMITTED", "MISSING")
RESEARCH_KINDS: tuple[str, ...] = ("weekly", "horizon", "window_fit")
FINANCE_SOURCES: tuple[str, ...] = ("our", "yahoo")

# --- gold response ---------------------------------------------------------

GOLD_RESPONSE_LINE_METRICS: tuple[str, ...] = (
    "forward_revenue_musd",
    "forward_ebitda_musd",
    "forward_net_income_musd",
    "forward_eps",
    "sustainable_fcf_musd",
)
GOLD_RESPONSE_CONSTANT_COLUMNS: tuple[str, ...] = (
    "market_cap_musd",
    "enterprise_value_musd",
    "net_debt_musd",
    "interest_expense_musd",
    "share_price_usd",
    "aisc_usd_per_oz",
    "cash_cost_usd_per_oz",
    "production_oz",
    "ebitda_ltm_musd",
)
GOLD_RESPONSE_SPOT_DISPLAY_COLUMNS: tuple[str, ...] = (
    "spot_margin_usd_per_oz",
    "spot_margin_pct",
    "spot_fcf_yield",
    "spot_ev_ebitda",
    "spot_forward_pe",
    "spot_leverage_stressed",
)

#: Cost basis the persisted spot margin columns are computed against. The pack
#: ships BOTH ``aisc_usd_per_oz`` and ``cash_cost_usd_per_oz`` as constants, so a
#: bare "margin" is ambiguous — label every number with its basis.
GOLD_RESPONSE_MARGIN_BASES: tuple[str, ...] = ("aisc", "cash_cost")

GOLD_RESPONSE_KEY_COLUMNS: tuple[str, ...] = ("ticker", "finance_source")
GOLD_RESPONSE_COLUMNS: tuple[str, ...] = (
    *GOLD_RESPONSE_KEY_COLUMNS,
    *(
        column
        for metric in GOLD_RESPONSE_LINE_METRICS
        for column in (f"line_slope_{metric}", f"line_intercept_{metric}")
    ),
    *GOLD_RESPONSE_CONSTANT_COLUMNS,
    "spot_gold_usd",
    "spot_gold_date",
    *GOLD_RESPONSE_SPOT_DISPLAY_COLUMNS,
    "spot_margin_basis",
    "gold_response_status",
    "gold_response_reason",
    "linearity_max_residual",
    *TICKER_PAGE_PROVENANCE_COLUMNS,
)

# --- percentiles -----------------------------------------------------------

PERCENTILES_KEY_COLUMNS: tuple[str, ...] = ("ticker", "finance_source", "metric_key")
PERCENTILES_COLUMNS: tuple[str, ...] = (
    *PERCENTILES_KEY_COLUMNS,
    "category",
    "raw_value",
    "unit",
    "basis",
    "source_tool",
    "source_as_of_date",
    "pct_high_good",
    "pct_low_good",
    "metric_available",
    "metric_reason",
    "rank_eligible",
    "rank_exclusion_reason",
    "eligible_peer_count",
    *TICKER_PAGE_PROVENANCE_COLUMNS,
)

# --- performance -----------------------------------------------------------

PERFORMANCE_KEY_COLUMNS: tuple[str, ...] = (
    "ticker",
    "series",
    "view",
    "horizon",
    "date",
)
PERFORMANCE_COLUMNS: tuple[str, ...] = (
    *PERFORMANCE_KEY_COLUMNS,
    "value",
    "rebase_date",
    "late_start",
    "series_status",
    "series_reason",
    "series_as_of_date",
    "series_source_run_id",
    "currency_basis",
    *TICKER_PAGE_PROVENANCE_COLUMNS,
)

# --- research series -------------------------------------------------------

# Three row-kinds share one keyed table; uniqueness is enforced per kind on
# (ticker, kind, <kind key>). The kind keys are nullable outside their kind.
RESEARCH_SERIES_KEY_COLUMNS: tuple[str, ...] = ("ticker", "kind")
RESEARCH_SERIES_KIND_KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "weekly": ("ticker", "kind", "date"),
    "horizon": ("ticker", "kind", "horizon_label"),
    "window_fit": ("ticker", "kind", "window"),
}
RESEARCH_SERIES_COLUMNS: tuple[str, ...] = (
    *RESEARCH_SERIES_KEY_COLUMNS,
    # weekly
    "date",
    "stock_return",
    "gold_return",
    "gdx_return",
    "gdxj_return",
    # horizon
    "horizon_label",
    "horizon_return",
    "basis",
    # window_fit
    "window",
    "up_beta",
    "down_beta",
    "r_squared",
    "weeks",
    "window_status",
    *TICKER_PAGE_PROVENANCE_COLUMNS,
)


# --- dtypes ----------------------------------------------------------------
#
# An EMPTY artifact must be typed exactly like a populated one. Untyped empty
# frames come back from parquet as all-object columns, so a degraded build
# silently changes the schema under every reader (and `pd.concat` of an empty
# object frame with a real one upcasts real columns back to object). These maps
# are applied to BOTH the empty constructors and the populated builder output,
# so the two are identical by construction, not by luck.
#
# `string` / `boolean` / `Int64` are the pandas nullable dtypes — they survive a
# parquet round-trip and, unlike object/float, can hold a real missing value
# without lying about the type.

_PROVENANCE_DTYPES: dict[str, str] = {
    "schema_version": "Int64",
    "source_run_id": "string",
    "snapshot_refresh_run_id": "string",
    "parent_refresh_id": "string",
    "config_hash": "string",
}

GOLD_RESPONSE_DTYPES: dict[str, str] = {
    "ticker": "string",
    "finance_source": "string",
    **{
        column: "float64"
        for metric in GOLD_RESPONSE_LINE_METRICS
        for column in (f"line_slope_{metric}", f"line_intercept_{metric}")
    },
    **{column: "float64" for column in GOLD_RESPONSE_CONSTANT_COLUMNS},
    "spot_gold_usd": "float64",
    "spot_gold_date": "string",
    **{column: "float64" for column in GOLD_RESPONSE_SPOT_DISPLAY_COLUMNS},
    "spot_margin_basis": "string",
    "gold_response_status": "string",
    "gold_response_reason": "string",
    "linearity_max_residual": "float64",
    **_PROVENANCE_DTYPES,
}

PERCENTILES_DTYPES: dict[str, str] = {
    "ticker": "string",
    "finance_source": "string",
    "metric_key": "string",
    "category": "string",
    "raw_value": "float64",
    "unit": "string",
    "basis": "string",
    "source_tool": "string",
    "source_as_of_date": "string",
    "pct_high_good": "float64",
    "pct_low_good": "float64",
    "metric_available": "boolean",
    "metric_reason": "string",
    "rank_eligible": "boolean",
    "rank_exclusion_reason": "string",
    "eligible_peer_count": "Int64",
    **_PROVENANCE_DTYPES,
}

PERFORMANCE_DTYPES: dict[str, str] = {
    "ticker": "string",
    "series": "string",
    "view": "string",
    "horizon": "string",
    "date": "datetime64[ns]",
    "value": "float64",
    "rebase_date": "datetime64[ns]",
    "late_start": "boolean",
    "series_status": "string",
    "series_reason": "string",
    "series_as_of_date": "datetime64[ns]",
    "series_source_run_id": "string",
    "currency_basis": "string",
    **_PROVENANCE_DTYPES,
}

RESEARCH_SERIES_DTYPES: dict[str, str] = {
    "ticker": "string",
    "kind": "string",
    "date": "datetime64[ns]",
    "stock_return": "float64",
    "gold_return": "float64",
    "gdx_return": "float64",
    "gdxj_return": "float64",
    "horizon_label": "string",
    "horizon_return": "float64",
    "basis": "string",
    "window": "string",
    "up_beta": "float64",
    "down_beta": "float64",
    "r_squared": "float64",
    "weeks": "Int64",
    "window_status": "string",
    **_PROVENANCE_DTYPES,
}

#: Per-artifact expected dtypes, keyed exactly like TICKER_PAGE_SCHEMA_VERSIONS.
EXPECTED_DTYPES: dict[str, dict[str, str]] = {
    "gold_response": GOLD_RESPONSE_DTYPES,
    "percentiles": PERCENTILES_DTYPES,
    "performance": PERFORMANCE_DTYPES,
    "research_series": RESEARCH_SERIES_DTYPES,
}

#: Contract column tuple per artifact (same keys as EXPECTED_DTYPES).
ARTIFACT_COLUMNS: dict[str, tuple[str, ...]] = {
    "gold_response": GOLD_RESPONSE_COLUMNS,
    "percentiles": PERCENTILES_COLUMNS,
    "performance": PERFORMANCE_COLUMNS,
    "research_series": RESEARCH_SERIES_COLUMNS,
}


def apply_expected_dtypes(frame: pd.DataFrame, *, artifact: str) -> pd.DataFrame:
    """Return ``frame`` with every contract column cast to its expected dtype."""

    expected = EXPECTED_DTYPES.get(artifact)
    if expected is None:
        raise ValueError(f"unknown ticker-page artifact: {artifact}")
    out = frame.copy()
    for column, dtype in expected.items():
        if column not in out.columns:
            continue
        if dtype == "datetime64[ns]":
            # `to_datetime` infers the RESOLUTION from the data (an empty column
            # comes back as datetime64[s]), which round-trips through parquet to
            # a different unit than a populated frame. Pin it.
            out[column] = pd.to_datetime(out[column], errors="coerce").astype(
                "datetime64[ns]"
            )
        else:
            out[column] = out[column].astype(dtype)
    return out


def empty_artifact_frame(artifact: str) -> pd.DataFrame:
    """A zero-row frame with the artifact's exact columns AND dtypes."""

    columns = ARTIFACT_COLUMNS.get(artifact)
    if columns is None:
        raise ValueError(f"unknown ticker-page artifact: {artifact}")
    return apply_expected_dtypes(
        pd.DataFrame({column: pd.Series(dtype="object") for column in columns}),
        artifact=artifact,
    )


def validate_frame_schema(
    frame: pd.DataFrame,
    *,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    allow_extra: bool = False,
) -> list[str]:
    """Return human-readable schema violations for ``frame`` (pure, no IO).

    Checks, in order: missing required columns, unexpected extra columns (when
    ``allow_extra`` is False), null key values, and duplicate keys. An empty
    list means the frame satisfies the contract.
    """
    violations: list[str] = []
    present = list(frame.columns)
    missing = [column for column in columns if column not in present]
    if missing:
        violations.append("missing columns: " + ", ".join(missing))
    if not allow_extra:
        extra = [column for column in present if column not in columns]
        if extra:
            violations.append("unexpected columns: " + ", ".join(sorted(extra)))

    available_keys = [column for column in key_columns if column in present]
    missing_keys = [column for column in key_columns if column not in present]
    if missing_keys:
        violations.append("missing key columns: " + ", ".join(missing_keys))
    if not available_keys:
        return violations

    for column in available_keys:
        null_count = int(frame[column].isna().sum())
        if null_count:
            violations.append(f"null values in key column {column}: {null_count} row(s)")

    if not missing_keys and not frame.empty:
        duplicate_count = int(frame.duplicated(subset=list(key_columns)).sum())
        if duplicate_count:
            violations.append(
                "duplicate keys on ("
                + ", ".join(key_columns)
                + f"): {duplicate_count} row(s)"
            )
    return violations
