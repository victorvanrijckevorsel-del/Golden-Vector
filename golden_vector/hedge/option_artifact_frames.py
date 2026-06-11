"""Convert option artifact builder results to persisted DataFrames."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from typing import Any, Literal, cast

import pandas as pd

from golden_vector.common.strings import normalize_ticker_series
from golden_vector.contracts.option_artifacts import OPTION_ARTIFACT_SCHEMA_VERSION
from golden_vector.hedge.candidate_puts import (
    CandidateSlotStatus,
    OptionCandidate,
    OptionCandidateSlot,
)
from golden_vector.features.options_chain import as_int
from golden_vector.hedge._helpers import as_float
from golden_vector.hedge.option_artifact_builder import OptionArtifactBuildResult
from golden_vector.hedge.option_availability import has_usable_option_slots
from golden_vector.hedge.option_trading import (
    OptionLiquidityMeasurement,
    OptionTradingRow,
    SideStatus,
)
from golden_vector.hedge.options_liquidity import OptionContractMetrics
from golden_vector.hedge.option_horizon_selection import (
    MostLiquidSelection,
    select_group_default_window,
    select_ticker_default_window,
)
from golden_vector.hedge.option_signals import OptionSignalArtifacts

CANDIDATE_FINDER_OPTION_COLUMNS: tuple[str, ...] = (
    "ticker",
    "as_of_date",
    "run_id",
    "optionability_tier",
    "iv_percentile_cross_sectional",
    # Signal-horizon fields (C2): name_iv_skew_signal is the name's own
    # put-minus-call skew; skew_residual_signal is benchmark-relative — the
    # number the Option Trading UI shows and what Bull/Bear presets score on.
    # The horizon travels in signal_horizon_days, never in column names.
    "name_iv_skew_signal",
    "iv_rv_ratio_signal",
    "skew_residual_signal",
    "benchmark_symbol",
    "signal_horizon_days",
    "options_fetch_status",
    "options_fetch_message",
    "underlying_price",
    "option_vehicle_type",
    "options_source_symbol",
)


def build_option_artifact_frames(
    *,
    built: OptionArtifactBuildResult,
    contract_metrics: tuple[OptionContractMetrics, ...],
    options_features: pd.DataFrame,
    manifest: dict[str, Any],
    source_run_id: str,
    parent_refresh_id: str | None,
    config_hash: str | None,
    risk_free_rate: float,
    risk_free_rate_is_fallback: bool,
    option_signals: OptionSignalArtifacts | None = None,
    dte_bands: dict[int, tuple[int, int]] | None = None,
    benchmark_tickers: tuple[str, ...] = (),
) -> dict[str, pd.DataFrame]:
    """Return all persisted option artifact frames for one option-artifact run."""

    signals = option_signals or _empty_option_signal_artifacts()
    overview_frame = _overview_frame(built.overview.rows)
    if dte_bands:
        overview_frame = _stamp_most_liquid_defaults(
            overview_frame,
            contract_metrics=contract_metrics,
            dte_bands=dte_bands,
            benchmark_tickers=benchmark_tickers,
        )
    frames = {
        "option_contract_metrics": _contract_metrics_frame(contract_metrics),
        "option_liquidity_measurements": _liquidity_measurements_frame(
            built.overview.liquidity_measurements
        ),
        "option_candidate_slots": _candidate_slots_frame(
            built.candidate_slots,
            built.call_candidate_slots,
        ),
        "option_selected_candidates": _selected_candidates_frame(
            built.candidate_grids,
            built.call_candidate_grids,
        ),
        "option_trading_overview": overview_frame,
        "candidate_finder_inputs": _candidate_finder_inputs_frame(
            options_features=options_features,
            put_slots=built.candidate_slots,
            call_slots=built.call_candidate_slots,
            signal_summary=signals.summary,
        ),
        "option_signal_summary": signals.summary,
        "option_skew_curve_points": signals.skew_curve_points,
        "option_oi_strike_points": signals.oi_strike_points,
        "option_signal_history_points": signals.history_points,
    }
    return {
        name: _stamp_frame(
            frame,
            manifest=manifest,
            source_run_id=source_run_id,
            parent_refresh_id=parent_refresh_id,
            config_hash=config_hash,
            risk_free_rate=risk_free_rate,
            risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        )
        for name, frame in frames.items()
    }


def selected_candidate_grids_from_frame(
    frame: pd.DataFrame,
) -> tuple[dict[str, list[OptionCandidate]], dict[str, list[OptionCandidate]]]:
    """Rebuild put/call candidate grids from the selected-candidates artifact."""

    put_candidates: dict[str, list[OptionCandidate]] = {}
    call_candidates: dict[str, list[OptionCandidate]] = {}
    for record in _records(frame):
        candidate = _candidate_from_record(record)
        if candidate is None:
            continue
        side = str(record.get("option_side") or "").lower()
        target = (
            call_candidates
            if side == "call" or candidate.option_type == "C"
            else put_candidates
        )
        target.setdefault(candidate.ticker, []).append(candidate)
    return put_candidates, call_candidates


def candidate_slots_from_frame(
    frame: pd.DataFrame,
) -> tuple[dict[str, list[OptionCandidateSlot]], dict[str, list[OptionCandidateSlot]]]:
    """Rebuild put/call slot maps from the candidate-slots artifact."""

    put_slots: dict[str, list[OptionCandidateSlot]] = {}
    call_slots: dict[str, list[OptionCandidateSlot]] = {}
    for record in _records(frame):
        slot = _slot_from_record(record)
        if slot is None:
            continue
        target = call_slots if slot.option_type == "C" else put_slots
        target.setdefault(slot.ticker, []).append(slot)
    return put_slots, call_slots


def liquidity_measurements_from_frame(
    frame: pd.DataFrame,
) -> tuple[OptionLiquidityMeasurement, ...]:
    """Rebuild liquidity measurement dataclasses from the persisted artifact."""

    measurements: list[OptionLiquidityMeasurement] = []
    for record in _records(frame):
        group_label = _optional_str(record.get("group_label"))
        if not group_label:
            continue
        measurements.append(
            OptionLiquidityMeasurement(
                group_label=group_label,
                ticker_count=_optional_int(record.get("ticker_count")) or 0,
                contract_count=_optional_int(record.get("contract_count")) or 0,
                median_rel_spread=as_float(record.get("median_rel_spread")),
                median_open_interest=as_float(record.get("median_open_interest")),
                median_volume=as_float(record.get("median_volume")),
                median_near_spot_depth=as_float(record.get("median_near_spot_depth")),
                tradable_count=_optional_int(record.get("tradable_count")) or 0,
                watch_count=_optional_int(record.get("watch_count")) or 0,
                no_trade_count=_optional_int(record.get("no_trade_count")) or 0,
            )
        )
    return tuple(measurements)


def overview_rows_from_frame(frame: pd.DataFrame) -> tuple[OptionTradingRow, ...]:
    """Rebuild Option Trading overview rows from the persisted artifact."""

    rows: list[OptionTradingRow] = []
    for record in _records(frame):
        ticker = _optional_str(record.get("ticker"))
        if not ticker:
            continue
        rows.append(
            OptionTradingRow(
                ticker=ticker,
                structural_delta_core=as_float(record.get("structural_delta_core")),
                down_beta_core=as_float(record.get("down_beta_core")),
                up_beta_core=as_float(record.get("up_beta_core")),
                confidence_label=_optional_str(record.get("confidence_label")) or "n/a",
                confidence_score=as_float(record.get("confidence_score")),
                iv_percentile_cross_sectional=as_float(
                    record.get("iv_percentile_cross_sectional")
                ),
                iv_skew_signal=as_float(record.get("iv_skew_signal")),
                iv_rv_ratio_signal=as_float(record.get("iv_rv_ratio_signal")),
                optionability_tier=_optional_str(record.get("optionability_tier")) or "none",
                put_status=_side_status(record.get("put_status")),
                call_status=_side_status(record.get("call_status")),
                pnl_put_at_context=as_float(record.get("pnl_put_at_context")),
                pnl_call_at_context=as_float(record.get("pnl_call_at_context")),
                notes=_tuple_value(record.get("notes")),
                current_stock_price=as_float(record.get("current_stock_price")),
                option_vehicle_type=_optional_str(record.get("option_vehicle_type"))
                or "single_stock",
                signal_horizon_days=_optional_int(record.get("signal_horizon_days")),
                context_horizon_days=_optional_int(record.get("context_horizon_days")),
                most_liquid_put_horizon_days=_optional_int(
                    record.get("most_liquid_put_horizon_days")
                ),
                most_liquid_put_expiration=_optional_str(
                    record.get("most_liquid_put_expiration")
                ),
                most_liquid_call_horizon_days=_optional_int(
                    record.get("most_liquid_call_horizon_days")
                ),
                most_liquid_call_expiration=_optional_str(
                    record.get("most_liquid_call_expiration")
                ),
            )
        )
    return tuple(rows)


def _contract_metrics_frame(
    metrics: tuple[OptionContractMetrics, ...],
) -> pd.DataFrame:
    return pd.DataFrame([_dataclass_row(metric) for metric in metrics])


def _liquidity_measurements_frame(
    measurements: tuple[OptionLiquidityMeasurement, ...],
) -> pd.DataFrame:
    return pd.DataFrame([_dataclass_row(measurement) for measurement in measurements])


def _candidate_slots_frame(
    put_slots: dict[str, list[OptionCandidateSlot]],
    call_slots: dict[str, list[OptionCandidateSlot]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for slots in (put_slots, call_slots):
        for ticker_slots in slots.values():
            rows.extend(_candidate_slot_row(slot) for slot in ticker_slots)
    return pd.DataFrame(rows)


def _selected_candidates_frame(
    put_candidates: dict[str, list[OptionCandidate]],
    call_candidates: dict[str, list[OptionCandidate]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for side, candidates_by_ticker in (("put", put_candidates), ("call", call_candidates)):
        for candidates in candidates_by_ticker.values():
            for candidate in candidates:
                row = _dataclass_row(candidate)
                row["option_side"] = side
                rows.append(row)
    return pd.DataFrame(rows)


def _overview_frame(rows: tuple[OptionTradingRow, ...]) -> pd.DataFrame:
    return pd.DataFrame([_dataclass_row(row) for row in rows])


def _stamp_most_liquid_defaults(
    overview_frame: pd.DataFrame,
    *,
    contract_metrics: tuple[OptionContractMetrics, ...],
    dte_bands: dict[int, tuple[int, int]],
    benchmark_tickers: tuple[str, ...],
) -> pd.DataFrame:
    """Stamp backend-selected most-liquid defaults onto the overview artifact.

    Milestone C3: the "Most liquid" defaults are chosen at build time and
    persisted — serve only reads them (C4 renders the switcher from these
    columns). Per-ticker defaults are side-aware; the group default is a
    per-ticker vote over single-stock miners.
    """

    if overview_frame.empty or "ticker" not in overview_frame.columns:
        return overview_frame
    result = overview_frame.copy()
    tickers = [str(ticker).upper() for ticker in result["ticker"]]
    per_side: dict[str, dict[str, MostLiquidSelection | None]] = {"P": {}, "C": {}}
    for side in ("P", "C"):
        for ticker in tickers:
            per_side[side][ticker] = select_ticker_default_window(
                metrics=contract_metrics,
                ticker=ticker,
                side=side,  # type: ignore[arg-type]
                dte_bands=dte_bands,
            )
    for side, prefix in (("P", "put"), ("C", "call")):
        result[f"most_liquid_{prefix}_horizon_days"] = [
            selection.horizon_days if (selection := per_side[side][ticker]) else None
            for ticker in tickers
        ]
        result[f"most_liquid_{prefix}_expiration"] = [
            selection.expiration if (selection := per_side[side][ticker]) else None
            for ticker in tickers
        ]
        result[f"group_default_{prefix}_horizon_days"] = select_group_default_window(
            metrics=contract_metrics,
            tickers=tickers,
            side=side,  # type: ignore[arg-type]
            dte_bands=dte_bands,
            exclude_tickers=benchmark_tickers,
        )
    return result


def _candidate_finder_inputs_frame(
    *,
    options_features: pd.DataFrame,
    put_slots: dict[str, list[OptionCandidateSlot]],
    call_slots: dict[str, list[OptionCandidateSlot]],
    signal_summary: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if options_features.empty:
        base = pd.DataFrame({"ticker": pd.Series(dtype="object")})
    else:
        base = options_features.copy()
    if "ticker" not in base.columns:
        base["ticker"] = pd.Series(dtype="object")
    signal_horizon = _summary_signal_horizon(signal_summary)
    if signal_horizon is not None:
        name_skew_column = f"iv_skew_{signal_horizon}d"
        iv_rv_column = f"iv_rv_ratio_{signal_horizon}d"
        if name_skew_column in base.columns:
            base["name_iv_skew_signal"] = base[name_skew_column]
        if iv_rv_column in base.columns:
            base["iv_rv_ratio_signal"] = base[iv_rv_column]
        base["signal_horizon_days"] = signal_horizon
    if signal_summary is not None and not signal_summary.empty:
        residual_column = (
            f"skew_residual_{signal_horizon}d" if signal_horizon is not None else None
        )
        join_columns = ["ticker", "benchmark_symbol"]
        if residual_column and residual_column in signal_summary.columns:
            join_columns.append(residual_column)
        summary_slice = signal_summary.loc[
            :, [column for column in join_columns if column in signal_summary.columns]
        ].copy()
        if residual_column in summary_slice.columns:
            summary_slice = summary_slice.rename(
                columns={residual_column: "skew_residual_signal"}
            )
        summary_slice["ticker"] = normalize_ticker_series(summary_slice["ticker"])
        base["ticker"] = normalize_ticker_series(base["ticker"])
        base = base.merge(summary_slice, on="ticker", how="left", suffixes=("", "_summary"))
    for column in CANDIDATE_FINDER_OPTION_COLUMNS:
        if column not in base.columns:
            base[column] = pd.NA
    base = base.loc[:, list(CANDIDATE_FINDER_OPTION_COLUMNS)].copy()
    base["ticker"] = normalize_ticker_series(base["ticker"])
    base["has_usable_put_candidate"] = base["ticker"].map(
        lambda ticker: has_usable_option_slots(put_slots.get(str(ticker), []))
    )
    base["has_usable_call_candidate"] = base["ticker"].map(
        lambda ticker: has_usable_option_slots(call_slots.get(str(ticker), []))
    )
    return base


def _summary_signal_horizon(signal_summary: pd.DataFrame | None) -> int | None:
    if signal_summary is None or signal_summary.empty:
        return None
    if "signal_horizon_days" not in signal_summary.columns:
        return None
    values = pd.to_numeric(
        signal_summary["signal_horizon_days"], errors="coerce"
    ).dropna()
    return int(values.iloc[0]) if not values.empty else None


def _candidate_slot_row(slot: OptionCandidateSlot) -> dict[str, Any]:
    row = {
        key: value
        for key, value in _dataclass_row(slot).items()
        if key not in {"candidate", "rejected_candidate"}
    }
    row["candidate_present"] = slot.candidate is not None
    row["rejected_candidate_present"] = slot.rejected_candidate is not None
    row.update(_prefixed_dataclass_row(slot.candidate, "candidate_"))
    row.update(_prefixed_dataclass_row(slot.rejected_candidate, "rejected_candidate_"))
    return row


def _prefixed_dataclass_row(value: object | None, prefix: str) -> dict[str, Any]:
    if value is None:
        return {}
    return {f"{prefix}{key}": item for key, item in _dataclass_row(value).items()}


def _dataclass_row(value: object) -> dict[str, Any]:
    if not is_dataclass(value):
        raise TypeError(f"Expected dataclass value, got {type(value).__name__}")
    return {
        field.name: _serialize_value(getattr(value, field.name))
        for field in fields(value)
    }


def _serialize_value(value: object) -> object:
    if isinstance(value, tuple):
        return json.dumps(list(value))
    return value


def _stamp_frame(
    frame: pd.DataFrame,
    *,
    manifest: dict[str, Any],
    source_run_id: str,
    parent_refresh_id: str | None,
    config_hash: str | None,
    risk_free_rate: float,
    risk_free_rate_is_fallback: bool,
) -> pd.DataFrame:
    result = frame.copy()
    result["schema_version"] = OPTION_ARTIFACT_SCHEMA_VERSION
    result["snapshot_refresh_run_id"] = str(manifest.get("refresh_run_id") or "")
    result["options_as_of_date"] = str(manifest.get("as_of_date") or "")
    result["source_run_id"] = source_run_id
    result["parent_refresh_id"] = parent_refresh_id
    result["config_hash"] = config_hash
    result["risk_free_rate"] = float(risk_free_rate)
    result["risk_free_rate_is_fallback"] = bool(risk_free_rate_is_fallback)
    result.attrs["schema_version"] = OPTION_ARTIFACT_SCHEMA_VERSION
    result.attrs["snapshot_refresh_run_id"] = str(manifest.get("refresh_run_id") or "")
    result.attrs["source_run_id"] = source_run_id
    result.attrs["parent_refresh_id"] = parent_refresh_id
    result.attrs["config_hash"] = config_hash
    return result


def _empty_option_signal_artifacts() -> OptionSignalArtifacts:
    return OptionSignalArtifacts(
        summary=pd.DataFrame(),
        skew_curve_points=pd.DataFrame(),
        oi_strike_points=pd.DataFrame(),
        history_points=pd.DataFrame(),
        next_history=pd.DataFrame(),
    )


def _slot_from_record(record: dict[str, Any]) -> OptionCandidateSlot | None:
    ticker = _optional_str(record.get("ticker"))
    option_type = _option_type(record.get("option_type"))
    horizon_days = _optional_int(record.get("horizon_days"))
    target_delta = as_float(record.get("target_delta"))
    status = _slot_status(record.get("status"))
    if (
        not ticker
        or option_type is None
        or horizon_days is None
        or target_delta is None
        or status is None
    ):
        return None
    return OptionCandidateSlot(
        ticker=ticker,
        option_type=option_type,
        horizon_days=horizon_days,
        target_delta=target_delta,
        expiration=_optional_str(record.get("expiration")),
        days_to_expiry=_optional_int(record.get("days_to_expiry")),
        status=status,
        reason=_optional_str(record.get("reason")) or "",
        candidate=_candidate_from_record(record, prefix="candidate_"),
        rejected_candidate=_candidate_from_record(record, prefix="rejected_candidate_"),
        listed_contract_count=_optional_int(record.get("listed_contract_count")) or 0,
        tradable_contract_count=_optional_int(record.get("tradable_contract_count")) or 0,
        bucket=_optional_str(record.get("bucket")),
        liquidity_tier=_optional_str(record.get("liquidity_tier")),
    )


def _candidate_from_record(
    record: dict[str, Any],
    *,
    prefix: str = "",
) -> OptionCandidate | None:
    ticker = _optional_str(record.get(f"{prefix}ticker"))
    option_type = _option_type(record.get(f"{prefix}option_type"))
    horizon_days = _optional_int(record.get(f"{prefix}horizon_days"))
    expiration = _optional_str(record.get(f"{prefix}expiration"))
    days_to_expiry = _optional_int(record.get(f"{prefix}days_to_expiry"))
    strike = as_float(record.get(f"{prefix}strike"))
    underlying_price = as_float(record.get(f"{prefix}underlying_price"))
    if (
        not ticker
        or option_type is None
        or horizon_days is None
        or not expiration
        or days_to_expiry is None
        or strike is None
        or underlying_price is None
    ):
        return None
    return OptionCandidate(
        ticker=ticker,
        horizon_days=horizon_days,
        expiration=expiration,
        days_to_expiry=days_to_expiry,
        strike=strike,
        bid=as_float(record.get(f"{prefix}bid")),
        ask=as_float(record.get(f"{prefix}ask")),
        mid=as_float(record.get(f"{prefix}mid")),
        open_interest=_optional_int(record.get(f"{prefix}open_interest")),
        volume=_optional_int(record.get(f"{prefix}volume")),
        implied_volatility=as_float(record.get(f"{prefix}implied_volatility")),
        delta=as_float(record.get(f"{prefix}delta")),
        delta_gap=as_float(record.get(f"{prefix}delta_gap")),
        premium_pct_spot=as_float(record.get(f"{prefix}premium_pct_spot")),
        underlying_price=underlying_price,
        last_price=as_float(record.get(f"{prefix}last_price")),
        option_type=option_type,
        bucket=_optional_str(record.get(f"{prefix}bucket")),
        liquidity_tier=_optional_str(record.get(f"{prefix}liquidity_tier")),
        rel_spread=as_float(record.get(f"{prefix}rel_spread")),
        half_spread_cost_pct=as_float(record.get(f"{prefix}half_spread_cost_pct")),
        liquidity_score=as_float(record.get(f"{prefix}liquidity_score")),
        moneyness_pct=as_float(record.get(f"{prefix}moneyness_pct")),
        otm_pct=as_float(record.get(f"{prefix}otm_pct")),
        quote_flags=_tuple_value(record.get(f"{prefix}quote_flags")),
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return list(frame.to_dict(orient="records"))


def _optional_str(value: object) -> str | None:
    if _is_missing(value):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _optional_int(value: object) -> int | None:
    return as_int(value)


def _option_type(value: object) -> Literal["P", "C"] | None:
    raw = _optional_str(value)
    if raw in {"P", "C"}:
        return cast(Literal["P", "C"], raw)
    return None


def _side_status(value: object) -> SideStatus:
    raw = _optional_str(value)
    if raw in {"tradable", "watch", "none"}:
        return cast(SideStatus, raw)
    return "none"


def _slot_status(value: object) -> CandidateSlotStatus | None:
    raw = _optional_str(value)
    if raw in {
        "accepted",
        "rejected",
        "no_chain",
        "no_price",
        "no_expiration",
        "no_contracts",
        "no_tradable",
        "no_delta",
    }:
        return cast(CandidateSlotStatus, raw)
    return None


def _tuple_value(value: object) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
