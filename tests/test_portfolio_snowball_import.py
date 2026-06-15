from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.portfolio.models import TickerInfo
from golden_vector.portfolio.snowball_import import (
    build_snowball_dry_run,
    candidate_manual_lot_payloads,
    render_snowball_dry_run_report,
)


def test_snowball_dry_run_maps_symbols_and_blocks_currency_gaps(tmp_path):
    paths = _paths(tmp_path)
    source = paths.manual_portfolio_dir / "Snowball Holdings.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "Holding": "EDVl",
                "Holdings' name": "Endeavour Mining PLC",
                "Shares": "225",
                "Currency": "GBP",
                "Cost basis": "5201.85",
            },
            {
                "Holding": "AAR",
                "Holdings' name": "Astral Resources NL",
                "Shares": "10000",
                "Currency": "GBP",
                "Cost basis": "1363.04",
            },
            {
                "Holding": "SBI",
                "Holdings' name": "Serabi Gold PLC",
                "Shares": "4566",
                "Currency": "GBP",
                "Cost basis": "16167.04",
            },
            {
                "Holding": "ZZZ",
                "Holdings' name": "Not In Universe",
                "Shares": "1",
                "Currency": "GBP",
                "Cost basis": "10",
            },
        ]
    ).to_csv(source, index=False)
    ticker_info = {
        "EDV.L": TickerInfo(ticker="EDV.L", currency="GBP", company="Endeavour Mining"),
        "AAR.AX": TickerInfo(ticker="AAR.AX", currency="AUD", company="Astral Resources"),
        "SRB.L": TickerInfo(ticker="SRB.L", currency="GBP", company="Serabi Gold"),
    }

    dry_run = build_snowball_dry_run(
        paths=paths,
        source_path=source,
        ticker_info=ticker_info,
    )
    rows = {row.raw_symbol: row for row in dry_run.holdings}

    assert rows["EDVl"].mapped_ticker == "EDV.L"
    assert rows["EDVl"].mapping_method == "lowercase_l_suffix"
    assert rows["EDVl"].import_status == "IMPORT_READY"
    assert rows["AAR"].mapped_ticker == "AAR.AX"
    assert "currency_model_gap" in rows["AAR"].issues
    assert rows["AAR"].import_status == "BLOCKED"
    assert rows["SBI"].mapped_ticker == "SRB.L"
    assert "manual_alias_review" in rows["SBI"].issues
    assert rows["SBI"].import_status == "REVIEW"
    assert rows["ZZZ"].mapped_ticker is None
    assert rows["ZZZ"].import_status == "BLOCKED"
    assert not paths.manual_portfolio_lots_path.exists()


def test_snowball_candidate_payloads_only_include_current_schema_safe_rows(tmp_path):
    paths = _paths(tmp_path)
    source = paths.manual_portfolio_dir / "Snowball Holdings.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "Holding": "EDVl",
                "Holdings' name": "Endeavour Mining PLC",
                "Shares": "2",
                "Currency": "GBP",
                "Cost basis": "50",
            },
            {
                "Holding": "AAR",
                "Holdings' name": "Astral Resources NL",
                "Shares": "100",
                "Currency": "GBP",
                "Cost basis": "20",
            },
        ]
    ).to_csv(source, index=False)
    dry_run = build_snowball_dry_run(
        paths=paths,
        source_path=source,
        ticker_info={
            "EDV.L": TickerInfo(ticker="EDV.L", currency="GBP"),
            "AAR.AX": TickerInfo(ticker="AAR.AX", currency="AUD"),
        },
    )

    payloads = candidate_manual_lot_payloads(dry_run)

    assert payloads == [
        {
            "ticker": "EDV.L",
            "shares": 2.0,
            "buy_price": 25.0,
            "buy_currency": "GBP",
            "buy_date": "2026-06-15",
            "note": "Snowball dry-run import from EDVl",
        }
    ]


def test_snowball_report_states_no_store_change_and_currency_model_gap(tmp_path):
    paths = _paths(tmp_path)
    source = paths.manual_portfolio_dir / "Snowball Holdings.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "Holding": "AAR",
                "Holdings' name": "Astral Resources NL",
                "Shares": "100",
                "Currency": "GBP",
                "Cost basis": "20",
            }
        ]
    ).to_csv(source, index=False)
    dry_run = build_snowball_dry_run(
        paths=paths,
        source_path=source,
        ticker_info={"AAR.AX": TickerInfo(ticker="AAR.AX", currency="AUD")},
    )

    report = render_snowball_dry_run_report(dry_run)

    assert "This report is read-only. No portfolio store was changed." in report
    assert "currency_model_gap" in report
    assert "cost-currency/base-currency model" in report


def _paths(tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(
        repo_root=tmp_path,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        raw_dir=tmp_path / "data" / "raw",
        intermediate_dir=tmp_path / "data" / "intermediate",
        output_dir=tmp_path / "data" / "output",
        manual_dir=tmp_path / "data" / "manual",
        runs_dir=tmp_path / "data" / "runs",
        reviews_dir=tmp_path / "reviews",
        tests_dir=tmp_path / "tests",
    )
