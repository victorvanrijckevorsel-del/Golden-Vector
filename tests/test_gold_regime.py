import pandas as pd

from golden_vector.features.gold_regime import (
    GOLD_REGIME_COLUMNS,
    build_gold_regime_frame,
)


def test_build_gold_regime_frame_uses_rolling_tail_thresholds():
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["NEM"] * 5,
            "week_period": [
                "2026-01-03/2026-01-09",
                "2026-01-10/2026-01-16",
                "2026-01-17/2026-01-23",
                "2026-01-24/2026-01-30",
                "2026-01-31/2026-02-06",
            ],
            "gold_log_ret": [-0.01, -0.02, -0.20, 0.15, 0.03],
        }
    )

    regimes = build_gold_regime_frame(
        weekly_returns,
        rolling_weeks=3,
        min_weeks=3,
        downside_hit_rate_threshold=-0.10,
        upside_hit_rate_threshold=0.10,
    )

    assert list(regimes.columns) == GOLD_REGIME_COLUMNS
    assert bool(regimes.loc[0, "gold_regime_ready"]) is False
    assert bool(regimes.loc[2, "gold_worst10_event"]) is True
    assert bool(regimes.loc[2, "gold_worst20_event"]) is True
    assert bool(regimes.loc[2, "gold_down_hit_event"]) is True
    assert bool(regimes.loc[3, "gold_best10_event"]) is True
    assert bool(regimes.loc[3, "gold_best20_event"]) is True
    assert bool(regimes.loc[3, "gold_up_hit_event"]) is True


def test_build_gold_regime_frame_returns_contract_columns_when_empty():
    regimes = build_gold_regime_frame(pd.DataFrame(), rolling_weeks=3, min_weeks=3)

    assert list(regimes.columns) == GOLD_REGIME_COLUMNS
    assert regimes.empty
