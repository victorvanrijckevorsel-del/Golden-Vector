import pandas as pd
import pytest

from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.hedge.speculation_section import build_speculation_section
from tests.helpers import build_test_paths


def test_build_speculation_section_returns_universe_blocks_without_holdings(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig()

    blocks = build_speculation_section(
        paths=paths,
        options_features=_features([("AEM", "directly_hedgeable", 0.20, 50.0)]),
        tool_a_frame=_tool_a([("AEM", 1.40, "HIGH")]),
        tool_b_frame=pd.DataFrame(),
        raw_options_by_ticker={"AEM": _candidate_chain()},
        risk_free_rate=0.04,
        config=config,
    )

    assert len(blocks) == 1
    assert blocks[0].ticker == "AEM"
    assert blocks[0].current_stock_price == 50.0
    assert [candidate.horizon_days for candidate in blocks[0].candidates] == [30, 60, 90]
    assert len(blocks[0].scenario_bundles) == 3
    assert all(
        len(bundle.rows) == len(config.default_scenarios)
        for bundle in blocks[0].scenario_bundles
    )
    assert blocks[0].annotations == []


def test_build_speculation_section_filters_sorts_and_caps_by_config(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig(
        optionability_tier_min="thin",
        speculation_max_tickers_default=2,
    )

    blocks = build_speculation_section(
        paths=paths,
        options_features=_features(
            [
                ("AEM", "directly_hedgeable", 0.20, 50.0),
                ("NEM", "directly_hedgeable", 0.10, 50.0),
                ("GFI", "thin", 0.05, 50.0),
                ("AAUC.TO", "none", 0.01, 20.0),
            ]
        ),
        tool_a_frame=_tool_a(
            [
                ("AEM", 1.40, "HIGH"),
                ("NEM", 1.20, "MEDIUM"),
                ("GFI", 1.10, "MEDIUM"),
            ]
        ),
        tool_b_frame=pd.DataFrame(),
        raw_options_by_ticker={
            "AEM": _candidate_chain(),
            "NEM": _candidate_chain(),
            "GFI": _candidate_chain(),
        },
        risk_free_rate=0.04,
        config=config,
    )

    assert [block.ticker for block in blocks] == ["GFI", "NEM"]


def test_build_speculation_section_default_filter_excludes_thin_tickers(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig()

    blocks = build_speculation_section(
        paths=paths,
        options_features=_features(
            [
                ("AEM", "directly_hedgeable", 0.20, 50.0),
                ("GFI", "thin", 0.05, 50.0),
            ]
        ),
        tool_a_frame=_tool_a([("AEM", 1.40, "HIGH"), ("GFI", 1.10, "MEDIUM")]),
        tool_b_frame=pd.DataFrame(),
        raw_options_by_ticker={"AEM": _candidate_chain(), "GFI": _candidate_chain()},
        risk_free_rate=0.04,
        config=config,
    )

    assert [block.ticker for block in blocks] == ["AEM"]


def test_build_speculation_section_honors_quantity_and_max_ticker_overrides(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig(speculation_max_tickers_default=10)

    blocks = build_speculation_section(
        paths=paths,
        options_features=_features(
            [
                ("AEM", "directly_hedgeable", 0.20, 50.0),
                ("NEM", "directly_hedgeable", 0.10, 50.0),
            ]
        ),
        tool_a_frame=_tool_a([("AEM", 1.40, "HIGH"), ("NEM", 1.40, "HIGH")]),
        tool_b_frame=pd.DataFrame(),
        raw_options_by_ticker={"AEM": _candidate_chain(), "NEM": _candidate_chain()},
        risk_free_rate=0.04,
        config=config,
        quantity=2,
        max_tickers=1,
    )

    assert [block.ticker for block in blocks] == ["NEM"]
    downside_row = next(
        row
        for row in blocks[0].scenario_bundles[0].rows
        if row.gold_pct_change == -0.10
    )
    assert downside_row.net_pnl_at_expiry == pytest.approx(
        downside_row.pnl_per_contract_at_expiry * 2 * 100
    )


def test_build_speculation_section_uses_tool_b_price_fallback(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig()

    blocks = build_speculation_section(
        paths=paths,
        options_features=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "optionability_tier": "directly_hedgeable",
                    "iv_percentile_cross_sectional": 0.20,
                }
            ]
        ),
        tool_a_frame=_tool_a([("AEM", 1.40, "HIGH")]),
        tool_b_frame=pd.DataFrame([{"ticker": "AEM", "share_price_usd": 50.0}]),
        raw_options_by_ticker={"AEM": _candidate_chain()},
        risk_free_rate=0.04,
        config=config,
    )

    assert blocks[0].current_stock_price == 50.0
    assert blocks[0].candidates


def test_build_speculation_section_annotates_missing_inputs(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig()

    blocks = build_speculation_section(
        paths=paths,
        options_features=_features([("AEM", "directly_hedgeable", 0.20, None)]),
        tool_a_frame=_tool_a([("AEM", 1.40, "HIGH")]),
        tool_b_frame=pd.DataFrame(),
        raw_options_by_ticker={},
        risk_free_rate=0.04,
        config=config,
    )

    assert blocks[0].candidates == []
    assert "Current stock price is unavailable." in blocks[0].annotations
    assert "No raw options chain is available." in blocks[0].annotations
    assert (
        "No usable listed put candidate found for the configured horizons."
        in blocks[0].annotations
    )


def test_build_speculation_section_uses_zero_rate_fallback_when_risk_free_rate_is_missing(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig()

    blocks = build_speculation_section(
        paths=paths,
        options_features=_features([("AEM", "directly_hedgeable", 0.20, 50.0)]),
        tool_a_frame=_tool_a([("AEM", 1.40, "HIGH")]),
        tool_b_frame=pd.DataFrame(),
        raw_options_by_ticker={"AEM": _candidate_chain()},
        risk_free_rate=None,
        config=config,
    )

    assert blocks[0].candidates
    assert "Risk-free rate is unavailable; using 0% fallback." in blocks[0].annotations


def test_build_speculation_section_bubbles_low_down_beta_annotation(tmp_path):
    paths = build_test_paths(tmp_path)
    config = HedgeReadinessConfig()

    blocks = build_speculation_section(
        paths=paths,
        options_features=_features([("AEM", "directly_hedgeable", 0.20, 50.0)]),
        tool_a_frame=_tool_a([("AEM", 0.05, "LOW")]),
        tool_b_frame=pd.DataFrame(),
        raw_options_by_ticker={"AEM": _candidate_chain()},
        risk_free_rate=0.04,
        config=config,
    )

    assert blocks[0].scenario_bundles
    assert blocks[0].scenario_bundles[0].rows == []
    assert any("Down-beta is too small" in note for note in blocks[0].annotations)


def _features(rows: list[tuple[str, str, float | None, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "optionability_tier": tier,
                "iv_percentile_cross_sectional": iv_percentile,
                "underlying_price": underlying_price,
            }
            for ticker, tier, iv_percentile, underlying_price in rows
        ]
    )


def _tool_a(rows: list[tuple[str, float, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "down_beta_core": down_beta_core,
                "confidence_label": confidence_label,
            }
            for ticker, down_beta_core, confidence_label in rows
        ]
    )


def _candidate_chain() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for expiration, days, put_prices in (
        ("2026-06-30", 30, [(45.0, 0.9, 1.1, 0.40), (47.5, 1.3, 1.5, 0.38)]),
        ("2026-07-30", 60, [(45.0, 1.8, 2.0, 0.42), (47.5, 2.5, 2.7, 0.41)]),
        ("2026-08-29", 90, [(45.0, 2.8, 3.0, 0.44), (47.5, 3.5, 3.8, 0.43)]),
    ):
        for strike, bid, ask, iv in put_prices:
            rows.append(_option(expiration, days, "P", strike, bid, ask, iv))
        rows.append(_option(expiration, days, "C", 55.0, 0.8, 1.0, 0.36))
    return pd.DataFrame(rows)


def _option(
    expiration: str,
    days_to_expiry: int,
    option_type: str,
    strike: float,
    bid: float,
    ask: float,
    implied_volatility: float,
) -> dict[str, object]:
    return {
        "expiration": expiration,
        "days_to_expiry": days_to_expiry,
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "lastPrice": (bid + ask) / 2,
        "volume": 20,
        "openInterest": 100,
        "impliedVolatility": implied_volatility,
    }
