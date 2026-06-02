"""Scenario P&L math for speculative put candidates."""

from __future__ import annotations

from dataclasses import dataclass

from golden_vector.features.black_scholes import black_scholes_put_price
from golden_vector.features.options_chain import CALENDAR_DAYS_PER_YEAR
from golden_vector.hedge.candidate_puts import CandidatePut

DOWN_BETA_MIN_FOR_SCENARIO = 0.10
OPTION_CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True)
class ScenarioRow:
    gold_pct_change: float
    implied_stock_price: float
    stock_clamped_at_zero: bool
    expiry_value_per_contract: float
    current_value_per_contract: float
    pnl_per_contract_at_expiry: float
    pnl_per_contract_if_closed_today: float
    net_pnl_at_expiry: float
    net_pnl_if_closed_today: float


@dataclass(frozen=True)
class CandidateScenarioBundle:
    ticker: str
    horizon: str
    candidate: CandidatePut
    rows: list[ScenarioRow]
    breakeven_gold_pct: float | None
    breakeven_annotation: str | None
    down_beta_used: float | None
    confidence_label: str
    skipped_reason: str | None = None


def compute_scenario_bundle(
    *,
    candidate: CandidatePut,
    current_stock_price: float,
    down_beta_core: float | None,
    confidence_label: str,
    risk_free_rate: float,
    gold_scenarios: tuple[float, ...] = (0.0, -0.05, -0.10, -0.15, -0.20),
    quantity: int = 5,
) -> CandidateScenarioBundle:
    """Compute model-based put P&L scenarios for one listed candidate."""

    base_kwargs = {
        "ticker": candidate.ticker,
        "horizon": f"{candidate.horizon_days}d",
        "candidate": candidate,
        "down_beta_used": down_beta_core,
        "confidence_label": confidence_label,
    }
    skipped_reason = _skip_reason(
        current_stock_price=current_stock_price,
        down_beta_core=down_beta_core,
        premium_mid=candidate.mid,
        quantity=quantity,
    )
    if skipped_reason is not None:
        return CandidateScenarioBundle(
            rows=[],
            breakeven_gold_pct=None,
            breakeven_annotation=None,
            skipped_reason=skipped_reason,
            **base_kwargs,
        )

    premium = float(candidate.mid or 0.0)
    down_beta = float(down_beta_core or 0.0)
    breakeven, breakeven_annotation = _breakeven_gold_pct(
        strike=candidate.strike,
        premium=premium,
        current_stock_price=current_stock_price,
        down_beta=down_beta,
    )

    rows: list[ScenarioRow] = []
    for gold_pct_change in gold_scenarios:
        raw_implied_price = current_stock_price * (1.0 + down_beta * gold_pct_change)
        implied_stock_price = max(0.0, raw_implied_price)
        current_value = black_scholes_put_price(
            spot=implied_stock_price,
            strike=candidate.strike,
            time_to_expiry_years=candidate.days_to_expiry / CALENDAR_DAYS_PER_YEAR,
            risk_free_rate=risk_free_rate,
            implied_volatility=candidate.implied_volatility,
        )
        if current_value is None:
            return CandidateScenarioBundle(
                rows=[],
                breakeven_gold_pct=None,
                breakeven_annotation=None,
                skipped_reason="Candidate implied volatility is missing or unusable.",
                **base_kwargs,
            )
        expiry_value = max(0.0, candidate.strike - implied_stock_price)
        pnl_at_expiry = expiry_value - premium
        pnl_if_closed_today = current_value - premium
        rows.append(
            ScenarioRow(
                gold_pct_change=float(gold_pct_change),
                implied_stock_price=implied_stock_price,
                stock_clamped_at_zero=raw_implied_price < 0,
                expiry_value_per_contract=expiry_value,
                current_value_per_contract=current_value,
                pnl_per_contract_at_expiry=pnl_at_expiry,
                pnl_per_contract_if_closed_today=pnl_if_closed_today,
                net_pnl_at_expiry=pnl_at_expiry * quantity * OPTION_CONTRACT_MULTIPLIER,
                net_pnl_if_closed_today=(
                    pnl_if_closed_today * quantity * OPTION_CONTRACT_MULTIPLIER
                ),
            )
        )

    return CandidateScenarioBundle(
        rows=rows,
        breakeven_gold_pct=breakeven,
        breakeven_annotation=breakeven_annotation,
        skipped_reason=None,
        **base_kwargs,
    )


def _skip_reason(
    *,
    current_stock_price: float,
    down_beta_core: float | None,
    premium_mid: float | None,
    quantity: int,
) -> str | None:
    if current_stock_price <= 0:
        return "Current stock price is unavailable."
    if premium_mid is None or premium_mid < 0:
        return "Candidate mid premium is unavailable."
    if quantity <= 0:
        return "Scenario quantity must be positive."
    if down_beta_core is None or down_beta_core <= DOWN_BETA_MIN_FOR_SCENARIO:
        return (
            "Down-beta is too small to model meaningful gold-down scenarios. "
            "This ticker's stock does not move with gold in the way a put thesis requires."
        )
    return None


def _breakeven_gold_pct(
    *,
    strike: float,
    premium: float,
    current_stock_price: float,
    down_beta: float,
) -> tuple[float | None, str | None]:
    breakeven = ((strike - premium) / current_stock_price - 1.0) / down_beta
    if breakeven > 0:
        return None, "Put is already in the money or breakeven requires gold to rise."
    return breakeven, None
