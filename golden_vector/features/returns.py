"""Compute horizon returns from USD-normalized equity data and gold prices."""

from __future__ import annotations


import numpy as np
import pandas as pd

from golden_vector.common.eligibility import ok_normalized_rows

from golden_vector.features.horizons import ParsedHorizon


RETURN_COLUMNS = [
    "ticker",
    "as_of_date",
    "horizon_id",
    "horizon_mode",
    "horizon_unit",
    "horizon_value",
    "start_date",
    "end_date",
    "equity_return",
    "gold_return",
    "gold_delta",
    "coverage_flag",
    "coverage_reason",
    "official_scoring_eligible",
]


def compute_horizon_returns_for_ticker(
    usd_equity_history: pd.DataFrame,
    gold_history: pd.DataFrame,
    horizons: list[ParsedHorizon],
    *,
    near_zero_gold_return_threshold: float,
) -> pd.DataFrame:
    if usd_equity_history.empty or gold_history.empty:
        return pd.DataFrame(columns=RETURN_COLUMNS)

    overlap = _build_overlap_frame(usd_equity_history, gold_history)
    if overlap.empty:
        return pd.DataFrame(columns=RETURN_COLUMNS)

    ticker = str(overlap["ticker"].iloc[0])
    date_index = pd.DatetimeIndex(overlap["date"])
    horizon_frames: list[pd.DataFrame] = []
    for horizon_order, horizon in enumerate(horizons):
        horizon_frames.append(
            _compute_horizon_frame(
                overlap=overlap,
                ticker=ticker,
                date_index=date_index,
                horizon=horizon,
                near_zero_gold_return_threshold=near_zero_gold_return_threshold,
                horizon_order=horizon_order,
            )
        )

    materialized = [frame for frame in horizon_frames if not frame.empty]
    if not materialized:
        return pd.DataFrame(columns=RETURN_COLUMNS)

    result = pd.concat(materialized, ignore_index=True)
    result = result.sort_values(
        ["as_of_date", "_horizon_order"],
        kind="stable",
    ).drop(columns=["_horizon_order"])
    return result[RETURN_COLUMNS].reset_index(drop=True)


def _build_overlap_frame(
    usd_equity_history: pd.DataFrame,
    gold_history: pd.DataFrame,
) -> pd.DataFrame:
    # C4: stale/invalid normalized rows must never become horizon returns.
    equity = ok_normalized_rows(usd_equity_history).copy()
    equity["date"] = pd.to_datetime(equity["date"])
    equity = equity.rename(columns={"return_basis_usd": "equity_basis_usd"})

    gold = gold_history.copy()
    gold["date"] = pd.to_datetime(gold["date"])
    gold["gold_basis_usd"] = gold["adj_close_usd"].where(
        gold["adj_close_usd"].notna(),
        gold["close_usd"],
    )

    overlap = equity.merge(
        gold[["date", "gold_basis_usd"]],
        how="inner",
        on="date",
    )
    overlap = overlap.sort_values("date").reset_index(drop=True)
    return overlap


def _compute_horizon_frame(
    *,
    overlap: pd.DataFrame,
    ticker: str,
    date_index: pd.DatetimeIndex,
    horizon: ParsedHorizon,
    near_zero_gold_return_threshold: float,
    horizon_order: int,
) -> pd.DataFrame:
    row_count = len(date_index)
    if row_count == 0:
        return pd.DataFrame(columns=RETURN_COLUMNS + ["_horizon_order"])

    start_positions = _resolve_start_positions(date_index, horizon)
    end_positions = np.arange(row_count, dtype=np.int64)

    equity_basis = pd.to_numeric(overlap["equity_basis_usd"], errors="coerce").to_numpy(dtype=float)
    gold_basis = pd.to_numeric(overlap["gold_basis_usd"], errors="coerce").to_numpy(dtype=float)

    equity_return = np.full(row_count, np.nan, dtype=float)
    gold_return = np.full(row_count, np.nan, dtype=float)
    gold_delta = np.full(row_count, np.nan, dtype=float)
    coverage_flag = np.full(row_count, "FAIL", dtype=object)
    coverage_reason = np.full(row_count, "INSUFFICIENT_HISTORY", dtype=object)
    official_scoring_eligible = np.zeros(row_count, dtype=bool)

    valid_history_mask = start_positions >= 0
    if valid_history_mask.any():
        valid_indices = end_positions[valid_history_mask]
        start_indices = start_positions[valid_history_mask]

        equity_start = equity_basis[start_indices]
        equity_end = equity_basis[valid_indices]
        gold_start = gold_basis[start_indices]
        gold_end = gold_basis[valid_indices]

        basis_available_mask = _positive_numeric_mask(equity_start)
        basis_available_mask &= _positive_numeric_mask(equity_end)
        basis_available_mask &= _positive_numeric_mask(gold_start)
        basis_available_mask &= _positive_numeric_mask(gold_end)

        missing_basis_indices = valid_indices[~basis_available_mask]
        coverage_reason[missing_basis_indices] = "MISSING_RETURN_BASIS"

        ready_indices = valid_indices[basis_available_mask]
        ready_start_indices = start_indices[basis_available_mask]
        if len(ready_indices) > 0:
            ready_equity_return = (equity_basis[ready_indices] / equity_basis[ready_start_indices]) - 1.0
            ready_gold_return = (gold_basis[ready_indices] / gold_basis[ready_start_indices]) - 1.0

            equity_return[ready_indices] = ready_equity_return
            gold_return[ready_indices] = ready_gold_return
            coverage_flag[ready_indices] = "PASS"
            coverage_reason[ready_indices] = "OK"
            if horizon.mode == "core":
                official_scoring_eligible[ready_indices] = True

            near_zero_mask = np.abs(ready_gold_return) < near_zero_gold_return_threshold
            near_zero_indices = ready_indices[near_zero_mask]
            if len(near_zero_indices) > 0:
                coverage_reason[near_zero_indices] = "NEAR_ZERO_GOLD_RETURN"
                official_scoring_eligible[near_zero_indices] = False

            delta_indices = ready_indices[~near_zero_mask]
            if len(delta_indices) > 0:
                gold_delta[delta_indices] = (
                    equity_return[delta_indices] / gold_return[delta_indices]
                )

    start_dates = np.empty(row_count, dtype=object)
    start_dates[:] = None
    valid_start_indices = np.where(start_positions >= 0)[0]
    for index in valid_start_indices.tolist():
        start_dates[index] = date_index[start_positions[index]].date()

    return pd.DataFrame(
        {
            "ticker": ticker,
            "as_of_date": date_index.date,
            "horizon_id": horizon.horizon_id,
            "horizon_mode": horizon.mode,
            "horizon_unit": horizon.unit,
            "horizon_value": horizon.value,
            "start_date": start_dates,
            "end_date": date_index.date,
            "equity_return": equity_return,
            "gold_return": gold_return,
            "gold_delta": gold_delta,
            "coverage_flag": coverage_flag,
            "coverage_reason": coverage_reason,
            "official_scoring_eligible": official_scoring_eligible,
            "_horizon_order": horizon_order,
        }
    )


def _resolve_start_positions(
    date_index: pd.DatetimeIndex,
    horizon: ParsedHorizon,
) -> np.ndarray:
    if horizon.unit == "D":
        positions = np.arange(len(date_index), dtype=np.int64) - horizon.value
        positions[positions < 0] = -1
        return positions

    offset = (
        pd.DateOffset(months=horizon.value)
        if horizon.unit == "M"
        else pd.DateOffset(years=horizon.value)
    )
    target_dates = pd.DatetimeIndex(date_index - offset)
    positions = date_index.searchsorted(target_dates, side="right") - 1
    positions = positions.astype(np.int64, copy=False)
    positions[positions < 0] = -1
    return positions




def _positive_numeric_mask(values: np.ndarray) -> np.ndarray:
    return np.isfinite(values) & (values > 0)
