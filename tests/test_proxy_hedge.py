import pandas as pd
import pytest

from golden_vector.hedge.proxy_hedge import map_proxy_hedges


def test_map_proxy_hedges_orders_optionable_matches_by_down_beta_diff():
    tool_a = pd.DataFrame(
        [
            {"ticker": "TARGET", "down_beta_core": 1.40},
            {
                "ticker": "AEM",
                "down_beta_core": 1.35,
                "confidence_score": 0.80,
                "screening_verdict": "WATCH",
            },
            {"ticker": "NEM", "down_beta_core": 1.75, "confidence_score": 0.70},
            {"ticker": "GFI", "down_beta_core": 0.80, "confidence_score": 0.60},
        ]
    )

    mapping = map_proxy_hedges(
        non_optionable_tickers=["target"],
        optionable_tickers=["GFI", "NEM", "AEM"],
        tool_a_frame=tool_a,
        top_n=2,
        max_beta_diff=0.20,
    )

    matches = mapping["TARGET"]
    assert [match.proxy_ticker for match in matches] == ["AEM", "NEM"]
    assert matches[0].down_beta_diff == pytest.approx(0.05)
    assert matches[0].basis_risk_label == "lower_basis_risk"
    assert matches[0].tool_a_confidence == pytest.approx(0.80)
    assert matches[0].tool_b_verdict == "WATCH"
    assert matches[1].basis_risk_label == "elevated_basis_risk"


def test_map_proxy_hedges_uses_sector_etf_fallback_when_no_optionable_match():
    tool_a = pd.DataFrame([{"ticker": "TARGET", "down_beta_core": 1.40}])

    mapping = map_proxy_hedges(
        non_optionable_tickers=["TARGET"],
        optionable_tickers=[],
        tool_a_frame=tool_a,
        benchmark_tickers=("GDX", "GDXJ"),
        top_n=2,
    )

    matches = mapping["TARGET"]
    assert [match.proxy_ticker for match in matches] == ["GDX", "GDXJ"]
    assert all(match.proxy_type == "sector_etf" for match in matches)
    assert all(match.basis_risk_label == "high_basis_risk_sector_proxy" for match in matches)
