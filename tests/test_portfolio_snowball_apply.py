from __future__ import annotations

import datetime as dt
from pathlib import Path

from golden_vector.portfolio.snowball_apply import (
    SOURCE_HL_ISA,
    SOURCE_SNOWBALL_IBKR,
    HlIsaLot,
    build_combined_gold_lots,
)
from golden_vector.portfolio.snowball_import import SnowballDryRun, SnowballHolding


def _row(raw, ticker, shares, cost, status):
    return SnowballHolding(
        raw_symbol=raw,
        name=raw,
        shares=shares,
        source_currency="GBP",
        cost_basis=cost,
        mapped_ticker=ticker,
        configured_currency="GBP",
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

    # 2 import-ready + 1 merged SRB + 1 HL ISA = 4 lots; blocked AAL excluded.
    assert len(lots) == 4
    assert "AAL" not in {lot.raw_broker_symbol for lot in lots}

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
