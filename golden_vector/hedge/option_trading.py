"""Structured option-trading data builders for the workspace UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from golden_vector.hedge._helpers import (
    as_float,
    is_optionable_tier,
    optionability_tier,
    row_float,
    row_string,
    rows_by_ticker_series,
)
from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.scenarios import CandidateScenarioBundle, compute_scenario_bundle

SideStatus = Literal["available", "thin", "none"]

PREFERRED_OPTION_HORIZON_DAYS = 60
PUT_CONTEXT_GOLD_MOVE = -0.10


@dataclass(frozen=True)
class OptionTradingRow:
    ticker: str
    down_beta_core: float | None
    up_beta_core: float | None
    confidence_label: str
    confidence_score: float | None
    iv_percentile_cross_sectional: float | None
    optionability_tier: str
    put_status: SideStatus
    call_status: SideStatus
    pnl_put_at_minus10_60d: float | None
    pnl_call_at_plus10_60d: float | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class OptionTradingOverviewData:
    rows: tuple[OptionTradingRow, ...]
    reason: str | None = None
    risk_free_rate_is_fallback: bool = False


@dataclass(frozen=True)
class OptionTradingDetailData:
    ticker: str
    row: OptionTradingRow | None
    put_candidates: tuple[CandidatePut, ...]
    put_bundles: tuple[CandidateScenarioBundle, ...]
    reason: str | None = None
    risk_free_rate_is_fallback: bool = False


def build_option_trading_overview(
    *,
    tool_a: pd.DataFrame,
    options_features: pd.DataFrame,
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    preferred_horizon_days: int = PREFERRED_OPTION_HORIZON_DAYS,
    put_context_gold_move: float = PUT_CONTEXT_GOLD_MOVE,
    down_beta_min_for_scenario: float = 0.10,
    risk_free_rate_is_fallback: bool = False,
) -> OptionTradingOverviewData:
    """Build optionable ticker rows for the workspace overview tab."""

    if options_features.empty:
        return OptionTradingOverviewData(
            rows=(),
            reason="No options feature snapshot is available yet.",
            risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        )

    feature_by_ticker = rows_by_ticker_series(options_features, strip=True)
    tool_a_by_ticker = rows_by_ticker_series(tool_a, strip=True)
    rows: list[OptionTradingRow] = []
    for ticker in sorted(feature_by_ticker):
        feature = feature_by_ticker[ticker]
        tier = optionability_tier(row_string(feature, "optionability_tier"))
        if not is_optionable_tier(tier):
            continue
        tool_a_row = tool_a_by_ticker.get(ticker)
        candidates = tuple(candidate_grids.get(ticker, []))
        rows.append(
            _build_row(
                ticker=ticker,
                feature=feature,
                tool_a_row=tool_a_row,
                candidates=candidates,
                risk_free_rate=risk_free_rate,
                target_horizons_days=target_horizons_days,
                preferred_horizon_days=preferred_horizon_days,
                put_context_gold_move=put_context_gold_move,
                down_beta_min_for_scenario=down_beta_min_for_scenario,
            )
        )

    rows.sort(
        key=lambda row: (
            row.down_beta_core is None,
            -(row.down_beta_core or 0.0),
            row.ticker,
        )
    )
    reason = None if rows else "No optionable tickers are available in the latest snapshot."
    return OptionTradingOverviewData(
        rows=tuple(rows),
        reason=reason,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )


def build_option_trading_detail(
    *,
    ticker: str,
    tool_a: pd.DataFrame,
    candidate_grids: dict[str, list[CandidatePut]],
    overview_row: OptionTradingRow | None,
    risk_free_rate: float,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    down_beta_min_for_scenario: float = 0.10,
    risk_free_rate_is_fallback: bool = False,
) -> OptionTradingDetailData:
    """Build put-side detail data for a single ticker."""

    normalized = ticker.strip().upper()
    candidates = tuple(candidate_grids.get(normalized, []))
    tool_a_row = rows_by_ticker_series(tool_a, strip=True).get(normalized)
    down_beta = row_float(tool_a_row, "down_beta_core")
    confidence_label = row_string(tool_a_row, "confidence_label") or "n/a"
    bundles = tuple(
        compute_scenario_bundle(
            candidate=candidate,
            current_stock_price=candidate.underlying_price,
            gold_beta=down_beta,
            confidence_label=confidence_label,
            risk_free_rate=risk_free_rate,
            gold_beta_min_for_scenario=down_beta_min_for_scenario,
            gold_scenarios=(0.0, -0.05, -0.10, -0.15, -0.20),
            quantity=1,
        )
        for candidate in candidates
    )
    return OptionTradingDetailData(
        ticker=normalized,
        row=overview_row,
        put_candidates=candidates,
        put_bundles=bundles,
        reason=(
            None
            if overview_row is not None
            else "Ticker is not optionable in the latest snapshot."
        ),
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )


def _build_row(
    *,
    ticker: str,
    feature: pd.Series,
    tool_a_row: pd.Series | None,
    candidates: tuple[CandidatePut, ...],
    risk_free_rate: float,
    target_horizons_days: tuple[int, ...],
    preferred_horizon_days: int,
    put_context_gold_move: float,
    down_beta_min_for_scenario: float,
) -> OptionTradingRow:
    tier = optionability_tier(row_string(feature, "optionability_tier"))
    down_beta = row_float(tool_a_row, "down_beta_core")
    up_beta = row_float(tool_a_row, "up_beta_core")
    confidence_label = row_string(tool_a_row, "confidence_label") or "n/a"
    notes: list[str] = []

    put_status = _put_status(
        feature=feature,
        candidates=candidates,
        optionability=tier,
        target_horizons_days=target_horizons_days,
    )
    call_status = _feature_side_status(
        feature=feature,
        side="call",
        optionability=tier,
        target_horizons_days=target_horizons_days,
    )

    pnl_put = _put_context_pnl(
        candidates=candidates,
        current_stock_price=_current_stock_price(feature, candidates),
        down_beta_core=down_beta,
        confidence_label=confidence_label,
        risk_free_rate=risk_free_rate,
        preferred_horizon_days=preferred_horizon_days,
        put_context_gold_move=put_context_gold_move,
        down_beta_min_for_scenario=down_beta_min_for_scenario,
    )
    if put_status != "available":
        notes.append("No usable put candidate found.")
    elif pnl_put is None:
        notes.append("No 60d put scenario could be modeled.")
    if call_status != "available":
        notes.append("No usable call quote found.")

    return OptionTradingRow(
        ticker=ticker,
        down_beta_core=down_beta,
        up_beta_core=up_beta,
        confidence_label=confidence_label,
        confidence_score=row_float(tool_a_row, "confidence_score"),
        iv_percentile_cross_sectional=row_float(feature, "iv_percentile_cross_sectional"),
        optionability_tier=tier,
        put_status=put_status,
        call_status=call_status,
        pnl_put_at_minus10_60d=pnl_put,
        pnl_call_at_plus10_60d=None,
        notes=tuple(notes),
    )


def _put_status(
    *,
    feature: pd.Series,
    candidates: tuple[CandidatePut, ...],
    optionability: str,
    target_horizons_days: tuple[int, ...],
) -> SideStatus:
    if candidates:
        return "available"
    if _side_feature_present(feature, "put", target_horizons_days):
        return "thin"
    if is_optionable_tier(optionability):
        return "thin"
    return "none"


def _feature_side_status(
    *,
    feature: pd.Series,
    side: Literal["put", "call"],
    optionability: str,
    target_horizons_days: tuple[int, ...],
) -> SideStatus:
    if _side_feature_present(feature, side, target_horizons_days):
        return "available"
    if is_optionable_tier(optionability):
        return "thin"
    return "none"


def _side_feature_present(
    feature: pd.Series,
    side: Literal["put", "call"],
    target_horizons_days: tuple[int, ...],
) -> bool:
    prefix = "put" if side == "put" else "call"
    for horizon in target_horizons_days:
        if row_float(feature, f"{prefix}_iv_25d_{horizon}d") is not None:
            return True
    return False


def _put_context_pnl(
    *,
    candidates: tuple[CandidatePut, ...],
    current_stock_price: float | None,
    down_beta_core: float | None,
    confidence_label: str,
    risk_free_rate: float,
    preferred_horizon_days: int,
    put_context_gold_move: float,
    down_beta_min_for_scenario: float,
) -> float | None:
    candidate = _candidate_for_horizon(candidates, preferred_horizon_days)
    if candidate is None or current_stock_price is None:
        return None
    bundle = compute_scenario_bundle(
        candidate=candidate,
        current_stock_price=current_stock_price,
        gold_beta=down_beta_core,
        confidence_label=confidence_label,
        risk_free_rate=risk_free_rate,
        gold_beta_min_for_scenario=down_beta_min_for_scenario,
        gold_scenarios=(put_context_gold_move,),
        quantity=1,
    )
    if not bundle.rows:
        return None
    return bundle.rows[0].pnl_per_contract_at_expiry


def _candidate_for_horizon(
    candidates: tuple[CandidatePut, ...],
    horizon_days: int,
) -> CandidatePut | None:
    for candidate in candidates:
        if candidate.horizon_days == horizon_days:
            return candidate
    return None


def _current_stock_price(
    feature: pd.Series,
    candidates: tuple[CandidatePut, ...],
) -> float | None:
    price = as_float(feature.get("underlying_price"))
    if price is not None and price > 0:
        return price
    if candidates:
        return candidates[0].underlying_price
    return None
