from __future__ import annotations

import math

import pandas as pd
import pytest

from golden_vector.features.percentile_ranks import oriented_percentile


def test_oriented_percentile_high_good():
    result = oriented_percentile(pd.Series([10, 20, 30]), high_good=True)

    assert result.tolist() == pytest.approx([100 / 3, 200 / 3, 100.0])


def test_oriented_percentile_low_good():
    result = oriented_percentile(pd.Series([10, 20, 30]), high_good=False)

    assert result.tolist() == pytest.approx([100.0, 200 / 3, 100 / 3])


def test_oriented_percentile_uses_average_rank_for_ties():
    result = oriented_percentile(pd.Series([10, 10, 30]), high_good=True)

    assert result.tolist() == [50.0, 50.0, 100.0]


def test_oriented_percentile_keeps_all_missing_as_missing():
    result = oriented_percentile(pd.Series([None, math.nan]), high_good=True)

    assert result.isna().all()


def test_oriented_percentile_one_value_is_100():
    result = oriented_percentile(pd.Series([None, 7.0]), high_good=True)

    assert math.isnan(result.iloc[0])
    assert result.iloc[1] == 100.0


def test_oriented_percentile_handles_negative_values():
    result = oriented_percentile(pd.Series([-2.0, -1.0, 0.0]), high_good=True)

    assert result.tolist() == pytest.approx([100 / 3, 200 / 3, 100.0])
