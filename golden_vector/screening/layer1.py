"""Layer 1 robust-screen formulas."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import Layer1Thresholds


def evaluate_layer1(
    row: pd.Series,
    *,
    gold_price_assumption: float,
    thresholds: Layer1Thresholds,
) -> dict[str, object]:
    reasons: list[str] = []

    market_cap_musd = _positive_float(row.get("market_cap_musd"))
    production_oz = _positive_float(row.get("production_oz"))
    aisc = _positive_float(row.get("aisc_usd_per_oz"))
    sustaining_capex_musd = _numeric(row.get("sustaining_capex_musd"))
    reserve_life_years = _positive_float(row.get("reserve_life_years"))
    net_debt_musd = _numeric(row.get("net_debt_musd"))
    ebitda_ltm_musd = _numeric(row.get("ebitda_ltm_musd"))

    if market_cap_musd is None:
        reasons.append("MISSING_MARKET_CAP")
    if production_oz is None:
        reasons.append("MISSING_PRODUCTION")
    if aisc is None:
        reasons.append("MISSING_AISC")
    if sustaining_capex_musd is None:
        reasons.append("MISSING_SUSTAINING_CAPEX")
    if reserve_life_years is None:
        reasons.append("MISSING_RESERVE_LIFE")
    if net_debt_musd is None:
        reasons.append("MISSING_NET_DEBT")
    if ebitda_ltm_musd is None:
        reasons.append("MISSING_EBITDA")

    if reasons:
        return {
            "layer1_status": "INCOMPLETE",
            "layer1_pass": False,
            "layer1_fail_reasons": ";".join(sorted(set(reasons))),
            "cash_margin_usd_per_oz": None,
            "margin_pct": None,
            "sustainable_fcf_musd": None,
            "fcf_yield": None,
            "leverage": None,
        }

    assert market_cap_musd is not None
    assert production_oz is not None
    assert aisc is not None
    assert sustaining_capex_musd is not None
    assert reserve_life_years is not None
    assert net_debt_musd is not None
    assert ebitda_ltm_musd is not None

    cash_margin_usd_per_oz = gold_price_assumption - aisc
    margin_pct = cash_margin_usd_per_oz / gold_price_assumption
    sustainable_fcf_musd = ((cash_margin_usd_per_oz * production_oz) / 1_000_000.0) - sustaining_capex_musd
    fcf_yield = sustainable_fcf_musd / market_cap_musd if market_cap_musd > 0 else None

    if aisc > thresholds.aisc_max:
        reasons.append("AISC_FAIL")
    if margin_pct < thresholds.margin_min:
        reasons.append("MARGIN_FAIL")
    if fcf_yield is None or fcf_yield < thresholds.fcf_yield_min:
        reasons.append("FCF_FAIL")
    if reserve_life_years < thresholds.reserve_life_min:
        reasons.append("RESERVE_LIFE_FAIL")

    leverage = None
    if ebitda_ltm_musd <= 0:
        reasons.append("LEVERAGE_NON_POSITIVE_EBITDA")
    else:
        leverage = net_debt_musd / ebitda_ltm_musd
        if leverage > thresholds.leverage_max:
            reasons.append("LEVERAGE_FAIL")

    return {
        "layer1_status": "PASS" if not reasons else "FAIL",
        "layer1_pass": len(reasons) == 0,
        "layer1_fail_reasons": None if not reasons else ";".join(sorted(set(reasons))),
        "cash_margin_usd_per_oz": cash_margin_usd_per_oz,
        "margin_pct": margin_pct,
        "sustainable_fcf_musd": sustainable_fcf_musd,
        "fcf_yield": fcf_yield,
        "leverage": leverage,
    }


def _numeric(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value: object) -> float | None:
    numeric = _numeric(value)
    if numeric is None or numeric <= 0:
        return None
    return numeric
