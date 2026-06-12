"""Site-wide column-help registry: hover explanations with config thresholds.

One registry owns every header/metric explanation so the wording can never
diverge across pages and templates never hard-code threshold numbers.
Threshold values are resolved at render time from the loaded ``AppConfig`` —
change the config and the tooltip changes with it.

Transport is a dotted-underlined ``.help-term`` span carrying the explanation
in a ``data-help`` attribute; ``help-popover.js`` shows it in a single shared
box on hover and keyboard focus (``workspace.css`` styles ``.help-term`` /
``.help-pop``). The registry keeps the explanation in separate parts (meaning
/ calculation / thresholds / direction) so wording never diverges and
templates never hard-code threshold numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Callable

from golden_vector.contracts.config_models import AppConfig


@dataclass(frozen=True)
class ColumnHelp:
    meaning: str
    calculation: str | None = None
    thresholds: Callable[[AppConfig], str] | None = None
    direction: str | None = None


def column_help_text(key: str, *, app_config: AppConfig | None = None) -> str | None:
    """Build the full plain-English hover text for a registered column."""

    spec = COLUMN_HELP.get(key)
    if spec is None:
        return None
    parts: list[str] = [spec.meaning]
    if spec.calculation:
        parts.append(spec.calculation)
    if spec.thresholds is not None and app_config is not None:
        try:
            parts.append(spec.thresholds(app_config))
        except Exception:
            # A page must never fail to render because one tooltip could not
            # resolve a config attribute; the meaning/direction still show.
            pass
    if spec.direction:
        parts.append(spec.direction)
    return "\n".join(part.strip() for part in parts if part and part.strip())


def help_term(
    label: str,
    *,
    key: str | None = None,
    app_config: AppConfig | None = None,
    text: str | None = None,
) -> str:
    """Wrap a label in a dotted-underlined help affordance.

    Use inside any cell or label, not just headers. The explanation rides in
    ``data-help``; ``help-popover.js`` renders the box on hover/focus. Pass an
    explicit ``text`` to explain something not in the registry. With no help
    text the label renders plain (escaped).
    """

    title = text if text is not None else (
        column_help_text(key, app_config=app_config) if key else None
    )
    if not title:
        return escape(label)
    return (
        "<span class=\"help-term\" tabindex=\"0\" role=\"note\" "
        f"data-help=\"{escape(title)}\">{escape(label)}</span>"
    )


def help_th(
    label: str,
    *,
    key: str | None = None,
    app_config: AppConfig | None = None,
    col_name: str | None = None,
    sort_numeric: bool = False,
    text: str | None = None,
) -> str:
    """Render a ``<th>`` whose label carries a registry-driven help popover."""

    attrs: list[str] = []
    if col_name:
        attrs.append(f" data-col-name=\"{escape(col_name)}\"")
    if sort_numeric:
        attrs.append(" data-sort-numeric")
    inner = help_term(label, key=key, app_config=app_config, text=text)
    return f"<th{''.join(attrs)}>{inner}</th>"


def _percent(value: float) -> str:
    return f"{value * 100:g}%"


def _tradable_thresholds(config: AppConfig) -> str:
    hedge = config.hedge_readiness
    return (
        "Current thresholds: relative spread <= "
        f"{_percent(hedge.option_liquidity_tradable_spread_pct)}, open interest >= "
        f"{hedge.option_liquidity_min_open_interest}, mid premium >= "
        f"{hedge.option_liquidity_min_premium:g}."
    )


def _watch_thresholds(config: AppConfig) -> str:
    hedge = config.hedge_readiness
    return (
        "Current thresholds: relative spread <= "
        f"{_percent(hedge.option_liquidity_watch_spread_pct)} with a usable two-sided quote."
    )


def _near_spot_thresholds(config: AppConfig) -> str:
    hedge = config.hedge_readiness
    return (
        "Near-spot means strikes within "
        f"{_percent(hedge.option_liquidity_near_spot_pct)} of the stock price."
    )


def _signal_quality_thresholds(config: AppConfig) -> str:
    hedge = config.hedge_readiness
    return (
        "Current thresholds: at least "
        f"{hedge.option_signal_area_min_contracts} signal-area contracts and "
        f"{_percent(hedge.option_signal_quote_coverage_min)} two-sided quote coverage."
    )


def _skew_thresholds(config: AppConfig) -> str:
    hedge = config.hedge_readiness
    return (
        f"Measured at the {hedge.option_signal_horizon_days}d signal window. "
        "A direction signal needs the difference to exceed "
        f"{hedge.option_signal_skew_residual_threshold * 100:g} vol pts."
    )


def _iv_percentile_thresholds(config: AppConfig) -> str:
    hedge = config.hedge_readiness
    return (
        f"Uses the {hedge.option_signal_horizon_days}d ATM implied volatility."
    )


COLUMN_HELP: dict[str, ColumnHelp] = {
    "measured_contracts": ColumnHelp(
        meaning="Number of cached contracts with a usable two-sided quote (bid/ask/mid).",
        direction="Higher means broader measurable coverage. Context only.",
    ),
    "tradable_count": ColumnHelp(
        meaning=(
            "Tradable means the contract has a valid bid/ask/mid, enough premium, "
            "a tight enough spread, and enough open interest to realistically trade."
        ),
        calculation=(
            "This is the chain-level liquidity tier. Candidate badges use a "
            "stricter per-bucket rule on top of it."
        ),
        thresholds=_tradable_thresholds,
        direction="Higher count is better.",
    ),
    "watch_count": ColumnHelp(
        meaning=(
            "Watch contracts are usable for context but not clean enough to call tradable "
            "(wider spreads or thinner interest)."
        ),
        thresholds=_watch_thresholds,
        direction="Context only.",
    ),
    "no_trade_count": ColumnHelp(
        meaning="Contracts rejected as too thin, too wide, or missing a usable quote.",
        direction="Lower is better.",
    ),
    "median_tradable_spread": ColumnHelp(
        meaning="Median bid/ask spread across tradable contracts only.",
        calculation="Relative spread = (ask - bid) / mid.",
        direction="Lower is better.",
    ),
    "median_tradable_oi": ColumnHelp(
        meaning=(
            "Median open interest across tradable contracts only. Open interest is the "
            "number of contracts outstanding."
        ),
        direction="Higher is better - it usually means deeper liquidity.",
    ),
    "median_tradable_volume": ColumnHelp(
        meaning="Median traded volume across tradable contracts only.",
        direction="Higher is better.",
    ),
    "median_tradable_near_spot_depth": ColumnHelp(
        meaning="Median count of quoted contracts near the current stock price, across tradable contracts only.",
        thresholds=_near_spot_thresholds,
        direction="Higher is better - more strikes to choose from near the money.",
    ),
    "skew_vs_benchmark": ColumnHelp(
        meaning=(
            "How much richer this stock's downside puts are priced versus its sector "
            "benchmark ETF (GDX/GDXJ). Benchmark rows show their own absolute skew as "
            "the baseline."
        ),
        calculation=(
            "Skew = 25-delta put IV minus 25-delta call IV at the signal "
            "window. Single stocks show their skew minus the benchmark's skew."
        ),
        thresholds=_skew_thresholds,
        direction="Positive means puts are priced richer than calls. Context, not a forecast.",
    ),
    "option_cost_signal": ColumnHelp(
        meaning="Whether option protection currently looks cheap or rich for this name.",
        calculation=(
            "Based on the implied-to-realized volatility ratio (IV/RV) and the IV rank "
            "versus this name's own stored history."
        ),
        direction="CHEAP favors buying options; RICH means protection is expensive.",
    ),
    "option_signal_quality": ColumnHelp(
        meaning="Whether the option signal for this row is built on good enough market data.",
        calculation=(
            "OK needs a benchmark chain plus enough signal-area contracts with fresh "
            "two-sided quotes. SPARSE/STALE_QUOTES/LOW_LIQUIDITY name the failing check."
        ),
        thresholds=_signal_quality_thresholds,
        direction="Only OK rows feed publishable signals.",
    ),
    "option_snapshot_date": ColumnHelp(
        meaning=(
            "Date of the cached option-chain snapshot used to build this page. "
            "Prices are from that snapshot, not live."
        ),
        direction="Context only.",
    ),
    "iv_percentile": ColumnHelp(
        meaning=(
            "Where this name's at-the-money implied volatility sits versus the other "
            "names in the same snapshot (0-100)."
        ),
        calculation=(
            "Cross-sectional percentile of signal-window ATM IV across the universe."
        ),
        thresholds=_iv_percentile_thresholds,
        direction="Higher means options are expensive relative to peers.",
    ),
}
