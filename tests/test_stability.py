import pandas as pd

from golden_vector.features.stability import compute_stability_score


def test_stability_score_requires_at_least_two_points():
    score = compute_stability_score(
        pd.DataFrame([{"gold_delta": 1.2}]),
        core_delta=1.2,
    )

    assert score is None


def test_stability_score_rewards_tighter_delta_dispersion():
    tight = compute_stability_score(
        pd.DataFrame([{"gold_delta": 1.0}, {"gold_delta": 1.05}, {"gold_delta": 0.95}]),
        core_delta=1.0,
    )
    noisy = compute_stability_score(
        pd.DataFrame([{"gold_delta": 1.0}, {"gold_delta": 1.8}, {"gold_delta": 0.2}]),
        core_delta=1.0,
    )

    assert tight is not None
    assert noisy is not None
    assert tight > noisy
