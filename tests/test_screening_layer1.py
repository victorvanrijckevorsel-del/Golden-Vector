from pathlib import Path

import pandas as pd
import pytest

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
    assert result["aisc_margin_yield"] > 0
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


def test_aisc_margin_estimate_is_zero_at_gold_equal_to_aisc():
    """C1 invariant: at gold == reported AISC the margin estimate is exactly 0,

    even with a large sustaining capex entered separately — reported AISC
    already includes sustaining capital, so it must never be charged twice.
    """
    app_config = load_app_config(ProjectPaths.discover()).app
    row = pd.Series(
        {
            "market_cap_musd": 5_000,
            "production_oz": 1_000_000,
            "aisc_usd_per_oz": 1419,
            "sustaining_capex_musd": 110,
            "reserve_life_years": 10,
            "net_debt_musd": 100,
            "ebitda_ltm_musd": 500,
        }
    )

    result = evaluate_layer1(
        row,
        gold_price_assumption=1419,  # gold == AISC
        thresholds=app_config.screening_params.layer1_thresholds,
    )

    assert result["aisc_margin_est_musd"] == 0.0
    assert result["aisc_margin_yield"] == 0.0


def test_aisc_margin_estimate_wdo_case_charges_sustaining_capex_once():
    """C1 WDO-style case from the Codex review: correct value is 583.85m, not 473.85m."""
    app_config = load_app_config(ProjectPaths.discover()).app
    row = pd.Series(
        {
            "market_cap_musd": 3_000,
            "production_oz": 192_500,
            "aisc_usd_per_oz": 1419,
            "sustaining_capex_musd": 110,
            "reserve_life_years": 10,
            "net_debt_musd": 100,
            "ebitda_ltm_musd": 500,
        }
    )

    result = evaluate_layer1(
        row,
        gold_price_assumption=4452,
        thresholds=app_config.screening_params.layer1_thresholds,
    )

    assert result["aisc_margin_est_musd"] == pytest.approx((4452 - 1419) * 192_500 / 1e6)
    assert result["aisc_margin_est_musd"] == pytest.approx(583.8525)


def test_aisc_margin_yield_threshold_flip_case():
    """C1: the double count could flip the 15% yield screen — prove the boundary.

    Chosen so the corrected yield passes 15% while the old (double-counted)
    formula would have failed it.
    """
    app_config = load_app_config(ProjectPaths.discover()).app
    thresholds = app_config.screening_params.layer1_thresholds
    row = pd.Series(
        {
            "market_cap_musd": 1_000,
            "production_oz": 100_000,
            "aisc_usd_per_oz": 2_000,
            "sustaining_capex_musd": 60,
            "reserve_life_years": 10,
            "net_debt_musd": 0,
            "ebitda_ltm_musd": 500,
        }
    )

    result = evaluate_layer1(
        row,
        gold_price_assumption=3_600,  # margin est = 160m -> 16% yield; old formula: 100m -> 10%
        thresholds=thresholds,
    )

    assert result["aisc_margin_est_musd"] == pytest.approx(160.0)
    assert result["aisc_margin_yield"] == pytest.approx(0.16)
    assert result["layer1_check_statuses"]["aisc_margin_yield"] == "PASS"
    old_formula_yield = (160.0 - 60.0) / 1_000
    assert old_formula_yield < thresholds.aisc_margin_yield_min  # documents the flip


def test_removed_fcf_names_swept_from_code_and_config():
    """C1 sweep: the double-count era names must not survive anywhere in

    production code or config — a straggler means a screen or tooltip still
    claims free-cash-flow semantics the inputs cannot support.
    """
    banned = ("sustainable_fcf_musd", "fcf_yield", "fcf_breakeven", "FCF_FAIL")
    repo = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for base, patterns in (("golden_vector", ("*.py",)), ("config", ("*.yaml",))):
        for pattern in patterns:
            for path in (repo / base).rglob(pattern):
                text = path.read_text(encoding="utf-8")
                for token in banned:
                    if token in text:
                        offenders.append(f"{path.relative_to(repo)}: {token}")
    assert not offenders, f"removed C1 names still present: {offenders}"
