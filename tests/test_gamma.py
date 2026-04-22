import pandas as pd

from golden_vector.features.gamma import compute_gamma_proxy


def test_gamma_proxy_returns_zero_when_gold_absolute_returns_are_identical():
    metric_rows = pd.DataFrame(
        [
            {"gold_return": 0.02, "gold_delta": 0.8},
            {"gold_return": -0.02, "gold_delta": 1.0},
            {"gold_return": 0.02, "gold_delta": 1.4},
        ]
    )

    gamma_proxy = compute_gamma_proxy(metric_rows)

    assert gamma_proxy == 0.0
