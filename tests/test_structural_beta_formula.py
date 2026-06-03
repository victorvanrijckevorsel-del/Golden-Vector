from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.contracts.config_models import ScoringConfig
from golden_vector.model.structural import compute_regression, compute_window_metric


def test_compute_window_metric_uses_split_sample_ols_with_intercept():
    """Lock Tool A's descriptive beta formula, not a D-CAPM variant.

    Gold returns are symmetric: -10..-1 and +1..+10. Stock returns use slope
    3.0 in gold-down weeks and slope 2.0 in gold-up weeks. Because the gold
    sample has mean zero, the full-sample OLS-with-intercept slope is the
    weighted average 2.5.
    """

    gold_returns = [float(value) for value in range(-10, 0)] + [
        float(value) for value in range(1, 11)
    ]
    stock_returns = [
        3.0 * value if value < 0 else 2.0 * value
        for value in gold_returns
    ]
    window_rows = pd.DataFrame(
        {
            "gold_weekly_log_return": gold_returns,
            "stock_weekly_log_return": stock_returns,
        }
    )

    metric = compute_window_metric(
        ticker="AEM",
        as_of_date=pd.Timestamp("2026-05-29"),
        window_id="6M",
        window_rows=window_rows,
        issue_summary=None,
        scoring_config=ScoringConfig(),
    )

    assert metric["structural_delta"] == pytest.approx(2.5)
    assert metric["up_beta"] == pytest.approx(2.0)
    assert metric["down_beta"] == pytest.approx(3.0)
    assert metric["gamma_value"] == pytest.approx(1.0)
    assert metric["asymmetry_ratio"] == pytest.approx(2.0 / 3.0)
    assert metric["up_week_count"] == 10
    assert metric["down_week_count"] == 10


def test_compute_regression_includes_intercept():
    result = compute_regression(
        x=pd.Series([1.0, 2.0, 3.0]),
        y=pd.Series([7.0, 9.0, 11.0]),
    )

    assert result is not None
    assert result.beta == pytest.approx(2.0)
    assert result.alpha == pytest.approx(5.0)

