from datetime import date

import pandas as pd

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


def test_compute_target_prices_applies_jurisdiction_discount_and_chooses_best_target():
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
    expected_peer_evebitda_target = (((1_000.0 * (benchmark.evebitda_2026 * 0.85)) - 500.0) * 1_000_000.0) / 100_000_000.0

    assert round(result["adjusted_peer_pe"], 4) == round(expected_adjusted_peer_pe, 4)
    assert round(result["target_price_peer_pe"], 4) == round(expected_peer_pe_target, 4)
    assert round(result["target_price_peer_fcf"], 4) == round(expected_peer_fcf_target, 4)
    assert round(result["target_price_peer_evebitda"], 4) == round(expected_peer_evebitda_target, 4)
    assert result["best_target_price_usd"] == max(
        result["target_price_peer_pe"],
        result["target_price_peak_pe"],
        result["target_price_peer_fcf"],
        result["target_price_peak_fcf"],
        result["target_price_peer_evebitda"],
        result["target_price_peak_evebitda"],
    )


def test_compute_target_prices_handles_net_cash_and_invalid_equity_value_cleanly():
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
    row_with_excessive_debt = pd.Series(
        {
            "market_cap_musd": 800.0,
            "share_price_usd": 10.0,
            "forward_eps": 1.0,
            "fcf_yield": 0.15,
            "forward_ebitda_musd": 150.0,
            "net_debt_musd": 5_000.0,
            "shares_outstanding": 50_000_000.0,
            "jurisdiction_tier": 1,
        }
    )

    net_cash_targets = compute_target_prices(row_with_net_cash, app_config=app_config)
    excessive_debt_targets = compute_target_prices(row_with_excessive_debt, app_config=app_config)

    assert net_cash_targets["target_price_peer_evebitda"] is not None
    assert excessive_debt_targets["target_price_peer_evebitda"] is None
