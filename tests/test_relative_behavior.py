import math

import pandas as pd
import pytest

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
        downside_hit_rate_log_threshold=math.log1p(-0.10),
        upside_hit_rate_log_threshold=math.log1p(0.10),
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


def test_hit_evidence_period_uses_published_week_period_end_dates():
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["AAA"] * 3,
            "week_period": [
                "2026-01-03/2026-01-09",
                "2026-01-10/2026-01-16",
                "2026-01-17/2026-01-23",
            ],
            "stock_log_ret": [-0.12, -0.05, -0.11],
            "gold_log_ret": [-0.08, -0.04, -0.06],
        }
    )
    gold_regimes = pd.DataFrame(
        {
            "week_period": weekly_returns["week_period"],
            "gold_log_ret": weekly_returns["gold_log_ret"],
            "gold_worst20_event": [True, False, True],
        }
    )

    metrics = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
    )

    assert metrics.loc[0, "downside_period_start"] == pd.Timestamp("2026-01-09")
    assert metrics.loc[0, "downside_period_end"] == pd.Timestamp("2026-01-23")


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
        downside_hit_rate_log_threshold=math.log1p(-0.10),
    )
    loose = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
        downside_hit_rate_log_threshold=math.log1p(-0.05),
    )

    assert strict.loc[0, "downside_hit_rate_10pct"] == 0.5
    assert loose.loc[0, "downside_hit_rate_10pct"] == 1.0


def test_downside_hit_threshold_is_exact_ordinary_ten_percent_decline():
    """C2 boundary: 'fell at least 10%' means the ORDINARY price return.

    A -0.10 LOG return is only a -9.52% ordinary decline and must NOT count;
    exactly log(0.90) is exactly -10% ordinary and MUST count.
    """
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["AAA"] * 3,
            "week_period": ["w1", "w2", "w3"],
            # exactly -10% ordinary | -9.52% ordinary | -10.6% ordinary
            # (boundary row uses log1p(-0.10), the config's own conversion, to
            # avoid a 1-ulp float mismatch with math.log(0.90))
            "stock_log_ret": [math.log1p(-0.10), -0.10, math.log(0.894)],
            "gold_log_ret": [-0.04, -0.05, -0.06],
        }
    )
    gold_regimes = pd.DataFrame(
        {
            "week_period": ["w1", "w2", "w3"],
            "gold_log_ret": [-0.04, -0.05, -0.06],
            "gold_worst20_event": [True, True, True],
        }
    )

    metrics = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
        downside_hit_rate_log_threshold=math.log1p(-0.10),
    )

    assert metrics.loc[0, "downside_hit_rate_10pct"] == 2 / 3
    assert metrics.loc[0, "downside_hit_rate_n"] == 3


def test_upside_hit_threshold_is_exact_ordinary_ten_percent_rally():
    """C2 mirror: +10% ordinary is log(1.10)=0.0953, not 0.10 log points."""
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["AAA"] * 3,
            "week_period": ["w1", "w2", "w3"],
            # exactly +10% ordinary | +9.42% ordinary | +10.52% ordinary
            "stock_log_ret": [math.log1p(0.10), 0.09, 0.10],
            "gold_log_ret": [0.04, 0.05, 0.06],
        }
    )
    gold_regimes = pd.DataFrame(
        {
            "week_period": ["w1", "w2", "w3"],
            "gold_log_ret": [0.04, 0.05, 0.06],
            "gold_best20_event": [True, True, True],
        }
    )

    metrics = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=2,
        upside_hit_rate_log_threshold=math.log1p(0.10),
    )

    assert metrics.loc[0, "upside_hit_rate_10pct"] == 2 / 3


def test_downside_context_primitives_are_aligned_and_recent_is_separate():
    weeks = pd.date_range("2023-01-06", periods=6, freq="52W-FRI")
    weekly_returns = pd.DataFrame(
        {
            "ticker": ["AAA"] * 6,
            "week_period": [str(pd.Period(day, freq="W-FRI")) for day in weeks],
            "stock_log_ret": [
                math.log1p(-0.20),
                math.log1p(-0.05),
                math.log1p(-0.12),
                math.log1p(-0.08),
                math.log1p(-0.15),
                math.log1p(-0.18),
            ],
            "gold_log_ret": [-0.05] * 6,
            "gdx_log_ret": [
                math.log1p(-0.11),
                math.log1p(-0.04),
                math.log1p(-0.08),
                math.log1p(-0.12),
                math.log1p(-0.09),
                math.log1p(-0.13),
            ],
        }
    )
    regimes = pd.DataFrame(
        {
            "week_period": weekly_returns["week_period"],
            "gold_log_ret": weekly_returns["gold_log_ret"],
            "gold_worst20_event": [True] * 6,
        }
    )

    row = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=regimes,
        min_events=2,
        downside_recent_years=2,
    ).iloc[0]

    assert row["downside_compare_n"] == 6
    assert row["downside_compare_stock_hit_count"] == 4
    assert row["downside_compare_gdx_hit_count"] == 3
    assert row["downside_compare_stock_hit_rate"] == 4 / 6
    assert row["downside_compare_stock_median_return"] == pytest.approx(-0.165)
    assert row["downside_compare_stock_worst_return"] == pytest.approx(-0.20)
    assert row["downside_recent_n"] == 3
    assert row["downside_recent_stock_hit_count"] == 2
    assert row["downside_recent_stock_hit_rate"] == pytest.approx(2 / 3)
