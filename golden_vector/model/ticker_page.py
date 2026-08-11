"""Ticker-page artifact producers (plan §4, §5.6, §7 — M1b).

Four pure builders that turn already-loaded inputs into DataFrames matching
``golden_vector/contracts/ticker_page.py`` exactly. Nothing here touches the
filesystem or a request path: the stage loads inputs, these compute, and
``ingestion/persist_ticker_page.py`` writes.

Every builder validates its own output against the contract before returning
and raises ``ValueError`` naming the violations, so a schema drift can never
reach an artifact.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from golden_vector.common.eligibility import is_score_eligible
from golden_vector.common.numeric import optional_float
from golden_vector.contracts.ticker_page import (
    FINANCE_SOURCES,
    GOLD_RESPONSE_COLUMNS,
    GOLD_RESPONSE_CONSTANT_COLUMNS,
    GOLD_RESPONSE_KEY_COLUMNS,
    GOLD_RESPONSE_LINE_METRICS,
    PERCENTILES_COLUMNS,
    PERCENTILES_KEY_COLUMNS,
    PERFORMANCE_COLUMNS,
    PERFORMANCE_KEY_COLUMNS,
    RESEARCH_SERIES_COLUMNS,
    RESEARCH_SERIES_KIND_KEY_COLUMNS,
    TICKER_PAGE_PROVENANCE_COLUMNS,
    apply_expected_dtypes,
    validate_frame_schema,
)
from golden_vector.features.percentile_ranks import oriented_percentile
from golden_vector.model.gold_lines import (
    MIN_X_SEPARATION,
    GoldLine,
    evaluate,
    line_from_two_points,
)

# Reuse, never fork: Tool D owns the guarded ">0 denominator" ratio used for
# stressed forward leverage (net debt / forward EBITDA, `leverage_stressed_at_g`).
# Tool B emits only the *trailing* `leverage` column (net debt / EBITDA LTM), so
# the stressed value must be derived here with Tool D's exact guard semantics.
from golden_vector.common.numeric import ratio_over_positive as _guarded_ratio
from golden_vector.model.tool_d import latest_gold_price_from_history
from golden_vector.screening.pipeline import compute_tool_b_in_memory

__all__ = [
    "build_gold_response_pack",
    "build_performance_series",
    "build_research_series",
    "build_score_percentiles",
]

#: Tool B column that backs each persisted spot display value (§5.6).
_SPOT_DISPLAY_SOURCE_COLUMNS: dict[str, str] = {
    "spot_margin_usd_per_oz": "cash_margin_usd_per_oz",
    "spot_margin_pct": "margin_pct",
    "spot_fcf_yield": "fcf_yield",
    "spot_ev_ebitda": "ev_ebitda",
    "spot_forward_pe": "forward_pe",
}

_PERFORMANCE_HORIZON_YEARS: dict[str, int] = {"1Y": 1, "3Y": 3, "5Y": 5}
#: 1Y renders daily; longer horizons resample to weekly (last observation, W-FRI).
_PERFORMANCE_RESAMPLE_RULE: dict[str, str | None] = {"1Y": None, "3Y": "W-FRI", "5Y": "W-FRI"}

_BENCHMARK_SERIES: tuple[str, ...] = ("gdx", "gdxj")


def _null_provenance() -> dict[str, Any]:
    """Placeholder provenance — stamped for real by the persistence layer."""
    return {column: None for column in TICKER_PAGE_PROVENANCE_COLUMNS}


def _validated(
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    name: str,
    artifact: str,
) -> pd.DataFrame:
    # Type first, then validate: an empty build and a populated build must leave
    # this function with byte-identical schemas (see contracts EXPECTED_DTYPES).
    frame = apply_expected_dtypes(
        pd.DataFrame(rows, columns=list(columns)), artifact=artifact
    )
    violations = validate_frame_schema(frame, columns=columns, key_columns=key_columns)
    if violations:
        raise ValueError(f"{name} does not satisfy its contract: " + "; ".join(violations))
    return frame


# ---------------------------------------------------------------------------
# Builder 1 — gold response pack
# ---------------------------------------------------------------------------


def _abs_tolerance_for(metric: str, dial: Any) -> float:
    if metric == "forward_eps":
        return float(dial.linearity_abs_tol_eps)
    return float(dial.linearity_abs_tol_musd)


def _tool_b_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for record in frame.to_dict(orient="records"):
        out[str(record["ticker"]).upper()] = record
    return out


def build_gold_response_pack(
    *,
    app_config: Any,
    manual_data: Any,
    normalized_market_snapshots: pd.DataFrame,
    official_fundamentals: pd.DataFrame | None,
    gold_history: pd.DataFrame,
    snapshot_refresh_run_id: str | None,
    snapshot_as_of_date: object,
    source_run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the gold-response pack + its linearity residual diagnostics.

    Returns ``(pack_frame, diagnostics_frame)``. The pack carries one row per
    (ticker, finance_source) with the five metric lines, the constants, and the
    spot display values evaluated at **true spot** — never Tool B's configured
    ``default_gold_price_assumption`` (plan §3.2).
    """

    dial = app_config.ticker_page.dial
    spot_gold_usd, spot_gold_date = latest_gold_price_from_history(gold_history)

    probes = sorted(float(probe) for probe in dial.probe_gold_usd)
    if len(probes) < 2:
        raise ValueError("ticker_page.dial.probe_gold_usd needs at least two probes")
    outer_low, outer_high = probes[0], probes[-1]

    # Evaluation grid = every configured probe plus true spot (deduplicated).
    grid: list[float] = list(probes)
    if all(abs(spot_gold_usd - probe) >= MIN_X_SEPARATION for probe in probes):
        grid.append(float(spot_gold_usd))
    grid = sorted(grid)

    def _spot_key() -> float:
        for gold in grid:
            if abs(gold - spot_gold_usd) < MIN_X_SEPARATION:
                return gold
        raise ValueError("spot gold price is not present in the evaluation grid")

    spot_key = _spot_key()

    evaluations: dict[str, dict[float, dict[str, dict[str, Any]]]] = {}
    degraded_sources: dict[str, str] = {}
    for finance_source in FINANCE_SOURCES:
        per_gold: dict[float, dict[str, dict[str, Any]]] = {}
        try:
            for gold in grid:
                per_gold[gold] = _tool_b_by_ticker(
                    compute_tool_b_in_memory(
                        app_config=app_config,
                        manual_data=manual_data,
                        normalized_market_snapshots=normalized_market_snapshots,
                        gold_price_assumption=gold,
                        snapshot_refresh_run_id=snapshot_refresh_run_id,
                        snapshot_as_of_date=snapshot_as_of_date,
                        source_run_id=source_run_id,
                        spot_gold_usd=spot_gold_usd,
                        spot_gold_date=spot_gold_date,
                        official_fundamentals=official_fundamentals,
                        finance_source=finance_source,
                    )
                )
        except Exception as error:  # noqa: BLE001 - degrade this source, keep the others
            if finance_source == "our":
                # Our View is a required input: fail loud (senior rule).
                raise
            degraded_sources[finance_source] = (
                f"Tool B could not be computed for finance_source={finance_source}: {error}"
            )
            continue
        evaluations[finance_source] = per_gold

    # Union across BOTH sources' spot evaluations, not just Our View. A ticker
    # that only the yahoo source can price (no manual inputs yet) still deserves
    # its yahoo row plus an explicit our-source DEGRADED_INPUTS row; keying off
    # `our` alone silently erased it from the artifact entirely.
    tickers = sorted(
        {
            ticker
            for per_gold in evaluations.values()
            for ticker in per_gold.get(spot_key, {})
        }
    )

    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    nonlinear_tickers: set[str] = set()

    for ticker in tickers:
        for finance_source in FINANCE_SOURCES:
            base: dict[str, Any] = {
                "ticker": ticker,
                "finance_source": finance_source,
                "spot_gold_usd": float(spot_gold_usd),
                "spot_gold_date": str(spot_gold_date),
                "gold_response_status": "OK",
                "gold_response_reason": None,
                "linearity_max_residual": None,
                **{f"line_slope_{m}": None for m in GOLD_RESPONSE_LINE_METRICS},
                **{f"line_intercept_{m}": None for m in GOLD_RESPONSE_LINE_METRICS},
                **{column: None for column in GOLD_RESPONSE_CONSTANT_COLUMNS},
                **{column: None for column in _SPOT_DISPLAY_SOURCE_COLUMNS},
                "spot_leverage_stressed": None,
                # Label every number with its basis: `cash_margin_usd_per_oz` is
                # gold - AISC (screening/layer1.py), NOT gold - cash cost, and the
                # pack ships both cost constants. Machine-readable so no reader has
                # to infer it from a column name that says "cash".
                "spot_margin_basis": "aisc",
                **_null_provenance(),
            }

            if finance_source in degraded_sources:
                base["gold_response_status"] = "DEGRADED_INPUTS"
                base["gold_response_reason"] = degraded_sources[finance_source]
                rows.append(base)
                continue

            per_gold = evaluations[finance_source]
            missing_at = [gold for gold in grid if ticker not in per_gold[gold]]
            if missing_at:
                base["gold_response_status"] = "DEGRADED_INPUTS"
                base["gold_response_reason"] = (
                    f"no Tool B row for {ticker} at gold price(s) "
                    + ", ".join(f"{gold:g}" for gold in missing_at)
                )
                rows.append(base)
                continue

            spot_row = per_gold[spot_key][ticker]
            for column in GOLD_RESPONSE_CONSTANT_COLUMNS:
                base[column] = optional_float(spot_row.get(column))
            for display_column, source_column in _SPOT_DISPLAY_SOURCE_COLUMNS.items():
                base[display_column] = optional_float(spot_row.get(source_column))
            base["spot_leverage_stressed"] = _guarded_ratio(
                optional_float(spot_row.get("net_debt_musd")),
                optional_float(spot_row.get("forward_ebitda_musd")),
            )

            missing_metrics: list[str] = []
            untested_probes: list[str] = []
            failures: list[str] = []
            max_residual: float | None = None

            for metric in GOLD_RESPONSE_LINE_METRICS:
                low_value = optional_float(per_gold[outer_low][ticker].get(metric))
                high_value = optional_float(per_gold[outer_high][ticker].get(metric))
                line: GoldLine | None = line_from_two_points(
                    outer_low, low_value, outer_high, high_value
                )
                if line is None:
                    missing_metrics.append(metric)
                    continue
                base[f"line_slope_{metric}"] = float(line.slope)
                base[f"line_intercept_{metric}"] = float(line.intercept)

                abs_tol = _abs_tolerance_for(metric, dial)
                for gold in grid:
                    actual = optional_float(per_gold[gold][ticker].get(metric))
                    if actual is None:
                        # The line is fitted from the OUTER probes only. An interior
                        # probe (or true spot) with no value means the fit was never
                        # tested where the page actually reads it — that is untested,
                        # not linear. Never ship it as OK.
                        untested_probes.append(f"{metric} at gold {gold:g}")
                        continue
                    expected = evaluate(line, gold)
                    if expected is None or not math.isfinite(expected):
                        continue
                    residual = abs(expected - actual)
                    tolerance = max(abs_tol, float(dial.linearity_rel_tol) * abs(actual))
                    passed = residual <= tolerance
                    diagnostics.append(
                        {
                            "ticker": ticker,
                            "finance_source": finance_source,
                            "metric": metric,
                            "probe_gold_usd": float(gold),
                            "expected": float(expected),
                            "actual": float(actual),
                            "residual": float(residual),
                            "tolerance_applied": float(tolerance),
                            "passed": bool(passed),
                        }
                    )
                    max_residual = residual if max_residual is None else max(max_residual, residual)
                    if not passed:
                        failures.append(
                            f"{metric} at gold {gold:g}: residual {residual:.6g} "
                            f"> tolerance {tolerance:.6g}"
                        )

            base["linearity_max_residual"] = max_residual
            if missing_metrics:
                base["gold_response_status"] = "DEGRADED_INPUTS"
                base["gold_response_reason"] = (
                    "missing Tool B values at the outer probes for: "
                    + ", ".join(missing_metrics)
                )
            elif failures:
                base["gold_response_status"] = "DEGRADED_NONLINEAR"
                base["gold_response_reason"] = "; ".join(failures)
                nonlinear_tickers.add(ticker)
            elif untested_probes:
                base["gold_response_status"] = "DEGRADED_INPUTS"
                base["gold_response_reason"] = (
                    "linearity is untested at probe(s) with no Tool B value: "
                    + ", ".join(untested_probes)
                )
            rows.append(base)

    if len(nonlinear_tickers) >= int(dial.systemic_min_tickers):
        worst = sorted(
            (row for row in diagnostics if not row["passed"]),
            key=lambda row: row["residual"],
            reverse=True,
        )[:5]
        detail = "; ".join(
            f"{row['ticker']}/{row['finance_source']}/{row['metric']}@{row['probe_gold_usd']:g}"
            f" residual={row['residual']:.6g} tol={row['tolerance_applied']:.6g}"
            for row in worst
        )
        raise ValueError(
            "systemic gold-response linearity failure: "
            f"{len(nonlinear_tickers)} ticker(s) failed "
            f"(threshold {int(dial.systemic_min_tickers)}). Worst rows: {detail}"
        )

    pack = _validated(
        rows,
        columns=GOLD_RESPONSE_COLUMNS,
        key_columns=GOLD_RESPONSE_KEY_COLUMNS,
        name="ticker_page_gold_response",
        artifact="gold_response",
    )
    diagnostics_frame = pd.DataFrame(
        diagnostics,
        columns=[
            "ticker",
            "finance_source",
            "metric",
            "probe_gold_usd",
            "expected",
            "actual",
            "residual",
            "tolerance_applied",
            "passed",
        ],
    )
    return pack, diagnostics_frame


# ---------------------------------------------------------------------------
# Builder 2 — score percentiles
# ---------------------------------------------------------------------------


def _indexed(frame: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for record in frame.to_dict(orient="records"):
        out[str(record["ticker"]).upper()] = record
    return out


def _as_of_text(record: dict[str, Any]) -> str | None:
    for column in ("as_of_date", "source_as_of_date", "snapshot_as_of_date"):
        value = record.get(column)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        return str(value)
    return None


def build_score_percentiles(
    *,
    app_config: Any,
    tool_a_latest: pd.DataFrame,
    tool_b_latest_by_source: dict[str, pd.DataFrame],
    tool_c_latest: pd.DataFrame,
    tool_d_latest: pd.DataFrame,
    source_run_ids: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Build the per-(ticker, finance_source, metric) percentile artifact (§7).

    Driven entirely by ``app_config.ticker_page.score_builder.metrics``. Tool A /
    Tool C / Tool D metrics are source-independent, but both source variants are
    emitted with identical values so the page's source toggle always finds a
    complete set.
    """

    del source_run_ids  # provenance is stamped by the persistence layer (§5.6)

    catalog = app_config.ticker_page.score_builder.metrics
    tool_a = _indexed(tool_a_latest)
    tool_c = _indexed(tool_c_latest)
    tool_d = _indexed(tool_d_latest)
    tool_b = {
        source: _indexed(tool_b_latest_by_source.get(source))
        for source in FINANCE_SOURCES
    }

    universe = sorted(
        set(tool_a)
        | set(tool_c)
        | set(tool_d)
        | {ticker for source_rows in tool_b.values() for ticker in source_rows}
    )

    rows: list[dict[str, Any]] = []
    for spec in catalog:
        for finance_source in FINANCE_SOURCES:
            if spec.source_tool == "tool_a":
                records = tool_a
            elif spec.source_tool == "tool_c":
                records = tool_c
            elif spec.source_tool == "tool_d":
                records = tool_d
            elif spec.source_tool == "tool_b":
                records = tool_b[finance_source]
            else:  # pragma: no cover - config validator bans other tools
                raise ValueError(f"unknown score metric source_tool: {spec.source_tool}")

            metric_rows: list[dict[str, Any]] = []
            for ticker in universe:
                record = records.get(ticker, {})
                raw_value = optional_float(record.get(spec.source_column))
                available = True
                metric_reason: str | None = None
                rank_eligible = True
                exclusion_reason: str | None = None
                in_pool = True
                forced_pct: tuple[float, float] | None = None

                if not record:
                    available = False
                    metric_reason = "no_source_row"
                elif spec.source_column not in record:
                    available = False
                    metric_reason = "source_column_missing"

                # Trading metrics inherit the shared Finder eligibility semantics.
                if available and spec.category == "trading":
                    if not is_score_eligible(record.get("score_eligible")):
                        available = False
                        metric_reason = "score_ineligible"
                        rank_eligible = False
                        exclusion_reason = "score_ineligible"

                if available and spec.source_tool == "tool_d":
                    status = str(record.get("resilience_data_status") or "").upper()
                    if status != "OK":
                        available = False
                        metric_reason = "resilience_data_not_ok"
                        rank_eligible = False
                        exclusion_reason = "resilience_data_not_ok"

                if available and spec.key == "asymmetry_ratio_core":
                    up_beta = optional_float(record.get("up_beta_core"))
                    down_beta = optional_float(record.get("down_beta_core"))
                    if up_beta is None or down_beta is None:
                        available = False
                        metric_reason = "ratio_undefined_for_beta_signs"
                        rank_eligible = False
                        exclusion_reason = "ratio_undefined_for_beta_signs"
                    elif down_beta > 0 and up_beta > 0:
                        pass  # normal pool member
                    elif down_beta <= 0 and up_beta > 0:
                        # Maximally favourable regime — mirrors model/scoring.py:59-60,
                        # which scores this case 1.0 outright rather than via the ratio.
                        # The row STAYS available and rank-eligible: the ratio itself is
                        # undefined (division by a non-positive down beta), but the
                        # *ranking* is defined and maximal, so the row is ranked top
                        # rather than dropped. It is excluded from the percentile pool
                        # (`in_pool=False`) so its absent raw value cannot distort peers,
                        # and carries a forced 100/0 percentile instead. 100 is the
                        # `rank(pct=True)` ceiling, so the forced value ties (never
                        # exceeds) the best in-pool row — the honest representation of
                        # "at least as favourable as anything in the pool".
                        in_pool = False
                        forced_pct = (100.0, 0.0)
                        metric_reason = "max_favourable_beta_regime"
                    else:
                        available = False
                        metric_reason = "ratio_undefined_for_beta_signs"
                        rank_eligible = False
                        exclusion_reason = "ratio_undefined_for_beta_signs"

                # A max-favourable row legitimately has no finite raw ratio; the
                # generic "no value" downgrade must not undo its availability.
                if available and raw_value is None and forced_pct is None:
                    available = False
                    metric_reason = metric_reason or "value_missing"

                if not available:
                    rank_eligible = False
                    exclusion_reason = exclusion_reason or metric_reason
                    in_pool = False
                    forced_pct = None

                metric_rows.append(
                    {
                        "ticker": ticker,
                        "finance_source": finance_source,
                        "metric_key": spec.key,
                        "category": spec.category,
                        "raw_value": raw_value,
                        "unit": spec.unit,
                        "basis": spec.basis,
                        "source_tool": spec.source_tool,
                        "source_as_of_date": _as_of_text(record),
                        "pct_high_good": None,
                        "pct_low_good": None,
                        "metric_available": bool(available),
                        "metric_reason": metric_reason,
                        "rank_eligible": bool(rank_eligible),
                        "rank_exclusion_reason": exclusion_reason,
                        "eligible_peer_count": 0,
                        "_in_pool": in_pool,
                        "_forced_pct": forced_pct,
                        **_null_provenance(),
                    }
                )

            pool_index = [
                position
                for position, row in enumerate(metric_rows)
                if row["_in_pool"] and row["raw_value"] is not None
            ]
            pool_values = pd.Series(
                [metric_rows[position]["raw_value"] for position in pool_index],
                dtype="float64",
            )
            peer_count = int(len(pool_index))
            if peer_count:
                high = oriented_percentile(pool_values, high_good=True)
                low = oriented_percentile(pool_values, high_good=False)
                for offset, position in enumerate(pool_index):
                    metric_rows[position]["pct_high_good"] = float(high.iloc[offset])
                    metric_rows[position]["pct_low_good"] = float(low.iloc[offset])
            for row in metric_rows:
                row["eligible_peer_count"] = peer_count
                if row["_forced_pct"] is not None:
                    row["pct_high_good"], row["pct_low_good"] = row["_forced_pct"]
                # Invariant: a percentile is a RANK. A row that is not available or
                # not rank-eligible must never carry one — a leaked percentile reads
                # on the page as a real standing against peers.
                if not row["metric_available"] or not row["rank_eligible"]:
                    row["pct_high_good"] = None
                    row["pct_low_good"] = None
                row.pop("_in_pool")
                row.pop("_forced_pct")
            rows.extend(metric_rows)

    return _validated(
        rows,
        columns=PERCENTILES_COLUMNS,
        key_columns=PERCENTILES_KEY_COLUMNS,
        name="ticker_page_percentiles",
        artifact="percentiles",
    )


# ---------------------------------------------------------------------------
# Builder 3 — performance series
# ---------------------------------------------------------------------------


def _usd_series(frame: pd.DataFrame | None, columns: tuple[str, ...]) -> pd.Series:
    """Resolve one history frame to a USD value series indexed by date.

    ONE basis column is chosen for the WHOLE series — the first candidate that
    carries any non-null data — and its nulls are kept as visible gaps. Never a
    per-row coalesce across candidates: the candidates are *different price
    bases* (dividend-adjusted vs unadjusted levels), so splicing them mid-series
    fabricates a step that reads as a real price move and poisons every rebased
    percentage after it. A gap is honest; a spliced level is not.
    """
    if frame is None or frame.empty or "date" not in frame.columns:
        return pd.Series(dtype="float64")
    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce").dt.normalize()
    numeric = pd.Series(float("nan"), index=working.index, dtype="float64")
    for column in columns:
        if column not in working.columns:
            continue
        candidate = pd.to_numeric(working[column], errors="coerce")
        if candidate.notna().any():
            numeric = candidate
            break
    resolved = pd.Series(numeric.to_numpy(), index=working["date"])
    resolved = resolved[resolved.index.notna() & resolved.notna()]
    resolved = resolved[~resolved.index.duplicated(keep="last")]
    return resolved.sort_index()


def _trading_day_lag(last_observation: pd.Timestamp, as_of: pd.Timestamp) -> int:
    """Trading days (Mon-Fri) between ``last_observation`` and ``as_of``.

    The staleness budget is a *market* budget: a Friday close read on Monday is
    one trading day old, not three. Measuring in calendar days made every normal
    weekend look like a 3-day outage and would omit healthy benchmarks. Holidays
    are not modelled (no exchange calendar in this repo), so the count is a
    conservative upper bound on true trading-day lag.
    """

    start = last_observation.normalize().to_numpy().astype("datetime64[D]")
    end = as_of.normalize().to_numpy().astype("datetime64[D]")
    if end <= start:
        return 0
    return int(np.busday_count(start, end))


def build_performance_series(
    *,
    app_config: Any,
    equity_history: pd.DataFrame,
    gold_history: pd.DataFrame,
    benchmark_histories: dict[str, pd.DataFrame],
    ticker: str,
    equity_as_of_date: object,
    series_source_run_ids: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Build the persisted performance chart series for ONE ticker (§4.4)."""

    chart = app_config.ticker_page.chart
    run_ids = dict(series_source_run_ids or {})
    ticker = str(ticker).upper()
    as_of = pd.Timestamp(equity_as_of_date).normalize()

    resolved: dict[str, pd.Series] = {
        "stock": _usd_series(equity_history, ("return_basis_usd", "adj_close_usd")),
        "gold": _usd_series(gold_history, ("adj_close_usd", "close_usd", "close")),
    }
    for name in _BENCHMARK_SERIES:
        history = None
        for key, frame in (benchmark_histories or {}).items():
            if str(key).lower() == name:
                history = frame
                break
        # Benchmark parquets carry `*_local` columns only; GDX/GDXJ are US-listed
        # USD ETFs, so local IS USD — the one normalize boundary for this producer
        # (plan §12 payload-spike producer note).
        resolved[name] = _usd_series(history, ("adj_close_local", "close_local"))

    statuses: dict[str, tuple[str, str | None]] = {}
    for name, series in resolved.items():
        if series.empty:
            statuses[name] = ("MISSING", f"{name} history is unavailable")
            continue
        if name in _BENCHMARK_SERIES:
            lag = _trading_day_lag(series.index[-1], as_of)
            if lag > int(chart.benchmark_max_staleness_days):
                statuses[name] = (
                    "STALE_OMITTED",
                    (
                        f"{name} last observation {series.index[-1].date()} is {lag} "
                        f"trading day(s) behind the equity as-of {as_of.date()} "
                        f"(limit {int(chart.benchmark_max_staleness_days)})"
                    ),
                )
                continue
        statuses[name] = ("OK", None)

    included = [name for name, (status, _) in statuses.items() if status == "OK"]
    rows: list[dict[str, Any]] = []
    if "stock" not in included:
        return _validated(
            rows,
            columns=PERFORMANCE_COLUMNS,
            key_columns=PERFORMANCE_KEY_COLUMNS,
            name="ticker_page_performance",
            artifact="performance",
        )

    # Common ending date = the earliest last-observation among included series.
    common_end = min(resolved[name].index[-1] for name in included)

    for horizon in chart.horizons:
        years = _PERFORMANCE_HORIZON_YEARS[horizon]
        cutoff = common_end - pd.DateOffset(years=years)
        rule = _PERFORMANCE_RESAMPLE_RULE[horizon]

        windowed: dict[str, pd.Series] = {}
        for name in included:
            series = resolved[name]
            series = series[(series.index >= cutoff) & (series.index <= common_end)]
            if rule is not None and not series.empty:
                series = series.resample(rule).last().dropna()
            windowed[name] = series

        live = [name for name in included if not windowed[name].empty]
        if not live or "stock" not in live:
            continue

        grid = sorted({date for name in live for date in windowed[name].index})
        window_start = grid[0]
        rebase_date = max(windowed[name].index[0] for name in live)

        for name in live:
            series = windowed[name]
            base_slice = series[series.index >= rebase_date]
            base_value = float(base_slice.iloc[0]) if not base_slice.empty else None
            late_start = bool(series.index[0] > window_start)
            series_as_of = series.index[-1]
            for date in grid:
                raw = float(series.loc[date]) if date in series.index else None
                rebased = (
                    None
                    if raw is None or base_value in (None, 0)
                    else (raw / base_value) * 100.0
                )
                for view, value in (("price", raw), ("rebased", rebased)):
                    rows.append(
                        {
                            "ticker": ticker,
                            "series": name,
                            "view": view,
                            "horizon": horizon,
                            "date": date,
                            "value": value,
                            "rebase_date": rebase_date,
                            "late_start": late_start,
                            "series_status": "OK",
                            "series_reason": None,
                            "series_as_of_date": series_as_of,
                            "series_source_run_id": run_ids.get(name, "unknown"),
                            "currency_basis": "USD",
                            **_null_provenance(),
                        }
                    )

        # One marker row per (series, view, horizon) for omitted/missing series —
        # never a drawn line, never a silent absence. An OK series with zero
        # observations inside THIS window is the same user-visible situation
        # (the line is absent), so it gets a marker too rather than vanishing.
        markers: list[tuple[str, str, str | None]] = [
            (name, status, reason)
            for name, (status, reason) in statuses.items()
            if status != "OK"
        ]
        markers.extend(
            (name, "MISSING", f"{name} has no observations in the {horizon} window")
            for name in included
            if name not in live
        )
        for name, status, reason in markers:
            series = resolved[name]
            series_as_of = series.index[-1] if not series.empty else as_of
            for view in ("price", "rebased"):
                rows.append(
                    {
                        "ticker": ticker,
                        "series": name,
                        "view": view,
                        "horizon": horizon,
                        "date": as_of,
                        "value": None,
                        "rebase_date": rebase_date,
                        "late_start": False,
                        "series_status": status,
                        "series_reason": reason,
                        "series_as_of_date": series_as_of,
                        "series_source_run_id": run_ids.get(name, "unknown"),
                        "currency_basis": "USD",
                        **_null_provenance(),
                    }
                )

    return _validated(
        rows,
        columns=PERFORMANCE_COLUMNS,
        key_columns=PERFORMANCE_KEY_COLUMNS,
        name="ticker_page_performance",
        artifact="performance",
    )


# ---------------------------------------------------------------------------
# Builder 4 — research series
# ---------------------------------------------------------------------------


def _first_column(record: dict[str, Any], *candidates: str) -> Any:
    for candidate in candidates:
        if candidate in record:
            return record[candidate]
    return None


def build_research_series(
    *,
    ticker: str,
    weekly_series_frame: pd.DataFrame | None,
    exploratory_horizons_frame: pd.DataFrame | None,
    structural_window_metrics_frame: pd.DataFrame | None,
) -> pd.DataFrame:
    """Reshape already-computed Tool A research inputs into the §5.6 schema.

    Pure reshape: nothing is recomputed and nothing is invented — an absent or
    empty input simply contributes no rows of that kind.
    """

    ticker = str(ticker).upper()
    empty = {column: None for column in RESEARCH_SERIES_COLUMNS}
    rows: list[dict[str, Any]] = []

    def _row(kind: str, **values: Any) -> dict[str, Any]:
        return {**empty, "ticker": ticker, "kind": kind, **values, **_null_provenance()}

    if weekly_series_frame is not None and not weekly_series_frame.empty:
        weekly = weekly_series_frame.copy()
        date_column = "as_of_date" if "as_of_date" in weekly.columns else "date"
        if date_column not in weekly.columns:
            # Fail loud on a REQUIRED input: a non-empty weekly frame with no date
            # column silently produced zero weekly rows, which renders as "this
            # ticker has no weekly history" rather than "the input changed shape".
            raise ValueError(
                "weekly_series_frame is non-empty but has neither of the accepted "
                "date columns: as_of_date, date"
            )
        weekly[date_column] = pd.to_datetime(weekly[date_column], errors="coerce")
        weekly = weekly[weekly[date_column].notna()]
        weekly = weekly.sort_values(date_column).drop_duplicates(
            subset=[date_column], keep="last"
        )
        for record in weekly.to_dict(orient="records"):
            rows.append(
                _row(
                    "weekly",
                    date=pd.Timestamp(record[date_column]).normalize(),
                    stock_return=optional_float(
                        _first_column(record, "stock_weekly_log_return", "stock_return")
                    ),
                    gold_return=optional_float(
                        _first_column(record, "gold_weekly_log_return", "gold_return")
                    ),
                    gdx_return=optional_float(
                        _first_column(record, "gdx_weekly_log_return", "gdx_return")
                    ),
                    gdxj_return=optional_float(
                        _first_column(record, "gdxj_weekly_log_return", "gdxj_return")
                    ),
                )
            )

    if exploratory_horizons_frame is not None and not exploratory_horizons_frame.empty:
        horizons = exploratory_horizons_frame.copy()
        if "horizon_id" in horizons.columns:
            horizons = horizons.drop_duplicates(subset=["horizon_id"], keep="last")
            for record in horizons.to_dict(orient="records"):
                label = record.get("horizon_id")
                if label is None or (isinstance(label, float) and math.isnan(label)):
                    continue
                rows.append(
                    _row(
                        "horizon",
                        horizon_label=str(label),
                        horizon_return=optional_float(
                            _first_column(record, "equity_return", "horizon_return")
                        ),
                        basis=str(record.get("horizon_mode") or "equity_return"),
                    )
                )

    if (
        structural_window_metrics_frame is not None
        and not structural_window_metrics_frame.empty
        and "window_id" in structural_window_metrics_frame.columns
    ):
        windows = structural_window_metrics_frame.copy()
        if "as_of_date" in windows.columns:
            windows["as_of_date"] = pd.to_datetime(windows["as_of_date"], errors="coerce")
            windows = windows.sort_values("as_of_date")
        windows = windows.drop_duplicates(subset=["window_id"], keep="last")
        for record in windows.to_dict(orient="records"):
            # A week count is a COUNT — emit it as a nullable integer, not a
            # float that renders "104.0" on the page.
            weeks_value = optional_float(_first_column(record, "week_count", "weeks"))
            weeks = None if weeks_value is None else int(round(weeks_value))
            rows.append(
                _row(
                    "window_fit",
                    window=str(record["window_id"]),
                    up_beta=optional_float(record.get("up_beta")),
                    down_beta=optional_float(record.get("down_beta")),
                    r_squared=optional_float(record.get("r_squared")),
                    weeks=weeks,
                    window_status=(
                        None
                        if record.get("window_status") is None
                        else str(record.get("window_status"))
                    ),
                )
            )

    frame = apply_expected_dtypes(
        pd.DataFrame(rows, columns=list(RESEARCH_SERIES_COLUMNS)),
        artifact="research_series",
    )
    violations = validate_frame_schema(
        frame,
        columns=RESEARCH_SERIES_COLUMNS,
        key_columns=("ticker", "kind"),
    )
    # Uniqueness is per row-kind (§5.6), not on (ticker, kind).
    violations = [note for note in violations if not note.startswith("duplicate keys")]
    for kind, kind_keys in RESEARCH_SERIES_KIND_KEY_COLUMNS.items():
        subset = frame[frame["kind"] == kind]
        if subset.empty:
            continue
        violations.extend(
            f"[kind={kind}] {note}"
            for note in validate_frame_schema(
                subset, columns=RESEARCH_SERIES_COLUMNS, key_columns=kind_keys
            )
        )
    if violations:
        raise ValueError(
            "ticker_page_research_series does not satisfy its contract: " + "; ".join(violations)
        )
    return frame
