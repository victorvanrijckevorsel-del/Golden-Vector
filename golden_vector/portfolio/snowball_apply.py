"""Apply the gold-universe holdings into the manual portfolio store.

Builds the combined real position from two account sources and writes it via the
store's atomic + versioned-backup writer:

- Snowball/IBKR side: the import-ready Snowball rows (cross-broker snapshot; for the
  overlapping names this equals the IBKR positions), plus the deterministic SRB+SBI
  -> SRB.L merge.
- Hargreaves Lansdown ISA side: the ISA lots for names also held there (ALTN.L, AAZ.L,
  PAF.L), so the stored position is the TRUE combined holding, not one account's slice.

Real-money data: the store is gitignored and never committed. The actual write is
always two-step (preview, then explicit confirm) and the store's _write_lots makes a
versioned backup before overwriting, so an apply is reversible.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pandas as pd

from golden_vector.portfolio.models import PortfolioLot
from golden_vector.portfolio.snowball_import import SnowballDryRun

SOURCE_SNOWBALL_IBKR = "snowball_ibkr"
SOURCE_HL_ISA = "hl_isa"

# Names held in BOTH the HL ISA and the Snowball/IBKR account; their ISA lots are
# ADDED (not merged) so the combined position is correct. Verified by the HL-vs-Snowball
# reconciliation: the accounts are separate and additive.
HL_ISA_GOLD_NAMES: dict[str, str] = {
    "AltynGold": "ALTN.L",
    "Anglo Asian": "AAZ.L",
    "Pan African": "PAF.L",
}


@dataclass(frozen=True)
class HlIsaLot:
    ticker: str
    shares: float
    cost_gbp: float
    buy_date: _dt.date | None


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def _lot_id() -> str:
    return uuid4().hex


def _excel_serial_to_date(value: object) -> _dt.date | None:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date(1899, 12, 30) + _dt.timedelta(days=int(float(value)))
    except (TypeError, ValueError):
        return None


def parse_hl_isa_gold_lots(
    hl_path: Path, *, names: dict[str, str] | None = None
) -> list[HlIsaLot]:
    """Net ISA holdings for the in-scope gold names from HL's 'Trade analysis' sheet.

    Sums purchases minus sales (positional columns: 2=trade date, 5=action,
    7=shares purchased, 8=shares sold, 11=sum paid) and totals the GBP cash paid on
    purchases. Returns one lot per name with net shares > 0.
    """

    names = names or HL_ISA_GOLD_NAMES
    frame = pd.read_excel(hl_path, sheet_name="Trade analysis ", header=0, engine="openpyxl")
    agg: dict[str, dict[str, object]] = {
        ticker: {"buy": 0.0, "sell": 0.0, "cost": 0.0, "dates": []} for ticker in names.values()
    }
    current: str | None = None
    for values in frame.itertuples(index=False, name=None):
        desc = values[0]
        if isinstance(desc, str) and desc.strip() and not desc.strip()[0].isdigit():
            current = re.split(r"\s+\d", desc, maxsplit=1)[0].strip()
        ticker = next(
            (tk for name, tk in names.items() if current and name.lower() in current.lower()),
            None,
        )
        if ticker is None:
            continue
        action = str(values[5] or "").strip().lower()
        if "purchase" in action:
            if pd.notna(values[7]):
                agg[ticker]["buy"] += float(values[7])  # type: ignore[index]
            if pd.notna(values[11]):
                agg[ticker]["cost"] += abs(float(values[11]))  # type: ignore[index]
            parsed = _excel_serial_to_date(values[2])
            if parsed is not None:
                agg[ticker]["dates"].append(parsed)  # type: ignore[union-attr]
        elif "sale" in action:
            if pd.notna(values[8]):
                agg[ticker]["sell"] += abs(float(values[8]))  # type: ignore[index]
    lots: list[HlIsaLot] = []
    for ticker, data in agg.items():
        net = float(data["buy"]) - float(data["sell"])  # type: ignore[arg-type]
        if net <= 0:
            continue
        # Fail loud rather than ship a wrong cost basis: this builder sums GROSS purchase cash, so a
        # partial sale would leave the remaining shares with overstated cost (and understated P&L).
        # We have no FIFO/avg-cost accounting here, so refuse instead of silently miscounting.
        if float(data["sell"]) > 0:  # type: ignore[arg-type]
            raise ValueError(
                f"HL ISA history for {ticker} contains a sale; gross-purchase cost basis would be "
                "overstated. Supply a current-holdings cost-basis export, or add FIFO/average-cost "
                "sale accounting, before importing this name."
            )
        dates = data["dates"]  # type: ignore[assignment]
        lots.append(
            HlIsaLot(
                ticker=ticker,
                shares=net,
                cost_gbp=round(float(data["cost"]), 2),  # type: ignore[arg-type]
                buy_date=min(dates) if dates else None,
            )
        )
    return lots


def _lot(
    *,
    ticker: str,
    shares: float,
    cost_total: float,
    quote_currency: str,
    cost_currency: str,
    buy_date: _dt.date,
    note: str | None,
    raw_symbol: str,
    source_name: str,
    source_file: str,
    now: _dt.datetime,
) -> PortfolioLot:
    # buy_currency is the QUOTE currency (the market the ticker trades in, e.g. AUD for
    # .AX) — the valuer matches it against the snapshot's price currency, so it must be
    # the quote currency, NOT the cost currency. cost_currency / cost_basis_total carry
    # the (possibly different) cost leg, e.g. a GBP cost on an AUD-quoted stock. buy_price
    # is the legacy per-share field and is not used for P&L (cost_basis_total is).
    shares = float(shares)
    cost_total = float(cost_total)
    return PortfolioLot(
        id=_lot_id(),
        ticker=ticker,
        shares=shares,
        buy_price=(cost_total / shares) if shares else 0.0,
        buy_currency=quote_currency,
        buy_date=buy_date,
        note=note,
        created_at=now,
        updated_at=now,
        cost_currency=cost_currency,
        cost_basis_total=cost_total,
        raw_broker_symbol=raw_symbol,
        source_name=source_name,
        source_file=source_file,
        cost_basis_as_of_date=buy_date,
    )


def build_combined_gold_lots(
    dry_run: SnowballDryRun,
    *,
    hl_isa_lots: list[HlIsaLot],
    snowball_as_of: _dt.date,
    hl_as_of: _dt.date,
    snowball_source_file: str,
    hl_source_file: str,
    now: _dt.datetime | None = None,
    merge_ticker: str = "SRB.L",
) -> list[PortfolioLot]:
    """The full combined gold position as portfolio lots.

    = one lot per import-ready Snowball row (source snowball_ibkr) + a single merged
    lot for the review rows that share ``merge_ticker`` (SRB + SBI -> SRB.L) + one lot
    per HL ISA holding (source hl_isa). HL lots are ADDED, never merged into the
    Snowball lot, so a name held in both accounts keeps two source-tagged lots.
    """

    now = now or _now()
    lots: list[PortfolioLot] = []
    for row in dry_run.import_ready_rows:
        lots.append(
            _lot(
                ticker=str(row.mapped_ticker),
                shares=row.shares,
                cost_total=row.cost_basis,
                quote_currency=row.configured_currency or row.source_currency,
                cost_currency=row.source_currency,
                buy_date=snowball_as_of,
                note=None,
                raw_symbol=row.raw_symbol,
                source_name=SOURCE_SNOWBALL_IBKR,
                source_file=snowball_source_file,
                now=now,
            )
        )
    merge_rows = [row for row in dry_run.review_rows if row.mapped_ticker == merge_ticker]
    if merge_rows:
        shares = sum(float(row.shares) for row in merge_rows)
        cost = sum(float(row.cost_basis) for row in merge_rows)
        symbols = " + ".join(row.raw_symbol for row in merge_rows)
        lots.append(
            _lot(
                ticker=merge_ticker,
                shares=shares,
                cost_total=cost,
                quote_currency=merge_rows[0].configured_currency or merge_rows[0].source_currency,
                cost_currency=merge_rows[0].source_currency,
                buy_date=snowball_as_of,
                note=f"Merged Snowball rows {symbols} (same company).",
                raw_symbol=symbols,
                source_name=SOURCE_SNOWBALL_IBKR,
                source_file=snowball_source_file,
                now=now,
            )
        )
    for hl in hl_isa_lots:
        lots.append(
            _lot(
                ticker=hl.ticker,
                shares=hl.shares,
                cost_total=hl.cost_gbp,
                # The HL ISA gold names (ALTN.L/AAZ.L/PAF.L) are London-listed, GBP-quoted,
                # with a GBP cost — quote and cost currency coincide here.
                quote_currency="GBP",
                cost_currency="GBP",
                buy_date=hl.buy_date or hl_as_of,
                note="Hargreaves Lansdown ISA holding (separate account, added to IBKR).",
                raw_symbol=hl.ticker,
                source_name=SOURCE_HL_ISA,
                source_file=hl_source_file,
                now=now,
            )
        )
    return lots


def combined_lots_preview(lots: list[PortfolioLot]) -> str:
    """A human-readable preview: per-ticker combined totals + per-lot detail by source."""

    by_ticker: dict[str, list[PortfolioLot]] = {}
    for lot in lots:
        by_ticker.setdefault(lot.ticker, []).append(lot)
    out: list[str] = [f"{len(lots)} lots across {len(by_ticker)} tickers:"]
    for ticker in sorted(by_ticker):
        group = by_ticker[ticker]
        tot_shares = sum(lot.shares for lot in group)
        tot_cost = sum(float(lot.cost_basis_total or 0.0) for lot in group)
        out.append(f"  {ticker}: {tot_shares:g} shares, cost {tot_cost:,.2f} (combined)")
        if len(group) > 1:
            for lot in group:
                out.append(
                    f"      - {lot.source_name}: {lot.shares:g} @ cost "
                    f"{float(lot.cost_basis_total or 0.0):,.2f} {lot.cost_currency}"
                )
    return "\n".join(out)
