"""Implied-move helpers for hedge-readiness reports."""

from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.features.options_chain import (
    compute_straddle_implied_move,
    normalize_options_chain,
)


def compute_implied_move_from_straddle(
    *,
    chain: pd.DataFrame,
    underlying_price: float,
    expiration: date | str,
    max_spread_pct: float = 0.35,
    min_open_interest: int = 1,
    min_volume: int = 0,
) -> float | None:
    """Return ATM straddle implied move when quote liquidity gates pass."""

    if chain.empty or underlying_price <= 0:
        return None
    frame = normalize_options_chain(
        chain,
        as_of_date=None,
        require_implied_volatility=False,
        require_days_to_expiry=False,
    )
    implied_move, gates_ok = compute_straddle_implied_move(
        frame,
        underlying_price=underlying_price,
        expiration=expiration,
        max_spread_pct=max_spread_pct,
        min_open_interest=min_open_interest,
        min_volume=min_volume,
    )
    if not gates_ok:
        return None
    return implied_move
