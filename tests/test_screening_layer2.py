import pandas as pd

from golden_vector.screening.layer2 import compute_layer2_metrics


def test_layer2_computes_positive_metrics_when_inputs_are_complete():
    row = pd.Series(
        {
            "production_oz": 1_000_000,
            "cash_cost_usd_per_oz": 900,
            "aisc_usd_per_oz": 1300,
            "royalty_rate": 0.03,
            "da_musd": 100,
            "interest_expense_musd": 20,
            "tax_rate": 0.30,
            "shares_outstanding": 200_000_000,
            "share_price_usd": 25.0,
            "market_cap_musd": 5_000,
            "net_debt_musd": 300,
            "sustainable_fcf_musd": 900,
        }
    )

    result = compute_layer2_metrics(row, gold_price_assumption=4000)

    assert result["layer2_incomplete_reasons"] is None
    assert result["forward_revenue_musd"] == 4000.0
    assert result["forward_eps"] > 0
    assert result["forward_pe"] > 0
    assert result["ev_ebitda"] > 0


def test_layer2_suppresses_forward_pe_when_forward_eps_is_negative():
    row = pd.Series(
        {
            "production_oz": 500_000,
            "cash_cost_usd_per_oz": 2000,
            "aisc_usd_per_oz": 2200,
            "royalty_rate": 0.20,
            "da_musd": 600,
            "interest_expense_musd": 200,
            "tax_rate": 0.30,
            "shares_outstanding": 100_000_000,
            "share_price_usd": 8.0,
            "market_cap_musd": 800,
            "net_debt_musd": 500,
            "sustainable_fcf_musd": -50,
        }
    )

    result = compute_layer2_metrics(row, gold_price_assumption=2500)

    assert result["forward_net_income_musd"] < 0
    assert result["forward_eps"] < 0
    assert result["forward_pe"] is None


def test_layer2_handles_negative_net_debt_as_net_cash():
    row = pd.Series(
        {
            "production_oz": 1_200_000,
            "cash_cost_usd_per_oz": 950,
            "aisc_usd_per_oz": 1250,
            "royalty_rate": 0.03,
            "da_musd": 120,
            "interest_expense_musd": 10,
            "tax_rate": 0.25,
            "shares_outstanding": 250_000_000,
            "share_price_usd": 22.0,
            "market_cap_musd": 5_500,
            "net_debt_musd": -500,
            "sustainable_fcf_musd": 1_000,
        }
    )

    result = compute_layer2_metrics(row, gold_price_assumption=4000)

    assert result["forward_pe"] is not None
    assert result["ev_ebitda"] is not None
    assert result["ev_ebitda"] < (5500 / result["forward_ebitda_musd"])
