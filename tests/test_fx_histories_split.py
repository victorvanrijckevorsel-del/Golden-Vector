"""Unit tests for splitting standardized raw FX into per-base-currency histories.

This is the foundation for the portfolio schema-v2 cost-currency FX leg: a lot
whose cost is in GBP but quotes in AUD needs a GBP->USD history, looked up via
the existing merge_fx_asof helper.
"""

from datetime import date

import pandas as pd
import pytest

from golden_vector.normalize.calendar import (
    merge_fx_asof,
    split_fx_histories_by_base_currency,
)


def _raw_fx() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"base_currency": "GBP", "date": date(2026, 6, 1), "fx_rate_to_usd": 1.27, "source_symbol": "GBPUSD=X"},
            {"base_currency": "GBP", "date": date(2026, 6, 8), "fx_rate_to_usd": 1.29, "source_symbol": "GBPUSD=X"},
            {"base_currency": "AUD", "date": date(2026, 6, 1), "fx_rate_to_usd": 0.66, "source_symbol": "AUDUSD=X"},
        ]
    )


def test_split_groups_by_base_currency_and_preserves_lookup_columns():
    histories = split_fx_histories_by_base_currency(_raw_fx())

    assert set(histories) == {"GBP", "AUD"}
    assert len(histories["GBP"]) == 2
    assert len(histories["AUD"]) == 1
    # The columns merge_fx_asof/build_fx_lookup need must survive the split.
    for needed in ("date", "fx_rate_to_usd", "source_symbol"):
        assert needed in histories["GBP"].columns


def test_split_empty_returns_empty_mapping():
    assert split_fx_histories_by_base_currency(pd.DataFrame()) == {}


def test_split_missing_required_columns_fails_loud():
    bad = pd.DataFrame([{"base_currency": "GBP", "date": date(2026, 6, 1)}])  # no fx_rate_to_usd/source_symbol
    with pytest.raises(ValueError, match="missing required columns"):
        split_fx_histories_by_base_currency(bad)


def test_split_output_feeds_merge_fx_asof_backward():
    histories = split_fx_histories_by_base_currency(_raw_fx())
    # A cost dated 2026-06-05 should pick up the 2026-06-01 GBP rate (backward as-of).
    frame = pd.DataFrame([{"cost_basis_as_of_date": date(2026, 6, 5)}])

    merged = merge_fx_asof(frame, date_column="cost_basis_as_of_date", fx_history=histories["GBP"])

    assert float(merged.loc[0, "fx_rate_to_usd"]) == pytest.approx(1.27)
