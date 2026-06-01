"""Cross-ticker comparison rows for put scenario bundles."""

from __future__ import annotations

from dataclasses import dataclass

from golden_vector.hedge.scenarios import CandidateScenarioBundle

DEFAULT_COMPARISON_SORT = "pnl_per_contract_minus10"
COMPARISON_SORT_COLUMNS = (
    "pnl_per_contract_minus5",
    "pnl_per_contract_minus10",
    "pnl_per_contract_minus20",
    "pnl_per_dollar_premium_minus10",
    "breakeven_gold_pct",
)


@dataclass(frozen=True)
class ComparisonRow:
    ticker: str
    horizon: str
    strike: float
    expiry: str
    premium_mid: float
    delta_gap: float | None
    breakeven_gold_pct: float | None
    pnl_per_contract_minus5: float | None
    pnl_per_contract_minus10: float | None
    pnl_per_contract_minus20: float | None
    pnl_per_dollar_premium_minus10: float | None


def build_comparison_table(
    *,
    bundles: list[CandidateScenarioBundle],
    sort_by: str = DEFAULT_COMPARISON_SORT,
    descending: bool = True,
) -> list[ComparisonRow]:
    """Flatten scenario bundles into sortable comparison rows."""

    if sort_by not in COMPARISON_SORT_COLUMNS:
        choices = ", ".join(COMPARISON_SORT_COLUMNS)
        raise ValueError(f"Unsupported comparison sort column {sort_by!r}; expected one of: {choices}")

    rows = [_comparison_row(bundle) for bundle in bundles]
    rows = [row for row in rows if row is not None]
    return sorted(rows, key=lambda row: _sort_key(row, sort_by, descending))


def _comparison_row(bundle: CandidateScenarioBundle) -> ComparisonRow | None:
    if bundle.skipped_reason is not None or not bundle.rows:
        return None
    premium_mid = bundle.candidate.mid
    if premium_mid is None:
        return None

    pnl_minus5 = _pnl_at_gold_change(bundle, -0.05)
    pnl_minus10 = _pnl_at_gold_change(bundle, -0.10)
    pnl_minus20 = _pnl_at_gold_change(bundle, -0.20)
    return_on_premium = (
        pnl_minus10 / premium_mid
        if premium_mid > 0 and pnl_minus10 is not None
        else None
    )
    return ComparisonRow(
        ticker=bundle.ticker,
        horizon=bundle.horizon,
        strike=bundle.candidate.strike,
        expiry=bundle.candidate.expiration,
        premium_mid=premium_mid,
        delta_gap=bundle.candidate.delta_gap,
        breakeven_gold_pct=bundle.breakeven_gold_pct,
        pnl_per_contract_minus5=pnl_minus5,
        pnl_per_contract_minus10=pnl_minus10,
        pnl_per_contract_minus20=pnl_minus20,
        pnl_per_dollar_premium_minus10=return_on_premium,
    )


def _pnl_at_gold_change(
    bundle: CandidateScenarioBundle,
    gold_pct_change: float,
) -> float | None:
    for row in bundle.rows:
        if abs(row.gold_pct_change - gold_pct_change) < 1e-9:
            return row.pnl_per_contract_at_expiry
    return None


def _sort_key(
    row: ComparisonRow,
    sort_by: str,
    descending: bool,
) -> tuple[bool, float]:
    value = getattr(row, sort_by)
    if value is None:
        return (True, 0.0)
    return (False, -value if descending else value)
