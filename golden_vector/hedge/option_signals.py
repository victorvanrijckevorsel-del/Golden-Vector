"""Refresh-time option-chain signal artifacts.

This module turns the cached option-chain snapshot into transparent signal
lanes. It is intentionally outside ``serve``: request handlers should read the
persisted artifacts, not recompute option analytics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.common.strings import normalize_ticker
from golden_vector.contracts.config_models import (
    SIGNAL_AREA_DTE_MAX as _SIGNAL_AREA_DTE_MAX,
    SIGNAL_AREA_DTE_MIN as _SIGNAL_AREA_DTE_MIN,
    AppConfig,
    UniverseTicker,
)
from golden_vector.hedge._helpers import as_float, row_float, rows_by_ticker_series
from golden_vector.hedge.options_liquidity import OptionContractMetrics

# Shared with the config validator (signal band must overlap this window).
SIGNAL_AREA_DTE_MIN = _SIGNAL_AREA_DTE_MIN
SIGNAL_AREA_DTE_MAX = _SIGNAL_AREA_DTE_MAX
SIGNAL_AREA_DELTA_MIN = 0.10
SIGNAL_AREA_DELTA_MAX = 0.35
DELTA_BUCKETS: tuple[float, ...] = (0.10, 0.25, 0.35)
ACTIVITY_DOMINANCE_MULTIPLE = 1.5
HISTORY_FILE_NAME = "option_signal_history.parquet"
SKEW_CURVE_POINT_COLUMNS: tuple[str, ...] = (
    "ticker",
    "series_ticker",
    "series_role",
    "horizon_days",
    "delta_bucket",
    "moneyness_bucket",
    "side",
    "iv",
    "liquidity_flag",
    "quote_flags",
)
OI_STRIKE_POINT_COLUMNS: tuple[str, ...] = (
    "ticker",
    "strike",
    "side",
    "open_interest",
    "volume",
    "is_spot",
    "days_to_expiry",
    "expiration",
    "liquidity_flag",
    "quote_flags",
)
# Long-form history (Milestone C2): one row per (ticker, as_of_date, horizon).
# The old wide 60d/90d columns are backfilled on load so stored history and
# the IV-rank series survive the migration.
LONG_HISTORY_COLUMNS: tuple[str, ...] = (
    "ticker",
    "as_of_date",
    "quote_snapshot_run_id",
    "benchmark_symbol",
    "signal_horizon_days",
    "skew_residual",
    "atm_iv",
    "iv_rv_ratio",
)
SIGNAL_HISTORY_POINT_COLUMNS: tuple[str, ...] = (
    "ticker",
    "as_of_date",
    "signal_horizon_days",
    "skew_residual",
    "atm_iv",
    "iv_rank",
    "iv_rv_ratio",
)


class _OptionSignalPaths(Protocol):
    output_options_dir: Path


@dataclass(frozen=True)
class OptionSignalArtifacts:
    summary: pd.DataFrame
    skew_curve_points: pd.DataFrame
    oi_strike_points: pd.DataFrame
    history_points: pd.DataFrame
    next_history: pd.DataFrame
    publish_blockers: tuple[str, ...] = ()


def option_signal_history_path(paths: _OptionSignalPaths) -> Path:
    return paths.output_options_dir / HISTORY_FILE_NAME


def build_option_signal_artifacts(
    *,
    app_config: AppConfig,
    options_features: pd.DataFrame,
    contract_metrics: tuple[OptionContractMetrics, ...],
    manifest: dict[str, Any],
    prior_history: pd.DataFrame | None = None,
    prior_contract_metrics: pd.DataFrame | None = None,
) -> OptionSignalArtifacts:
    """Build all option-signal frames from refresh-time inputs."""

    features_by_ticker = rows_by_ticker_series(options_features, strip=True)
    metrics_by_ticker = _metrics_by_ticker(contract_metrics)
    history = _normalize_history(prior_history)
    prior_metrics_by_contract = _prior_metrics_by_contract(prior_contract_metrics)
    benchmark_by_ticker = _benchmark_map(app_config)
    summary_rows: list[dict[str, Any]] = []
    current_history_rows: list[dict[str, Any]] = []

    for ticker in sorted(features_by_ticker):
        feature = features_by_ticker[ticker]
        metrics = metrics_by_ticker.get(ticker, ())
        benchmark_symbol = benchmark_by_ticker.get(ticker, "GDX")
        row = _summary_row(
            ticker=ticker,
            feature=feature,
            metrics=metrics,
            features_by_ticker=features_by_ticker,
            benchmark_symbol=benchmark_symbol,
            history=history,
            prior_metrics_by_contract=prior_metrics_by_contract,
            app_config=app_config,
            manifest=manifest,
        )
        summary_rows.append(row)
        if row.get("data_quality_label") == "OK":
            current_history_rows.extend(
                _history_rows(
                    row=row,
                    feature=feature,
                    horizons=tuple(app_config.hedge_readiness.display_horizons_days),
                )
            )

    summary = pd.DataFrame(summary_rows)
    next_history = _append_history(
        history,
        pd.DataFrame(current_history_rows),
    )
    history_points = _history_points_frame(next_history)
    publish_blockers = _publish_blockers(summary, app_config=app_config)
    return OptionSignalArtifacts(
        summary=summary,
        skew_curve_points=_skew_curve_points_frame(
            metrics_by_ticker=metrics_by_ticker,
            app_config=app_config,
        ),
        oi_strike_points=_oi_strike_points_frame(
            metrics_by_ticker,
            app_config=app_config,
        ),
        history_points=history_points,
        next_history=next_history,
        publish_blockers=tuple(publish_blockers),
    )


def load_option_signal_history(paths: _OptionSignalPaths) -> pd.DataFrame:
    # This file is the ONLY copy of the accumulated IV-rank input series.
    # A missing file is a legitimate empty start; an EXISTING file that
    # cannot be read must fail loud - read_optional_parquet would return
    # empty and the next persist would silently wipe the whole history.
    path = option_signal_history_path(paths)
    if not path.exists():
        return _normalize_history(pd.DataFrame())
    frame = pd.read_parquet(path)
    return _normalize_history(frame)


def prepare_option_signal_history(
    *,
    paths: _OptionSignalPaths,
    history: pd.DataFrame,
) -> tuple[Path, pd.DataFrame]:
    """Run the shrink guard and normalize the next history WITHOUT writing it.

    Returns ``(target_path, normalized_frame)`` so the actual write can be STAGED
    inside an atomic group swap (history + the option latest aliases publish as one
    transaction). Raises if the new history would shrink the accumulated distinct
    as-of dates, so the guard fires before any live file is touched.
    """
    path = option_signal_history_path(paths)
    normalized = _normalize_history(history)
    # Shrink guard: the cumulative history may only grow in as-of dates.
    # Refusing a shrinking write turns any silent-wipe bug upstream into a
    # loud error instead of irreversible data loss.
    if path.exists():
        existing_dates = _distinct_as_of_dates(pd.read_parquet(path))
        next_dates = _distinct_as_of_dates(normalized)
        if next_dates < existing_dates:
            raise ValueError(
                "Refusing to overwrite option signal history: new history has "
                f"{next_dates} distinct as-of dates, file on disk has "
                f"{existing_dates}. This would destroy accumulated IV history."
            )
    return path, normalized


def persist_option_signal_history(
    *,
    paths: _OptionSignalPaths,
    history: pd.DataFrame,
) -> None:
    path, normalized = prepare_option_signal_history(paths=paths, history=history)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_parquet_atomic(normalized, path, index=False)


def _distinct_as_of_dates(frame: pd.DataFrame) -> int:
    if frame.empty or "as_of_date" not in frame.columns:
        return 0
    return int(frame["as_of_date"].astype(str).nunique())


def _summary_row(
    *,
    ticker: str,
    feature: pd.Series,
    metrics: tuple[OptionContractMetrics, ...],
    features_by_ticker: dict[str, pd.Series],
    benchmark_symbol: str,
    history: pd.DataFrame,
    prior_metrics_by_contract: dict[tuple[str, str, str, float], dict[str, float]],
    app_config: AppConfig,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    signal_metrics = _signal_area_metrics(metrics, app_config=app_config)
    raw_coverage = _quote_coverage(metrics)
    signal_coverage = _quote_coverage(signal_metrics)
    signal_horizon = int(app_config.hedge_readiness.option_signal_horizon_days)
    display_horizons = tuple(app_config.hedge_readiness.display_horizons_days)
    history_for_ticker = _history_for_ticker(
        history,
        ticker,
        signal_horizon_days=signal_horizon,
    )
    # Depth counts USABLE observations (non-null ATM IV) — the same series
    # IV-rank consumes. Backfilled 90d rows carry no ATM IV, so counting raw
    # rows would skip LIMITED_HISTORY while IV-rank still returns None
    # (audit M1; plan Decision 2 promised calm LIMITED_HISTORY).
    if "atm_iv" in history_for_ticker.columns:
        history_depth = int(
            pd.to_numeric(history_for_ticker["atm_iv"], errors="coerce").notna().sum()
        )
    else:
        history_depth = 0
    min_history = int(app_config.hedge_readiness.option_signal_history_min_samples)
    atm_iv_signal = row_float(feature, f"atm_iv_{signal_horizon}d")
    iv_rv_ratio_signal = row_float(feature, f"iv_rv_ratio_{signal_horizon}d")
    iv_rank = _iv_rank(
        current=atm_iv_signal,
        history_for_ticker=history_for_ticker,
        min_samples=min_history,
    )
    benchmark_feature = features_by_ticker.get(benchmark_symbol)
    is_benchmark = ticker == benchmark_symbol
    benchmark_available = is_benchmark or benchmark_feature is not None
    name_skews = {
        horizon: row_float(feature, f"iv_skew_{horizon}d")
        for horizon in display_horizons
    }
    sector_skews = {
        horizon: (
            name_skews[horizon]
            if is_benchmark
            else (
                row_float(benchmark_feature, f"iv_skew_{horizon}d")
                if benchmark_feature is not None
                else None
            )
        )
        for horizon in display_horizons
    }
    residuals = {
        horizon: _difference(name_skews[horizon], sector_skews[horizon])
        for horizon in display_horizons
    }
    direction_value = (
        name_skews.get(signal_horizon) if is_benchmark else residuals.get(signal_horizon)
    )
    direction_candidate = _direction_candidate(
        direction_value,
        threshold=app_config.hedge_readiness.option_signal_skew_residual_threshold,
    )
    activity = _activity_metrics(
        ticker=ticker,
        metrics=signal_metrics,
        prior_metrics_by_contract=prior_metrics_by_contract,
        app_config=app_config,
        direction_candidate=direction_candidate,
    )
    direction_label = _confirmed_direction_label(
        direction_candidate,
        activity_label=str(activity["activity_label"]),
    )
    data_quality = _data_quality_label(
        benchmark_available=benchmark_available,
        signal_contract_count=len(signal_metrics),
        signal_area_quote_coverage=signal_coverage,
        tradable_signal_count=sum(
            1 for metric in signal_metrics if metric.liquidity_tier == "tradable"
        ),
        app_config=app_config,
    )
    cost_label = _cost_label(
        iv_rv_ratio=iv_rv_ratio_signal,
        iv_rank=iv_rank,
        history_depth=history_depth,
        min_history=min_history,
    )
    row: dict[str, Any] = {
        "ticker": ticker,
        "benchmark_symbol": benchmark_symbol,
        "as_of_date": str(manifest.get("as_of_date") or ""),
        "signal_horizon_days": signal_horizon,
        "headline": _headline(
            ticker=ticker,
            benchmark_symbol=benchmark_symbol,
            direction_label=direction_label,
            direction_candidate=direction_candidate,
            residual=residuals.get(signal_horizon),
            name_skew=name_skews.get(signal_horizon),
            sector_skew=sector_skews.get(signal_horizon),
            activity_label=activity["activity_label"],
            iv_rv_ratio=iv_rv_ratio_signal,
            data_quality_label=data_quality,
            is_benchmark=is_benchmark,
        ),
        "direction_label": direction_label,
        "direction_candidate_label": direction_candidate,
        "direction_reason": _direction_reason(
            direction_label=direction_label,
            direction_candidate=direction_candidate,
            residual=residuals.get(signal_horizon),
            name_skew=name_skews.get(signal_horizon),
            benchmark_symbol=benchmark_symbol,
            is_benchmark=is_benchmark,
        ),
        "activity_label": activity["activity_label"],
        "activity_reason": activity["activity_reason"],
        "cost_label": cost_label,
        "cost_reason": _cost_reason(
            cost_label=cost_label,
            iv_rv_ratio=iv_rv_ratio_signal,
            iv_rank=iv_rank,
            history_depth=history_depth,
            min_history=min_history,
        ),
        "data_quality_label": data_quality,
        "data_quality_reason": _data_quality_reason(
            data_quality_label=data_quality,
            signal_area_quote_coverage=signal_coverage,
            signal_contract_count=len(signal_metrics),
            benchmark_symbol=benchmark_symbol,
        ),
        "iv_rv_ratio": iv_rv_ratio_signal,
        "atm_iv_signal": atm_iv_signal,
        "iv_rank": iv_rank,
        "history_depth": history_depth,
        "signal_area_quote_coverage": signal_coverage,
        "raw_chain_quote_coverage": raw_coverage,
        "signal_area_contract_count": len(signal_metrics),
        "raw_chain_contract_count": len(metrics),
        "liquidity_tier": _signal_liquidity_tier(signal_metrics),
        "freshness_status": "STALE_QUOTES" if data_quality == "STALE_QUOTES" else "CURRENT",
        "oi_change_valid": bool(activity["oi_change_valid"]),
        "oi_change_put": activity["oi_change_put"],
        "oi_change_call": activity["oi_change_call"],
        "volume_to_oi_put": activity["volume_to_oi_put"],
        "volume_to_oi_call": activity["volume_to_oi_call"],
        "quote_snapshot_run_id": str(manifest.get("refresh_run_id") or ""),
        "option_vehicle_type": str(feature.get("option_vehicle_type") or "single_stock"),
    }
    for horizon in display_horizons:
        row[f"name_skew_{horizon}d"] = name_skews[horizon]
        row[f"sector_skew_{horizon}d"] = sector_skews[horizon]
        row[f"skew_residual_{horizon}d"] = residuals[horizon]
    return row


def _history_rows(
    *,
    row: dict[str, Any],
    feature: pd.Series,
    horizons: tuple[int, ...],
) -> list[dict[str, Any]]:
    """Long-form history rows: one per horizon with a usable observation."""

    rows: list[dict[str, Any]] = []
    for horizon in horizons:
        skew_residual = row.get(f"skew_residual_{horizon}d")
        atm_iv = row_float(feature, f"atm_iv_{horizon}d")
        iv_rv_ratio = row_float(feature, f"iv_rv_ratio_{horizon}d")
        if skew_residual is None and atm_iv is None and iv_rv_ratio is None:
            continue
        rows.append(
            {
                "ticker": row.get("ticker"),
                "as_of_date": row.get("as_of_date"),
                "quote_snapshot_run_id": row.get("quote_snapshot_run_id"),
                "benchmark_symbol": row.get("benchmark_symbol"),
                "signal_horizon_days": int(horizon),
                "skew_residual": skew_residual,
                "atm_iv": atm_iv,
                "iv_rv_ratio": iv_rv_ratio,
            }
        )
    return rows


def _metrics_by_ticker(
    metrics: tuple[OptionContractMetrics, ...],
) -> dict[str, tuple[OptionContractMetrics, ...]]:
    grouped: dict[str, list[OptionContractMetrics]] = {}
    for metric in metrics:
        grouped.setdefault(metric.ticker.upper(), []).append(metric)
    return {ticker: tuple(items) for ticker, items in grouped.items()}


def _benchmark_map(app_config: AppConfig) -> dict[str, str]:
    result: dict[str, str] = {}
    benchmarks = {
        str(ticker).upper()
        for ticker in app_config.hedge_readiness.benchmark_tickers
    }
    for ticker_config in app_config.universe.tickers:
        ticker = ticker_config.ticker.upper()
        if ticker in benchmarks:
            result[ticker] = ticker
            continue
        explicit = _explicit_benchmark(ticker_config, benchmarks=benchmarks)
        result[ticker] = explicit or _default_benchmark(ticker_config, benchmarks=benchmarks)
    for benchmark in benchmarks:
        result.setdefault(benchmark, benchmark)
    return result


def _explicit_benchmark(
    ticker_config: UniverseTicker,
    *,
    benchmarks: set[str],
) -> str | None:
    value = normalize_ticker(getattr(ticker_config, "option_benchmark_symbol", None))
    if value and value in benchmarks:
        return value
    return None


def _default_benchmark(
    ticker_config: UniverseTicker,
    *,
    benchmarks: set[str],
) -> str:
    ticker = ticker_config.ticker.upper()
    exchange = str(ticker_config.exchange or "").upper()
    if "GDXJ" in benchmarks and (ticker.endswith(".V") or exchange in {"TSXV", "TSX-V"}):
        return "GDXJ"
    return "GDX" if "GDX" in benchmarks else sorted(benchmarks)[0]


def _signal_quality_metrics(
    metrics: tuple[OptionContractMetrics, ...],
    *,
    app_config: AppConfig,
) -> tuple[OptionContractMetrics, ...]:
    """Delta/IV sanity filter WITHOUT the signal-area DTE clamp.

    The chart frames use this per configured horizon band — long-dated bands
    (230/550) sit wholly outside the 45-150 signal area, so clamping there
    would make their chart artifacts structurally empty (pre-ship audit H1).
    """

    min_iv = float(app_config.hedge_readiness.candidate_min_implied_volatility)
    max_iv = float(app_config.hedge_readiness.candidate_max_implied_volatility)
    result = []
    for metric in metrics:
        if metric.underlying_price <= 0:
            continue
        if metric.implied_volatility is None or not (min_iv <= metric.implied_volatility <= max_iv):
            continue
        if metric.delta is None:
            continue
        abs_delta = abs(float(metric.delta))
        if not (SIGNAL_AREA_DELTA_MIN <= abs_delta <= SIGNAL_AREA_DELTA_MAX):
            continue
        result.append(metric)
    return tuple(result)


def _signal_area_metrics(
    metrics: tuple[OptionContractMetrics, ...],
    *,
    app_config: AppConfig,
) -> tuple[OptionContractMetrics, ...]:
    """Signal-area contracts: quality filter PLUS the 45-150 DTE window.

    Drives the published Signal/Activity/Quality lanes only — never the
    per-horizon chart frames.
    """

    return tuple(
        metric
        for metric in _signal_quality_metrics(metrics, app_config=app_config)
        if SIGNAL_AREA_DTE_MIN <= metric.days_to_expiry <= SIGNAL_AREA_DTE_MAX
    )


def _quote_coverage(metrics: tuple[OptionContractMetrics, ...]) -> float | None:
    if not metrics:
        return None
    usable = sum(
        1
        for metric in metrics
        if metric.bid is not None
        and metric.ask is not None
        and metric.mid is not None
        and metric.bid > 0
        and metric.ask > 0
        and metric.mid > 0
    )
    return usable / len(metrics)


def _data_quality_label(
    *,
    benchmark_available: bool,
    signal_contract_count: int,
    signal_area_quote_coverage: float | None,
    tradable_signal_count: int,
    app_config: AppConfig,
) -> str:
    if not benchmark_available:
        return "NO_BENCHMARK"
    if signal_contract_count < int(app_config.hedge_readiness.option_signal_area_min_contracts):
        return "SPARSE"
    coverage = signal_area_quote_coverage
    if coverage is not None and coverage < float(app_config.hedge_readiness.option_signal_quote_coverage_min):
        return "STALE_QUOTES"
    if tradable_signal_count == 0:
        return "LOW_LIQUIDITY"
    return "OK"


def _data_quality_reason(
    *,
    data_quality_label: str,
    signal_area_quote_coverage: float | None,
    signal_contract_count: int,
    benchmark_symbol: str,
) -> str:
    coverage = "-" if signal_area_quote_coverage is None else f"{signal_area_quote_coverage:.0%}"
    if data_quality_label == "OK":
        return f"Signal-area quote coverage is {coverage}."
    if data_quality_label == "NO_BENCHMARK":
        return f"The benchmark chain for {benchmark_symbol} is missing, so residual skew is unavailable."
    if data_quality_label == "STALE_QUOTES":
        return f"Only {coverage} of signal-area contracts have two-sided quotes."
    if data_quality_label == "LOW_LIQUIDITY":
        return "Signal-area contracts exist, but none pass the tradable liquidity tier."
    return f"Only {signal_contract_count} signal-area contracts are available."


def _direction_candidate(value: float | None, *, threshold: float) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value >= threshold:
        return "DOWNSIDE"
    if value <= -threshold:
        return "UPSIDE"
    return "NEUTRAL"


def _confirmed_direction_label(direction_candidate: str, *, activity_label: str) -> str:
    """Apply the asymmetric evidence bar for equity option signals.

    Sector-relative residual skew removes the broad market downside bias, but
    a bullish call-rich read is still less common and easier to overstate from
    quotes alone. Keep DOWNSIDE as a skew read; require a call-side volume pulse
    before publishing UPSIDE as the headline label.
    """

    if direction_candidate == "UPSIDE" and activity_label != "UPSIDE_VOLUME_PULSE":
        return "NEUTRAL"
    return direction_candidate


def _direction_reason(
    *,
    direction_label: str,
    direction_candidate: str,
    residual: float | None,
    name_skew: float | None,
    benchmark_symbol: str,
    is_benchmark: bool,
) -> str:
    if is_benchmark:
        if name_skew is None:
            return "Sector 25-delta skew is unavailable."
        points = name_skew * 100.0
        if direction_label == "DOWNSIDE":
            return (
                f"{benchmark_symbol} sector puts are {points:.1f} vol pts richer "
                "than calls; residual vs itself is 0.0 vol pts."
            )
        if direction_label == "UPSIDE":
            return (
                f"{benchmark_symbol} sector calls are {-points:.1f} vol pts richer "
                "than puts; residual vs itself is 0.0 vol pts."
            )
        if direction_candidate == "UPSIDE":
            return (
                f"{benchmark_symbol} sector calls are {-points:.1f} vol pts richer "
                "than puts, but an upside read requires a call-side volume pulse."
            )
        return f"{benchmark_symbol} sector skew is close to neutral ({points:.1f} vol pts)."
    if residual is None:
        return "Sector-relative 25-delta skew is unavailable."
    points = residual * 100.0
    if direction_label == "DOWNSIDE":
        return f"Downside puts are {points:.1f} vol pts richer than {benchmark_symbol}."
    if direction_label == "UPSIDE":
        return f"Calls are {-points:.1f} vol pts richer than the {benchmark_symbol} reference."
    if direction_candidate == "UPSIDE":
        return (
            f"Calls are {-points:.1f} vol pts richer than the {benchmark_symbol} reference, "
            "but an upside read requires a call-side volume pulse."
        )
    return f"Sector-relative skew is close to neutral ({points:.1f} vol pts)."


def _activity_metrics(
    *,
    ticker: str,
    metrics: tuple[OptionContractMetrics, ...],
    prior_metrics_by_contract: dict[tuple[str, str, str, float], dict[str, float]],
    app_config: AppConfig,
    direction_candidate: str,
) -> dict[str, Any]:
    put_volume, put_oi = _side_volume_oi(metrics, "P")
    call_volume, call_oi = _side_volume_oi(metrics, "C")
    put_ratio = _safe_ratio(put_volume, put_oi)
    call_ratio = _safe_ratio(call_volume, call_oi)
    oi_change_put, put_valid = _side_oi_change(
        ticker=ticker,
        option_type="P",
        metrics=metrics,
        prior_metrics_by_contract=prior_metrics_by_contract,
    )
    oi_change_call, call_valid = _side_oi_change(
        ticker=ticker,
        option_type="C",
        metrics=metrics,
        prior_metrics_by_contract=prior_metrics_by_contract,
    )
    # This lane reads VOLUME relative to open interest (a "volume pulse"), not an
    # actual open-interest build. High volume can be closing trades or churn, so it
    # is deliberately NOT called "confirmation" of new positioning (audit H5).
    min_ratio = float(app_config.hedge_readiness.option_signal_activity_volume_to_oi_min)
    label = "QUIET"
    reason = "No side shows a signal-area volume pulse (volume high versus open interest)."
    if direction_candidate == "DOWNSIDE" and put_ratio is not None:
        if put_ratio >= min_ratio and put_ratio >= ACTIVITY_DOMINANCE_MULTIPLE * (call_ratio or 0.0):
            label = "DOWNSIDE_VOLUME_PULSE"
            reason = (
                f"Put volume is {put_ratio:.0%} of open interest in the signal area "
                "(a volume pulse, not confirmed new positioning)."
            )
    elif direction_candidate == "UPSIDE":
        label = "NO_UPSIDE_VOLUME_PULSE"
        if call_ratio is None:
            reason = "Upside skew needs a call-side volume pulse, but call open interest is unavailable."
        elif call_ratio < min_ratio:
            reason = (
                "Upside skew needs a call-side volume pulse; "
                f"call volume is only {call_ratio:.0%} of open interest in the signal area."
            )
        elif call_ratio < ACTIVITY_DOMINANCE_MULTIPLE * (put_ratio or 0.0):
            reason = (
                "Upside skew needs a call-side volume pulse; "
                "call volume is not dominant versus put volume."
            )
        else:
            label = "UPSIDE_VOLUME_PULSE"
            reason = (
                f"Call volume is {call_ratio:.0%} of open interest in the signal area "
                "(a volume pulse, not confirmed new positioning)."
            )
    if direction_candidate == "UNAVAILABLE":
        label = "N/A"
        reason = "Activity is not interpreted without a valid direction lane."
    return {
        "activity_label": label,
        "activity_reason": reason,
        "volume_to_oi_put": put_ratio,
        "volume_to_oi_call": call_ratio,
        "oi_change_put": oi_change_put,
        "oi_change_call": oi_change_call,
        "oi_change_valid": put_valid or call_valid,
    }


def _side_volume_oi(
    metrics: tuple[OptionContractMetrics, ...],
    option_type: str,
) -> tuple[float, float]:
    filtered = [metric for metric in metrics if metric.option_type == option_type]
    return (
        float(sum(metric.volume for metric in filtered)),
        float(sum(metric.open_interest for metric in filtered)),
    )


def _side_oi_change(
    *,
    ticker: str,
    option_type: str,
    metrics: tuple[OptionContractMetrics, ...],
    prior_metrics_by_contract: dict[tuple[str, str, str, float], dict[str, float]],
) -> tuple[float | None, bool]:
    if not prior_metrics_by_contract:
        return None, False
    change = 0.0
    matched = 0
    for metric in metrics:
        if metric.option_type != option_type:
            continue
        prior = prior_metrics_by_contract.get(
            (ticker.upper(), option_type, metric.expiration, float(metric.strike))
        )
        if prior is None:
            continue
        previous_oi = as_float(prior.get("open_interest"))
        if previous_oi is None:
            continue
        change += float(metric.open_interest) - previous_oi
        matched += 1
    return (change, True) if matched else (None, False)


def _cost_label(
    *,
    iv_rv_ratio: float | None,
    iv_rank: float | None,
    history_depth: int,
    min_history: int,
) -> str:
    if history_depth < min_history:
        return "LIMITED_HISTORY"
    if iv_rank is not None:
        if iv_rank >= 75.0:
            return "RICH"
        if iv_rank <= 25.0:
            return "CHEAP"
    if iv_rv_ratio is not None:
        if iv_rv_ratio >= 1.30:
            return "RICH"
        if iv_rv_ratio <= 0.80:
            return "CHEAP"
    return "NORMAL"


def _cost_reason(
    *,
    cost_label: str,
    iv_rv_ratio: float | None,
    iv_rank: float | None,
    history_depth: int,
    min_history: int,
) -> str:
    ratio_text = "-" if iv_rv_ratio is None else f"{iv_rv_ratio:.2f}x realized"
    if cost_label == "LIMITED_HISTORY":
        return f"Only {history_depth}/{min_history} clean snapshots; IV/RV is {ratio_text}."
    rank_text = "-" if iv_rank is None else f"{iv_rank:.0f}th percentile"
    return f"IV/RV is {ratio_text}; own-history IV rank is {rank_text}."


def _headline(
    *,
    ticker: str,
    benchmark_symbol: str,
    direction_label: str,
    direction_candidate: str,
    residual: float | None,
    name_skew: float | None,
    sector_skew: float | None,
    activity_label: str,
    iv_rv_ratio: float | None,
    data_quality_label: str,
    is_benchmark: bool,
) -> str:
    if data_quality_label != "OK":
        return f"{ticker}: option signal unavailable ({data_quality_label.replace('_', ' ').lower()})."
    skew_text = "-" if name_skew is None else f"{name_skew * 100:.1f} vol pts absolute"
    ratio_text = "-" if iv_rv_ratio is None else f"IV {iv_rv_ratio:.2f}x realized"
    direction_text = (
        "unconfirmed upside"
        if direction_candidate == "UPSIDE" and direction_label == "NEUTRAL"
        else direction_label.lower()
    )
    if is_benchmark:
        return (
            f"{ticker}: {direction_text} sector skew "
            f"({skew_text}; residual vs itself 0.0 vol pts); "
            f"{activity_label.lower().replace('_', ' ')}; {ratio_text}."
        )
    residual_text = "-" if residual is None else f"{residual * 100:.1f} vol pts vs {benchmark_symbol}"
    sector_text = "-" if sector_skew is None else f"{sector_skew * 100:.1f} sector"
    return (
        f"{ticker}: {direction_text} skew ({residual_text}; "
        f"{skew_text}, {sector_text}); {activity_label.lower().replace('_', ' ')}; {ratio_text}."
    )


def _signal_liquidity_tier(metrics: tuple[OptionContractMetrics, ...]) -> str:
    if any(metric.liquidity_tier == "tradable" for metric in metrics):
        return "tradable"
    if any(metric.liquidity_tier == "watch" for metric in metrics):
        return "watch"
    return "none"


def _iv_rank(
    *,
    current: float | None,
    history_for_ticker: pd.DataFrame,
    min_samples: int,
) -> float | None:
    if current is None or len(history_for_ticker.index) < min_samples:
        return None
    values = pd.to_numeric(history_for_ticker.get("atm_iv"), errors="coerce").dropna()
    if len(values.index) < min_samples:
        return None
    return float((values <= current).sum() / len(values.index) * 100.0)


def _history_for_ticker(
    history: pd.DataFrame,
    ticker: str,
    *,
    signal_horizon_days: int,
) -> pd.DataFrame:
    if history.empty or "ticker" not in history.columns:
        return pd.DataFrame()
    mask = history["ticker"].astype(str).str.upper() == ticker.upper()
    if "signal_horizon_days" in history.columns:
        horizons = pd.to_numeric(history["signal_horizon_days"], errors="coerce")
        mask = mask & (horizons == int(signal_horizon_days))
    return history[mask].copy()


def _normalize_history(frame: pd.DataFrame | None) -> pd.DataFrame:
    columns = list(LONG_HISTORY_COLUMNS)
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    result = frame.copy()
    if "skew_residual_60d" in result.columns and "signal_horizon_days" not in result.columns:
        result = _backfill_legacy_history(result)
    for column in columns:
        if column not in result.columns:
            result[column] = None
    result["ticker"] = result["ticker"].map(normalize_ticker)
    result["signal_horizon_days"] = pd.to_numeric(
        result["signal_horizon_days"], errors="coerce"
    )
    result = result.dropna(subset=["ticker", "signal_horizon_days"])
    result["signal_horizon_days"] = result["signal_horizon_days"].astype(int)
    return result[columns].reset_index(drop=True)


def _backfill_legacy_history(frame: pd.DataFrame) -> pd.DataFrame:
    """One-time logical migration of the wide 60d/90d history to long form.

    The stored IV-rank series must survive: every legacy row becomes a 60d
    long row (skew residual + ATM IV + IV/RV) and, when present, a 90d row
    (skew residual only — the wide format never stored 90d ATM IV).
    """

    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        base = {
            "ticker": record.get("ticker"),
            "as_of_date": record.get("as_of_date"),
            "quote_snapshot_run_id": record.get("quote_snapshot_run_id"),
            "benchmark_symbol": record.get("benchmark_symbol"),
        }
        rows.append(
            {
                **base,
                "signal_horizon_days": 60,
                # as_float is NaN-safe; to_dict() yields float('nan') for
                # missing values and `nan is not None` is True (audit H2).
                "skew_residual": as_float(record.get("skew_residual_60d")),
                "atm_iv": as_float(record.get("atm_iv_60d")),
                "iv_rv_ratio": as_float(record.get("iv_rv_ratio")),
            }
        )
        residual_90d = as_float(record.get("skew_residual_90d"))
        if residual_90d is not None:
            rows.append(
                {
                    **base,
                    "signal_horizon_days": 90,
                    "skew_residual": residual_90d,
                    "atm_iv": None,
                    "iv_rv_ratio": None,
                }
            )
    return pd.DataFrame(rows, columns=list(LONG_HISTORY_COLUMNS))


def _append_history(history: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    if current.empty:
        return history.copy()
    result = pd.concat([history, current], ignore_index=True)
    return (
        result.drop_duplicates(
            subset=["ticker", "as_of_date", "signal_horizon_days"],
            keep="last",
        )
        .sort_values(["ticker", "as_of_date", "signal_horizon_days"])
        .reset_index(drop=True)
    )


def _history_points_frame(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=SIGNAL_HISTORY_POINT_COLUMNS)
    result = history.copy()
    result["iv_rank"] = None
    return result[list(SIGNAL_HISTORY_POINT_COLUMNS)]


def _skew_curve_points_frame(
    *,
    metrics_by_ticker: dict[str, tuple[OptionContractMetrics, ...]],
    app_config: AppConfig,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    horizons = tuple(app_config.hedge_readiness.display_horizons_days)
    for ticker, metrics in sorted(metrics_by_ticker.items()):
        # Quality filter only — the per-horizon config band does the DTE
        # scoping. Routing through the 45-150 signal area here would leave
        # every long-dated horizon permanently empty (audit H1).
        quality_metrics = _signal_quality_metrics(metrics, app_config=app_config)
        for horizon in horizons:
            lower, upper = _horizon_band(horizon, app_config)
            horizon_metrics = [
                metric for metric in quality_metrics if lower <= metric.days_to_expiry <= upper
            ]
            for option_type in ("P", "C"):
                side_metrics = [metric for metric in horizon_metrics if metric.option_type == option_type]
                for bucket in DELTA_BUCKETS:
                    selected = _nearest_delta_metric(side_metrics, bucket)
                    rows.append(
                        {
                            "ticker": ticker,
                            "series_ticker": ticker,
                            "series_role": "name",
                            "horizon_days": horizon,
                            "delta_bucket": bucket,
                            "moneyness_bucket": None if selected is None else selected.otm_pct,
                            "side": option_type,
                            "iv": None if selected is None else selected.implied_volatility,
                            "liquidity_flag": _chart_liquidity_flag(selected),
                            "quote_flags": "" if selected is None else "|".join(selected.quote_flags),
                        }
                    )
    return pd.DataFrame(rows, columns=SKEW_CURVE_POINT_COLUMNS)


def _oi_strike_points_frame(
    metrics_by_ticker: dict[str, tuple[OptionContractMetrics, ...]],
    *,
    app_config: AppConfig,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    bands = [
        _horizon_band(horizon, app_config)
        for horizon in app_config.hedge_readiness.display_horizons_days
    ]
    for ticker, metrics in sorted(metrics_by_ticker.items()):
        for metric in _signal_quality_metrics(metrics, app_config=app_config):
            # Cover every configured horizon band, not the 45-150 signal
            # area — long-dated open interest must be visible (audit H1).
            if not any(lower <= metric.days_to_expiry <= upper for lower, upper in bands):
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "strike": metric.strike,
                    "side": metric.option_type,
                    "open_interest": metric.open_interest,
                    "volume": metric.volume,
                    "is_spot": False,
                    "days_to_expiry": metric.days_to_expiry,
                    "expiration": metric.expiration,
                    "liquidity_flag": _chart_liquidity_flag(metric),
                    "quote_flags": "|".join(metric.quote_flags),
                }
            )
    return pd.DataFrame(rows, columns=OI_STRIKE_POINT_COLUMNS)


def _chart_liquidity_flag(metric: OptionContractMetrics | None) -> str:
    if metric is None:
        return "missing"
    if "unusable_iv" in metric.quote_flags:
        return "unusable_iv"
    if "lottery_like" in metric.quote_flags:
        return "lottery_like"
    if "extreme_iv" in metric.quote_flags:
        return "extreme_iv"
    return metric.liquidity_tier


def _horizon_band(horizon: int, app_config: AppConfig) -> tuple[int, int]:
    raw = app_config.hedge_readiness.option_dte_bands.get(horizon)
    if raw and len(raw) >= 2:
        return int(raw[0]), int(raw[1])
    return horizon, horizon


def _nearest_delta_metric(
    metrics: list[OptionContractMetrics],
    target_abs_delta: float,
) -> OptionContractMetrics | None:
    with_delta = [metric for metric in metrics if metric.delta is not None]
    if not with_delta:
        return None
    return sorted(
        with_delta,
        key=lambda metric: (
            abs(abs(float(metric.delta or 0.0)) - target_abs_delta),
            metric.rel_spread is None,
            metric.rel_spread or 999.0,
            -metric.open_interest,
        ),
    )[0]


def _publish_blockers(summary: pd.DataFrame, *, app_config: AppConfig) -> list[str]:
    benchmark_tickers = {
        str(ticker).upper()
        for ticker in app_config.hedge_readiness.benchmark_tickers
    }
    if not benchmark_tickers:
        return []
    if summary.empty or "ticker" not in summary.columns or "data_quality_label" not in summary.columns:
        return [
            "Option signal benchmark rows are missing; keeping the previous complete model state."
        ]
    ticker_series = summary["ticker"].astype(str).str.upper()
    present = {ticker for ticker in ticker_series if ticker in benchmark_tickers}
    missing = sorted(benchmark_tickers.difference(present))
    benchmark_rows = summary[
        ticker_series.isin(benchmark_tickers)
        | (summary.get("option_vehicle_type", pd.Series(index=summary.index)).astype(str) == "benchmark_etf")
    ]
    invalid = benchmark_rows[
        benchmark_rows["data_quality_label"].astype(str).str.upper() != "OK"
    ]
    if not missing and invalid.empty:
        return []
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    for record in invalid.head(8).to_dict(orient="records"):
        details.append(
            f"{str(record.get('ticker') or '').upper()}={record.get('data_quality_label')}"
        )
    if len(invalid.index) > 8:
        details.append(f"+{len(invalid.index) - 8} more")
    return [
        "Option signal benchmark rows are not publishable ("
        + "; ".join(details)
        + "); keeping the previous complete model state."
    ]


def _prior_metrics_by_contract(
    frame: pd.DataFrame | None,
) -> dict[tuple[str, str, str, float], dict[str, float]]:
    if frame is None or frame.empty:
        return {}
    required = {"ticker", "option_type", "expiration", "strike"}
    if not required.issubset(frame.columns):
        return {}
    result: dict[tuple[str, str, str, float], dict[str, float]] = {}
    for record in frame.to_dict(orient="records"):
        ticker = normalize_ticker(record.get("ticker"))
        option_type = str(record.get("option_type") or "").upper()
        expiration = str(record.get("expiration") or "")
        strike = as_float(record.get("strike"))
        if not ticker or option_type not in {"P", "C"} or not expiration or strike is None:
            continue
        result[(ticker, option_type, expiration, float(strike))] = {
            "open_interest": as_float(record.get("open_interest")) or 0.0,
        }
    return result


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator
