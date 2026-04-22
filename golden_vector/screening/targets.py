"""Tool B target-price scenarios."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import AppConfig


def determine_size_category(market_cap_musd: float | None) -> str | None:
    if market_cap_musd is None or pd.isna(market_cap_musd):
        return None
    if market_cap_musd > 15_000:
        return "large"
    if market_cap_musd > 2_000:
        return "mid"
    if market_cap_musd > 500:
        return "small"
    return "micro"


def compute_target_prices(
    row: pd.Series,
    *,
    app_config: AppConfig,
) -> dict[str, object]:
    size_category = determine_size_category(_numeric(row.get("market_cap_musd")))
    if size_category is None:
        return _empty_targets(size_category=None)

    benchmark = app_config.screening_params.peer_benchmarks[size_category]
    jurisdiction_tier = int(_numeric(row.get("jurisdiction_tier")) or 3)
    tier_discount = _tier_discount(app_config, jurisdiction_tier)

    share_price_usd = _positive(row.get("share_price_usd"))
    forward_eps = _positive(row.get("forward_eps"))
    actual_fcf_yield = _positive(row.get("fcf_yield"))
    forward_ebitda_musd = _positive(row.get("forward_ebitda_musd"))
    net_debt_musd = _numeric(row.get("net_debt_musd"))
    shares_outstanding = _positive(row.get("shares_outstanding"))

    adjusted_peer_pe = benchmark.pe_2026 * (1.0 - tier_discount)
    adjusted_peak_pe = benchmark.pe_2011_peak * (1.0 - tier_discount)

    target_price_peer_pe = (
        adjusted_peer_pe * forward_eps
        if forward_eps is not None
        else None
    )
    target_price_peak_pe = (
        adjusted_peak_pe * forward_eps
        if forward_eps is not None
        else None
    )

    target_price_peer_fcf = _target_price_from_yield(
        share_price_usd=share_price_usd,
        actual_yield=actual_fcf_yield,
        target_yield=benchmark.fcf_yield_2026,
    )
    target_price_peak_fcf = _target_price_from_yield(
        share_price_usd=share_price_usd,
        actual_yield=actual_fcf_yield,
        target_yield=benchmark.fcf_yield_2011,
    )

    target_price_peer_evebitda = _target_price_from_evebitda(
        ebitda_musd=forward_ebitda_musd,
        target_multiple=benchmark.evebitda_2026 * (1.0 - tier_discount),
        net_debt_musd=net_debt_musd,
        shares_outstanding=shares_outstanding,
    )
    target_price_peak_evebitda = _target_price_from_evebitda(
        ebitda_musd=forward_ebitda_musd,
        target_multiple=benchmark.evebitda_2011 * (1.0 - tier_discount),
        net_debt_musd=net_debt_musd,
        shares_outstanding=shares_outstanding,
    )

    targets = {
        "target_price_peer_pe": target_price_peer_pe,
        "target_price_peak_pe": target_price_peak_pe,
        "target_price_peer_fcf": target_price_peer_fcf,
        "target_price_peak_fcf": target_price_peak_fcf,
        "target_price_peer_evebitda": target_price_peer_evebitda,
        "target_price_peak_evebitda": target_price_peak_evebitda,
    }
    valid_targets = [value for value in targets.values() if value is not None]
    best_target_price_usd = max(valid_targets) if valid_targets else None
    best_upside_pct = (
        ((best_target_price_usd - share_price_usd) / share_price_usd)
        if best_target_price_usd is not None and share_price_usd is not None
        else None
    )

    return {
        "size_category": size_category,
        "adjusted_peer_pe": adjusted_peer_pe,
        "adjusted_peak_pe": adjusted_peak_pe,
        **targets,
        "best_target_price_usd": best_target_price_usd,
        "best_upside_pct": best_upside_pct,
    }


def _empty_targets(*, size_category: str | None) -> dict[str, object]:
    return {
        "size_category": size_category,
        "adjusted_peer_pe": None,
        "adjusted_peak_pe": None,
        "target_price_peer_pe": None,
        "target_price_peak_pe": None,
        "target_price_peer_fcf": None,
        "target_price_peak_fcf": None,
        "target_price_peer_evebitda": None,
        "target_price_peak_evebitda": None,
        "best_target_price_usd": None,
        "best_upside_pct": None,
    }


def _tier_discount(app_config: AppConfig, jurisdiction_tier: int) -> float:
    discounts = app_config.screening_params.jurisdiction_discounts
    return {
        1: discounts.tier_1,
        2: discounts.tier_2,
        3: discounts.tier_3,
    }.get(jurisdiction_tier, discounts.tier_3)


def _target_price_from_yield(
    *,
    share_price_usd: float | None,
    actual_yield: float | None,
    target_yield: float,
) -> float | None:
    if share_price_usd is None or actual_yield is None or actual_yield <= 0 or target_yield <= 0:
        return None
    return share_price_usd * (actual_yield / target_yield)


def _target_price_from_evebitda(
    *,
    ebitda_musd: float | None,
    target_multiple: float,
    net_debt_musd: float | None,
    shares_outstanding: float | None,
) -> float | None:
    if (
        ebitda_musd is None
        or ebitda_musd <= 0
        or net_debt_musd is None
        or shares_outstanding is None
        or shares_outstanding <= 0
        or target_multiple <= 0
    ):
        return None
    equity_value_usd = ((ebitda_musd * target_multiple) - net_debt_musd) * 1_000_000.0
    if equity_value_usd <= 0:
        return None
    return equity_value_usd / shares_outstanding


def _numeric(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive(value: object) -> float | None:
    numeric = _numeric(value)
    if numeric is None or numeric <= 0:
        return None
    return numeric
