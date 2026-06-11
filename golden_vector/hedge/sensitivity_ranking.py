"""Universe-wide gold-downside sensitivity ranking for hedge readiness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from golden_vector.hedge._helpers import (
    as_float,
    latest_row_dict,
    optionability_tier as normalize_optionability_tier,
    rows_by_ticker_dict,
    unique_preserving_order,
)
from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.scenarios import compute_scenario_bundle

RANKING_PNL_GOLD_MOVE = -0.10


@dataclass(frozen=True)
class SensitivityRow:
    rank: int | None
    ticker: str
    structural_delta_core: float | None
    down_beta_core: float | None
    up_beta_core: float | None
    confidence_label: str
    confidence_score: float | None
    iv_percentile_cross_sectional: float | None
    iv_skew_signal: float | None
    iv_rv_ratio_signal: float | None
    pnl_at_minus10_context: float | None
    optionability_tier: str
    notes: list[str]


@dataclass(frozen=True)
class SensitivityRankingData:
    rows: list[SensitivityRow]
    sort_by: str
    total_count: int
    score_eligible_count: int


def build_sensitivity_ranking(
    *,
    tool_a_frame: pd.DataFrame,
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float | None,
    down_beta_min_for_scenario: float,
    signal_horizon_days: int,
    sort_by: str = "down_beta_core",
    max_tickers: int | None = None,
) -> SensitivityRankingData:
    """Rank the universe by Tool A core down-beta and attach signal-window put P&L."""

    if sort_by != "down_beta_core":
        raise ValueError("Sensitivity ranking supports only sort_by='down_beta_core'.")

    feature_by_ticker = _features_by_ticker(options_features)
    built_rows = [
        _build_row(
            signal_horizon_days=signal_horizon_days,
            ticker=ticker,
            tool_a_row=tool_a_row,
            feature=feature_by_ticker.get(ticker),
            candidates=candidate_grids.get(ticker, []),
            risk_free_rate=risk_free_rate,
            down_beta_min_for_scenario=down_beta_min_for_scenario,
        )
        for ticker, tool_a_row in rows_by_ticker_dict(tool_a_frame).items()
    ]
    rankable = [row for row, is_rankable, _score_eligible in built_rows if is_rankable]
    rankable.sort(key=lambda row: (-(row.down_beta_core or 0.0), row.ticker))
    reranked = [
        SensitivityRow(
            rank=index,
            ticker=row.ticker,
            structural_delta_core=row.structural_delta_core,
            down_beta_core=row.down_beta_core,
            up_beta_core=row.up_beta_core,
            confidence_label=row.confidence_label,
            confidence_score=row.confidence_score,
            iv_percentile_cross_sectional=row.iv_percentile_cross_sectional,
            iv_skew_signal=row.iv_skew_signal,
            iv_rv_ratio_signal=row.iv_rv_ratio_signal,
            pnl_at_minus10_context=row.pnl_at_minus10_context,
            optionability_tier=row.optionability_tier,
            notes=row.notes,
        )
        for index, row in enumerate(rankable, start=1)
    ]
    unranked = sorted(
        (row for row, is_rankable, _score_eligible in built_rows if not is_rankable),
        key=lambda row: row.ticker,
    )
    ordered = [*reranked, *unranked]
    if max_tickers is not None:
        ordered = ordered[:max(0, max_tickers)]
    return SensitivityRankingData(
        rows=ordered,
        sort_by=sort_by,
        total_count=len(built_rows),
        score_eligible_count=sum(
            1
            for _row, is_rankable, score_eligible in built_rows
            if is_rankable and score_eligible
        ),
    )


def _build_row(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    feature: dict[str, Any] | None,
    candidates: list[CandidatePut],
    risk_free_rate: float | None,
    down_beta_min_for_scenario: float,
    signal_horizon_days: int,
) -> tuple[SensitivityRow, bool, bool]:
    down_beta = as_float(tool_a_row.get("down_beta_core"))
    score_eligible = _as_bool(tool_a_row.get("score_eligible"), default=True)
    notes: list[str] = []
    if not score_eligible:
        notes.append("score withheld; downside beta shown for context")
    if down_beta is None:
        notes.append("down-beta unavailable")

    optionability_tier = normalize_optionability_tier(
        (feature or {}).get("optionability_tier")
    )
    if feature is None:
        notes.append("no options features")
    if optionability_tier == "none":
        notes.append("no listed options")

    context_candidate = _candidate_for_horizon(candidates, horizon_days=signal_horizon_days)
    pnl_at_minus10 = None
    if context_candidate is None:
        notes.append(f"no {signal_horizon_days}d candidate")
    elif down_beta is not None:
        bundle = compute_scenario_bundle(
            candidate=context_candidate,
            current_stock_price=context_candidate.underlying_price,
            gold_beta=down_beta,
            confidence_label=str(tool_a_row.get("confidence_label") or "n/a"),
            risk_free_rate=risk_free_rate or 0.0,
            gold_beta_min_for_scenario=down_beta_min_for_scenario,
            gold_scenarios=(RANKING_PNL_GOLD_MOVE,),
            quantity=1,
        )
        if bundle.skipped_reason:
            notes.append(bundle.skipped_reason)
        elif bundle.rows:
            pnl_at_minus10 = bundle.rows[0].pnl_per_contract_at_expiry

    is_rankable = down_beta is not None
    return (
        SensitivityRow(
            rank=None,
            ticker=ticker,
            structural_delta_core=as_float(tool_a_row.get("structural_delta_core")),
            down_beta_core=down_beta,
            up_beta_core=as_float(tool_a_row.get("up_beta_core")),
            confidence_label=str(tool_a_row.get("confidence_label") or "n/a"),
            confidence_score=as_float(tool_a_row.get("confidence_score")),
            iv_percentile_cross_sectional=as_float(
                (feature or {}).get("iv_percentile_cross_sectional")
            ),
            iv_skew_signal=as_float(
                (feature or {}).get(f"iv_skew_{signal_horizon_days}d")
            ),
            iv_rv_ratio_signal=as_float(
                (feature or {}).get(
                    f"iv_rv_ratio_{signal_horizon_days}d"
                )
            ),
            pnl_at_minus10_context=pnl_at_minus10,
            optionability_tier=optionability_tier,
            notes=unique_preserving_order(notes),
        ),
        is_rankable,
        score_eligible,
    )


def _features_by_ticker(
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    if isinstance(options_features, pd.DataFrame):
        return rows_by_ticker_dict(options_features)
    result: dict[str, dict[str, Any]] = {}
    for ticker, frame in options_features.items():
        normalized = str(ticker).upper()
        if frame.empty:
            result[normalized] = {"ticker": normalized}
            continue
        result[normalized] = latest_row_dict(frame, fallback_ticker=normalized)
    return result


def _candidate_for_horizon(
    candidates: list[CandidatePut],
    *,
    horizon_days: int,
) -> CandidatePut | None:
    for candidate in candidates:
        if candidate.horizon_days == horizon_days:
            return candidate
    return None


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None or pd.isna(value):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}
