"""Tool B output schema contract."""

from __future__ import annotations

import pandas as pd

STALE_TOOL_B_MESSAGE = "Tool B output is stale - re-run python main.py refresh"

REMOVED_TOOL_B_TARGET_COLUMNS = {
    "adjusted_peer_pe",
    "adjusted_peak_pe",
    "target_price_peer_pe",
    "target_price_peak_pe",
    "target_price_peer_fcf",
    "target_price_peak_fcf",
    "upside_peer_pe_pct",
    "upside_peak_pe_pct",
    "upside_peer_fcf_pct",
    "upside_peak_fcf_pct",
    "best_target_price_usd",
    "best_upside_pct",
    "tool_b_score",
    "tool_b_rank",
}

REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS = {
    "finance_source",
    "cash_margin_usd_per_oz",
    "margin_pct",
    "enterprise_value_musd",
    "ev_ebitda",
    "forward_pe",
    "fcf_yield",
    "leverage",
    "ev_ebitda_our_view",
    "ev_ebitda_official",
    "ev_ebitda_differs",
    "leverage_our_view",
    "leverage_official",
    "leverage_differs",
    "net_debt_musd_our_view",
    "net_debt_musd_official",
    "interest_expense_musd",
    "interest_expense_musd_our_view",
    "interest_expense_musd_official",
    "cash_margin_usd_per_oz_our_view",
    "cash_margin_usd_per_oz_official",
    "margin_pct_our_view",
    "margin_pct_official",
    "forward_ebitda_musd_our_view",
    "forward_ebitda_musd_official",
    "forward_pe_our_view",
    "forward_pe_official",
    "fcf_yield_our_view",
    "fcf_yield_official",
    "screening_verdict_official",
    "confidence_official",
    "layer1_status_official",
    "layer1_pass_official",
    "layer1_fail_reasons_official",
    "layer2_incomplete_reasons_official",
    "enterprise_value_musd_official",
    "forward_revenue_musd_official",
    "forward_net_income_musd_official",
    "forward_eps_official",
    "sustainable_fcf_musd_official",
    "fundamental_check_score_official",
    "fundamental_check_rank_official",
    "fundamental_checks_passed_official",
    "fundamental_checks_total_official",
    "fundamental_check_summary_official",
    "financial_data_status",
    "divergent_field_count",
    "max_divergence_pct",
    "fundamental_check_score",
    "fundamental_check_rank",
    "fundamental_checks_passed",
    "fundamental_checks_total",
    "fundamental_check_summary",
    # Spot-gold provenance (Gold dial M1): readers must always know which
    # gold price a row was computed at and how far that is from spot.
    "gold_price_used",
    "spot_gold_usd",
    "spot_gold_date",
    "gold_price_basis",
}

TOOL_B_OUTPUT_COLUMNS = [
    "ticker",
    "as_of_date",
    "gold_price_assumption",
    "gold_price_used",
    "spot_gold_usd",
    "spot_gold_date",
    "gold_price_basis",
    "layer1_status",
    "layer1_pass",
    "layer1_fail_reasons",
    "layer2_incomplete_reasons",
    "screening_verdict",
    "confidence",
    "jurisdiction_tier",
    "market_cap_musd",
    "share_price_usd",
    "enterprise_value_musd",
    "production_oz",
    "aisc_usd_per_oz",
    "cash_cost_usd_per_oz",
    "net_debt_musd",
    "interest_expense_musd",
    "reserve_life_years",
    "cash_margin_usd_per_oz",
    "margin_pct",
    "forward_revenue_musd",
    "forward_ebitda_musd",
    "forward_net_income_musd",
    "forward_eps",
    "forward_pe",
    "ev_ebitda",
    "ev_ebitda_our_view",
    "ev_ebitda_official",
    "ev_ebitda_differs",
    "ev_ebitda_trailing",
    "sustainable_fcf_musd",
    "fcf_yield",
    "leverage",
    "leverage_our_view",
    "leverage_official",
    "leverage_differs",
    "enterprise_value_musd_our_view",
    "enterprise_value_musd_official",
    "financial_data_status",
    "financial_difference_summary",
    "divergent_field_count",
    "max_divergence_pct",
    "fundamental_check_score_official",
    "fundamental_check_rank_official",
    "fundamental_checks_passed_official",
    "fundamental_checks_total_official",
    "fundamental_check_summary_official",
    "fundamental_check_score",
    "fundamental_check_rank",
    "fundamental_checks_passed",
    "fundamental_checks_total",
    "fundamental_check_summary",
    "missing_manual_fields",
    "next_financial_report_date",
    "next_production_report_date",
    "snapshot_refresh_run_id",
    "snapshot_as_of_date",
    "snapshot_normalization_status",
    "fx_staleness_days",
    "fx_policy_max_staleness_days",
    "fx_policy_block_on_stale_fx",
    "source_run_id",
    "finance_source",
    "screening_verdict_official",
    "confidence_official",
    "layer1_status_official",
    "layer1_pass_official",
    "layer1_fail_reasons_official",
    "layer2_incomplete_reasons_official",
    "net_debt_musd_our_view",
    "net_debt_musd_official",
    "interest_expense_musd_our_view",
    "interest_expense_musd_official",
    "cash_margin_usd_per_oz_our_view",
    "cash_margin_usd_per_oz_official",
    "margin_pct_our_view",
    "margin_pct_official",
    "forward_revenue_musd_our_view",
    "forward_revenue_musd_official",
    "forward_ebitda_musd_our_view",
    "forward_ebitda_musd_official",
    "forward_net_income_musd_our_view",
    "forward_net_income_musd_official",
    "forward_eps_our_view",
    "forward_eps_official",
    "forward_pe_our_view",
    "forward_pe_official",
    "sustainable_fcf_musd_our_view",
    "sustainable_fcf_musd_official",
    "fcf_yield_our_view",
    "fcf_yield_official",
]


class ToolBStaleSchemaError(ValueError):
    """Raised when a Tool B artifact still uses the removed target schema."""


def validate_tool_b_output_schema(
    frame: pd.DataFrame,
    *,
    label: str = "Tool B output",
) -> pd.DataFrame:
    """Fail loudly if a Tool B artifact predates the simple-fundamentals schema."""

    if frame.empty and len(frame.columns) == 0:
        return frame
    old_columns = _removed_target_like_columns(frame.columns)
    missing_columns = sorted(REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS.difference(frame.columns))
    if old_columns or missing_columns:
        details: list[str] = []
        if old_columns:
            details.append("old target columns present: " + ", ".join(old_columns))
        if missing_columns:
            details.append("new fundamental columns missing: " + ", ".join(missing_columns))
        raise ToolBStaleSchemaError(
            f"{STALE_TOOL_B_MESSAGE} ({label}: {'; '.join(details)})"
        )
    return frame


def _removed_target_like_columns(columns: pd.Index | list[str]) -> list[str]:
    """Return removed Tool B target columns, including pattern-based variants."""
    removed: set[str] = set()
    for column in columns:
        name = str(column)
        if name in REMOVED_TOOL_B_TARGET_COLUMNS:
            removed.add(name)
            continue
        if name.startswith(("target_price_", "upside_", "best_")):
            removed.add(name)
    return sorted(removed)
