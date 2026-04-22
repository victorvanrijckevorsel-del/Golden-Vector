"""Compute horizon returns from USD-normalized equity data and gold prices."""

from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.features.horizons import ParsedHorizon, resolve_horizon_start_date


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
    rows: list[dict[str, object]] = []

    for as_of_date in overlap["date"].tolist():
        for horizon in horizons:
            rows.append(
                _compute_row(
                    overlap=overlap,
                    ticker=ticker,
                    as_of_date=as_of_date,
                    horizon=horizon,
                    near_zero_gold_return_threshold=near_zero_gold_return_threshold,
                )
            )

    return pd.DataFrame(rows, columns=RETURN_COLUMNS)


def _build_overlap_frame(
    usd_equity_history: pd.DataFrame,
    gold_history: pd.DataFrame,
) -> pd.DataFrame:
    equity = usd_equity_history.copy()
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


def _compute_row(
    *,
    overlap: pd.DataFrame,
    ticker: str,
    as_of_date: pd.Timestamp,
    horizon: ParsedHorizon,
    near_zero_gold_return_threshold: float,
) -> dict[str, object]:
    start_date = resolve_horizon_start_date(
        overlap["date"],
        as_of_date=as_of_date.date(),
        horizon=horizon,
    )
    if start_date is None:
        return _coverage_row(
            ticker=ticker,
            as_of_date=as_of_date.date(),
            horizon=horizon,
            coverage_reason="INSUFFICIENT_HISTORY",
        )

    start_row = overlap.loc[overlap["date"] == pd.Timestamp(start_date)]
    end_row = overlap.loc[overlap["date"] == as_of_date]
    if start_row.empty or end_row.empty:
        return _coverage_row(
            ticker=ticker,
            as_of_date=as_of_date.date(),
            horizon=horizon,
            coverage_reason="MISSING_OVERLAP",
        )

    equity_start = _as_positive_float(start_row["equity_basis_usd"].iloc[0])
    equity_end = _as_positive_float(end_row["equity_basis_usd"].iloc[0])
    gold_start = _as_positive_float(start_row["gold_basis_usd"].iloc[0])
    gold_end = _as_positive_float(end_row["gold_basis_usd"].iloc[0])

    if None in (equity_start, equity_end, gold_start, gold_end):
        return _coverage_row(
            ticker=ticker,
            as_of_date=as_of_date.date(),
            horizon=horizon,
            coverage_reason="MISSING_RETURN_BASIS",
            start_date=start_date,
        )

    equity_return = (equity_end / equity_start) - 1.0
    gold_return = (gold_end / gold_start) - 1.0

    if abs(gold_return) < near_zero_gold_return_threshold:
        return {
            "ticker": ticker,
            "as_of_date": as_of_date.date(),
            "horizon_id": horizon.horizon_id,
            "horizon_mode": horizon.mode,
            "horizon_unit": horizon.unit,
            "horizon_value": horizon.value,
            "start_date": start_date,
            "end_date": as_of_date.date(),
            "equity_return": equity_return,
            "gold_return": gold_return,
            "gold_delta": None,
            "coverage_flag": "PASS",
            "coverage_reason": "NEAR_ZERO_GOLD_RETURN",
            "official_scoring_eligible": False,
        }

    return {
        "ticker": ticker,
        "as_of_date": as_of_date.date(),
        "horizon_id": horizon.horizon_id,
        "horizon_mode": horizon.mode,
        "horizon_unit": horizon.unit,
        "horizon_value": horizon.value,
        "start_date": start_date,
        "end_date": as_of_date.date(),
        "equity_return": equity_return,
        "gold_return": gold_return,
        "gold_delta": equity_return / gold_return,
        "coverage_flag": "PASS",
        "coverage_reason": "OK",
        "official_scoring_eligible": horizon.mode == "core",
    }


def _coverage_row(
    *,
    ticker: str,
    as_of_date: date,
    horizon: ParsedHorizon,
    coverage_reason: str,
    start_date: date | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "horizon_id": horizon.horizon_id,
        "horizon_mode": horizon.mode,
        "horizon_unit": horizon.unit,
        "horizon_value": horizon.value,
        "start_date": start_date,
        "end_date": as_of_date,
        "equity_return": None,
        "gold_return": None,
        "gold_delta": None,
        "coverage_flag": "FAIL",
        "coverage_reason": coverage_reason,
        "official_scoring_eligible": False,
    }


def _as_positive_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return numeric
