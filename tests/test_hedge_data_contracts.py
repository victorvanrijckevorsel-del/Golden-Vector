from datetime import date

import pandas as pd

from golden_vector.contracts.data_models import ToolAOutput, ToolBOutput
from golden_vector.features.options import compute_options_features


def test_hedge_reads_only_real_tool_a_columns():
    expected = {
        "ticker",
        "down_beta_core",
        "up_beta_core",
        "confidence_score",
        "confidence_label",
        "score_eligible",
    }

    assert expected <= set(ToolAOutput.model_fields)


def test_hedge_reads_only_real_tool_b_columns():
    expected = {
        "ticker",
        "share_price_usd",
        "screening_verdict",
    }

    assert expected <= set(ToolBOutput.model_fields)


def test_options_features_contract_contains_hedge_columns():
    features = compute_options_features(
        chain=pd.DataFrame(),
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
    )

    assert {
        "ticker",
        "optionability_tier",
        "iv_percentile_cross_sectional",
    } <= set(features)
