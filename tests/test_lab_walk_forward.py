"""M1: walk-forward folds, evaluation metrics, and the three leakage canaries."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from golden_vector.lab.evaluation import (
    evaluate_predictions,
    mae_improvement_pct,
)
from golden_vector.lab.forward_returns import build_forward_return_panel
from golden_vector.lab.walk_forward import (
    assert_no_label_overlap,
    effective_n,
    generate_folds,
)


def _weekly_grid(n_weeks: int) -> list[str]:
    periods = pd.period_range("2020-01-03", periods=n_weeks, freq="W-FRI")
    return [str(period) for period in periods]


# ---------------------------------------------------------------- folds


def test_folds_purge_label_horizon_before_test() -> None:
    grid = _weekly_grid(120)
    folds = generate_folds(
        grid,
        label_horizon_weeks=13,
        min_train_weeks=52,
        test_weeks=13,
    )
    assert folds
    for fold in folds:
        assert len(fold.purged_periods) == 13
        assert_no_label_overlap(fold, label_horizon_weeks=13)
        # No leakage by construction: ordering train < purge < test.
        assert fold.train_periods[-1] < fold.purged_periods[0]
        assert fold.purged_periods[-1] < fold.test_periods[0]


def test_folds_expand_and_step() -> None:
    grid = _weekly_grid(150)
    folds = generate_folds(
        grid,
        label_horizon_weeks=4,
        min_train_weeks=52,
        test_weeks=13,
    )
    assert len(folds) >= 2
    assert len(folds[1].train_periods) > len(folds[0].train_periods)
    assert folds[0].test_periods[-1] < folds[1].test_periods[0]


def test_overlap_assertion_fires_on_bad_fold() -> None:
    grid = _weekly_grid(80)
    folds = generate_folds(
        grid,
        label_horizon_weeks=1,
        min_train_weeks=52,
        test_weeks=13,
    )
    with pytest.raises(AssertionError, match="overlap"):
        assert_no_label_overlap(folds[0], label_horizon_weeks=26)


def test_effective_n_divides_by_horizon() -> None:
    assert effective_n(260, label_horizon_weeks=26) == 10.0


# ------------------------------------------------------- forward labels


def test_forward_returns_strictly_forward_and_complete_only() -> None:
    weekly = pd.DataFrame(
        {
            "ticker": ["AEM"] * 6,
            "week_period": _weekly_grid(6),
            "stock_log_ret": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
            "gold_log_ret": [0.0] * 6,
            "gdx_log_ret": [0.005] * 6,
            "gdxj_log_ret": [0.004] * 6,
        }
    )
    panel = build_forward_return_panel(weekly, horizons_weeks=[2])
    row0 = panel.iloc[0]
    # t=0 label = weeks 1..2 (0.02 + 0.03), NOT week 0's own 0.01.
    assert row0["fwd_log_ret_2w"] == pytest.approx(0.05)
    assert row0["fwd_alpha_gdx_2w"] == pytest.approx(0.05 - 0.01)
    # The final 2 weeks have no complete forward window.
    assert panel["fwd_log_ret_2w"].notna().sum() == 4


def test_forward_returns_require_full_window() -> None:
    weekly = pd.DataFrame(
        {
            "ticker": ["AEM"] * 4,
            "week_period": _weekly_grid(4),
            "stock_log_ret": [0.01, np.nan, 0.03, 0.04],
            "gold_log_ret": [0.0] * 4,
            "gdx_log_ret": [0.0] * 4,
            "gdxj_log_ret": [0.0] * 4,
        }
    )
    panel = build_forward_return_panel(weekly, horizons_weeks=[2])
    # t=0 window covers the NaN week — must be NA, not a silent partial sum.
    assert pd.isna(panel.iloc[0]["fwd_log_ret_2w"])
    assert panel.iloc[1]["fwd_log_ret_2w"] == pytest.approx(0.07)


def test_forward_returns_missing_week_row_does_not_stretch_window() -> None:
    """An absent week (missing row, not NaN) must not let an h-week label
    silently span more than h calendar weeks."""

    grid = _weekly_grid(6)
    weekly = pd.DataFrame(
        {
            "ticker": ["AEM"] * 5,
            "week_period": [grid[0], grid[1], grid[3], grid[4], grid[5]],  # week 2 absent
            "stock_log_ret": [0.01, 0.02, 0.04, 0.05, 0.06],
            "gold_log_ret": [0.0] * 5,
            "gdx_log_ret": [0.0] * 5,
            "gdxj_log_ret": [0.0] * 5,
        }
    )
    panel = build_forward_return_panel(weekly, horizons_weeks=[2])
    assert len(panel) == 6  # gap week reinstated as a NaN row
    by_period = panel.set_index("week_period")
    # t=1's window covers weeks 2..3; week 2 is missing -> NA, never 0.02+0.04.
    assert pd.isna(by_period.loc[grid[1], "fwd_log_ret_2w"])
    assert pd.isna(by_period.loc[grid[0], "fwd_log_ret_2w"])
    # t=3's window covers weeks 4..5, fully present.
    assert by_period.loc[grid[3], "fwd_log_ret_2w"] == pytest.approx(0.11)
    assert (panel["ticker"] == "AEM").all()


# ------------------------------------------------------- evaluation


def _panel(n_dates: int = 30, n_tickers: int = 20, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for date in _weekly_grid(n_dates):
        labels = rng.normal(0, 0.05, n_tickers)
        for i in range(n_tickers):
            rows.append({"week_period": date, "ticker": f"T{i}", "label": labels[i]})
    return pd.DataFrame(rows)


def test_evaluation_scores_a_skilled_signal() -> None:
    panel = _panel()
    rng = np.random.default_rng(11)
    panel["prediction"] = panel["label"] * 0.5 + rng.normal(0, 0.05, len(panel))
    result = evaluate_predictions(panel, label_horizon_weeks=4)
    assert result.rank_ic_mean is not None and result.rank_ic_mean > 0.2
    assert result.rank_ic_t_stat is not None and result.rank_ic_t_stat > 2
    assert not result.leakage_alarm
    assert result.effective_n_dates == result.n_dates / 4


# ------------------------------------------- the three leakage canaries


def test_canary_1_label_as_feature_trips_alarm() -> None:
    panel = _panel()
    panel["prediction"] = panel["label"]  # rigged: the label itself
    result = evaluate_predictions(panel, label_horizon_weeks=4)
    assert result.leakage_alarm
    assert any("LEAKAGE" in note for note in result.notes)


def test_canary_2_shuffled_labels_show_no_skill() -> None:
    panel = _panel()
    rng = np.random.default_rng(13)
    panel["prediction"] = panel["label"] * 0.5
    panel["label"] = rng.permutation(panel["label"].to_numpy())
    result = evaluate_predictions(panel, label_horizon_weeks=4)
    assert result.rank_ic_t_stat is None or abs(result.rank_ic_t_stat) < 2
    assert not result.leakage_alarm


def test_canary_3_forward_shifted_feature_is_caught() -> None:
    """A feature built from t+1..t+h returns IS the label — alarm must fire."""

    weekly = pd.DataFrame(
        {
            "ticker": np.repeat([f"T{i}" for i in range(10)], 40),
            "week_period": _weekly_grid(40) * 10,
            "stock_log_ret": np.random.default_rng(5).normal(0, 0.03, 400),
            "gold_log_ret": 0.0,
            "gdx_log_ret": 0.0,
            "gdxj_log_ret": 0.0,
        }
    )
    panel = build_forward_return_panel(weekly, horizons_weeks=[4])
    rigged = panel.dropna(subset=["fwd_log_ret_4w"]).rename(
        columns={"fwd_log_ret_4w": "label"}
    )
    rigged["prediction"] = rigged["label"].astype(float)  # the shifted feature
    result = evaluate_predictions(rigged, label_horizon_weeks=4)
    assert result.leakage_alarm


# ------------------------------------------------------- gate helper


def test_mae_improvement_pct() -> None:
    assert mae_improvement_pct(0.09, 0.10) == pytest.approx(10.0)
    assert mae_improvement_pct(0.11, 0.10) == pytest.approx(-10.0)
    assert mae_improvement_pct(0.1, 0.0) is None
