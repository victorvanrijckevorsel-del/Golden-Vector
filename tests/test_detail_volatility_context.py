"""Non-canonical window volatility context uses the ONE pipeline classifier.

Regression for the expanded-review HIGH finding: a serve-side fork read a
misspelled config attribute, swallowed the AttributeError, and classified
EVERY non-canonical window as UNKNOWN — rendering "Residual volatility is
moderate" copy for an 89%-vol window.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.serve.detail_panels import _compute_window_volatility


def _scoring_config():
    return load_app_config(ProjectPaths.discover()).app.scoring


def _weekly_series(*, weekly_vol: float, n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-05", periods=n, freq="W-FRI")
    return pd.DataFrame(
        {
            "as_of_date": dates,
            "stock_weekly_log_return": rng.normal(0, weekly_vol, n),
            "gold_weekly_log_return": rng.normal(0, 0.015, n),
        }
    )


def test_noisy_non_canonical_window_classifies_high_not_unknown() -> None:
    # ~12% weekly vol ≈ 87% annualized — far above every high-noise band.
    diag = _compute_window_volatility(
        tool_a_row={"volatility_anchor_window_id": "12M"},
        active_window="6M",
        weekly_series=_weekly_series(weekly_vol=0.12),
        scoring_config=_scoring_config(),
    )
    assert diag["volatility_context"] in {"HIGH_NOISE", "HIGH_DOWNSIDE_RISK"}, diag
    assert diag["residual_volatility"] is not None


def test_calm_non_canonical_window_classifies_low_noise_control() -> None:
    diag = _compute_window_volatility(
        tool_a_row={"volatility_anchor_window_id": "12M"},
        active_window="6M",
        weekly_series=_weekly_series(weekly_vol=0.005),
        scoring_config=_scoring_config(),
    )
    assert diag["volatility_context"] == "LOW_NOISE", diag
