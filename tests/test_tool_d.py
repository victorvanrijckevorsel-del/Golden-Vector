from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import ToolDConfig
from golden_vector.model.tool_d import (
    TOOL_D_OUTPUT_COLUMNS,
    ToolDExecutionInputs,
    build_tool_d_output_frame,
    compute_tool_d_outputs,
)
from golden_vector.screening.manual_data import (
    LoadedManualScreeningData,
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import upsert_company_input
from tests.helpers import build_test_paths


def test_compute_tool_d_outputs_uses_forward_ebitda_not_tool_b_leverage(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _only_active_tickers(load_app_config(ProjectPaths.discover()).app, "NEM")
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    upsert_company_input(paths, ticker="NEM", values=_manual_payload())
    manual_data = load_manual_screening_data(paths, tickers=["NEM"])
    tool_b_latest = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "source_run_id": "tool-b-run",
                # Deliberately bogus: Tool D must not read this trailing leverage column.
                "leverage": 999.0,
            }
        ]
    )

    output = compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=app_config,
            manual_data=manual_data,
            normalized_market_snapshots=_market_snapshot(),
            tool_b_latest=tool_b_latest,
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            snapshot_refresh_run_id="refresh-run",
            snapshot_as_of_date="2026-06-01",
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    expected_leverage = row["net_debt_musd"] / row["forward_ebitda_musd_at_g"]
    assert list(output.columns) == TOOL_D_OUTPUT_COLUMNS
    assert row["source_tool_b_run_id"] == "tool-b-run"
    assert row["leverage_stressed_at_g"] == pytest.approx(expected_leverage)
    assert row["leverage_stressed_at_g"] != 999.0
    assert row["forward_ebitda_musd_at_spot"] > row["forward_ebitda_musd_at_g"]
    assert row["tool_d_quality_rank"] == 100.0


def test_tool_d_quality_rank_uses_exact_three_components_fcf_context_only():
    manual_data = _manual_data(
        [
            _manual_payload(ticker="AAA", aisc=1500, net_debt=1000),
            _manual_payload(ticker="BBB", aisc=2000, net_debt=1000),
        ]
    )
    stressed = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=1000, fcf_yield=0.05),
            # BBB has much higher FCF yield, but worse headroom/leverage/EV-EBITDA.
            _tool_b_row("BBB", forward_ebitda=500, fcf_yield=0.90),
        ]
    )
    spot = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=900, fcf_yield=0.05),
            _tool_b_row("BBB", forward_ebitda=450, fcf_yield=0.90),
        ]
    )

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame(
            [
                {"ticker": "AAA", "source_run_id": "tool-b-run"},
                {"ticker": "BBB", "source_run_id": "tool-b-run"},
            ]
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    rows = output.set_index("ticker")

    assert rows.loc["AAA", "tool_d_quality_rank"] == 100.0
    assert rows.loc["BBB", "tool_d_quality_rank"] == 50.0
    assert rows.loc["BBB", "fcf_yield"] > rows.loc["AAA", "fcf_yield"]


def _only_active_tickers(app_config, *tickers: str):
    targets = {ticker.upper() for ticker in tickers}
    new_tickers = [
        ticker.model_copy(update={"active": ticker.ticker in targets})
        for ticker in app_config.universe.tickers
    ]
    return app_config.model_copy(
        update={"universe": app_config.universe.model_copy(update={"tickers": new_tickers})}
    )


def _market_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "snapshot_date": date(2026, 6, 1),
                "share_price_usd": 60.0,
                "market_cap_usd": 48_000_000_000.0,
                "shares_outstanding": 800_000_000.0,
                "normalization_status": "OK",
            }
        ]
    )


def _manual_payload(
    *,
    ticker: str = "NEM",
    aisc: float = 1300,
    net_debt: float = 2000,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "production_oz": 6_000_000,
        "aisc_usd_per_oz": aisc,
        "cash_cost_usd_per_oz": 900,
        "royalty_rate": 0.03,
        "sustaining_capex_musd": 900,
        "da_musd": 500,
        "interest_expense_musd": 100,
        "tax_rate": 0.30,
        "reserve_life_years": 12,
        "net_debt_musd": net_debt,
        "ebitda_ltm_musd": 5000,
    }


def _manual_data(rows: list[dict[str, object]]) -> LoadedManualScreeningData:
    return LoadedManualScreeningData(
        company_inputs=pd.DataFrame(rows),
        source_verification=pd.DataFrame(),
        reporting_calendar=pd.DataFrame(),
        stock_notes=pd.DataFrame(),
        store_path=ProjectPaths.discover().manual_screening_store_path,
        store_created=False,
        seeded_tickers=[],
        imported_csv_files=[],
    )


def _tool_b_row(ticker: str, *, forward_ebitda: float, fcf_yield: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "as_of_date": date(2026, 6, 1),
        "snapshot_refresh_run_id": "refresh-run",
        "market_cap_musd": 3000,
        "screening_verdict": "WATCHLIST",
        "confidence": "VERIFIED",
        "fcf_yield": fcf_yield,
        "best_upside_pct": 0.5,
        "forward_ebitda_musd": forward_ebitda,
    }
