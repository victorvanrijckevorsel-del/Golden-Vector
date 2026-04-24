from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.targets import compute_target_prices, determine_size_category


def test_determine_size_category_uses_expected_market_cap_bands():
    assert determine_size_category(None) is None
    assert determine_size_category(250) == "micro"
    assert determine_size_category(800) == "small"
    assert determine_size_category(5000) == "mid"
    assert determine_size_category(20000) == "large"


def test_compute_target_prices_returns_empty_targets_without_market_cap():
    app_config = load_app_config(ProjectPaths.discover()).app
    row = pd.Series({"share_price_usd": 20.0, "forward_eps": 2.0})

    result = compute_target_prices(row, app_config=app_config)

    assert result["size_category"] is None
    assert result["best_target_price_usd"] is None
    assert result["best_upside_pct"] is None


def test_compute_target_prices_applies_jurisdiction_discount_and_emits_four_scenarios():
    app_config = load_app_config(ProjectPaths.discover()).app
    benchmark = app_config.screening_params.peer_benchmarks["mid"]
    row = pd.Series(
        {
            "ticker": "NEM",
            "snapshot_date": date(2026, 2, 1),
            "market_cap_musd": 5_000.0,
            "share_price_usd": 20.0,
            "forward_eps": 2.0,
            "fcf_yield": 0.20,
            "forward_ebitda_musd": 1_000.0,
            "net_debt_musd": 500.0,
            "shares_outstanding": 100_000_000.0,
            "jurisdiction_tier": 2,
        }
    )

    result = compute_target_prices(row, app_config=app_config)

    expected_adjusted_peer_pe = benchmark.pe_2026 * (1.0 - app_config.screening_params.jurisdiction_discounts.tier_2)
    expected_peer_pe_target = expected_adjusted_peer_pe * 2.0
    expected_peer_fcf_target = 20.0 * (0.20 / benchmark.fcf_yield_2026)

    assert round(result["adjusted_peer_pe"], 4) == round(expected_adjusted_peer_pe, 4)
    assert round(result["target_price_peer_pe"], 4) == round(expected_peer_pe_target, 4)
    assert round(result["target_price_peer_fcf"], 4) == round(expected_peer_fcf_target, 4)

    # Per-scenario upside %s should match (target - share) / share for each scenario.
    assert round(result["upside_peer_pe_pct"], 4) == round((expected_peer_pe_target - 20.0) / 20.0, 4)
    assert round(result["upside_peer_fcf_pct"], 4) == round((expected_peer_fcf_target - 20.0) / 20.0, 4)

    # EV/EBITDA-derived targets are no longer emitted (Excel never had them).
    assert "target_price_peer_evebitda" not in result
    assert "target_price_peak_evebitda" not in result

    # best_target_price_usd is the max of the four canonical scenarios only.
    assert result["best_target_price_usd"] == max(
        result["target_price_peer_pe"],
        result["target_price_peak_pe"],
        result["target_price_peer_fcf"],
        result["target_price_peak_fcf"],
    )


def test_best_upside_pct_is_max_of_four_canonical_scenarios():
    """Locks the max-of-4 semantics of best_upside_pct.

    The pool used to be 6 (adding EV/EBITDA-derived targets) but those
    were dropped for Excel parity. compute_tool_b_score still consumes
    best_upside_pct as its upside input, so this test prevents a silent
    regression that re-introduces more scenarios into the max.
    """
    app_config = load_app_config(ProjectPaths.discover()).app
    row = pd.Series(
        {
            "ticker": "TEST",
            "snapshot_date": date(2026, 2, 1),
            "market_cap_musd": 5_000.0,
            "share_price_usd": 20.0,
            "forward_eps": 2.0,
            "fcf_yield": 0.15,
            "forward_ebitda_musd": 800.0,
            "net_debt_musd": 200.0,
            "shares_outstanding": 100_000_000.0,
            "jurisdiction_tier": 2,
        }
    )

    result = compute_target_prices(row, app_config=app_config)

    four_upsides = [
        result["upside_peer_pe_pct"],
        result["upside_peak_pe_pct"],
        result["upside_peer_fcf_pct"],
        result["upside_peak_fcf_pct"],
    ]
    assert all(v is not None for v in four_upsides)
    assert result["best_upside_pct"] == pytest.approx(max(four_upsides))

    # And the matching best target price equals max of the four target prices.
    four_targets = [
        result["target_price_peer_pe"],
        result["target_price_peak_pe"],
        result["target_price_peer_fcf"],
        result["target_price_peak_fcf"],
    ]
    assert result["best_target_price_usd"] == pytest.approx(max(four_targets))


def test_compute_target_prices_handles_net_cash_and_missing_inputs_cleanly():
    """Targets gracefully fill in even when some inputs are zero/missing.

    With the EV/EBITDA-derived targets removed, the previous "excessive
    debt produces None EV/EBITDA target" check is no longer applicable.
    Instead, verify the four canonical scenarios still compute correctly
    when the row has net cash, and emit None when an upstream input
    (forward_eps) is absent.
    """
    app_config = load_app_config(ProjectPaths.discover()).app
    row_with_net_cash = pd.Series(
        {
            "market_cap_musd": 800.0,
            "share_price_usd": 10.0,
            "forward_eps": 1.0,
            "fcf_yield": 0.15,
            "forward_ebitda_musd": 150.0,
            "net_debt_musd": -100.0,
            "shares_outstanding": 50_000_000.0,
            "jurisdiction_tier": 1,
        }
    )
    row_missing_eps = pd.Series(
        {
            "market_cap_musd": 800.0,
            "share_price_usd": 10.0,
            "forward_eps": None,
            "fcf_yield": 0.15,
            "forward_ebitda_musd": 150.0,
            "net_debt_musd": 50.0,
            "shares_outstanding": 50_000_000.0,
            "jurisdiction_tier": 1,
        }
    )

    net_cash_targets = compute_target_prices(row_with_net_cash, app_config=app_config)
    missing_eps_targets = compute_target_prices(row_missing_eps, app_config=app_config)

    # Net-cash row computes all four scenarios + best.
    assert net_cash_targets["target_price_peer_pe"] is not None
    assert net_cash_targets["target_price_peer_fcf"] is not None
    assert net_cash_targets["best_target_price_usd"] is not None

    # Missing forward_eps -> P/E targets are None, FCF targets still compute.
    assert missing_eps_targets["target_price_peer_pe"] is None
    assert missing_eps_targets["target_price_peak_pe"] is None
    assert missing_eps_targets["target_price_peer_fcf"] is not None
    assert missing_eps_targets["upside_peer_pe_pct"] is None
    assert missing_eps_targets["upside_peer_fcf_pct"] is not None
