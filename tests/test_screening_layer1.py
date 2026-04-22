import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.layer1 import evaluate_layer1


def test_layer1_passes_when_all_robustness_gates_clear():
    app_config = load_app_config(ProjectPaths.discover()).app
    row = pd.Series(
        {
            "market_cap_musd": 10_000,
            "production_oz": 5_000_000,
            "aisc_usd_per_oz": 1200,
            "sustaining_capex_musd": 500,
            "reserve_life_years": 12,
            "net_debt_musd": 500,
            "ebitda_ltm_musd": 3_000,
        }
    )

    result = evaluate_layer1(
        row,
        gold_price_assumption=4000,
        thresholds=app_config.screening_params.layer1_thresholds,
    )

    assert result["layer1_status"] == "PASS"
    assert bool(result["layer1_pass"]) is True
    assert result["fcf_yield"] > 0
    assert result["leverage"] < 1


def test_layer1_flags_non_positive_ebitda_as_fail():
    app_config = load_app_config(ProjectPaths.discover()).app
    row = pd.Series(
        {
            "market_cap_musd": 2_000,
            "production_oz": 800_000,
            "aisc_usd_per_oz": 1500,
            "sustaining_capex_musd": 100,
            "reserve_life_years": 8,
            "net_debt_musd": 600,
            "ebitda_ltm_musd": 0,
        }
    )

    result = evaluate_layer1(
        row,
        gold_price_assumption=3200,
        thresholds=app_config.screening_params.layer1_thresholds,
    )

    assert result["layer1_status"] == "FAIL"
    assert "LEVERAGE_NON_POSITIVE_EBITDA" in str(result["layer1_fail_reasons"])
