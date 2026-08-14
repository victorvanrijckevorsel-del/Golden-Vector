"""Ticker-page artifact schemas (mirrors plan §5.6 exactly, 1:1).

M1a contract only: constants + a pure schema-validation helper. Producers land
in M1b; model-state / manifest wiring lands with them.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

TICKER_PAGE_SCHEMA_VERSIONS: dict[str, int] = {
    # v2 persists the five line-metric values at true spot so the server page
    # is complete and truthful without JavaScript.
    "gold_response": 2,
    # v2 adds the distribution-strip geometry (strip_pos, universe_min/max) so
    # serve can draw the cohort rug without computing a single fraction.
    "percentiles": 2,
    # v2 (C4): actual observation dates (no invented W-FRI labels), one shared
    # anchor rebased to exactly 100, pre-anchor rebased points removed, and the
    # trim/source-date disclosure columns below.
    "performance": 2,
    # v2 (C9): horizon rows persist the full retained ladder (gold return/delta,
    # coverage flag/reason, exact period) 1:1, and every kind carries an
    # explicit per-kind status so an absent kind can never be silent.
    "research_series": 2,
    # Feature A: professional currency attribution, one row per configured
    # ticker and chart horizon (USD listings carry explicit N/A rows).
    "fx_attribution": 1,
    # Descriptive (not scoring) stock/GDX/peer downside context, with full and
    # configured-recent scopes. Values are computed in Tool C and aggregated in
    # the ticker-page producer; serve code only formats them.
    "downside_context": 1,
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
PERFORMANCE_SERIES_STATUSES: tuple[str, ...] = (
    "OK",
    "STALE_OMITTED",
    "MISSING",
    # C4: the stock series is required for the chart; when it is absent every
    # other series gets this explicit state instead of silently vanishing.
    "OMITTED_NO_STOCK",
)
RESEARCH_KINDS: tuple[str, ...] = ("weekly", "horizon", "window_fit")
FINANCE_SOURCES: tuple[str, ...] = ("our", "yahoo")

# The ONE alias table for finance-source tokens (W4). Older surfaces still emit
# `official` / `market` / `yahoo_fundamentals` in links and stored parameters, so
# both the request path and the artifact read boundary must agree on what those
# mean. Two policies read this one table:
#   * normalize_finance_source  — request/route policy: unknown falls back to the
#     default Our View, because a user-typed query param must never 500 a page.
#   * canonical_finance_source  — reader policy: unknown returns None so the
#     caller can fail loud, because an unrecognized token inside the codebase is
#     a bug, not a user typo.
FINANCE_SOURCE_ALIASES: dict[str, str] = {
    "our": "our",
    "yahoo": "yahoo",
    "official": "yahoo",
    "market": "yahoo",
    "yahoo_fundamentals": "yahoo",
}


def canonical_finance_source(value: object) -> str | None:
    """Return the canonical source for a KNOWN token, else ``None``.

    Reader boundary: callers turn ``None`` into their own fail-loud error, so a
    typo (``"ours"``) can never be silently served as Our View data.
    """

    return FINANCE_SOURCE_ALIASES.get(str(value or "").strip().lower())


def normalize_finance_source(value: object) -> Literal["our", "yahoo"]:
    """Return the canonical source mode used by Tool B scenario views.

    Request policy: anything unrecognized resolves to ``"our"`` (the default
    view). Re-exported by ``screening.pipeline`` for its historical callers.
    """

    resolved = canonical_finance_source(value)
    return "yahoo" if resolved == "yahoo" else "our"


# --- gold response ---------------------------------------------------------

GOLD_RESPONSE_LINE_METRICS: tuple[str, ...] = (
    "forward_revenue_musd",
    "forward_ebitda_musd",
    "forward_net_income_musd",
    "forward_eps",
    "aisc_margin_est_musd",
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
    "spot_aisc_margin_yield",
    "spot_ev_ebitda",
    "spot_forward_pe",
    "spot_leverage_stressed",
)
GOLD_RESPONSE_SPOT_LINE_COLUMNS: tuple[str, ...] = tuple(
    f"spot_{metric}" for metric in GOLD_RESPONSE_LINE_METRICS
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
    *GOLD_RESPONSE_SPOT_LINE_COLUMNS,
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
    # Distribution-strip geometry: `strip_pos` is this row's 0..1 position within
    # the eligible cohort's raw_value span, `universe_min`/`universe_max` are that
    # span's ends. Serve maps fraction -> pixel and never computes the fraction.
    "strip_pos",
    "universe_min",
    "universe_max",
    "metric_available",
    "metric_reason",
    "rank_eligible",
    "rank_exclusion_reason",
    "eligible_peer_count",
    # v2 metric evidence (null for metrics that declare none)
    "eligible_observation_count",
    "hit_count",
    "source_period_start",
    "source_period_end",
    "source_verification_status",
    "source_verification_date",
    *TICKER_PAGE_PROVENANCE_COLUMNS,
)

# --- downside context ------------------------------------------------------

DOWNSIDE_CONTEXT_KEY_COLUMNS: tuple[str, ...] = ("ticker", "scope", "subject")
DOWNSIDE_CONTEXT_SCOPES: tuple[str, ...] = ("full_history", "recent")
DOWNSIDE_CONTEXT_SUBJECTS: tuple[str, ...] = ("stock", "gdx", "peer_median")
DOWNSIDE_CONTEXT_STATUSES: tuple[str, ...] = (
    "OK",
    "THIN_EVIDENCE",
    "MISSING",
)
DOWNSIDE_CONTEXT_COLUMNS: tuple[str, ...] = (
    *DOWNSIDE_CONTEXT_KEY_COLUMNS,
    "window_years",
    "qualifying_week_count",
    "hit_count",
    "hit_rate",
    "median_hit_return",
    "worst_hit_return",
    "period_start",
    "period_end",
    "frequency_peer_count",
    "severity_peer_count",
    "frequency_vs_gdx_delta",
    "frequency_vs_peer_delta",
    "severity_vs_gdx_delta",
    "severity_vs_peer_delta",
    "frequency_vs_full_delta",
    "severity_vs_full_delta",
    "comparison_summary",
    "trend_summary",
    "context_status",
    "context_reason",
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
    # C4 (v2): the source's TRUE last observation, the shared trim boundary,
    # why the series was trimmed, and which price basis backs the values.
    "source_last_date",
    "common_end_date",
    "trim_reason",
    "price_basis",
    "series_source_run_id",
    "currency_basis",
    *TICKER_PAGE_PROVENANCE_COLUMNS,
)

# --- fx attribution --------------------------------------------------------

#: How the FX effect relates to the local move over the selected window.
FX_ATTRIBUTION_RELATIONSHIPS: tuple[str, ...] = (
    "SAME_DIRECTION",
    "OFFSET",
    "REVERSAL",
    "LOCAL_FLAT",
    "UNAVAILABLE",
    "NOT_APPLICABLE_USD",
)
FX_ATTRIBUTION_STATUSES: tuple[str, ...] = ("OK", "UNAVAILABLE", "NOT_APPLICABLE_USD")

FX_ATTRIBUTION_KEY_COLUMNS: tuple[str, ...] = ("ticker", "horizon")
#: Returns (`local_return`, `fx_return`, `usd_return`) are FRACTIONS.
#: ``fx_contribution_pp`` is the ONE percentage-point-scaled column
#: (usd_return - local_return, x100) — named with its unit on purpose.
#: ``share_of_usd_move`` / ``offset_of_local_move`` are nullable fractions and
#: only populated for the relationship whose headline uses them.
FX_ATTRIBUTION_COLUMNS: tuple[str, ...] = (
    *FX_ATTRIBUTION_KEY_COLUMNS,
    "quote_currency",
    "start_date",
    "end_date",
    "local_start_value",
    "local_end_value",
    "local_return",
    "fx_start_rate",
    "fx_end_rate",
    "fx_start_source_date",
    "fx_end_source_date",
    "fx_source_symbol",
    "fx_return",
    "usd_start_value",
    "usd_end_value",
    "usd_return",
    "fx_contribution_pp",
    "relationship",
    "share_of_usd_move",
    "offset_of_local_move",
    "attribution_status",
    "attribution_reason",
    "price_basis",
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
    # horizon (v2/C9: the retained Full-Research ladder persists 1:1 — the UI
    # must read these fields, never recompute them in a request handler)
    "horizon_label",
    "horizon_return",
    "basis",
    "horizon_gold_return",
    "horizon_gold_delta",
    "horizon_coverage_flag",
    "horizon_coverage_reason",
    "horizon_start_date",
    "horizon_end_date",
    # window_fit
    "window",
    "up_beta",
    "down_beta",
    "r_squared",
    "weeks",
    "window_status",
    # v2/C9: explicit per-kind status — a kind with no rows still has a row
    # saying so (kind_status MISSING + reason); data rows carry OK.
    "kind_status",
    "kind_reason",
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
    **{column: "float64" for column in GOLD_RESPONSE_SPOT_LINE_COLUMNS},
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
    "strip_pos": "float64",
    "universe_min": "float64",
    "universe_max": "float64",
    "metric_available": "boolean",
    "metric_reason": "string",
    "rank_eligible": "boolean",
    "rank_exclusion_reason": "string",
    "eligible_peer_count": "Int64",
    "eligible_observation_count": "Int64",
    "hit_count": "Int64",
    "source_period_start": "datetime64[ns]",
    "source_period_end": "datetime64[ns]",
    "source_verification_status": "string",
    "source_verification_date": "string",
    **_PROVENANCE_DTYPES,
}

DOWNSIDE_CONTEXT_DTYPES: dict[str, str] = {
    "ticker": "string",
    "scope": "string",
    "subject": "string",
    "window_years": "Int64",
    "qualifying_week_count": "Int64",
    "hit_count": "Int64",
    "hit_rate": "float64",
    "median_hit_return": "float64",
    "worst_hit_return": "float64",
    "period_start": "datetime64[ns]",
    "period_end": "datetime64[ns]",
    "frequency_peer_count": "Int64",
    "severity_peer_count": "Int64",
    "frequency_vs_gdx_delta": "float64",
    "frequency_vs_peer_delta": "float64",
    "severity_vs_gdx_delta": "float64",
    "severity_vs_peer_delta": "float64",
    "frequency_vs_full_delta": "float64",
    "severity_vs_full_delta": "float64",
    "comparison_summary": "string",
    "trend_summary": "string",
    "context_status": "string",
    "context_reason": "string",
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
    "source_last_date": "datetime64[ns]",
    "common_end_date": "datetime64[ns]",
    "trim_reason": "string",
    "price_basis": "string",
    "series_source_run_id": "string",
    "currency_basis": "string",
    **_PROVENANCE_DTYPES,
}

FX_ATTRIBUTION_DTYPES: dict[str, str] = {
    "ticker": "string",
    "horizon": "string",
    "quote_currency": "string",
    "start_date": "datetime64[ns]",
    "end_date": "datetime64[ns]",
    "local_start_value": "float64",
    "local_end_value": "float64",
    "local_return": "float64",
    "fx_start_rate": "float64",
    "fx_end_rate": "float64",
    "fx_start_source_date": "datetime64[ns]",
    "fx_end_source_date": "datetime64[ns]",
    "fx_source_symbol": "string",
    "fx_return": "float64",
    "usd_start_value": "float64",
    "usd_end_value": "float64",
    "usd_return": "float64",
    "fx_contribution_pp": "float64",
    "relationship": "string",
    "share_of_usd_move": "float64",
    "offset_of_local_move": "float64",
    "attribution_status": "string",
    "attribution_reason": "string",
    "price_basis": "string",
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
    "horizon_gold_return": "float64",
    "horizon_gold_delta": "float64",
    "horizon_coverage_flag": "string",
    "horizon_coverage_reason": "string",
    "horizon_start_date": "datetime64[ns]",
    "horizon_end_date": "datetime64[ns]",
    "kind_status": "string",
    "kind_reason": "string",
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
    "fx_attribution": FX_ATTRIBUTION_DTYPES,
    "research_series": RESEARCH_SERIES_DTYPES,
    "downside_context": DOWNSIDE_CONTEXT_DTYPES,
}

#: Contract column tuple per artifact (same keys as EXPECTED_DTYPES).
ARTIFACT_COLUMNS: dict[str, tuple[str, ...]] = {
    "gold_response": GOLD_RESPONSE_COLUMNS,
    "percentiles": PERCENTILES_COLUMNS,
    "performance": PERFORMANCE_COLUMNS,
    "fx_attribution": FX_ATTRIBUTION_COLUMNS,
    "research_series": RESEARCH_SERIES_COLUMNS,
    "downside_context": DOWNSIDE_CONTEXT_COLUMNS,
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
