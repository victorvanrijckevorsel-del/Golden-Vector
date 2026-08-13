"""Structured option-trading data builders for the workspace UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import pandas as pd

from golden_vector.common.numeric import bool_or_false
from golden_vector.common.options import OPTION_CONTRACT_MULTIPLIER
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

SideStatus = Literal["tradable", "watch", "none"]
OptionSide = Literal["put", "call"]
SizingMode = Literal["contracts", "budget"]

# Bare-construction fallback only; production paths resolve the horizon
# from config (signal horizon) or the stamped most-liquid default. Kept at
# the signal-horizon default so a bare request is never a retired horizon.
PREFERRED_OPTION_HORIZON_DAYS = 90
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
    # True when the user picked the horizon explicitly; False lets the
    # backend-stamped "Most liquid" default take over on the detail page.
    horizon_explicit: bool = False
    # True when the user provided any size control (size_mode/quantity/budget); lets
    # the window switcher preserve sizing state without emitting silent defaults.
    size_explicit: bool = False


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
    tool_a_refresh_run_ids: tuple[str, ...] = ()
    tool_b_refresh_run_ids: tuple[str, ...] = ()
    context_warnings: tuple[str, ...] = ()
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
    # Signal-horizon fields (Milestone C2): horizon-agnostic names; the
    # actual horizon is carried in signal_horizon_days, never the field name.
    iv_skew_signal: float | None
    iv_rv_ratio_signal: float | None
    optionability_tier: str
    put_status: SideStatus
    call_status: SideStatus
    pnl_put_at_context: float | None
    pnl_call_at_context: float | None
    notes: tuple[str, ...]
    current_stock_price: float | None = None
    option_vehicle_type: str = "single_stock"
    signal_horizon_days: int | None = None
    context_horizon_days: int | None = None
    # Backend-selected "Most liquid" defaults (Milestone C3/C4): stamped at
    # build time per side; serve renders them, never recomputes them.
    most_liquid_put_horizon_days: int | None = None
    most_liquid_put_expiration: str | None = None
    most_liquid_call_horizon_days: int | None = None
    most_liquid_call_expiration: str | None = None
    # Per-(side x display-horizon) candidate status, stamped at build time as a
    # JSON string so the overview horizon selector (Part A) can show each
    # horizon's Put/Call status + expiry without recomputing in serve. Shape:
    # {"P": {"230": {"status","expiration","dte"}, ...}, "C": {...}}.
    per_horizon_status_json: str | None = None
    source_refresh_run_id: str | None = None
    source_as_of_date: str | None = None
    captured_at_utc: str | None = None
    carried_forward: bool = False
    attempt_status: str | None = None
    attempt_message: str | None = None
    display_staleness_trading_days: int | None = None
    display_freshness_status: str | None = None


@dataclass(frozen=True)
class OptionLiquidityMeasurement:
    group_label: str
    ticker_count: int
    contract_count: int
    median_rel_spread: float | None
    median_open_interest: float | None
    median_volume: float | None
    median_near_spot_depth: float | None
    tradable_count: int = 0
    watch_count: int = 0
    no_trade_count: int = 0


@dataclass(frozen=True)
class OptionTradingOverviewData:
    rows: tuple[OptionTradingRow, ...]
    reason: str | None = None
    risk_free_rate_is_fallback: bool = False
    source_context: OptionTradingSourceContext | None = None
    liquidity_measurements: tuple[OptionLiquidityMeasurement, ...] = ()
    # Backend-selected group defaults (C3/C4): per-ticker vote over miners,
    # stamped on the persisted overview artifact; serve only renders them.
    group_default_put_horizon_days: int | None = None
    group_default_call_horizon_days: int | None = None


@dataclass(frozen=True)
class OptionProxyFallback:
    ticker: str
    side: OptionSide
    horizon_days: int
    candidate: OptionCandidate
    reason: str


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
    proxy_fallbacks: tuple[OptionProxyFallback, ...] = ()
    proxy_fallback_note: str | None = None
    signal_row: dict[str, object] | None = None
    skew_curve_points: tuple[dict[str, object], ...] = ()
    oi_strike_points: tuple[dict[str, object], ...] = ()
    signal_history_points: tuple[dict[str, object], ...] = ()


def build_option_trading_overview(
    *,
    tool_a: pd.DataFrame,
    options_features: pd.DataFrame,
    candidate_grids: dict[str, list[OptionCandidate]],
    risk_free_rate: float,
    target_horizons_days: tuple[int, ...],
    signal_horizon_days: int,
    call_candidate_grids: dict[str, list[OptionCandidate]] | None = None,
    preferred_horizon_days: int | None = None,
    put_context_gold_move: float = PUT_CONTEXT_GOLD_MOVE,
    call_context_gold_move: float = CALL_CONTEXT_GOLD_MOVE,
    down_beta_min_for_scenario: float = 0.10,
    risk_free_rate_is_fallback: bool = False,
    source_context: OptionTradingSourceContext | None = None,
    liquidity_measurements: tuple[OptionLiquidityMeasurement, ...] = (),
) -> OptionTradingOverviewData:
    """Build optionable ticker rows for the workspace overview tab."""

    if preferred_horizon_days is None:
        # Context P&L follows the signal horizon until the most-liquid
        # selector (Milestone C3) supplies a per-ticker default.
        preferred_horizon_days = signal_horizon_days
    if options_features.empty:
        return OptionTradingOverviewData(
            rows=(),
            reason="No options feature snapshot is available yet.",
            risk_free_rate_is_fallback=risk_free_rate_is_fallback,
            source_context=source_context,
            liquidity_measurements=liquidity_measurements,
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
                signal_horizon_days=signal_horizon_days,
                preferred_horizon_days=preferred_horizon_days,
                put_context_gold_move=put_context_gold_move,
                call_context_gold_move=call_context_gold_move,
                down_beta_min_for_scenario=down_beta_min_for_scenario,
            )
        )

    rows.sort(
        key=lambda row: (
            row.option_vehicle_type != "benchmark_etf",
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
        liquidity_measurements=liquidity_measurements,
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
    target_horizons_days: tuple[int, ...] = (90, 180, 230, 550),  # callers pass config
    down_beta_min_for_scenario: float = 0.10,
    # Put-side downside gold ladder; the serve caller threads
    # hedge_readiness.default_scenarios so this page can't drift from the Hedge
    # Readiness / Speculation ladders. The call ladder is the sign-mirror of this.
    put_gold_scenarios: tuple[float, ...] = (0.0, -0.05, -0.10, -0.15, -0.20),
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
            gold_scenarios=put_gold_scenarios,
            quantity=1,
        )
        for candidate in put_candidates
        if candidate.liquidity_tier == "tradable"
    )
    # Call ladder = the sign-mirror of the put ladder, so both derive from ONE
    # source (config.default_scenarios). default_scenarios is validated put-side
    # (<= 0); negating yields the valid >= 0 call moves. The "+ 0.0" normalizes
    # the negated base case (-0.0 -> 0.0) so the rendered Gold Move cell shows
    # "0.0%" rather than "-0.0%"; non-zero moves are unaffected.
    call_gold_scenarios = tuple(-move + 0.0 for move in put_gold_scenarios)
    call_bundles = tuple(
        compute_scenario_bundle(
            candidate=candidate,
            current_stock_price=candidate.underlying_price,
            gold_beta=up_beta,
            confidence_label=confidence_label,
            risk_free_rate=risk_free_rate,
            strategy=OptionStrategy.LONG_CALL,
            gold_beta_min_for_scenario=down_beta_min_for_scenario,
            gold_scenarios=call_gold_scenarios,
            quantity=1,
        )
        for candidate in call_candidates
        if candidate.liquidity_tier == "tradable"
    )
    sizing = build_option_sizing_result(
        request=sizing_request
        or OptionSizingRequest(horizon_days=target_horizons_days[0]),
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
        bucket_note = f" {_sizing_bucket_label(request.bucket)}" if request.bucket else ""
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
    return candidate.mid * contracts * OPTION_CONTRACT_MULTIPLIER


def _rescale_bundle(
    bundle: CandidateScenarioBundle,
    contracts: int,
) -> CandidateScenarioBundle:
    scaled_rows = [
        replace(
            row,
            net_pnl_at_expiry=(
                row.pnl_per_contract_at_expiry * contracts * OPTION_CONTRACT_MULTIPLIER
            ),
            net_pnl_if_closed_today=(
                row.pnl_per_contract_if_closed_today * contracts * OPTION_CONTRACT_MULTIPLIER
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
    signal_horizon_days: int,
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
    option_vehicle_type = row_string(feature, "option_vehicle_type") or "single_stock"
    current_stock_price = _current_stock_price(
        feature,
        put_candidates if put_candidates else call_candidates,
    )

    put_status = _candidate_side_status(put_candidates)
    call_status = _candidate_side_status(call_candidates)

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
    if put_status == "watch":
        notes.append("Put candidate is Watch tier; spread may be expensive.")
    elif put_status != "tradable":
        notes.append("No liquid put candidate found.")
    if call_status == "watch":
        notes.append("Call candidate is Watch tier; spread may be expensive.")
    elif call_status != "tradable":
        notes.append("No liquid call candidate found.")
    if option_vehicle_type == "benchmark_etf":
        notes.append("Benchmark ETF option vehicle.")

    return OptionTradingRow(
        ticker=ticker,
        structural_delta_core=row_float(tool_a_row, "structural_delta_core"),
        down_beta_core=down_beta,
        up_beta_core=up_beta,
        confidence_label=confidence_label,
        confidence_score=row_float(tool_a_row, "confidence_score"),
        iv_percentile_cross_sectional=row_float(feature, "iv_percentile_cross_sectional"),
        iv_skew_signal=row_float(feature, f"iv_skew_{signal_horizon_days}d"),
        iv_rv_ratio_signal=row_float(feature, f"iv_rv_ratio_{signal_horizon_days}d"),
        optionability_tier=tier,
        put_status=put_status,
        call_status=call_status,
        pnl_put_at_context=pnl_put,
        pnl_call_at_context=pnl_call,
        notes=tuple(notes),
        current_stock_price=current_stock_price,
        option_vehicle_type=option_vehicle_type,
        signal_horizon_days=int(signal_horizon_days),
        context_horizon_days=int(preferred_horizon_days),
        source_refresh_run_id=row_string(feature, "source_refresh_run_id"),
        source_as_of_date=row_string(feature, "source_as_of_date")
        or row_string(feature, "as_of_date"),
        captured_at_utc=row_string(feature, "captured_at_utc"),
        carried_forward=bool_or_false(feature.get("carried_forward")),
        attempt_status=row_string(feature, "attempt_status"),
        attempt_message=row_string(feature, "attempt_message"),
    )


def _candidate_side_status(candidates: tuple[OptionCandidate, ...]) -> SideStatus:
    if any(candidate.liquidity_tier == "tradable" for candidate in candidates):
        return "tradable"
    if any(candidate.liquidity_tier == "watch" for candidate in candidates):
        return "watch"
    return "none"


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
        if candidate.horizon_days == horizon_days and candidate.liquidity_tier == "tradable":
            return candidate
    return None


def _sizing_bucket_label(bucket: str | None) -> str:
    if bucket == "near_atm":
        return "Near-ATM"
    if bucket == "directional":
        return "Directional"
    return str(bucket or "").replace("_", " ").title()


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
