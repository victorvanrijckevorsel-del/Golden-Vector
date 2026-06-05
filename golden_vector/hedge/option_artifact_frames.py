"""Convert option artifact builder results to persisted DataFrames."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from typing import Any

import pandas as pd

from golden_vector.contracts.option_artifacts import OPTION_ARTIFACT_SCHEMA_VERSION
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_artifact_builder import OptionArtifactBuildResult
from golden_vector.hedge.option_availability import has_usable_option_slots
from golden_vector.hedge.option_trading import (
    OptionLiquidityMeasurement,
    OptionTradingRow,
)
from golden_vector.hedge.options_liquidity import OptionContractMetrics


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
) -> dict[str, pd.DataFrame]:
    """Return all persisted option artifact frames for one option-artifact run."""

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
        "option_trading_overview": _overview_frame(built.overview.rows),
        "candidate_finder_inputs": _candidate_finder_inputs_frame(
            options_features=options_features,
            put_slots=built.candidate_slots,
            call_slots=built.call_candidate_slots,
        ),
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


def _candidate_finder_inputs_frame(
    *,
    options_features: pd.DataFrame,
    put_slots: dict[str, list[OptionCandidateSlot]],
    call_slots: dict[str, list[OptionCandidateSlot]],
) -> pd.DataFrame:
    if options_features.empty:
        base = pd.DataFrame({"ticker": pd.Series(dtype="object")})
    else:
        base = options_features.copy()
    if "ticker" not in base.columns:
        base["ticker"] = pd.Series(dtype="object")
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    base["has_usable_put_candidate"] = base["ticker"].map(
        lambda ticker: has_usable_option_slots(put_slots.get(str(ticker), []))
    )
    base["has_usable_call_candidate"] = base["ticker"].map(
        lambda ticker: has_usable_option_slots(call_slots.get(str(ticker), []))
    )
    return base


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
    return result
