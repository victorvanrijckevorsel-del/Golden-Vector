"""Dry-run parser for Snowball portfolio holding exports.

The Snowball file is a current-position snapshot, not a transaction ledger.
This module intentionally starts read-only: it parses, maps broker symbols to
Golden Vector tickers, compares against the existing manual store, and reports
what would be safe or unsafe to import. It does not overwrite manual_lots.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.numeric import optional_float
from golden_vector.common.strings import clean_string, normalize_ticker
from golden_vector.portfolio.manual_store import load_lots
from golden_vector.portfolio.models import TickerInfo

REQUIRED_SNOWBALL_COLUMNS = (
    "Holding",
    "Holdings' name",
    "Shares",
    "Currency",
    "Cost basis",
)

# Broker aliases that are not derivable from Yahoo-style suffix rules. These
# are REVIEW mappings: same company, but the listing/currency needs human signoff
# before writing to the current single-currency-per-ticker lot store.
BROKER_SYMBOL_ALIASES: dict[str, str] = {
    "SBI": "SRB.L",  # Serabi TSX line; Snowball also carries SRB.L separately.
}


@dataclass(frozen=True)
class SnowballHolding:
    raw_symbol: str
    name: str
    shares: float
    source_currency: str
    cost_basis: float
    mapped_ticker: str | None
    configured_currency: str | None
    mapping_method: str
    import_status: str
    issues: tuple[str, ...]

    @property
    def cost_per_share_source_currency(self) -> float:
        return self.cost_basis / self.shares


@dataclass(frozen=True)
class ExistingPortfolioPosition:
    ticker: str
    shares: float
    cost_local: float
    currency: str


@dataclass(frozen=True)
class SnowballDryRun:
    source_path: Path
    holdings: tuple[SnowballHolding, ...]
    existing_positions: tuple[ExistingPortfolioPosition, ...]

    @property
    def total_cost_basis(self) -> float:
        return sum(row.cost_basis for row in self.holdings)

    @property
    def mapped_rows(self) -> tuple[SnowballHolding, ...]:
        return tuple(row for row in self.holdings if row.mapped_ticker)

    @property
    def import_ready_rows(self) -> tuple[SnowballHolding, ...]:
        return tuple(row for row in self.holdings if row.import_status == "IMPORT_READY")

    @property
    def review_rows(self) -> tuple[SnowballHolding, ...]:
        return tuple(row for row in self.holdings if row.import_status == "REVIEW")

    @property
    def blocked_rows(self) -> tuple[SnowballHolding, ...]:
        return tuple(row for row in self.holdings if row.import_status == "BLOCKED")


def build_snowball_dry_run(
    *,
    paths: ProjectPaths,
    source_path: Path,
    ticker_info: dict[str, TickerInfo],
) -> SnowballDryRun:
    """Parse a Snowball holdings CSV and compare it with the current store."""

    holdings = tuple(
        _parse_snowball_frame(
            _read_snowball_csv(source_path),
            ticker_info=ticker_info,
        )
    )
    holdings = _with_duplicate_mapping_issues(holdings)
    existing_positions = tuple(_existing_positions(paths))
    return SnowballDryRun(
        source_path=source_path,
        holdings=holdings,
        existing_positions=existing_positions,
    )


def write_snowball_dry_run_report(
    dry_run: SnowballDryRun,
    report_path: Path,
) -> Path:
    """Write a private Markdown dry-run report for cross-checking."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_snowball_dry_run_report(dry_run), encoding="utf-8")
    return report_path


def render_snowball_dry_run_report(dry_run: SnowballDryRun) -> str:
    """Render a human-readable dry-run report.

    The report is intended for data/manual/portfolio/ (gitignored) because it
    includes position quantities and costs.
    """

    holdings = dry_run.holdings
    mapped = dry_run.mapped_rows
    ready = dry_run.import_ready_rows
    review = dry_run.review_rows
    blocked = dry_run.blocked_rows
    existing = dry_run.existing_positions
    lines = [
        "# Snowball Portfolio Import Dry Run",
        "",
        "This report is read-only. No portfolio store was changed.",
        "",
        "## Summary",
        "",
        f"- Source file: `{dry_run.source_path}`",
        f"- Snowball rows parsed: {len(holdings)}",
        f"- Rows mapped to Golden Vector tickers: {len(mapped)}",
        f"- Rows import-ready under the current store model: {len(ready)}",
        f"- Rows needing human review: {len(review)}",
        f"- Rows blocked: {len(blocked)}",
        f"- Snowball total cost basis: GBP {dry_run.total_cost_basis:,.2f}",
        f"- Existing manual-store positions: {len(existing)}",
        "",
        "## Key Safety Finding",
        "",
        (
            "Snowball's `Currency` column is GBP for every row. For non-GBP "
            "listings, this appears to be broker/base cost basis rather than the "
            "security's quote currency. The current `manual_lots.json` schema "
            "stores only one `buy_currency` and requires it to match the ticker's "
            "configured quote currency, so those rows cannot be safely written "
            "without adding a separate cost-currency/base-currency model."
        ),
        "",
        "## Parsed Holdings",
        "",
        "| Raw symbol | Name | Shares | Source cost ccy | Cost basis | Mapped ticker | Config ccy | Status | Issues |",
        "|---|---|---:|---|---:|---|---|---|---|",
    ]
    for row in holdings:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.raw_symbol),
                    _md(row.name),
                    _fmt_number(row.shares),
                    _md(row.source_currency),
                    _fmt_money(row.cost_basis),
                    _md(row.mapped_ticker or "-"),
                    _md(row.configured_currency or "-"),
                    _md(row.import_status),
                    _md("; ".join(row.issues) if row.issues else "-"),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Current Manual Store Aggregate",
            "",
            "| Ticker | Shares | Cost local | Currency |",
            "|---|---:|---:|---|",
        ]
    )
    for row in existing:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.ticker),
                    _fmt_number(row.shares),
                    _fmt_money(row.cost_local),
                    _md(row.currency),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Recommended Next Step",
            "",
            (
                "Do not overwrite `manual_lots.json` yet. First decide whether the "
                "portfolio store should be upgraded to store `cost_currency` "
                "separately from quote currency. Once that exists, Snowball can "
                "become the source of truth for current positions and HL can stay "
                "as an audit/history source."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def candidate_manual_lot_payloads(dry_run: SnowballDryRun) -> list[dict[str, object]]:
    """Return safe current-schema lot payloads for IMPORT_READY rows only."""

    payloads: list[dict[str, object]] = []
    for row in dry_run.import_ready_rows:
        assert row.mapped_ticker is not None
        payloads.append(
            {
                "ticker": row.mapped_ticker,
                "shares": row.shares,
                "buy_price": row.cost_per_share_source_currency,
                "buy_currency": row.source_currency,
                "buy_date": "2026-06-15",
                "note": f"Snowball dry-run import from {row.raw_symbol}",
            }
        )
    return payloads


def _read_snowball_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Snowball holdings file not found: {path}")
    frame = pd.read_csv(path, dtype=object, encoding="utf-8-sig")
    missing = [column for column in REQUIRED_SNOWBALL_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(
            "Snowball holdings file is missing required columns: "
            + ", ".join(missing)
        )
    return frame[list(REQUIRED_SNOWBALL_COLUMNS)].copy()


def _parse_snowball_frame(
    frame: pd.DataFrame,
    *,
    ticker_info: dict[str, TickerInfo],
) -> list[SnowballHolding]:
    holdings: list[SnowballHolding] = []
    for raw in frame.to_dict(orient="records"):
        raw_symbol = clean_string(raw.get("Holding"))
        name = clean_string(raw.get("Holdings' name"))
        shares = optional_float(raw.get("Shares"))
        currency = (clean_string(raw.get("Currency")) or "").upper()
        cost_basis = optional_float(raw.get("Cost basis"))
        if not raw_symbol and not name and shares is None and cost_basis is None:
            continue
        issues: list[str] = []
        if not raw_symbol:
            issues.append("missing_symbol")
        if not name:
            issues.append("missing_name")
        if shares is None or shares <= 0:
            issues.append("invalid_shares")
        if not currency:
            issues.append("missing_source_currency")
        if cost_basis is None or cost_basis <= 0:
            issues.append("invalid_cost_basis")
        mapped_ticker, mapping_method = _map_symbol(raw_symbol, ticker_info)
        info = ticker_info.get(mapped_ticker or "")
        configured_currency = info.currency if info else None
        if mapped_ticker is None:
            issues.append("unmapped_ticker")
        elif info is None or not info.active:
            issues.append("inactive_or_missing_universe_ticker")
        elif currency != configured_currency:
            issues.append("currency_model_gap")
        if mapping_method == "manual_alias":
            issues.append("manual_alias_review")
        status = _import_status(issues)
        holdings.append(
            SnowballHolding(
                raw_symbol=str(raw_symbol or ""),
                name=str(name or ""),
                shares=float(shares or 0.0),
                source_currency=currency,
                cost_basis=float(cost_basis or 0.0),
                mapped_ticker=mapped_ticker,
                configured_currency=configured_currency,
                mapping_method=mapping_method,
                import_status=status,
                issues=tuple(issues),
            )
        )
    return holdings


def _map_symbol(
    raw_symbol: str | None,
    ticker_info: dict[str, TickerInfo],
) -> tuple[str | None, str]:
    text = clean_string(raw_symbol)
    if not text:
        return None, "missing"
    normalized = normalize_ticker(text)
    if normalized in ticker_info:
        return normalized, "exact"
    alias = BROKER_SYMBOL_ALIASES.get(normalized or "")
    if alias in ticker_info:
        return alias, "manual_alias"
    lse_candidate = _lse_candidate(text)
    if lse_candidate in ticker_info:
        return lse_candidate, "lowercase_l_suffix"
    base_matches = [
        ticker
        for ticker in ticker_info
        if ticker.split(".", maxsplit=1)[0] == normalized
    ]
    if len(base_matches) == 1:
        return base_matches[0], "unique_base_symbol"
    if len(base_matches) > 1:
        return None, "ambiguous_base_symbol"
    return None, "unmapped"


def _lse_candidate(raw_symbol: str) -> str | None:
    stripped = raw_symbol.strip()
    if not stripped.endswith("l"):
        return None
    stem = stripped[:-1].strip().upper()
    if not stem:
        return None
    return f"{stem}.L"


def _with_duplicate_mapping_issues(
    holdings: tuple[SnowballHolding, ...],
) -> tuple[SnowballHolding, ...]:
    counts: dict[str, int] = {}
    for row in holdings:
        if row.mapped_ticker:
            counts[row.mapped_ticker] = counts.get(row.mapped_ticker, 0) + 1
    updated: list[SnowballHolding] = []
    for row in holdings:
        if row.mapped_ticker and counts.get(row.mapped_ticker, 0) > 1:
            issues = tuple(dict.fromkeys([*row.issues, "multiple_source_rows_same_ticker"]))
            updated.append(
                SnowballHolding(
                    raw_symbol=row.raw_symbol,
                    name=row.name,
                    shares=row.shares,
                    source_currency=row.source_currency,
                    cost_basis=row.cost_basis,
                    mapped_ticker=row.mapped_ticker,
                    configured_currency=row.configured_currency,
                    mapping_method=row.mapping_method,
                    import_status=_import_status(list(issues)),
                    issues=issues,
                )
            )
        else:
            updated.append(row)
    return tuple(updated)


def _import_status(issues: list[str]) -> str:
    blocking = {
        "missing_symbol",
        "invalid_shares",
        "missing_source_currency",
        "invalid_cost_basis",
        "unmapped_ticker",
        "inactive_or_missing_universe_ticker",
        "currency_model_gap",
    }
    review = {
        "manual_alias_review",
        "multiple_source_rows_same_ticker",
    }
    issue_set = set(issues)
    if issue_set & blocking:
        return "BLOCKED"
    if issue_set & review:
        return "REVIEW"
    return "IMPORT_READY"


def _existing_positions(paths: ProjectPaths) -> list[ExistingPortfolioPosition]:
    positions: dict[tuple[str, str], ExistingPortfolioPosition] = {}
    for lot in load_lots(paths):
        key = (lot.ticker, lot.buy_currency)
        existing = positions.get(key)
        if existing is None:
            positions[key] = ExistingPortfolioPosition(
                ticker=lot.ticker,
                shares=lot.shares,
                cost_local=lot.cost_local,
                currency=lot.buy_currency,
            )
            continue
        positions[key] = ExistingPortfolioPosition(
            ticker=lot.ticker,
            shares=existing.shares + lot.shares,
            cost_local=existing.cost_local + lot.cost_local,
            currency=lot.buy_currency,
        )
    return sorted(positions.values(), key=lambda item: (item.ticker, item.currency))


def _fmt_number(value: float) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def _md(value: object) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")
