"""Layer 2 forward earnings and valuation formulas."""

from __future__ import annotations

import pandas as pd

from golden_vector.common.numeric import optional_float as _numeric


def compute_layer2_metrics(
    row: pd.Series,
    *,
    gold_price_assumption: float,
) -> dict[str, object]:
    production_oz = _positive_float(row.get("production_oz"))
    cash_cost_usd_per_oz = _positive_float(row.get("cash_cost_usd_per_oz"))
    aisc_usd_per_oz = _positive_float(row.get("aisc_usd_per_oz"))
    royalty_rate = _rate(row.get("royalty_rate"))
    da_musd = _numeric(row.get("da_musd"))
    interest_expense_musd = _numeric(row.get("interest_expense_musd"))
    tax_rate = _rate(row.get("tax_rate"))
    shares_outstanding = _positive_float(row.get("shares_outstanding"))
    share_price_usd = _positive_float(row.get("share_price_usd"))
    market_cap_musd = _positive_float(row.get("market_cap_musd"))
    net_debt_musd = _numeric(row.get("net_debt_musd"))
    sustainable_fcf_musd = _numeric(row.get("sustainable_fcf_musd"))

    required_missing = []
    for field_name, value in (
        ("production_oz", production_oz),
        ("royalty_rate", royalty_rate),
        ("da_musd", da_musd),
        ("interest_expense_musd", interest_expense_musd),
        ("tax_rate", tax_rate),
        ("shares_outstanding", shares_outstanding),
        ("share_price_usd", share_price_usd),
        ("market_cap_musd", market_cap_musd),
        ("net_debt_musd", net_debt_musd),
        ("sustainable_fcf_musd", sustainable_fcf_musd),
    ):
        if value is None:
            required_missing.append(field_name)

    if cash_cost_usd_per_oz is None and aisc_usd_per_oz is None:
        required_missing.append("cash_cost_or_aisc")

    if required_missing:
        return {
            "forward_revenue_musd": None,
            "forward_ebitda_musd": None,
            "forward_net_income_musd": None,
            "forward_eps": None,
            "forward_pe": None,
            "ev_ebitda": None,
            "layer2_incomplete_reasons": ";".join(sorted(set(required_missing))),
        }

    assert production_oz is not None
    assert royalty_rate is not None
    assert da_musd is not None
    assert interest_expense_musd is not None
    assert tax_rate is not None
    assert shares_outstanding is not None
    assert share_price_usd is not None
    assert market_cap_musd is not None
    assert net_debt_musd is not None
    assert sustainable_fcf_musd is not None

    forward_revenue_musd = (gold_price_assumption * production_oz) / 1_000_000.0
    if cash_cost_usd_per_oz is not None and cash_cost_usd_per_oz > 0:
        operating_margin_usd_per_oz = gold_price_assumption - cash_cost_usd_per_oz
    else:
        assert aisc_usd_per_oz is not None
        operating_margin_usd_per_oz = gold_price_assumption - (aisc_usd_per_oz * 0.7)

    forward_ebitda_musd = (
        (operating_margin_usd_per_oz * production_oz) / 1_000_000.0
    ) - (forward_revenue_musd * royalty_rate)
    forward_net_income_musd = (
        forward_ebitda_musd - da_musd - interest_expense_musd
    ) * (1.0 - tax_rate)
    forward_eps = (forward_net_income_musd * 1_000_000.0) / shares_outstanding
    forward_pe = (
        share_price_usd / forward_eps
        if forward_eps is not None and forward_eps > 0
        else None
    )
    ev_ebitda = (
        (market_cap_musd + net_debt_musd) / forward_ebitda_musd
        if forward_ebitda_musd > 0
        else None
    )

    return {
        "forward_revenue_musd": forward_revenue_musd,
        "forward_ebitda_musd": forward_ebitda_musd,
        "forward_net_income_musd": forward_net_income_musd,
        "forward_eps": forward_eps,
        "forward_pe": forward_pe,
        "ev_ebitda": ev_ebitda,
        "layer2_incomplete_reasons": None,
    }


def _positive_float(value: object) -> float | None:
    numeric = _numeric(value)
    if numeric is None or numeric <= 0:
        return None
    return numeric


def _rate(value: object) -> float | None:
    numeric = _numeric(value)
    if numeric is None:
        return None
    if numeric > 1.0:
        return numeric / 100.0
    return numeric
