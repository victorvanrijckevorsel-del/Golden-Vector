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
    result_suffix: str = ""  # full unit shown in the FORMULA POPOVER (e.g. "x", " $/oz", "%")
    result_scale: float = 1.0
    # Unit shown in the in-table CELL. Defaults to result_suffix; set to "" for "multiple"/unit
    # ratios (x, $/oz) so the cell stays compact (the column header carries the unit) while the
    # popover keeps the full unit. Percent fields keep "%" because the cell needs it to be read.
    cell_suffix: str | None = None


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
        cell_suffix="",
    ),
    "leverage": _MetricFormula(
        help_key="tool_b_leverage",
        label="Net Debt/EBITDA",
        components=(_Component("Net debt", "net_debt_musd"),),
        result_field="leverage",
        result_decimals=2,
        result_suffix="x",
        cell_suffix="",
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
        cell_suffix="",
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
        cell_suffix="",
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


def metric_value_text(metric_key: str, value: object) -> str | None:
    """Format an arbitrary ratio value with the metric's scale/decimals and CELL unit (the compact
    in-table unit — "57.1%", "2.0", "2,383"; the "x"/"$/oz" suffix lives only in the popover).
    None if the metric is unknown or the value is unavailable/non-finite."""

    spec = _METRIC_FORMULAS.get(metric_key)
    if spec is None:
        return None
    result = _fmt(value, spec.result_decimals, spec.result_scale)
    if result is None:
        return None
    suffix = spec.cell_suffix if spec.cell_suffix is not None else spec.result_suffix
    return f"{result}{suffix}"


def metric_result_text(metric_key: str, row: Mapping[str, object] | None) -> str | None:
    """The formatted CELL result for a ratio read from ``row`` (scale + decimals + cell unit), e.g.
    "57.1%", "2.0", "2,383". The popover repeats the value with its FULL unit, so the cell stays
    compact while the info button spells out the unit. None if unknown/unavailable."""

    if not row:
        return None
    spec = _METRIC_FORMULAS.get(metric_key)
    if spec is None:
        return None
    return metric_value_text(metric_key, row.get(spec.result_field))


def metric_formula_text(metric_key: str, row: Mapping[str, object] | None) -> str | None:
    """Plain-English "label = formula. inputs -> result" for one ratio, or None if the ratio
    is unknown or its value is unavailable (degrade per item — never invent a number)."""

    spec = _METRIC_FORMULAS.get(metric_key)
    if spec is None or not row:
        return None
    result = _fmt(row.get(spec.result_field), spec.result_decimals, spec.result_scale)
    if result is None:
        return None
    help_spec = COLUMN_HELP.get(spec.help_key)
    formula = ((help_spec.calculation if help_spec else "") or "").strip().rstrip(".")
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
