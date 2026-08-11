from datetime import date

import pandas as pd
import pytest

from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import ToolDConfig
from golden_vector.model.gold_lines import (
    MIN_INVERTIBLE_SLOPE,
    GoldLine,
    evaluate,
    line_from_two_points,
    x_for_value,
)
from golden_vector.model.tool_d import build_tool_d_output_frame
from golden_vector.screening.manual_data import LoadedManualScreeningData


def test_line_from_two_points_hand_computed_slope_and_intercept():
    line = line_from_two_points(3000.0, 2000.0, 4000.0, 3000.0)

    assert line == GoldLine(slope=1.0, intercept=-1000.0)


def test_line_from_two_points_negative_slope_is_kept_here():
    """The generic fitter is direction-agnostic; only callers judge sign."""
    line = line_from_two_points(1000.0, 500.0, 2000.0, 100.0)

    assert line is not None
    assert line.slope == pytest.approx(-0.4)
    assert line.intercept == pytest.approx(900.0)


def test_line_from_two_points_same_x_is_degenerate():
    assert line_from_two_points(2000.0, 100.0, 2000.0, 500.0) is None
    # Closer than the separation floor counts as the same point too.
    assert line_from_two_points(2000.0, 100.0, 2000.005, 500.0) is None


def test_line_from_two_points_missing_value_returns_none():
    assert line_from_two_points(2000.0, None, 3000.0, 500.0) is None
    assert line_from_two_points(2000.0, 100.0, 3000.0, None) is None
    assert line_from_two_points(None, 100.0, 3000.0, 500.0) is None


def test_evaluate_round_trips_the_fitting_points():
    line = line_from_two_points(3000.0, 2000.0, 4000.0, 3000.0)

    assert evaluate(line, 3000.0) == pytest.approx(2000.0)
    assert evaluate(line, 4000.0) == pytest.approx(3000.0)
    assert evaluate(line, 3500.0) == pytest.approx(2500.0)
    assert evaluate(None, 3500.0) is None
    assert evaluate(line, None) is None


def test_x_for_value_inverts_back_to_a_point_that_evaluates_to_y():
    line = line_from_two_points(3000.0, 2000.0, 5000.0, 8000.0)

    x = x_for_value(line, 5000.0)

    assert x is not None
    assert evaluate(line, x) == pytest.approx(5000.0)


def test_x_for_value_zero_slope_returns_none():
    flat = line_from_two_points(3000.0, 2000.0, 4000.0, 2000.0)

    assert flat == GoldLine(slope=0.0, intercept=2000.0)
    assert x_for_value(flat, 2500.0) is None
    assert x_for_value(None, 2500.0) is None
    assert x_for_value(flat, None) is None


def test_tool_d_gold_thresholds_match_hand_computed_line_inversion():
    """Tool D still produces the same gold thresholds after the extraction.

    Stressed EBITDA 2000 at gold 3000 and anchor EBITDA 3000 at gold 4000 give
    slope 1.0 and intercept -1000. Interest cover (100) therefore lands at gold
    1100; debt stress needs EBITDA = net debt 2000 / danger 3.0 = 666.67, at
    gold 1666.67. Cost breakeven is reported AISC (1300) — C1 removed the
    double-counted "FCF breakeven" concept.
    """
    manual_data = LoadedManualScreeningData(
        company_inputs=pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "production_oz": 6_000_000,
                    "aisc_usd_per_oz": 1300,
                    "cash_cost_usd_per_oz": 900,
                    "royalty_rate": 0.03,
                    "sustaining_capex_musd": 900,
                    "da_musd": 500,
                    "interest_expense_musd": 100,
                    "tax_rate": 0.30,
                    "reserve_life_years": 12,
                    "net_debt_musd": 2000,
                    "ebitda_ltm_musd": 5000,
                }
            ]
        ),
        source_verification=pd.DataFrame(),
        reporting_calendar=pd.DataFrame(),
        stock_notes=pd.DataFrame(),
        store_path=ProjectPaths.discover().manual_screening_store_path,
        store_created=False,
        seeded_tickers=[],
        imported_csv_files=[],
    )

    def tool_b_row(forward_ebitda: float) -> dict[str, object]:
        return {
            "ticker": "AAA",
            "as_of_date": date(2026, 6, 1),
            "snapshot_refresh_run_id": "refresh-run",
            "market_cap_musd": 3000,
            "screening_verdict": "WATCHLIST",
            "confidence": "VERIFIED",
            "aisc_margin_yield": 0.01,
            "forward_ebitda_musd": forward_ebitda,
            "net_debt_musd": None,
            "interest_expense_musd": None,
        }

    output = build_tool_d_output_frame(
        stressed_tool_b=pd.DataFrame([tool_b_row(2000)]),
        spot_tool_b=pd.DataFrame([tool_b_row(3000)]),
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert row["interest_cover_gold_usd"] == pytest.approx(1100.0)
    assert row["debt_stress_gold_usd"] == pytest.approx(1666.6666667)
    assert row["breaks_even_at_gold_usd"] == pytest.approx(1300.0)
    assert "fcf_breakeven_gold_usd" not in row.index


def test_x_for_value_rejects_a_near_flat_slope():
    """The flat-slope guard is REAL, not decorative.

    ``MIN_INVERTIBLE_SLOPE`` used to be 0.0, so only an exactly-flat line was
    rejected and a slope of 1e-300 produced a confident-looking gold price made
    entirely of floating-point noise.
    """

    assert MIN_INVERTIBLE_SLOPE > 0.0

    exactly_flat = GoldLine(slope=0.0, intercept=5.0)
    assert x_for_value(exactly_flat, 10.0) is None

    at_the_threshold = GoldLine(slope=MIN_INVERTIBLE_SLOPE, intercept=5.0)
    assert x_for_value(at_the_threshold, 10.0) is None

    negative_near_flat = GoldLine(slope=-MIN_INVERTIBLE_SLOPE / 2.0, intercept=5.0)
    assert x_for_value(negative_near_flat, 10.0) is None

    # Healthy control: an ordinary slope still inverts exactly.
    usable = GoldLine(slope=2.0, intercept=5.0)
    assert x_for_value(usable, 25.0) == pytest.approx(10.0)
    # And a slope just above the threshold is still accepted (not over-guarded).
    just_above = GoldLine(slope=MIN_INVERTIBLE_SLOPE * 10.0, intercept=0.0)
    assert x_for_value(just_above, MIN_INVERTIBLE_SLOPE * 10.0) == pytest.approx(1.0)
