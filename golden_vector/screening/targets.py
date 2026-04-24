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

    # The four canonical scenarios. These are what the Excel
    # `Top performers` sheet exposes (columns AA / AC / AI / AK).
    targets = {
        "target_price_peer_pe": target_price_peer_pe,
        "target_price_peak_pe": target_price_peak_pe,
        "target_price_peer_fcf": target_price_peer_fcf,
        "target_price_peak_fcf": target_price_peak_fcf,
    }

    # Per-scenario upside %. Each = (target - share_price) / share_price
    # so the workspace can surface the four scenarios independently instead
    # of only the aggressive max(...).
    upside_pct = {
        "upside_peer_pe_pct": _upside_pct(target_price_peer_pe, share_price_usd),
        "upside_peak_pe_pct": _upside_pct(target_price_peak_pe, share_price_usd),
        "upside_peer_fcf_pct": _upside_pct(target_price_peer_fcf, share_price_usd),
        "upside_peak_fcf_pct": _upside_pct(target_price_peak_fcf, share_price_usd),
    }

    # best_target_price_usd / best_upside_pct are derived "max of the four
    # canonical scenarios" helpers used by compute_tool_b_score. They are
    # NOT surfaced as headline columns in the workspace Tool B view — the
    # four scenarios are shown side by side instead.
    #
    # Semantic note: this pool used to include two EV/EBITDA-derived
    # target prices (6 total). Dropping those as part of the parity work
    # narrowed the pool to the 4 canonical scenarios the friend's Excel
    # actually exposes. tool_b_score's formula is unchanged syntactically,
    # but its `best_upside_pct` input is now max-of-4 rather than
    # max-of-6. This means tool_b_score is slightly lower for tickers
    # whose maximum scenario was previously a 2011-peak EV/EBITDA target.
    # Accepting this change as faithful to the friend's model (EV/EBITDA
    # targets were a Python-only invention).
    valid_targets = [value for value in targets.values() if value is not None]
    best_target_price_usd = max(valid_targets) if valid_targets else None
    best_upside_pct = _upside_pct(best_target_price_usd, share_price_usd)

    return {
        "size_category": size_category,
        "adjusted_peer_pe": adjusted_peer_pe,
        "adjusted_peak_pe": adjusted_peak_pe,
        **targets,
        **upside_pct,
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
        "upside_peer_pe_pct": None,
        "upside_peak_pe_pct": None,
        "upside_peer_fcf_pct": None,
        "upside_peak_fcf_pct": None,
        "best_target_price_usd": None,
        "best_upside_pct": None,
    }


def _upside_pct(target_price: float | None, share_price: float | None) -> float | None:
    if target_price is None or share_price is None or share_price <= 0:
        return None
    return (target_price - share_price) / share_price


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
