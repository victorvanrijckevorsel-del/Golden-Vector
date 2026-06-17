from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.portfolio.snowball_apply import (
    SOURCE_HL_ISA,
    SOURCE_SNOWBALL_IBKR,
    HlIsaLot,
    build_combined_gold_lots,
    parse_hl_isa_gold_lots,
)
from golden_vector.portfolio.snowball_import import SnowballDryRun, SnowballHolding


def _row(raw, ticker, shares, cost, status, configured="GBP"):
    return SnowballHolding(
        raw_symbol=raw,
        name=raw,
        shares=shares,
        source_currency="GBP",  # cost currency
        cost_basis=cost,
        mapped_ticker=ticker,
        configured_currency=configured,  # quote currency (AUD for .AX)
        mapping_method="config",
        import_status=status,
        issues=(),
    )


def _dry_run() -> SnowballDryRun:
    return SnowballDryRun(
        source_path=Path("Snowball Holdings.csv"),
        holdings=(
            _row("EDVl", "EDV.L", 225, 5201.85, "IMPORT_READY"),
            _row("ALTNl", "ALTN.L", 998, 14414.46, "IMPORT_READY"),
            # AUD-quoted ASX name with a GBP cost: quote currency must be AUD, cost GBP.
            _row("CLA", "CLA.AX", 3256844, 21832.52, "IMPORT_READY", configured="AUD"),
            # SRB + SBI both map to SRB.L and are flagged REVIEW -> deterministic merge.
            _row("SRB", "SRB.L", 4391, 14997.41, "REVIEW"),
            _row("SBI", "SRB.L", 4566, 16167.04, "REVIEW"),
            _row("AALl", None, 280, 8081.97, "BLOCKED"),  # must be excluded
        ),
        existing_positions=(),
    )


def test_build_combined_gold_lots_merges_srb_adds_isa_and_excludes_blocked():
    hl = [
        HlIsaLot(ticker="ALTN.L", shares=209, cost_gbp=2492.46, buy_date=dt.date(2025, 12, 12)),
    ]
    lots = build_combined_gold_lots(
        _dry_run(),
        hl_isa_lots=hl,
        snowball_as_of=dt.date(2026, 6, 2),
        hl_as_of=dt.date(2026, 1, 6),
        snowball_source_file="Snowball Holdings.csv",
        hl_source_file="HL Analysis.xlsx",
        now=dt.datetime(2026, 6, 16, tzinfo=dt.timezone.utc),
    )
    by_ticker: dict[str, list] = {}
    for lot in lots:
        by_ticker.setdefault(lot.ticker, []).append(lot)

    # 3 import-ready + 1 merged SRB + 1 HL ISA = 5 lots; blocked AAL excluded.
    assert len(lots) == 5
    assert "AAL" not in {lot.raw_broker_symbol for lot in lots}

    # AUD-quoted ASX name with a GBP cost: quote currency AUD (so the valuer matches the
    # AUD price snapshot), cost currency GBP. This is the bug the first apply had.
    cla = by_ticker["CLA.AX"][0]
    assert cla.buy_currency == "AUD"
    assert cla.cost_currency == "GBP"
    assert round(float(cla.cost_basis_total), 2) == 21832.52

    # SRB+SBI merged into ONE SRB.L lot, shares and cost summed, Snowball-sourced.
    srb = by_ticker["SRB.L"]
    assert len(srb) == 1
    assert srb[0].shares == 4391 + 4566
    assert round(float(srb[0].cost_basis_total), 2) == round(14997.41 + 16167.04, 2)
    assert srb[0].source_name == SOURCE_SNOWBALL_IBKR

    # ALTN.L held in both accounts -> TWO source-tagged lots, not merged.
    altn = sorted(by_ticker["ALTN.L"], key=lambda lot: lot.source_name)
    assert [lot.source_name for lot in altn] == [SOURCE_HL_ISA, SOURCE_SNOWBALL_IBKR]
    assert {lot.shares for lot in altn} == {209, 998}

    # Cost basis carried as v2 fields; buy_price = cost / shares; GBP cost currency.
    edv = by_ticker["EDV.L"][0]
    assert edv.cost_currency == "GBP"
    assert round(float(edv.cost_basis_total), 2) == 5201.85
    assert round(edv.buy_price, 4) == round(5201.85 / 225, 4)

    # HL ISA lot keeps its real buy date and is tagged hl_isa.
    isa = next(lot for lot in altn if lot.source_name == SOURCE_HL_ISA)
    assert isa.buy_date == dt.date(2025, 12, 12)
    assert round(float(isa.cost_basis_total), 2) == 2492.46


def test_hl_parser_fails_loud_when_a_sale_is_present(tmp_path):
    """Gross-purchase cost basis would be overstated by a partial sale, so the parser must refuse
    rather than silently miscount P&L (Codex MEDIUM; no FIFO/avg-cost accounting here)."""
    cols = [f"c{i}" for i in range(12)]
    rows = [
        ["Testco plc"] + [None] * 11,  # name header -> sets current name
        [None, None, 46000, None, None, "Purchase", None, 100.0, None, None, None, 1000.0],
        [None, None, 46010, None, None, "Sale", None, None, 30.0, None, None, None],
    ]
    path = tmp_path / "hl.xlsx"
    pd.DataFrame(rows, columns=cols).to_excel(path, sheet_name="Trade analysis ", index=False)
    with pytest.raises(ValueError, match="contains a sale"):
        parse_hl_isa_gold_lots(path, names={"Testco": "TEST.L"})


def test_hl_parser_nets_pure_purchases_without_a_sale(tmp_path):
    # Control: with no sale, the same shape parses cleanly to one lot.
    cols = [f"c{i}" for i in range(12)]
    rows = [
        ["Testco plc"] + [None] * 11,
        [None, None, 46000, None, None, "Purchase", None, 100.0, None, None, None, 1000.0],
    ]
    path = tmp_path / "hl.xlsx"
    pd.DataFrame(rows, columns=cols).to_excel(path, sheet_name="Trade analysis ", index=False)
    lots = parse_hl_isa_gold_lots(path, names={"Testco": "TEST.L"})
    assert len(lots) == 1
    assert lots[0].shares == 100.0
    assert lots[0].cost_gbp == 1000.0


def test_portfolio_schema_v8_contract_includes_new_columns():
    from golden_vector.portfolio.benchmark_betas import BENCHMARK_BETA_COLUMNS
    from golden_vector.portfolio.models import PORTFOLIO_SCHEMA_VERSION
    from golden_vector.portfolio.pipeline import POSITION_COLUMNS

    assert PORTFOLIO_SCHEMA_VERSION == 8
    assert {"avg_cost_gbp", "pnl_fraction_gbp"} <= set(POSITION_COLUMNS)
    assert {
        "down_beta_6m",
        "up_beta_6m",
        "down_beta_12m",
        "up_beta_12m",
        "down_beta_3y",
        "up_beta_3y",
    } <= set(BENCHMARK_BETA_COLUMNS)
