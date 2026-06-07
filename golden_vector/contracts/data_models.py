"""Core data contracts for pipeline datasets."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StrictDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawEquityDaily(StrictDataModel):
    ticker: str
    date: date
    open_local: float | None = None
    high_local: float | None = None
    low_local: float | None = None
    close_local: float | None = None
    adj_close_local: float | None = None
    volume: float | None = None
    currency: str
    exchange: str | None = None
    source: str
    source_symbol: str
    fetched_at_utc: datetime


class RawFxDaily(StrictDataModel):
    base_currency: str
    quote_currency: str
    date: date
    fx_pair: str
    fx_rate_to_usd: float
    source: str
    source_symbol: str
    fetched_at_utc: datetime


class RawGoldDaily(StrictDataModel):
    date: date
    gold_symbol: str
    close_usd: float
    adj_close_usd: float | None = None
    source: str
    source_symbol: str
    fetched_at_utc: datetime


class MarketSnapshot(StrictDataModel):
    ticker: str
    snapshot_date: date
    share_price_local: float
    currency: str
    fx_rate_to_usd: float | None = None
    share_price_usd: float | None = None
    market_cap_usd: float | None = None
    shares_outstanding: float | None = None
    source: str
    source_run_id: str


class UsdEquityDaily(StrictDataModel):
    ticker: str
    date: date
    currency: str
    exchange: str | None = None
    open_local: float | None = None
    high_local: float | None = None
    low_local: float | None = None
    close_local: float | None = None
    adj_close_local: float | None = None
    return_basis_local: float | None = None
    fx_rate_to_usd: float | None = None
    fx_source_date: date | None = None
    fx_source_symbol: str | None = None
    fx_staleness_days: int | None = None
    open_usd: float | None = None
    high_usd: float | None = None
    low_usd: float | None = None
    close_usd: float | None = None
    adj_close_usd: float | None = None
    return_basis_usd: float | None = None
    volume: float | None = None
    source: str
    source_symbol: str
    fetched_at_utc: datetime
    normalization_status: str


class NormalizedMarketSnapshot(StrictDataModel):
    ticker: str
    snapshot_date: date
    currency: str
    share_price_local: float
    fx_rate_to_usd: float | None = None
    fx_source_date: date | None = None
    fx_source_symbol: str | None = None
    fx_staleness_days: int | None = None
    share_price_usd: float | None = None
    market_cap_usd: float | None = None
    shares_outstanding: float | None = None
    source: str
    source_run_id: str
    normalization_status: str


class HorizonMetric(StrictDataModel):
    ticker: str
    as_of_date: date
    horizon_id: str
    horizon_mode: str
    horizon_unit: str
    horizon_value: int
    start_date: date | None = None
    end_date: date
    equity_return: float | None = None
    gold_return: float | None = None
    gold_delta: float | None = None
    coverage_flag: str
    coverage_reason: str
    official_scoring_eligible: bool


class ToolAStructuralWindowMetric(StrictDataModel):
    ticker: str
    as_of_date: date
    window_id: str
    week_count: int
    window_status: str
    window_reason: str
    structural_delta: float | None = None
    intercept_alpha: float | None = None
    r_squared: float | None = None
    up_week_count: int = 0
    down_week_count: int = 0
    up_beta: float | None = None
    down_beta: float | None = None
    gamma_value: float | None = None
    asymmetry_ratio: float | None = None
    normalization_issue_summary: str | None = None
    source_run_id: str | None = None


class ToolAOutput(StrictDataModel):
    ticker: str
    as_of_date: date
    anchor_window_id: str | None = None
    volatility_anchor_window_id: str | None = None
    structural_delta_6m: float | None = None
    structural_delta_12m: float | None = None
    structural_delta_3y: float | None = None
    structural_delta_core: float | None = None
    gamma_6m: float | None = None
    gamma_12m: float | None = None
    gamma_3y: float | None = None
    structural_gamma_core: float | None = None
    up_beta_6m: float | None = None
    down_beta_6m: float | None = None
    up_beta_12m: float | None = None
    down_beta_12m: float | None = None
    up_beta_3y: float | None = None
    down_beta_3y: float | None = None
    up_beta_core: float | None = None
    down_beta_core: float | None = None
    asymmetry_ratio_6m: float | None = None
    asymmetry_ratio_12m: float | None = None
    asymmetry_ratio_3y: float | None = None
    asymmetry_ratio_core: float | None = None
    r_squared_6m: float | None = None
    r_squared_12m: float | None = None
    r_squared_3y: float | None = None
    weeks_6m: int = 0
    weeks_12m: int = 0
    weeks_3y: int = 0
    window_status_6m: str | None = None
    window_status_12m: str | None = None
    window_status_3y: str | None = None
    delta_stability_score: float | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    total_volatility_52w: float | None = None
    residual_volatility_52w: float | None = None
    downside_volatility_52w: float | None = None
    volatility_context: str | None = None
    profile_label: str | None = None
    tool_a_score: float | None = None
    tool_a_rank: int | None = None
    score_eligible: bool
    score_eligibility_reason: str
    eligible_structural_window_count: int
    positive_delta_window_count: int
    normalization_issue_summary: str | None = None
    snapshot_refresh_run_id: str
    fx_policy_max_staleness_days: int
    fx_policy_block_on_stale_fx: bool
    delta_explanation: str
    gamma_explanation: str
    asymmetry_explanation: str
    volatility_explanation: str
    confidence_explanation: str
    interaction_explanation: str
    tool_a_summary_explanation: str
    source_run_id: str


class ManualScreeningInput(StrictDataModel):
    ticker: str
    production_oz: float | None = None
    aisc_usd_per_oz: float | None = None
    cash_cost_usd_per_oz: float | None = None
    royalty_rate: float | None = None
    sustaining_capex_musd: float | None = None
    da_musd: float | None = None
    interest_expense_musd: float | None = None
    tax_rate: float | None = None
    reserve_life_years: float | None = None
    net_debt_musd: float | None = None
    ebitda_ltm_musd: float | None = None


class SourceVerificationRecord(StrictDataModel):
    ticker: str
    field_name: str
    verification_status: str
    source_date: date | None = None
    source_url: str | None = None
    notes: str | None = None


class ToolBOutput(StrictDataModel):
    ticker: str
    as_of_date: date
    gold_price_assumption: float
    layer1_status: str
    layer1_pass: bool
    layer1_fail_reasons: str | None = None
    layer2_incomplete_reasons: str | None = None
    screening_verdict: str
    confidence: str
    jurisdiction_tier: int | None = None
    market_cap_musd: float | None = None
    share_price_usd: float | None = None
    enterprise_value_musd: float | None = None
    production_oz: float | None = None
    aisc_usd_per_oz: float | None = None
    cash_cost_usd_per_oz: float | None = None
    net_debt_musd: float | None = None
    reserve_life_years: float | None = None
    cash_margin_usd_per_oz: float | None = None
    margin_pct: float | None = None
    forward_revenue_musd: float | None = None
    forward_ebitda_musd: float | None = None
    forward_net_income_musd: float | None = None
    forward_eps: float | None = None
    forward_pe: float | None = None
    ev_ebitda: float | None = None
    sustainable_fcf_musd: float | None = None
    fcf_yield: float | None = None
    leverage: float | None = None
    fundamental_check_score: float | None = None
    fundamental_check_rank: int | None = None
    fundamental_checks_passed: int | None = None
    fundamental_checks_total: int | None = None
    fundamental_check_summary: str | None = None
    missing_manual_fields: str | None = None
    next_financial_report_date: date | None = None
    next_production_report_date: date | None = None
    snapshot_refresh_run_id: str | None = None
    snapshot_as_of_date: date | None = None
    snapshot_normalization_status: str | None = None
    fx_staleness_days: int | None = None
    fx_policy_max_staleness_days: int
    fx_policy_block_on_stale_fx: bool
    source_run_id: str


class FetchStatusRecord(StrictDataModel):
    dataset: str
    entity: str
    source_symbol: str
    status: str
    row_count: int = 0
    started_at_utc: datetime
    completed_at_utc: datetime
    message: str | None = None


class QaCheckResult(StrictDataModel):
    check_name: str
    status: str
    dataset: str
    entity: str
    message: str
