"""Shared gold-shock exposure math for portfolio and hedge surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from golden_vector.common.numeric import optional_float

DEFAULT_GOLD_DOWN_SCENARIO_FRACTION = -0.10
DEFAULT_GOLD_DOWN_MIN_BETA = 0.10


@dataclass(frozen=True)
class GoldShockExposure:
    value_usd: float | None
    beta: float | None
    effective_beta: float | None
    shock_fraction: float
    pnl_usd: float | None
    loss_usd: float | None
    effective_exposure_usd: float | None
    modelable: bool
    reason: str | None
    stock_clamped_at_zero: bool


def compute_gold_shock_exposure(
    *,
    value_usd: object,
    beta: object,
    shock_fraction: float = DEFAULT_GOLD_DOWN_SCENARIO_FRACTION,
    min_effective_beta: float | None = DEFAULT_GOLD_DOWN_MIN_BETA,
) -> GoldShockExposure:
    """Return one transparent linear gold-shock result.

    The primitive floors negative beta at zero and clamps downside P&L so a
    stock can lose at most 100% of its value. ``min_effective_beta=None`` keeps
    zero-beta rows modelable with zero loss for legacy hedge displays that need
    to show an explicit zero rather than skip the row.
    """

    value = optional_float(value_usd)
    parsed_beta = optional_float(beta)
    scenario = float(shock_fraction)
    if value is None or value <= 0:
        return _unmodelable(
            value=value,
            beta=parsed_beta,
            shock_fraction=scenario,
            reason="Position value is missing or non-positive.",
        )
    if parsed_beta is None:
        return _unmodelable(
            value=value,
            beta=None,
            shock_fraction=scenario,
            reason="Gold beta is missing.",
        )

    effective_beta = max(float(parsed_beta), 0.0)
    if min_effective_beta is not None and effective_beta <= float(min_effective_beta):
        return _unmodelable(
            value=value,
            beta=parsed_beta,
            shock_fraction=scenario,
            effective_beta=effective_beta,
            reason="Gold beta is too small for modeled exposure.",
        )

    raw_pnl = value * effective_beta * scenario
    pnl = max(-value, raw_pnl) if raw_pnl < 0 else raw_pnl
    loss = max(-pnl, 0.0)
    return GoldShockExposure(
        value_usd=value,
        beta=parsed_beta,
        effective_beta=effective_beta,
        shock_fraction=scenario,
        pnl_usd=pnl,
        loss_usd=loss,
        effective_exposure_usd=value * effective_beta,
        modelable=True,
        reason=None,
        stock_clamped_at_zero=raw_pnl < -value,
    )


def _unmodelable(
    *,
    value: float | None,
    beta: float | None,
    shock_fraction: float,
    reason: str,
    effective_beta: float | None = None,
) -> GoldShockExposure:
    return GoldShockExposure(
        value_usd=value,
        beta=beta,
        effective_beta=effective_beta,
        shock_fraction=shock_fraction,
        pnl_usd=None,
        loss_usd=None,
        effective_exposure_usd=None,
        modelable=False,
        reason=reason,
        stock_clamped_at_zero=False,
    )
