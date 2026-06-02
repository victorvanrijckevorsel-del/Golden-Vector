"""Universe-level speculative put candidate selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.hedge._helpers import (
    as_float as _as_float,
    rows_by_ticker_dict as _rows_by_ticker,
    unique_preserving_order,
)
from golden_vector.hedge.candidate_puts import CandidatePut, build_candidate_put_grid
from golden_vector.hedge.scenarios import CandidateScenarioBundle, compute_scenario_bundle


@dataclass(frozen=True)
class SpeculationTickerBlock:
    ticker: str
    current_stock_price: float | None
    optionability_tier: str
    iv_percentile_cross_sectional: float | None
    down_beta_core: float | None
    confidence_label: str
    candidates: list[CandidatePut]
    scenario_bundles: list[CandidateScenarioBundle]
    annotations: list[str]


def build_speculation_section(
    *,
    paths: ProjectPaths,
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
    tool_a_frame: pd.DataFrame,
    tool_b_frame: pd.DataFrame,
    raw_options_by_ticker: dict[str, pd.DataFrame],
    risk_free_rate: float | None,
    config: HedgeReadinessConfig,
    quantity: int | None = None,
    max_tickers: int | None = None,
) -> list[SpeculationTickerBlock]:
    """Build universe-level put candidate blocks, independent of holdings."""

    _ = paths
    selected = _selected_features(
        options_features=options_features,
        optionability_tier_min=config.optionability_tier_min,
        max_tickers=max_tickers
        if max_tickers is not None
        else config.speculation_max_tickers_default,
    )
    if not selected:
        return []

    tool_a_by_ticker = _rows_by_ticker(tool_a_frame)
    tool_b_by_ticker = _rows_by_ticker(tool_b_frame)
    chains_by_ticker = {
        str(ticker).upper(): chain
        for ticker, chain in raw_options_by_ticker.items()
    }
    scenario_quantity = (
        quantity
        if quantity is not None
        else config.default_scenario_quantity
    )
    return [
        _ticker_block(
            feature=feature,
            tool_a_row=tool_a_by_ticker.get(feature["ticker"]),
            tool_b_row=tool_b_by_ticker.get(feature["ticker"]),
            chain=chains_by_ticker.get(feature["ticker"], pd.DataFrame()),
            risk_free_rate=risk_free_rate,
            config=config,
            quantity=scenario_quantity,
        )
        for feature in selected
    ]


def _selected_features(
    *,
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
    optionability_tier_min: str,
    max_tickers: int,
) -> list[dict[str, Any]]:
    if max_tickers <= 0:
        return []
    allowed_tiers = (
        {"directly_hedgeable", "thin"}
        if optionability_tier_min == "thin"
        else {"directly_hedgeable"}
    )
    rows = [
        row
        for row in _feature_rows(options_features)
        if row["optionability_tier"] in allowed_tiers
    ]
    rows.sort(
        key=lambda row: (
            row["iv_percentile_cross_sectional"] is None,
            row["iv_percentile_cross_sectional"]
            if row["iv_percentile_cross_sectional"] is not None
            else 0.0,
            row["ticker"],
        )
    )
    return rows[:max_tickers]


def _ticker_block(
    *,
    feature: dict[str, Any],
    tool_a_row: dict[str, Any] | None,
    tool_b_row: dict[str, Any] | None,
    chain: pd.DataFrame,
    risk_free_rate: float | None,
    config: HedgeReadinessConfig,
    quantity: int,
) -> SpeculationTickerBlock:
    ticker = feature["ticker"]
    current_stock_price = _current_stock_price(
        feature=feature,
        tool_b_row=tool_b_row,
        chain=chain,
    )
    down_beta_core = _as_float((tool_a_row or {}).get("down_beta_core"))
    confidence_label = _confidence_label(tool_a_row)
    annotations: list[str] = []
    candidates = _candidate_grid(
        ticker=ticker,
        chain=chain,
        current_stock_price=current_stock_price,
        risk_free_rate=risk_free_rate,
        config=config,
    )
    if current_stock_price is None:
        annotations.append("Current stock price is unavailable.")
    if chain.empty:
        annotations.append("No raw options chain is available.")
    if risk_free_rate is None:
        annotations.append("Risk-free rate is unavailable; using 0% fallback.")
    if not candidates:
        annotations.append("No usable listed put candidate found for the configured horizons.")

    scenario_bundles = [
        compute_scenario_bundle(
            candidate=candidate,
            current_stock_price=current_stock_price or 0.0,
            down_beta_core=down_beta_core,
            confidence_label=confidence_label,
            risk_free_rate=risk_free_rate or 0.0,
            gold_scenarios=tuple(config.default_scenarios),
            quantity=quantity,
        )
        for candidate in candidates
    ]
    annotations.extend(_scenario_annotations(scenario_bundles))
    return SpeculationTickerBlock(
        ticker=ticker,
        current_stock_price=current_stock_price,
        optionability_tier=feature["optionability_tier"],
        iv_percentile_cross_sectional=feature["iv_percentile_cross_sectional"],
        down_beta_core=down_beta_core,
        confidence_label=confidence_label,
        candidates=candidates,
        scenario_bundles=scenario_bundles,
        annotations=unique_preserving_order(annotations),
    )


def _candidate_grid(
    *,
    ticker: str,
    chain: pd.DataFrame,
    current_stock_price: float | None,
    risk_free_rate: float | None,
    config: HedgeReadinessConfig,
) -> list[CandidatePut]:
    if current_stock_price is None or current_stock_price <= 0:
        return []
    return build_candidate_put_grid(
        ticker=ticker,
        chain=chain,
        underlying_price=current_stock_price,
        risk_free_rate=risk_free_rate if risk_free_rate is not None else 0.0,
        target_horizons_days=tuple(config.target_horizons_days),
        target_delta=config.target_delta,
        max_spread_pct=config.candidate_max_spread_pct,
        min_open_interest=config.candidate_min_open_interest,
        min_volume=config.candidate_min_volume,
        min_implied_volatility=config.candidate_min_implied_volatility,
        max_implied_volatility=config.candidate_max_implied_volatility,
    )


def _scenario_annotations(bundles: list[CandidateScenarioBundle]) -> list[str]:
    annotations: list[str] = []
    for bundle in bundles:
        if bundle.skipped_reason:
            annotations.append(bundle.skipped_reason)
        if bundle.breakeven_annotation:
            annotations.append(bundle.breakeven_annotation)
        if any(row.stock_clamped_at_zero for row in bundle.rows):
            annotations.append("One or more scenarios clamp modeled stock price at $0.")
    return annotations


def _feature_rows(
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    if isinstance(options_features, pd.DataFrame):
        iterable = (row.to_dict() for _, row in options_features.iterrows())
    else:
        iterable = (_last_feature_row(ticker, frame) for ticker, frame in options_features.items())
    rows: list[dict[str, Any]] = []
    for row in iterable:
        ticker = str(row.get("ticker") or "").upper()
        optionability_tier = str(row.get("optionability_tier") or "none")
        if not ticker:
            continue
        rows.append(
            {
                **row,
                "ticker": ticker,
                "optionability_tier": optionability_tier,
                "iv_percentile_cross_sectional": _as_float(
                    row.get("iv_percentile_cross_sectional")
                ),
            }
        )
    return rows


def _last_feature_row(ticker: str, frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"ticker": ticker}
    row = frame.iloc[-1].to_dict()
    row.setdefault("ticker", ticker)
    return row


def _current_stock_price(
    *,
    feature: dict[str, Any],
    tool_b_row: dict[str, Any] | None,
    chain: pd.DataFrame,
) -> float | None:
    for value in (
        feature.get("underlying_price"),
        (tool_b_row or {}).get("share_price_usd"),
        _first_chain_value(chain, "underlying_price"),
    ):
        price = _as_float(value)
        if price is not None and price > 0:
            return price
    return None


def _first_chain_value(chain: pd.DataFrame, column: str) -> object:
    if chain.empty or column not in chain.columns:
        return None
    return chain[column].dropna().iloc[0] if not chain[column].dropna().empty else None


def _confidence_label(tool_a_row: dict[str, Any] | None) -> str:
    if not tool_a_row:
        return "n/a"
    label = str(tool_a_row.get("confidence_label") or "").strip()
    if label:
        return label
    confidence_score = _as_float(tool_a_row.get("confidence_score"))
    return f"score {confidence_score:.2f}" if confidence_score is not None else "n/a"
