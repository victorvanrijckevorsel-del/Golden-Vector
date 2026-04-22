import pandas as pd

from golden_vector.contracts.config_models import DeltaBucketThresholds
from golden_vector.features.delta import (
    assign_delta_bucket,
    compute_core_delta,
    compute_delta_component_score,
)


def test_compute_core_delta_uses_median_of_available_values():
    frame = pd.DataFrame({"gold_delta": [1.8, None, 0.9, 1.2]})

    result = compute_core_delta(frame)

    assert result == 1.2


def test_assign_delta_bucket_uses_absolute_magnitude_thresholds():
    thresholds = DeltaBucketThresholds(low_max=0.75, moderate_max=1.5)

    assert assign_delta_bucket(None, thresholds) is None
    assert assign_delta_bucket(-0.5, thresholds) == "LOW"
    assert assign_delta_bucket(1.2, thresholds) == "MODERATE"
    assert assign_delta_bucket(-2.0, thresholds) == "HIGH"


def test_compute_delta_component_score_returns_zero_for_missing_or_non_positive_delta():
    thresholds = DeltaBucketThresholds(low_max=0.75, moderate_max=1.5)

    assert compute_delta_component_score(None, thresholds) == 0.0
    assert compute_delta_component_score(0.0, thresholds) == 0.0
    assert compute_delta_component_score(-0.8, thresholds) == 0.0


def test_compute_delta_component_score_scales_across_low_moderate_and_high_bands():
    thresholds = DeltaBucketThresholds(low_max=0.75, moderate_max=1.5)

    low_band = compute_delta_component_score(0.375, thresholds)
    moderate_band = compute_delta_component_score(1.125, thresholds)
    high_band = compute_delta_component_score(3.0, thresholds)

    assert round(low_band, 4) == 0.25
    assert round(moderate_band, 4) == 0.625
    assert high_band == 1.0
