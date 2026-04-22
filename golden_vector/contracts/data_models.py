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


class ToolAOutput(StrictDataModel):
    ticker: str
    as_of_date: date
    core_delta: float | None = None
    delta_bucket: str | None = None
    gamma_proxy: float | None = None
    stability_score: float | None = None
    regime_tag: str | None = None
    tool_a_score: float | None = None
    tool_a_rank: int | None = None
    score_eligible: bool
    score_eligibility_reason: str
    coverage_summary: str
    eligible_core_horizon_count: int
    pass_core_horizon_count: int
    fail_core_horizon_count: int
    total_core_horizon_count: int
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
    size_category: str | None = None
    market_cap_musd: float | None = None
    share_price_usd: float | None = None
    forward_revenue_musd: float | None = None
    forward_ebitda_musd: float | None = None
    forward_net_income_musd: float | None = None
    forward_eps: float | None = None
    forward_pe: float | None = None
    ev_ebitda: float | None = None
    sustainable_fcf_musd: float | None = None
    fcf_yield: float | None = None
    leverage: float | None = None
    adjusted_peer_pe: float | None = None
    adjusted_peak_pe: float | None = None
    target_price_peer_pe: float | None = None
    target_price_peak_pe: float | None = None
    target_price_peer_fcf: float | None = None
    target_price_peak_fcf: float | None = None
    target_price_peer_evebitda: float | None = None
    target_price_peak_evebitda: float | None = None
    best_target_price_usd: float | None = None
    best_upside_pct: float | None = None
    tool_b_score: float | None = None
    tool_b_rank: int | None = None
    missing_manual_fields: str | None = None
    next_financial_report_date: date | None = None
    next_production_report_date: date | None = None
    source_run_id: str


class CombinedOutput(StrictDataModel):
    ticker: str
    as_of_date: date
    gold_price_assumption: float
    core_delta: float | None = None
    regime_tag: str | None = None
    tool_a_score: float | None = None
    tool_a_rank: int | None = None
    screening_verdict: str | None = None
    confidence: str | None = None
    tool_b_rank: int | None = None
    tool_b_score: float | None = None
    best_upside_pct: float | None = None
    forward_pe: float | None = None
    fcf_yield: float | None = None
    combined_score: float | None = None
    combined_rank: int | None = None
    combined_verdict: str
    join_status: str
    coverage_summary: str
    tool_a_run_id: str | None = None
    tool_b_run_id: str | None = None
    combined_run_id: str


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
