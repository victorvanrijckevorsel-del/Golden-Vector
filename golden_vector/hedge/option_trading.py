"""Structured option-trading data builders for the workspace UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.scenarios import (
    CandidateScenarioBundle,
    OptionStrategy,
    compute_scenario_bundle,
)

SideStatus = Literal["available", "thin", "none"]
OptionSide = Literal["put", "call"]
SizingMode = Literal["contracts", "budget"]

PREFERRED_OPTION_HORIZON_DAYS = 60
OPTION_CONTEXT_SIGNAL_HORIZON_DAYS = 60
PUT_CONTEXT_GOLD_MOVE = -0.10
CALL_CONTEXT_GOLD_MOVE = 0.10


@dataclass(frozen=True)
class OptionSizingRequest:
    side: OptionSide = "put"
    horizon_days: int = PREFERRED_OPTION_HORIZON_DAYS
    bucket: str | None = None
    size_mode: SizingMode = "contracts"
    quantity: int = 5
    budget: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptionSizingResult:
    request: OptionSizingRequest
    contracts: int
    premium_spend: float | None
    leftover_cash: float | None
    bundle: CandidateScenarioBundle | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptionTradingSourceContext:
    as_of_date: str | None = None
    refresh_run_id: str | None = None
    risk_free_rate: float | None = None
    risk_free_rate_is_fallback: bool = False
    source_label: str = "Cached Yahoo Finance data via yfinance"


@dataclass(frozen=True)
class OptionTradingRow:
    ticker: str
    structural_delta_core: float | None
    down_beta_core: float | None
    up_beta_core: float | None
    confidence_label: str
    confidence_score: float | None
    iv_percentile_cross_sectional: float | None
    iv_skew_60d: float | None
    iv_rv_ratio_60d: float | None
    optionability_tier: str
    put_status: SideStatus
    call_status: SideStatus
    pnl_put_at_minus10_60d: float | None
    pnl_call_at_plus10_60d: float | None
    notes: tuple[str, ...]
    current_stock_price: float | None = None


@dataclass(frozen=True)
class OptionTradingOverviewData:
    rows: tuple[OptionTradingRow, ...]
    reason: str | None = None
    risk_free_rate_is_fallback: bool = False
    source_context: OptionTradingSourceContext | None = None


@dataclass(frozen=True)
class OptionTradingDetailData:
    ticker: str
    row: OptionTradingRow | None
    put_candidates: tuple[OptionCandidate, ...]
    put_bundles: tuple[CandidateScenarioBundle, ...]
    put_slots: tuple[OptionCandidateSlot, ...] = ()
    call_candidates: tuple[OptionCandidate, ...] = ()
    call_bundles: tuple[CandidateScenarioBundle, ...] = ()
    call_slots: tuple[OptionCandidateSlot, ...] = ()
    sizing: OptionSizingResult | None = None
    reason: str | None = None
    risk_free_rate_is_fallback: bool = False
    source_context: OptionTradingSourceContext | None = None


def build_option_trading_overview(
    *,
    tool_a: pd.DataFrame,
    options_features: pd.DataFrame,
    candidate_grids: dict[str, list[OptionCandidate]],
    risk_free_rate: float,
    call_candidate_grids: dict[str, list[OptionCandidate]] | None = None,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    preferred_horizon_days: int = PREFERRED_OPTION_HORIZON_DAYS,
    put_context_gold_move: float = PUT_CONTEXT_GOLD_MOVE,
    call_context_gold_move: float = CALL_CONTEXT_GOLD_MOVE,
    down_beta_min_for_scenario: float = 0.10,
    risk_free_rate_is_fallback: bool = False,
    source_context: OptionTradingSourceContext | None = None,
) -> OptionTradingOverviewData:
    """Build optionable ticker rows for the workspace overview tab."""

    if options_features.empty:
        return OptionTradingOverviewData(
            rows=(),
            reason="No options feature snapshot is available yet.",
            risk_free_rate_is_fallback=risk_free_rate_is_fallback,
            source_context=source_context,
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
        put_candidates = tuple(candidate_grids.get(ticker, []))
        call_candidates = tuple((call_candidate_grids or {}).get(ticker, []))
        rows.append(
            _build_row(
                ticker=ticker,
                feature=feature,
                tool_a_row=tool_a_row,
                put_candidates=put_candidates,
                call_candidates=call_candidates,
                risk_free_rate=risk_free_rate,
                target_horizons_days=target_horizons_days,
                preferred_horizon_days=preferred_horizon_days,
                put_context_gold_move=put_context_gold_move,
                call_context_gold_move=call_context_gold_move,
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
        source_context=source_context,
    )


def build_option_trading_detail(
    *,
    ticker: str,
    tool_a: pd.DataFrame,
    candidate_grids: dict[str, list[OptionCandidate]],
    overview_row: OptionTradingRow | None,
    risk_free_rate: float,
    call_candidate_grids: dict[str, list[OptionCandidate]] | None = None,
    put_candidate_slots: dict[str, list[OptionCandidateSlot]] | None = None,
    call_candidate_slots: dict[str, list[OptionCandidateSlot]] | None = None,
    sizing_request: OptionSizingRequest | None = None,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    down_beta_min_for_scenario: float = 0.10,
    risk_free_rate_is_fallback: bool = False,
    source_context: OptionTradingSourceContext | None = None,
) -> OptionTradingDetailData:
    """Build put and call detail data for a single ticker."""

    normalized = ticker.strip().upper()
    put_candidates = tuple(candidate_grids.get(normalized, []))
    call_candidates = tuple((call_candidate_grids or {}).get(normalized, []))
    put_slots = tuple((put_candidate_slots or {}).get(normalized, []))
    call_slots = tuple((call_candidate_slots or {}).get(normalized, []))
    tool_a_row = rows_by_ticker_series(tool_a, strip=True).get(normalized)
    down_beta = row_float(tool_a_row, "down_beta_core")
    up_beta = row_float(tool_a_row, "up_beta_core")
    confidence_label = row_string(tool_a_row, "confidence_label") or "n/a"
    put_bundles = tuple(
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
        for candidate in put_candidates
    )
    call_bundles = tuple(
        compute_scenario_bundle(
            candidate=candidate,
            current_stock_price=candidate.underlying_price,
            gold_beta=up_beta,
            confidence_label=confidence_label,
            risk_free_rate=risk_free_rate,
            strategy=OptionStrategy.LONG_CALL,
            gold_beta_min_for_scenario=down_beta_min_for_scenario,
            gold_scenarios=(0.0, 0.05, 0.10, 0.15, 0.20),
            quantity=1,
        )
        for candidate in call_candidates
    )
    sizing = build_option_sizing_result(
        request=sizing_request or OptionSizingRequest(),
        put_bundles=put_bundles,
        call_bundles=call_bundles,
    )
    return OptionTradingDetailData(
        ticker=normalized,
        row=overview_row,
        put_candidates=put_candidates,
        put_bundles=put_bundles,
        put_slots=put_slots,
        call_candidates=call_candidates,
        call_bundles=call_bundles,
        call_slots=call_slots,
        sizing=sizing,
        reason=(
            None
            if overview_row is not None
            else "Ticker is not optionable in the latest snapshot."
        ),
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        source_context=source_context,
    )


def build_option_sizing_result(
    *,
    request: OptionSizingRequest,
    put_bundles: tuple[CandidateScenarioBundle, ...],
    call_bundles: tuple[CandidateScenarioBundle, ...],
) -> OptionSizingResult:
    """Apply contracts/budget sizing to one cached per-contract scenario bundle."""

    bundles = put_bundles if request.side == "put" else call_bundles
    bundle = _bundle_for_request(bundles, request)
    notes = list(request.notes)
    if bundle is None:
        bucket_note = f" {request.bucket.replace('_', ' ')}" if request.bucket else ""
        notes.append(
            f"No {request.horizon_days}d{bucket_note} {request.side} candidate is available."
        )
        return OptionSizingResult(
            request=request,
            contracts=0,
            premium_spend=None,
            leftover_cash=request.budget if request.size_mode == "budget" else None,
            bundle=None,
            notes=tuple(notes),
        )
    if bundle.skipped_reason:
        notes.append(bundle.skipped_reason)

    contracts = request.quantity
    leftover_cash = None
    premium_spend = _premium_spend(bundle.candidate, contracts)
    if request.size_mode == "budget":
        budget = float(request.budget or 0.0)
        cost_per_contract = _premium_spend(bundle.candidate, 1)
        if cost_per_contract is None or cost_per_contract <= 0:
            contracts = 0
            premium_spend = None
            leftover_cash = budget
            notes.append("Candidate mid premium is unavailable, so budget sizing cannot buy contracts.")
        else:
            contracts = int(budget // cost_per_contract)
            premium_spend = contracts * cost_per_contract
            leftover_cash = budget - premium_spend
            if contracts < 1:
                notes.append("Budget is below the cost of one standard 100-share option contract.")

    return OptionSizingResult(
        request=request,
        contracts=contracts,
        premium_spend=premium_spend,
        leftover_cash=leftover_cash,
        bundle=_rescale_bundle(bundle, contracts),
        notes=tuple(notes),
    )


def _bundle_for_request(
    bundles: tuple[CandidateScenarioBundle, ...],
    request: OptionSizingRequest,
) -> CandidateScenarioBundle | None:
    horizon = f"{request.horizon_days}d"
    bucket = str(request.bucket or "").strip()
    for bundle in bundles:
        candidate_bucket = str(bundle.candidate.bucket or "").strip()
        if bundle.horizon == horizon and (not bucket or candidate_bucket == bucket):
            return bundle
    return None


def _premium_spend(candidate: OptionCandidate, contracts: int) -> float | None:
    if candidate.mid is None or candidate.mid < 0:
        return None
    return candidate.mid * contracts * 100.0


def _rescale_bundle(
    bundle: CandidateScenarioBundle,
    contracts: int,
) -> CandidateScenarioBundle:
    scaled_rows = [
        replace(
            row,
            net_pnl_at_expiry=(
                row.pnl_per_contract_at_expiry * contracts * 100.0
            ),
            net_pnl_if_closed_today=(
                row.pnl_per_contract_if_closed_today * contracts * 100.0
            ),
        )
        for row in bundle.rows
    ]
    return replace(bundle, rows=scaled_rows)


def _build_row(
    *,
    ticker: str,
    feature: pd.Series,
    tool_a_row: pd.Series | None,
    put_candidates: tuple[OptionCandidate, ...],
    call_candidates: tuple[OptionCandidate, ...],
    risk_free_rate: float,
    target_horizons_days: tuple[int, ...],
    preferred_horizon_days: int,
    put_context_gold_move: float,
    call_context_gold_move: float,
    down_beta_min_for_scenario: float,
) -> OptionTradingRow:
    tier = optionability_tier(row_string(feature, "optionability_tier"))
    down_beta = row_float(tool_a_row, "down_beta_core")
    up_beta = row_float(tool_a_row, "up_beta_core")
    confidence_label = row_string(tool_a_row, "confidence_label") or "n/a"
    notes: list[str] = []
    current_stock_price = _current_stock_price(
        feature,
        put_candidates if put_candidates else call_candidates,
    )

    put_status = _candidate_side_status(
        feature=feature,
        candidates=put_candidates,
        side="put",
        optionability=tier,
        target_horizons_days=target_horizons_days,
    )
    call_status = _candidate_side_status(
        feature=feature,
        candidates=call_candidates,
        side="call",
        optionability=tier,
        target_horizons_days=target_horizons_days,
    )

    pnl_put = _context_pnl(
        candidates=put_candidates,
        current_stock_price=_current_stock_price(feature, put_candidates),
        gold_beta=down_beta,
        confidence_label=confidence_label,
        risk_free_rate=risk_free_rate,
        strategy=OptionStrategy.LONG_PUT,
        preferred_horizon_days=preferred_horizon_days,
        context_gold_move=put_context_gold_move,
        gold_beta_min_for_scenario=down_beta_min_for_scenario,
    )
    pnl_call = _context_pnl(
        candidates=call_candidates,
        current_stock_price=_current_stock_price(feature, call_candidates),
        gold_beta=up_beta,
        confidence_label=confidence_label,
        risk_free_rate=risk_free_rate,
        strategy=OptionStrategy.LONG_CALL,
        preferred_horizon_days=preferred_horizon_days,
        context_gold_move=call_context_gold_move,
        gold_beta_min_for_scenario=down_beta_min_for_scenario,
    )
    if put_status != "available":
        notes.append("No usable put candidate found.")
    if call_status != "available":
        notes.append("No usable call candidate found.")

    return OptionTradingRow(
        ticker=ticker,
        structural_delta_core=row_float(tool_a_row, "structural_delta_core"),
        down_beta_core=down_beta,
        up_beta_core=up_beta,
        confidence_label=confidence_label,
        confidence_score=row_float(tool_a_row, "confidence_score"),
        iv_percentile_cross_sectional=row_float(feature, "iv_percentile_cross_sectional"),
        iv_skew_60d=row_float(
            feature,
            f"iv_skew_{OPTION_CONTEXT_SIGNAL_HORIZON_DAYS}d",
        ),
        iv_rv_ratio_60d=row_float(
            feature,
            f"iv_rv_ratio_{OPTION_CONTEXT_SIGNAL_HORIZON_DAYS}d",
        ),
        optionability_tier=tier,
        put_status=put_status,
        call_status=call_status,
        pnl_put_at_minus10_60d=pnl_put,
        pnl_call_at_plus10_60d=pnl_call,
        notes=tuple(notes),
        current_stock_price=current_stock_price,
    )


def _candidate_side_status(
    *,
    feature: pd.Series,
    candidates: tuple[OptionCandidate, ...],
    side: Literal["put", "call"],
    optionability: str,
    target_horizons_days: tuple[int, ...],
) -> SideStatus:
    if candidates:
        return "available"
    if _side_feature_present(feature, side, target_horizons_days):
        return "thin"
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


def _context_pnl(
    *,
    candidates: tuple[OptionCandidate, ...],
    current_stock_price: float | None,
    gold_beta: float | None,
    confidence_label: str,
    risk_free_rate: float,
    strategy: OptionStrategy,
    preferred_horizon_days: int,
    context_gold_move: float,
    gold_beta_min_for_scenario: float,
) -> float | None:
    candidate = _candidate_for_horizon(candidates, preferred_horizon_days)
    if candidate is None or current_stock_price is None:
        return None
    bundle = compute_scenario_bundle(
        candidate=candidate,
        current_stock_price=current_stock_price,
        gold_beta=gold_beta,
        confidence_label=confidence_label,
        risk_free_rate=risk_free_rate,
        strategy=strategy,
        gold_beta_min_for_scenario=gold_beta_min_for_scenario,
        gold_scenarios=(context_gold_move,),
        quantity=1,
    )
    if not bundle.rows:
        return None
    return bundle.rows[0].pnl_per_contract_at_expiry


def _candidate_for_horizon(
    candidates: tuple[OptionCandidate, ...],
    horizon_days: int,
) -> OptionCandidate | None:
    for candidate in candidates:
        if candidate.horizon_days == horizon_days:
            return candidate
    return None


def _current_stock_price(
    feature: pd.Series,
    candidates: tuple[OptionCandidate, ...],
) -> float | None:
    price = as_float(feature.get("underlying_price"))
    if price is not None and price > 0:
        return price
    if candidates:
        return candidates[0].underlying_price
    return None
