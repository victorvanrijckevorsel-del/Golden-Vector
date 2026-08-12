"""Render Yahoo fundamentals provenance for source-mode UI affordances."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.strings import normalize_ticker
from golden_vector.fundamentals.artifacts import load_official_fundamentals
from golden_vector.serve.column_help import help_icon

FIELD_LABELS = {
    "net_debt_musd": "Net debt",
    "ebitda_ltm_musd": "EBITDA LTM",
    "da_musd": "D&A",
    "interest_expense_musd": "Interest expense",
}
TICKER_PROVENANCE_FIELDS = tuple(FIELD_LABELS)

METRIC_FIELD_DEPENDENCIES = {
    "leverage": ("net_debt_musd", "ebitda_ltm_musd"),
    "ev_ebitda": ("net_debt_musd",),
    "forward_pe": ("da_musd", "interest_expense_musd"),
}


@dataclass(frozen=True)
class FundamentalsStatementPeriod:
    """The statement facts the provenance tooltip already states, as DATA.

    ``period_end`` is the financial-statement period the Yahoo numbers describe
    and ``fetched_at`` is when they were retrieved. They are deliberately kept
    apart from every run date in the UI: a run date says when *we* computed,
    which is not the period the statement covers.

    Both are the DISTINCT persisted values across the ticker's provenance rows,
    in the order they appear. Normally there is exactly one of each; when the
    fields genuinely disagree, every value is reported rather than one being
    picked — the same per-field truth the tooltip prints.
    """

    period_ends: tuple[str, ...] = ()
    fetched_at: tuple[str, ...] = ()

    @property
    def period_end_text(self) -> str:
        return "; ".join(self.period_ends)

    @property
    def fetched_at_text(self) -> str:
        return "; ".join(self.fetched_at)


@dataclass(frozen=True)
class FundamentalsProvenance:
    """Two views of ONE read of the official fundamentals artifact.

    The tooltip needs rendered explanations; the ticker page's data-quality
    table needs the statement period as a value. Reading the parquet twice per
    request to serve both would be the obvious way to get this wrong.
    """

    lookup: dict[tuple[str, str], str] = field(default_factory=dict)
    statement_periods: dict[str, FundamentalsStatementPeriod] = field(
        default_factory=dict
    )


def load_fundamentals_provenance(paths: ProjectPaths | None) -> FundamentalsProvenance:
    """Read the official fundamentals artifact once and derive both views."""

    if paths is None:
        return FundamentalsProvenance()
    try:
        frame = load_official_fundamentals(paths)
    except Exception:
        return FundamentalsProvenance()
    return FundamentalsProvenance(
        lookup=fundamentals_provenance_lookup(frame),
        statement_periods=fundamentals_statement_periods(frame),
    )


def load_fundamentals_provenance_lookup(
    paths: ProjectPaths | None,
) -> dict[tuple[str, str], str]:
    """Return {(ticker, field_name): explanation} for official fundamentals."""

    return load_fundamentals_provenance(paths).lookup


def fundamentals_provenance_lookup(frame: pd.DataFrame) -> dict[tuple[str, str], str]:
    if frame.empty or not {"ticker", "field_name"}.issubset(frame.columns):
        return {}
    lookup: dict[tuple[str, str], str] = {}
    for row in frame.to_dict(orient="records"):
        ticker = normalize_ticker(row.get("ticker"))
        field_name = str(row.get("field_name") or "").strip()
        if not ticker or not field_name:
            continue
        text = _field_explanation(row)
        if text:
            lookup[(ticker, field_name)] = text
    return lookup


def fundamentals_statement_periods(
    frame: pd.DataFrame,
) -> dict[str, FundamentalsStatementPeriod]:
    """Return {ticker: statement facts} from the SAME rows the tooltip reads.

    Selection and de-duplication only — the persisted ``period_end`` and
    ``fetched_at_utc`` are reported as they stand, never coalesced, inferred
    from a run date, or filled in from the other source.
    """

    if frame.empty or "ticker" not in frame.columns:
        return {}
    periods: dict[str, list[str]] = {}
    fetched: dict[str, list[str]] = {}
    for row in frame.to_dict(orient="records"):
        ticker = normalize_ticker(row.get("ticker"))
        if not ticker:
            continue
        for column, sink in (("period_end", periods), ("fetched_at_utc", fetched)):
            value = _text(row.get(column))
            if value and value not in sink.setdefault(ticker, []):
                sink[ticker].append(value)
    return {
        ticker: FundamentalsStatementPeriod(
            period_ends=tuple(periods.get(ticker, ())),
            fetched_at=tuple(fetched.get(ticker, ())),
        )
        for ticker in set(periods) | set(fetched)
    }


def provenance_icon_for_metric(
    ticker: object,
    metric_name: str,
    lookup: dict[tuple[str, str], str],
) -> str:
    fields = METRIC_FIELD_DEPENDENCIES.get(metric_name, ())
    return provenance_icon_for_fields(ticker, fields, lookup)


def provenance_icon_for_fields(
    ticker: object,
    fields: Iterable[str],
    lookup: dict[tuple[str, str], str],
) -> str:
    text = provenance_text_for_fields(ticker, fields, lookup)
    if not text:
        return ""
    return help_icon("Yahoo fundamentals", text=text)


def provenance_text_for_fields(
    ticker: object,
    fields: Iterable[str],
    lookup: dict[tuple[str, str], str],
) -> str:
    ticker_text = str(ticker or "").upper().strip()
    if not ticker_text:
        return ""
    parts = [
        lookup[(ticker_text, field_name)]
        for field_name in fields
        if (ticker_text, field_name) in lookup
    ]
    return "\n\n".join(parts)


def ticker_provenance_icon(
    ticker: object,
    lookup: dict[tuple[str, str], str],
) -> str:
    return provenance_icon_for_fields(ticker, TICKER_PROVENANCE_FIELDS, lookup)


def _field_explanation(row: dict[str, object]) -> str:
    field_name = str(row.get("field_name") or "").strip()
    label = FIELD_LABELS.get(field_name, field_name.replace("_", " ").title())
    value_status = _text(row.get("value_status")) or "UNKNOWN"
    origin = _text(row.get("value_origin")) or "unknown"
    period_end = _text(row.get("period_end"))
    currency = _text(row.get("statement_currency"))
    formula = _text(row.get("calculation_formula"))
    components = _component_lines(row.get("components_json"))

    origin_text = _origin_text(origin)
    basis_parts = [f"Status: {value_status}."]
    if period_end:
        basis_parts.append(f"Period end: {period_end}.")
    if currency:
        basis_parts.append(f"Statement currency: {currency}.")
    if formula:
        basis_parts.append(f"Formula: {formula}.")
    if components:
        basis_parts.append("Components: " + "; ".join(components) + ".")
    return f"{label}: {origin_text} " + " ".join(basis_parts)


def _origin_text(origin: str) -> str:
    return {
        "calculated_from_yahoo_fields": "calculated from multiple Yahoo line items.",
        "cash_missing_assumed_zero": (
            "calculated from Yahoo debt fields with cash missing and assumed zero."
        ),
        "reconciled_with_reported_field": (
            "calculated from Yahoo line items and reconciled to Yahoo's reported EBITDA."
        ),
        "reported_field_diverged": (
            "calculated from Yahoo line items, but Yahoo's reported EBITDA did not reconcile."
        ),
        "yahoo_reported_component": "taken directly from one Yahoo line item.",
        "sign_normalized_yahoo_component": (
            "taken from one Yahoo line item with the sign normalized to a positive expense."
        ),
        "missing_yahoo_inputs": "not available because Yahoo inputs are missing.",
    }.get(origin, f"origin: {origin}.")


def _component_lines(raw: object) -> list[str]:
    text = _text(raw)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    lines: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        component = _text(item.get("component")) or "component"
        line_item = _text(item.get("yahoo_line_item"))
        status = _text(item.get("status"))
        value_source = (
            item.get("normalized_value")
            if item.get("normalized_value") is not None
            else item.get("value_musd")
        )
        value = _text(value_source)
        contribution = _text(item.get("contribution_musd"))
        formula_sign = _text(item.get("formula_sign"))
        normalization = _text(item.get("normalization"))
        bits = [component.replace("_", " ")]
        if value:
            bits.append(f"= {value} MUSD")
        if contribution and (contribution != value or formula_sign.startswith("-")):
            if contribution.startswith("-") or formula_sign.startswith("-"):
                bits.append(f"subtracts {contribution.lstrip('-')} MUSD in formula")
            else:
                bits.append(f"contributes {contribution} MUSD in formula")
        if normalization == "absolute_value":
            bits.append("sign normalized to positive expense")
        if line_item:
            bits.append(f"Yahoo line: {line_item}")
        if status and status != "OK":
            bits.append(f"status: {status}")
        detail = ", ".join(bits[1:])
        lines.append(f"{bits[0]} ({detail})" if detail else bits[0])
    return lines


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text
