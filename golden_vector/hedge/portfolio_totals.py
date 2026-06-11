"""Portfolio-level downside and hedge-cost aggregation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.hedge._helpers import (
    row_float,
    rows_by_ticker_series,
    unique_preserving_order,
)
from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.holdings import Holding
from golden_vector.model.gold_shock import compute_gold_shock_exposure

OPTION_CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True)
class HoldingResolved:
    ticker: str
    mode: str
    shares: float | None
    dollar_exposure: float | None
    current_stock_price: float | None
    current_notional: float | None
    down_beta_core: float | None
    context_candidate: CandidatePut | None
    totals_exclusion_reason: str | None
    downside_modelable: bool
    downside_skip_reason: str | None
    hedge_cost_modelable: bool
    hedge_cost_skip_reason: str | None


@dataclass(frozen=True)
class PortfolioScenarioRow:
    gold_pct_change: float
    portfolio_value_at_scenario: float
    portfolio_loss_dollars: float
    portfolio_loss_pct: float


@dataclass(frozen=True)
class PortfolioTotalsData:
    holdings_count: int
    holdings_resolved_count: int
    holdings_excluded_from_totals: list[tuple[str, str]]
    downside_model_skipped: list[tuple[str, str]]
    hedge_cost_skipped: list[tuple[str, str]]
    current_total_value: float
    hedge_cost_by_protection: dict[float, float]
    scenario_rows: list[PortfolioScenarioRow]
    interpretive_notes: list[str]


def compute_portfolio_totals(
    *,
    holdings: list[Holding],
    tool_a_frame: pd.DataFrame,
    tool_b_frame: pd.DataFrame,
    options_features: pd.DataFrame | None = None,
    candidate_grids: dict[str, list[CandidatePut]],
    config: HedgeReadinessConfig,
) -> PortfolioTotalsData | None:
    """Aggregate modeled portfolio downside and put hedge costs."""

    if not holdings:
        return None

    tool_a_by_ticker = rows_by_ticker_series(tool_a_frame)
    tool_b_by_ticker = rows_by_ticker_series(tool_b_frame)
    feature_by_ticker = (
        rows_by_ticker_series(options_features)
        if options_features is not None
        else {}
    )
    resolved = [
        _resolve_holding(
            holding=holding,
            tool_a_row=tool_a_by_ticker.get(holding.ticker),
            tool_b_row=tool_b_by_ticker.get(holding.ticker),
            feature_row=feature_by_ticker.get(holding.ticker),
            candidates=candidate_grids.get(holding.ticker, []),
            config=config,
        )
        for holding in holdings
    ]
    current_total = sum(
        holding.current_notional or 0.0
        for holding in resolved
    )
    protection_levels = tuple(config.protection_levels)
    hedge_cost_by_protection = {
        level: _hedge_cost_at_level(
            resolved=resolved,
            protection_level=level,
        )
        for level in protection_levels
    }
    scenario_rows = [
        _scenario_row(
            resolved=resolved,
            current_total=current_total,
            gold_pct_change=gold_pct_change,
        )
        for gold_pct_change in config.default_scenarios
    ]
    excluded_from_totals = [
        (holding.ticker, holding.totals_exclusion_reason)
        for holding in resolved
        if holding.totals_exclusion_reason is not None
    ]
    downside_skipped = [
        (holding.ticker, holding.downside_skip_reason)
        for holding in resolved
        if holding.current_notional is not None and holding.downside_skip_reason is not None
    ]
    hedge_cost_skipped = [
        (holding.ticker, holding.hedge_cost_skip_reason)
        for holding in resolved
        if holding.current_notional is not None and holding.hedge_cost_skip_reason is not None
    ]
    return PortfolioTotalsData(
        holdings_count=len(holdings),
        holdings_resolved_count=sum(
            1
            for holding in resolved
            if holding.current_notional is not None
        ),
        holdings_excluded_from_totals=excluded_from_totals,
        downside_model_skipped=downside_skipped,
        hedge_cost_skipped=hedge_cost_skipped,
        current_total_value=current_total,
        hedge_cost_by_protection=hedge_cost_by_protection,
        scenario_rows=scenario_rows,
        interpretive_notes=_interpretive_notes(
            current_total=current_total,
            hedge_cost_by_protection=hedge_cost_by_protection,
            protection_levels=protection_levels,
        ),
    )


def _resolve_holding(
    *,
    holding: Holding,
    tool_a_row: pd.Series | None,
    tool_b_row: pd.Series | None,
    feature_row: pd.Series | None,
    candidates: list[CandidatePut],
    config: HedgeReadinessConfig,
) -> HoldingResolved:
    signal_horizon_days = config.option_signal_horizon_days
    context_candidate = _candidate_for_horizon(candidates, horizon_days=signal_horizon_days)
    price_candidate = context_candidate or (candidates[0] if candidates else None)
    current_price = _current_stock_price(
        feature_row=feature_row,
        tool_b_row=tool_b_row,
        candidate=price_candidate,
    )
    mode = "shares" if holding.shares is not None else "dollar_exposure"
    current_notional = _current_notional(
        holding=holding,
        current_stock_price=current_price,
    )
    down_beta = row_float(tool_a_row, "down_beta_core")
    totals_exclusion_reason = _totals_exclusion_reason(
        mode=mode,
        current_notional=current_notional,
    )
    downside_skip_reason = _downside_skip_reason(
        current_notional=current_notional,
        down_beta_core=down_beta,
        config=config,
    )
    hedge_cost_skip_reason = _hedge_cost_skip_reason(
        signal_horizon_days=signal_horizon_days,
        current_notional=current_notional,
        current_stock_price=current_price,
        context_candidate=context_candidate,
    )
    return HoldingResolved(
        ticker=holding.ticker,
        mode=mode,
        shares=holding.shares,
        dollar_exposure=holding.dollar_exposure,
        current_stock_price=current_price,
        current_notional=current_notional,
        down_beta_core=down_beta,
        context_candidate=context_candidate,
        totals_exclusion_reason=totals_exclusion_reason,
        downside_modelable=(
            current_notional is not None and downside_skip_reason is None
        ),
        downside_skip_reason=downside_skip_reason,
        hedge_cost_modelable=(
            current_notional is not None and hedge_cost_skip_reason is None
        ),
        hedge_cost_skip_reason=hedge_cost_skip_reason,
    )


def _scenario_row(
    *,
    resolved: list[HoldingResolved],
    current_total: float,
    gold_pct_change: float,
) -> PortfolioScenarioRow:
    scenario_value = sum(
        _holding_value_at_scenario(
            holding=holding,
            gold_pct_change=gold_pct_change,
        )
        for holding in resolved
    )
    loss = current_total - scenario_value
    return PortfolioScenarioRow(
        gold_pct_change=float(gold_pct_change),
        portfolio_value_at_scenario=scenario_value,
        portfolio_loss_dollars=loss,
        portfolio_loss_pct=(loss / current_total) if current_total > 0 else 0.0,
    )


def _holding_value_at_scenario(
    *,
    holding: HoldingResolved,
    gold_pct_change: float,
) -> float:
    if holding.current_notional is None:
        return 0.0
    if not holding.downside_modelable:
        return holding.current_notional
    shock = compute_gold_shock_exposure(
        value_usd=holding.current_notional,
        beta=holding.down_beta_core,
        shock_fraction=gold_pct_change,
        min_effective_beta=None,
    )
    if shock.pnl_usd is None:
        return holding.current_notional
    return holding.current_notional + shock.pnl_usd


def _hedge_cost_at_level(
    *,
    resolved: list[HoldingResolved],
    protection_level: float,
) -> float:
    total = 0.0
    for holding in resolved:
        if not _hedge_cost_eligible(holding):
            continue
        assert holding.current_notional is not None
        assert holding.current_stock_price is not None
        assert holding.context_candidate is not None
        assert holding.context_candidate.mid is not None
        target_shares = (
            holding.current_notional * protection_level / holding.current_stock_price
        )
        contracts = math.ceil(target_shares / OPTION_CONTRACT_MULTIPLIER)
        total += contracts * holding.context_candidate.mid * OPTION_CONTRACT_MULTIPLIER
    return total


def _hedge_cost_eligible(holding: HoldingResolved) -> bool:
    return (
        holding.hedge_cost_modelable
        and holding.current_notional is not None
        and holding.current_stock_price is not None
        and holding.context_candidate is not None
        and holding.context_candidate.mid is not None
    )


def _totals_exclusion_reason(
    *,
    mode: str,
    current_notional: float | None,
) -> str | None:
    if current_notional is not None:
        return None
    if mode == "shares":
        return "missing share price"
    return "missing notional"


def _downside_skip_reason(
    *,
    current_notional: float | None,
    down_beta_core: float | None,
    config: HedgeReadinessConfig,
) -> str | None:
    if current_notional is None:
        return "not included in portfolio totals"
    if (
        down_beta_core is None
        or down_beta_core <= config.down_beta_min_for_scenario
    ):
        return "down-beta unavailable or too small"
    return None


def _hedge_cost_skip_reason(
    *,
    current_notional: float | None,
    current_stock_price: float | None,
    context_candidate: CandidatePut | None,
    signal_horizon_days: int,
) -> str | None:
    reasons: list[str] = []
    if current_notional is None:
        return "not included in portfolio totals"
    if current_stock_price is None:
        reasons.append("no hedge-cost inputs")
    if context_candidate is None:
        reasons.append(f"no {signal_horizon_days}d candidate")
    if (
        context_candidate is not None
        and (context_candidate.mid is None or context_candidate.mid < 0)
    ):
        reasons.append("no hedge-cost inputs")
    unique_reasons = unique_preserving_order(reasons)
    return "; ".join(unique_reasons) if unique_reasons else None


def _current_notional(
    *,
    holding: Holding,
    current_stock_price: float | None,
) -> float | None:
    if holding.dollar_exposure is not None:
        return holding.dollar_exposure
    if holding.shares is None or current_stock_price is None:
        return None
    return holding.shares * current_stock_price


def _current_stock_price(
    *,
    feature_row: pd.Series | None,
    tool_b_row: pd.Series | None,
    candidate: CandidatePut | None,
) -> float | None:
    price = row_float(feature_row, "underlying_price")
    if price is not None and price > 0:
        return price
    if candidate is not None and candidate.underlying_price > 0:
        return candidate.underlying_price
    price = row_float(tool_b_row, "share_price_usd")
    if price is not None and price > 0:
        return price
    return None


def _candidate_for_horizon(
    candidates: list[CandidatePut],
    *,
    horizon_days: int,
) -> CandidatePut | None:
    for candidate in candidates:
        if candidate.horizon_days == horizon_days:
            return candidate
    return None


def _interpretive_notes(
    *,
    current_total: float,
    hedge_cost_by_protection: dict[float, float],
    protection_levels: tuple[float, ...],
) -> list[str]:
    if current_total <= 0:
        return ["No portfolio notional could be resolved."]
    notes: list[str] = []
    for level in protection_levels:
        cost = hedge_cost_by_protection.get(level, 0.0)
        notes.append(
            f"Hedging {level:.0%} costs {cost / current_total:.1%} of portfolio."
        )
    return notes
