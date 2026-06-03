from dataclasses import fields
from datetime import date

import pandas as pd

from golden_vector.contracts.data_models import ToolAOutput, ToolBOutput
from golden_vector.features.options import compute_options_features
from golden_vector.hedge.candidate_puts import OptionCandidate
from golden_vector.hedge.scenarios import CandidateScenarioBundle, ScenarioRow


def test_hedge_reads_only_real_tool_a_columns():
    expected = {
        "ticker",
        "structural_delta_core",
        "down_beta_core",
        "up_beta_core",
        "confidence_score",
        "confidence_label",
        "score_eligible",
        "snapshot_refresh_run_id",
        "source_run_id",
    }

    assert expected <= set(ToolAOutput.model_fields)


def test_hedge_reads_only_real_tool_b_columns():
    expected = {
        "ticker",
        "share_price_usd",
        "screening_verdict",
        "snapshot_refresh_run_id",
        "source_run_id",
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
    features.update(
        {
            "run_id": "options-run",
            "underlying_price": 50.0,
            "options_snapshot_path": "data/runs/options-run/snapshots/options/AEM.parquet",
            "options_fetch_status": "OK",
            "options_fetch_message": None,
        }
    )

    assert {
        "ticker",
        "run_id",
        "underlying_price",
        "options_snapshot_path",
        "options_fetch_status",
        "options_fetch_message",
        "optionability_tier",
        "iv_percentile_cross_sectional",
        "atm_iv_60d",
        "put_iv_25d_60d",
        "call_iv_25d_60d",
        "iv_skew_60d",
        "iv_rv_ratio_60d",
        "put_call_oi_ratio_total",
        "put_call_oi_ratio_otm",
    } <= set(features)


def test_option_candidate_and_scenario_contract_contains_rendered_fields():
    option_candidate_fields = {field.name for field in fields(OptionCandidate)}
    assert {
        "ticker",
        "horizon_days",
        "expiration",
        "days_to_expiry",
        "strike",
        "bid",
        "ask",
        "mid",
        "open_interest",
        "volume",
        "implied_volatility",
        "delta",
        "delta_gap",
        "premium_pct_spot",
        "underlying_price",
        "option_type",
    } <= option_candidate_fields

    scenario_row_fields = {field.name for field in fields(ScenarioRow)}
    assert {
        "gold_pct_change",
        "implied_stock_price",
        "stock_clamped_at_zero",
        "expiry_value_per_contract",
        "current_value_per_contract",
        "pnl_per_contract_at_expiry",
        "pnl_per_contract_if_closed_today",
        "net_pnl_at_expiry",
        "net_pnl_if_closed_today",
    } <= scenario_row_fields

    bundle_fields = {field.name for field in fields(CandidateScenarioBundle)}
    assert {
        "ticker",
        "horizon",
        "candidate",
        "rows",
        "breakeven_gold_pct",
        "breakeven_annotation",
        "gold_beta_used",
        "confidence_label",
        "skipped_reason",
    } <= bundle_fields
