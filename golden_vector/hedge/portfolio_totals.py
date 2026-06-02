"""Portfolio-level downside and hedge-cost aggregation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.hedge._helpers import row_float, rows_by_ticker_series
from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.holdings import Holding

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
    candidate_60d: CandidatePut | None
    skipped_reason: str | None


@dataclass(frozen=True)
class PortfolioScenarioRow:
    gold_pct_change: float
    portfolio_value_at_scenario: float
    portfolio_loss_dollars: float
    portfolio_loss_pct: float
    hedge_cost_by_protection: dict[float, float]


@dataclass(frozen=True)
class PortfolioTotalsData:
    holdings_count: int
    holdings_resolved_count: int
    holdings_skipped: list[tuple[str, str]]
    current_total_value: float
    scenario_rows: list[PortfolioScenarioRow]
    interpretive_notes: list[str]


def compute_portfolio_totals(
    *,
    holdings: list[Holding],
    tool_a_frame: pd.DataFrame,
    tool_b_frame: pd.DataFrame,
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float | None,
    config: HedgeReadinessConfig,
) -> PortfolioTotalsData | None:
    """Aggregate modeled portfolio downside and put hedge costs."""

    _ = risk_free_rate
    if not holdings:
        return None

    tool_a_by_ticker = rows_by_ticker_series(tool_a_frame)
    tool_b_by_ticker = rows_by_ticker_series(tool_b_frame)
    resolved = [
        _resolve_holding(
            holding=holding,
            tool_a_row=tool_a_by_ticker.get(holding.ticker),
            tool_b_row=tool_b_by_ticker.get(holding.ticker),
            candidates=candidate_grids.get(holding.ticker, []),
            config=config,
        )
        for holding in holdings
    ]
    current_total = sum(
        holding.current_notional or 0.0
        for holding in resolved
    )
    scenario_rows = [
        _scenario_row(
            resolved=resolved,
            current_total=current_total,
            gold_pct_change=gold_pct_change,
            protection_levels=tuple(config.protection_levels),
        )
        for gold_pct_change in config.default_scenarios
    ]
    skipped = [
        (holding.ticker, holding.skipped_reason)
        for holding in resolved
        if holding.skipped_reason is not None
    ]
    return PortfolioTotalsData(
        holdings_count=len(holdings),
        holdings_resolved_count=sum(
            1
            for holding in resolved
            if holding.current_notional is not None
        ),
        holdings_skipped=skipped,
        current_total_value=current_total,
        scenario_rows=scenario_rows,
        interpretive_notes=_interpretive_notes(
            current_total=current_total,
            scenario_rows=scenario_rows,
            protection_levels=tuple(config.protection_levels),
        ),
    )


def _resolve_holding(
    *,
    holding: Holding,
    tool_a_row: pd.Series | None,
    tool_b_row: pd.Series | None,
    candidates: list[CandidatePut],
    config: HedgeReadinessConfig,
) -> HoldingResolved:
    candidate_60d = _candidate_for_horizon(candidates, horizon_days=60)
    current_price = _current_stock_price(
        tool_b_row=tool_b_row,
        candidate=candidate_60d,
    )
    mode = "shares" if holding.shares is not None else "dollar_exposure"
    current_notional = _current_notional(
        holding=holding,
        current_stock_price=current_price,
    )
    down_beta = row_float(tool_a_row, "down_beta_core")
    skip_reasons = _skip_reasons(
        mode=mode,
        current_stock_price=current_price,
        current_notional=current_notional,
        down_beta_core=down_beta,
        candidate_60d=candidate_60d,
        config=config,
    )
    return HoldingResolved(
        ticker=holding.ticker,
        mode=mode,
        shares=holding.shares,
        dollar_exposure=holding.dollar_exposure,
        current_stock_price=current_price,
        current_notional=current_notional,
        down_beta_core=down_beta,
        candidate_60d=candidate_60d,
        skipped_reason="; ".join(skip_reasons) if skip_reasons else None,
    )


def _scenario_row(
    *,
    resolved: list[HoldingResolved],
    current_total: float,
    gold_pct_change: float,
    protection_levels: tuple[float, ...],
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
        hedge_cost_by_protection={
            level: _hedge_cost_at_level(
                resolved=resolved,
                protection_level=level,
            )
            for level in protection_levels
        },
    )


def _holding_value_at_scenario(
    *,
    holding: HoldingResolved,
    gold_pct_change: float,
) -> float:
    if holding.current_notional is None:
        return 0.0
    if (
        holding.down_beta_core is None
        or (
            holding.skipped_reason is not None
            and "down-beta unavailable or too small" in holding.skipped_reason
        )
    ):
        return holding.current_notional
    factor = max(0.0, 1.0 + holding.down_beta_core * gold_pct_change)
    return holding.current_notional * factor


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
        assert holding.candidate_60d is not None
        assert holding.candidate_60d.mid is not None
        target_shares = (
            holding.current_notional * protection_level / holding.current_stock_price
        )
        contracts = math.ceil(target_shares / OPTION_CONTRACT_MULTIPLIER)
        total += contracts * holding.candidate_60d.mid * OPTION_CONTRACT_MULTIPLIER
    return total


def _hedge_cost_eligible(holding: HoldingResolved) -> bool:
    return (
        holding.current_notional is not None
        and holding.current_stock_price is not None
        and holding.candidate_60d is not None
        and holding.candidate_60d.mid is not None
        and holding.candidate_60d.mid >= 0
    )


def _skip_reasons(
    *,
    mode: str,
    current_stock_price: float | None,
    current_notional: float | None,
    down_beta_core: float | None,
    candidate_60d: CandidatePut | None,
    config: HedgeReadinessConfig,
) -> list[str]:
    reasons: list[str] = []
    if current_notional is None:
        reasons.append("missing share price")
    if (
        down_beta_core is None
        or down_beta_core <= config.down_beta_min_for_scenario
    ):
        reasons.append("down-beta unavailable or too small")
    if candidate_60d is None:
        reasons.append("no 60d candidate")
    if mode == "dollar_exposure" and current_stock_price is None:
        reasons.append("no hedge-cost inputs")
    if candidate_60d is not None and candidate_60d.mid is None:
        reasons.append("no hedge-cost inputs")
    return _unique_reasons(reasons)


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
    tool_b_row: pd.Series | None,
    candidate: CandidatePut | None,
) -> float | None:
    price = row_float(tool_b_row, "share_price_usd")
    if price is not None and price > 0:
        return price
    if candidate is not None and candidate.underlying_price > 0:
        return candidate.underlying_price
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
    scenario_rows: list[PortfolioScenarioRow],
    protection_levels: tuple[float, ...],
) -> list[str]:
    if current_total <= 0:
        return ["No portfolio notional could be resolved."]
    notes: list[str] = []
    first_row = scenario_rows[0] if scenario_rows else None
    if first_row is not None:
        for level in protection_levels:
            cost = first_row.hedge_cost_by_protection.get(level, 0.0)
            notes.append(
                f"Hedging {level:.0%} costs {cost / current_total:.1%} of portfolio."
            )
    return notes


def _unique_reasons(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
