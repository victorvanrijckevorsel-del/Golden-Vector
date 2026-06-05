import pandas as pd

from golden_vector.features.relative_behavior import (
    RELATIVE_BEHAVIOR_COLUMNS,
    compute_relative_behavior_metrics,
)


def test_compute_relative_behavior_metrics_outputs_values_and_counts():
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["AAA"] * 4,
            "week_period": ["w1", "w2", "w3", "w4"],
            "stock_log_ret": [-0.12, -0.05, 0.14, 0.04],
            "gold_log_ret": [-0.08, -0.04, 0.09, 0.02],
            "gdx_log_ret": [-0.10, -0.08, 0.10, 0.05],
            "gdxj_log_ret": [0.0, 0.0, 0.0, 0.0],
        }
    )
    gold_regimes = pd.DataFrame(
        {
            "week_period": ["w1", "w2", "w3", "w4"],
            "gold_log_ret": [-0.08, -0.04, 0.09, 0.02],
            "gold_worst10_event": [True, False, False, False],
            "gold_worst20_event": [True, True, False, False],
            "gold_best10_event": [False, False, True, False],
            "gold_best20_event": [False, False, True, True],
        }
    )

    metrics = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
        downside_hit_rate_threshold=-0.10,
        upside_hit_rate_threshold=0.10,
    )
    row = metrics.iloc[0]

    assert list(metrics.columns) == RELATIVE_BEHAVIOR_COLUMNS
    assert row["rel_weakness_vs_gold_pct"] == 1.0
    assert row["rel_weakness_vs_gold_n"] == 2
    assert row["rel_weakness_vs_gdx_pct"] == 0.5
    assert row["rel_weakness_vs_gdxj_pct"] == 1.0
    assert row["rel_strength_vs_gold_pct"] == 1.0
    assert row["rel_strength_vs_gdx_pct"] == 0.5
    assert row["rel_strength_vs_gdxj_pct"] == 1.0
    assert row["n_weeks_gold"] == 4
    assert row["n_weeks_gdx"] == 4
    assert row["n_weeks_gdxj"] == 4
    assert row["downside_hit_rate_10pct"] == 0.5
    assert row["downside_hit_rate_n"] == 2
    assert row["upside_hit_rate_10pct"] == 0.5
    assert row["tail_avg_return_worst20pct"] == (-0.12 - 0.05) / 2
    assert row["tail_avg_return_worst20pct_n"] == 2
    assert pd.isna(row["tail_avg_return_worst10pct"])
    assert row["tail_avg_return_worst10pct_n"] == 1


def test_compute_relative_behavior_metrics_counts_each_benchmark_intersection():
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["AAA"] * 2,
            "week_period": ["w1", "w2"],
            "stock_log_ret": [-0.12, -0.05],
            "gold_log_ret": [-0.08, -0.04],
            "gdx_log_ret": [-0.10, None],
            "gdxj_log_ret": [0.0, 0.0],
        }
    )
    gold_regimes = pd.DataFrame(
        {
            "week_period": ["w1", "w2"],
            "gold_log_ret": [-0.08, -0.04],
            "gold_worst20_event": [True, True],
        }
    )

    metrics = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
    )
    row = metrics.iloc[0]

    assert row["rel_weakness_vs_gold_n"] == 2
    assert row["rel_weakness_vs_gdx_n"] == 1
    assert row["rel_weakness_vs_gdxj_n"] == 2
    assert pd.isna(row["rel_weakness_vs_gdx_pct"])


def test_compute_relative_behavior_threshold_config_changes_hit_rates():
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["AAA"] * 2,
            "week_period": ["w1", "w2"],
            "stock_log_ret": [-0.08, -0.12],
            "gold_log_ret": [-0.04, -0.05],
        }
    )
    gold_regimes = pd.DataFrame(
        {
            "week_period": ["w1", "w2"],
            "gold_log_ret": [-0.04, -0.05],
            "gold_worst20_event": [True, True],
        }
    )

    strict = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
        downside_hit_rate_threshold=-0.10,
    )
    loose = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
        downside_hit_rate_threshold=-0.05,
    )

    assert strict.loc[0, "downside_hit_rate_10pct"] == 0.5
    assert loose.loc[0, "downside_hit_rate_10pct"] == 1.0
