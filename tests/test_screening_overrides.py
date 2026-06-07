"""Tests for the Tool B screening-parameter overrides plumbing.

Covers URL-param parsing, app_config overlay, and the in-memory Tool B
compute helper. End-to-end workspace behavior is exercised separately in
test_workspace_app.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.pipeline import compute_tool_b_in_memory
from golden_vector.serve.screening_overrides import (
    ScreeningOverrideError,
    ScreeningOverrides,
    apply_overrides,
    parse_query_overrides,
)


def _app_config():
    return load_app_config(ProjectPaths.discover()).app


# ---------------------------------------------------------------------------
# parse_query_overrides
# ---------------------------------------------------------------------------


def test_parse_query_overrides_returns_empty_when_no_params():
    overrides = parse_query_overrides({})
    assert overrides.has_any() is False
    assert overrides.gold_price is None
    assert overrides.layer1 == {}
    assert overrides.verdict == {}
    assert overrides.jurisdiction == {}


def test_parse_query_overrides_maps_gold_price_and_thresholds():
    overrides = parse_query_overrides({
        "gold_price": ["4500"],
        "pe_target": ["8"],
        "aisc_target": ["1600"],
        "fcf_yield_target": ["20"],  # percent -> 0.20
        "margin_target": ["50"],
        "reserve_life_target": ["8"],
        "leverage_target": ["2"],
        "tier1_discount": ["0"],
        "tier2_discount": ["15"],  # percent -> 0.15
        "tier3_discount": ["30"],
    })
    assert overrides.has_any()
    assert overrides.gold_price == 4500.0
    assert overrides.verdict["strong_candidate_forward_pe_max"] == 8.0
    assert overrides.layer1["aisc_max"] == 1600.0
    assert overrides.layer1["fcf_yield_min"] == pytest.approx(0.20)
    assert overrides.layer1["margin_min"] == pytest.approx(0.50)
    assert overrides.layer1["reserve_life_min"] == 8.0
    assert overrides.layer1["leverage_max"] == 2.0
    assert overrides.jurisdiction["tier_1"] == 0.0
    assert overrides.jurisdiction["tier_2"] == pytest.approx(0.15)
    assert overrides.jurisdiction["tier_3"] == pytest.approx(0.30)


def test_parse_query_overrides_accepts_fractional_percent_input():
    """Users who type 0.15 directly should get the same fraction as '15'."""
    ovr_int = parse_query_overrides({"fcf_yield_target": ["15"]})
    ovr_frac = parse_query_overrides({"fcf_yield_target": ["0.15"]})
    assert ovr_int.layer1["fcf_yield_min"] == pytest.approx(0.15)
    assert ovr_frac.layer1["fcf_yield_min"] == pytest.approx(0.15)


def test_parse_query_overrides_ignores_blank_values():
    overrides = parse_query_overrides({
        "gold_price": [""],
        "pe_target": ["   "],
        "aisc_target": ["1700"],
    })
    assert overrides.gold_price is None
    assert overrides.layer1 == {"aisc_max": 1700.0}


def test_parse_query_overrides_rejects_non_numeric():
    with pytest.raises(ScreeningOverrideError):
        parse_query_overrides({"gold_price": ["abc"]})


def test_parse_query_overrides_rejects_negative_values():
    with pytest.raises(ScreeningOverrideError):
        parse_query_overrides({"gold_price": ["-5"]})


def test_parse_query_overrides_rejects_zero_gold_price():
    with pytest.raises(ScreeningOverrideError):
        parse_query_overrides({"gold_price": ["0"]})


def test_parse_query_overrides_rejects_discount_above_100():
    # 150 would map to 1.5 which doesn't make sense as a discount fraction.
    with pytest.raises(ScreeningOverrideError):
        parse_query_overrides({"tier2_discount": ["150"]})


def test_parse_query_overrides_rejects_discount_equal_to_100():
    """A 100% discount collapses every P/E target to zero, which
    produces meaningless target prices. Reject at the boundary.

    Error message must say so in plain English because typing `100`
    and typing `1.0` both land at the same rejection path — the user
    needs to see the interpretation.
    """
    with pytest.raises(ScreeningOverrideError) as exc:
        parse_query_overrides({"tier2_discount": ["100"]})
    msg = str(exc.value)
    assert "100%" in msg
    assert "interpreted" in msg.lower()


def test_parse_query_overrides_rejects_fractional_discount_equal_to_one():
    """Same rejection when user types 1.0 directly (already-fractional).

    And the interpretation in the message should make clear why: `1.0`
    got treated as 100% because that's how the fraction convention works.
    """
    with pytest.raises(ScreeningOverrideError) as exc:
        parse_query_overrides({"tier2_discount": ["1.0"]})
    msg = str(exc.value)
    assert "100%" in msg


def test_parse_query_overrides_accepts_discount_just_under_100():
    """Boundary case: 99% is allowed (extreme but mathematically valid)."""
    overrides = parse_query_overrides({"tier2_discount": ["99"]})
    assert overrides.jurisdiction["tier_2"] == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# apply_overrides
# ---------------------------------------------------------------------------


def test_apply_overrides_with_empty_returns_same_config():
    app_config = _app_config()
    result = apply_overrides(app_config, ScreeningOverrides())
    assert result is app_config


def test_apply_overrides_layers_thresholds_into_screening_params():
    app_config = _app_config()
    overrides = parse_query_overrides({
        "aisc_target": ["1600"],
        "pe_target": ["7"],
        "tier2_discount": ["20"],
    })
    overridden = apply_overrides(app_config, overrides)

    assert overridden is not app_config
    assert overridden.screening_params.layer1_thresholds.aisc_max == 1600.0
    assert overridden.screening_params.verdict_thresholds.strong_candidate_forward_pe_max == 7.0
    assert overridden.screening_params.jurisdiction_discounts.tier_2 == pytest.approx(0.20)

    # Fields NOT overridden must pass through unchanged.
    assert (
        overridden.screening_params.layer1_thresholds.margin_min
        == app_config.screening_params.layer1_thresholds.margin_min
    )
    assert (
        overridden.screening_params.jurisdiction_discounts.tier_3
        == app_config.screening_params.jurisdiction_discounts.tier_3
    )

    # And the original config must remain unchanged.
    assert app_config.screening_params.layer1_thresholds.aisc_max == 1850.0


# ---------------------------------------------------------------------------
# compute_tool_b_in_memory
# ---------------------------------------------------------------------------


def _minimal_manual_data_for_test(tickers):
    """Minimal LoadedManualScreeningData stub for pipeline tests."""
    from golden_vector.screening.manual_data import LoadedManualScreeningData
    return LoadedManualScreeningData(
        store_path=None,  # type: ignore[arg-type]
        store_created=False,
        imported_csv_files=[],
        seeded_tickers=tickers,
        company_inputs=pd.DataFrame(columns=[
            "ticker", "production_oz", "aisc_usd_per_oz", "cash_cost_usd_per_oz",
            "royalty_rate", "sustaining_capex_musd", "da_musd",
            "interest_expense_musd", "tax_rate", "reserve_life_years",
            "net_debt_musd", "ebitda_ltm_musd",
        ]),
        source_verification=pd.DataFrame(columns=[
            "ticker", "field_name", "verification_status",
            "source_date", "source_url", "notes",
        ]),
        reporting_calendar=pd.DataFrame(columns=[
            "ticker", "next_financial_report_date",
            "next_production_report_date", "notes",
        ]),
        stock_notes=pd.DataFrame(columns=[
            "id", "ticker", "note_text", "note_tag", "note_status", "created_at_utc",
        ]),
    )


def test_compute_tool_b_in_memory_produces_incomplete_when_manual_data_blank():
    """With no manual data, every active ticker lands as INCOMPLETE. The
    function must still return a DataFrame with the expected schema and
    not raise."""
    app_config = _app_config()
    active_tickers = [
        t.ticker for t in app_config.universe.tickers
        if t.active and t.tool_b_enabled
    ]
    manual = _minimal_manual_data_for_test(active_tickers)
    snapshots = pd.DataFrame(columns=[
        "ticker", "snapshot_date", "share_price_usd", "market_cap_usd",
        "shares_outstanding", "normalization_status", "fx_staleness_days",
    ])

    result = compute_tool_b_in_memory(
        app_config=app_config,
        manual_data=manual,
        normalized_market_snapshots=snapshots,
        gold_price_assumption=4500.0,
    )

    assert len(result.index) == len(active_tickers)
    assert set(result["screening_verdict"].unique()) == {"INCOMPLETE"}
    assert "fundamental_check_rank" in result.columns
    assert "fundamental_check_summary" in result.columns
    removed_target_columns = {
        "target_price_peer_pe",
        "target_price_peak_pe",
        "target_price_peer_fcf",
        "target_price_peak_fcf",
        "upside_peer_pe_pct",
        "upside_peak_pe_pct",
        "upside_peer_fcf_pct",
        "upside_peak_fcf_pct",
        "target_price_peer_evebitda",
        "target_price_peak_evebitda",
        "best_target_price_usd",
        "best_upside_pct",
    }
    assert not removed_target_columns.intersection(result.columns)


def test_compute_tool_b_in_memory_respects_gold_price_override():
    """At $4500, forward EPS / forward P/E / upsides should differ from $4000
    for a ticker that has complete manual data."""
    app_config = _app_config()
    # Build a single-ticker universe overlay so we don't depend on the
    # full repo universe being in any particular state.
    from golden_vector.contracts.config_models import UniverseTicker, UniverseConfig
    nem = UniverseTicker(
        ticker="NEM", company="Newmont", exchange="NYSE", currency="USD",
        jurisdiction_tier=2, active=True, tool_a_enabled=True, tool_b_enabled=True,
    )
    small_universe = UniverseConfig(version=1, tickers=[nem])
    small_app_config = app_config.model_copy(update={"universe": small_universe})

    from golden_vector.screening.manual_data import LoadedManualScreeningData
    manual = LoadedManualScreeningData(
        store_path=None,  # type: ignore[arg-type]
        store_created=False,
        imported_csv_files=[],
        seeded_tickers=["NEM"],
        company_inputs=pd.DataFrame([{
            "ticker": "NEM",
            "production_oz": 5_900_000.0,
            "aisc_usd_per_oz": 1566.0,
            "cash_cost_usd_per_oz": 1180.0,
            "royalty_rate": 0.03,
            "sustaining_capex_musd": 1400.0,
            "da_musd": 2500.0,
            "interest_expense_musd": 200.0,
            "tax_rate": 0.28,
            "reserve_life_years": 22.0,
            "net_debt_musd": 500.0,
            "ebitda_ltm_musd": 11850.0,
        }]),
        source_verification=pd.DataFrame(columns=[
            "ticker", "field_name", "verification_status",
            "source_date", "source_url", "notes",
        ]),
        reporting_calendar=pd.DataFrame(columns=[
            "ticker", "next_financial_report_date",
            "next_production_report_date", "notes",
        ]),
        stock_notes=pd.DataFrame(columns=[
            "id", "ticker", "note_text", "note_tag", "note_status", "created_at_utc",
        ]),
    )
    snapshots = pd.DataFrame([{
        "ticker": "NEM",
        "snapshot_date": pd.Timestamp("2026-04-23").date(),
        "share_price_usd": 111.0,
        "market_cap_usd": 120_000_000_000.0,
        "shares_outstanding": 1_081_081_081.0,
        "normalization_status": "OK",
        "fx_staleness_days": 0,
    }])

    low = compute_tool_b_in_memory(
        app_config=small_app_config,
        manual_data=manual,
        normalized_market_snapshots=snapshots,
        gold_price_assumption=4000.0,
    )
    high = compute_tool_b_in_memory(
        app_config=small_app_config,
        manual_data=manual,
        normalized_market_snapshots=snapshots,
        gold_price_assumption=4500.0,
    )

    low_row = low[low["ticker"] == "NEM"].iloc[0]
    high_row = high[high["ticker"] == "NEM"].iloc[0]

    # Revenue scales linearly with gold price.
    assert high_row["forward_revenue_musd"] > low_row["forward_revenue_musd"]
    # Forward EPS grows with gold price (higher operating margin).
    assert high_row["forward_eps"] > low_row["forward_eps"]
    # Forward P/E is inverse (same share price, bigger EPS).
    assert high_row["forward_pe"] < low_row["forward_pe"]
