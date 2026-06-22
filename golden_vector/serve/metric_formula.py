"""Formula + live-number explanations for the Corporate Finance ratios.

Victor's requirement: each ratio's info button should TEACH — show the formula AND the actual
numbers that produced this ticker's value, not a generic "raw value" / bare provenance line.

The formula text is pulled from the column-help registry (the single source already shown in
column headers), and the component numbers come from the row. Used by both the ticker-detail
"Latest Corporate Finance Snapshot" and the /tool-b overview so the explanation is identical
wherever a ratio appears. Pure rendering of already-computed values — no new arithmetic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from golden_vector.common.numeric import optional_finite_float
from golden_vector.serve.column_help import COLUMN_HELP, help_icon


@dataclass(frozen=True)
class _Component:
    label: str
    field: str
    decimals: int = 0
    scale: float = 1.0  # display value = raw * scale (100 to render a fraction as a percent)


@dataclass(frozen=True)
class _MetricFormula:
    help_key: str  # column-help entry whose `calculation` is the formula (one source of truth)
    label: str
    components: tuple[_Component, ...]
    result_field: str
    result_decimals: int
    result_suffix: str = ""
    result_scale: float = 1.0


# The Corporate Finance ratios whose info button shows formula + live inputs. Raw line items
# (market cap, share price, net debt) keep their existing provenance affordance; these are the
# derived ratios where "how it is calculated" is the useful explanation.
_METRIC_FORMULAS: dict[str, _MetricFormula] = {
    "ev_ebitda": _MetricFormula(
        help_key="tool_b_ev_ebitda",
        label="EV/EBITDA",
        components=(
            _Component("Market cap", "market_cap_musd"),
            _Component("Net debt", "net_debt_musd"),
            _Component("forward EBITDA", "forward_ebitda_musd"),
        ),
        result_field="ev_ebitda",
        result_decimals=1,
        result_suffix="x",
    ),
    "leverage": _MetricFormula(
        help_key="tool_b_leverage",
        label="Net Debt/EBITDA",
        components=(_Component("Net debt", "net_debt_musd"),),
        result_field="leverage",
        result_decimals=2,
        result_suffix="x",
    ),
    "forward_pe": _MetricFormula(
        help_key="tool_b_forward_pe",
        label="Forward P/E",
        components=(
            _Component("Share price", "share_price_usd", decimals=2),
            _Component("forward EPS", "forward_eps", decimals=2),
        ),
        result_field="forward_pe",
        result_decimals=2,
        result_suffix="x",
    ),
    "cash_margin_usd_per_oz": _MetricFormula(
        help_key="tool_b_cash_margin",
        label="Cash margin",
        components=(
            _Component("Gold price", "gold_price_assumption"),
            _Component("AISC", "aisc_usd_per_oz"),
        ),
        result_field="cash_margin_usd_per_oz",
        result_decimals=0,
        result_suffix=" $/oz",
    ),
    "margin_pct": _MetricFormula(
        help_key="tool_b_margin_pct",
        label="Margin %",
        components=(
            _Component("Cash margin", "cash_margin_usd_per_oz"),
            _Component("Gold price", "gold_price_assumption"),
        ),
        result_field="margin_pct",
        result_decimals=1,
        result_suffix="%",
        result_scale=100.0,
    ),
    "fcf_yield": _MetricFormula(
        help_key="tool_b_fcf_yield",
        label="FCF yield",
        components=(
            _Component("Sustainable FCF", "sustainable_fcf_musd"),
            _Component("Market cap", "market_cap_musd"),
        ),
        result_field="fcf_yield",
        result_decimals=1,
        result_suffix="%",
        result_scale=100.0,
    ),
}


def has_metric_formula(metric_key: str) -> bool:
    return metric_key in _METRIC_FORMULAS


def _fmt(value: object, decimals: int, scale: float = 1.0) -> str | None:
    number = optional_finite_float(value)
    if number is None:
        return None
    return f"{number * scale:,.{decimals}f}"


def metric_result_text(metric_key: str, row: Mapping[str, object] | None) -> str | None:
    """The formatted result for a ratio (scale + decimals + suffix), e.g. "57.1%", "2.0x",
    "2,383 $/oz" — the SAME value the formula popover concludes with. Rendering a cell with this
    guarantees the cell and its info button can never disagree. None if unknown/unavailable."""

    spec = _METRIC_FORMULAS.get(metric_key)
    if spec is None or not row:
        return None
    result = _fmt(row.get(spec.result_field), spec.result_decimals, spec.result_scale)
    if result is None:
        return None
    return f"{result}{spec.result_suffix}"


def metric_formula_text(metric_key: str, row: Mapping[str, object] | None) -> str | None:
    """Plain-English "label = formula. inputs -> result" for one ratio, or None if the ratio
    is unknown or its value is unavailable (degrade per item — never invent a number)."""

    spec = _METRIC_FORMULAS.get(metric_key)
    if spec is None or not row:
        return None
    result = _fmt(row.get(spec.result_field), spec.result_decimals, spec.result_scale)
    if result is None:
        return None
    formula = (COLUMN_HELP[spec.help_key].calculation or "").strip().rstrip(".")
    component_bits = [
        f"{component.label} {value}"
        for component in spec.components
        if (value := _fmt(row.get(component.field), component.decimals, component.scale))
        is not None
    ]
    head = f"{spec.label} = {formula}" if formula else spec.label
    # No orphan "formula. -> result" when every input degraded away: go formula -> result.
    if component_bits:
        return f"{head}. {', '.join(component_bits)} → {result}{spec.result_suffix}"
    return f"{head} → {result}{spec.result_suffix}"


def metric_formula_icon(metric_key: str, row: Mapping[str, object] | None, *, extra: str = "") -> str:
    """Click-to-open info button explaining a ratio's formula + this ticker's numbers. ``extra``
    appends source provenance (e.g. Yahoo origin/period) below the formula. Returns "" when the
    ratio has no formula spec or no computable value."""

    text = metric_formula_text(metric_key, row)
    if not text:
        return ""
    if extra:
        text = f"{text}\n\n{extra}"
    return help_icon(_METRIC_FORMULAS[metric_key].label, text=text)
