"""Gold weekly regime classification for Tool C."""

from __future__ import annotations

import math
import pandas as pd

GOLD_REGIME_COLUMNS = [
    "week_period",
    "gold_log_ret",
    "gold_worst10_event",
    "gold_worst20_event",
    "gold_best10_event",
    "gold_best20_event",
    "gold_down_hit_event",
    "gold_up_hit_event",
    "gold_regime_ready",
]


def build_gold_regime_frame(
    weekly_returns: pd.DataFrame,
    *,
    rolling_weeks: int = 156,
    min_weeks: int = 52,
    downside_hit_rate_log_threshold: float = math.log1p(-0.10),
    upside_hit_rate_log_threshold: float = math.log1p(0.10),
) -> pd.DataFrame:
    """Classify gold weeks with rolling tail thresholds.

    The function expects Tool C's weekly return contract and emits one row per
    `week_period`. Quantile events are false until the warm-up has enough
    history, so downstream event counts remain honest.
    """

    if rolling_weeks <= 0 or min_weeks <= 0:
        raise ValueError("rolling_weeks and min_weeks must be positive")
    if min_weeks > rolling_weeks:
        raise ValueError("min_weeks must not exceed rolling_weeks")
    if downside_hit_rate_log_threshold >= 0:
        raise ValueError("downside_hit_rate_log_threshold must be negative")
    if upside_hit_rate_log_threshold <= 0:
        raise ValueError("upside_hit_rate_log_threshold must be positive")
    if weekly_returns.empty or "week_period" not in weekly_returns.columns:
        return pd.DataFrame(columns=GOLD_REGIME_COLUMNS)

    gold = weekly_returns[["week_period", "gold_log_ret"]].drop_duplicates(
        subset=["week_period"],
        keep="last",
    ).copy()
    gold["gold_log_ret"] = pd.to_numeric(gold["gold_log_ret"], errors="coerce")
    gold = gold.loc[gold["gold_log_ret"].notna()].copy()
    if gold.empty:
        return pd.DataFrame(columns=GOLD_REGIME_COLUMNS)

    gold = gold.sort_values("week_period").reset_index(drop=True)
    rolling = gold["gold_log_ret"].rolling(
        window=rolling_weeks,
        min_periods=min_weeks,
    )
    worst10 = rolling.quantile(0.10)
    worst20 = rolling.quantile(0.20)
    best80 = rolling.quantile(0.80)
    best90 = rolling.quantile(0.90)
    ready = worst10.notna()

    gold["gold_worst10_event"] = ready & gold["gold_log_ret"].le(worst10)
    gold["gold_worst20_event"] = ready & gold["gold_log_ret"].le(worst20)
    gold["gold_best10_event"] = ready & gold["gold_log_ret"].ge(best90)
    gold["gold_best20_event"] = ready & gold["gold_log_ret"].ge(best80)
    gold["gold_down_hit_event"] = ready & gold["gold_log_ret"].le(
        downside_hit_rate_log_threshold
    )
    gold["gold_up_hit_event"] = ready & gold["gold_log_ret"].ge(
        upside_hit_rate_log_threshold
    )
    gold["gold_regime_ready"] = ready
    return gold[GOLD_REGIME_COLUMNS].reset_index(drop=True)
