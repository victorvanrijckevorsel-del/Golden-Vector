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


def _hit_rate_thresholds(config: AppConfig) -> str:
    pct = config.tool_c.downside_hit_rate_threshold_pct
    return (
        f"A 'hit' is a week the stock moved more than {abs(pct):g}% in the "
        "measured direction."
    )


def _debt_stress_thresholds(config: AppConfig) -> str:
    return (
        "Danger band is Net Debt / EBITDA at or above "
        f"{config.tool_d.debt_stress_leverage_danger_threshold:g}x."
    )


def _ev_ebitda_cap_thresholds(config: AppConfig) -> str:
    return (
        "Values above "
        f"{config.tool_d.max_reasonable_ev_ebitda:g}x are treated as not "
        "meaningful and shown blank."
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
    # ---- Tool A: Gold Sensitivity ----
    "tool_a_delta": ColumnHelp(
        meaning=(
            "How much this stock tends to move for each 1% move in the gold price "
            "— its gold beta over the core window."
        ),
        calculation="Slope of weekly stock returns regressed on weekly gold returns.",
        direction="Higher means more leveraged to gold (both up and down).",
    ),
    "tool_a_gamma": ColumnHelp(
        meaning="How much the gold beta itself shifts between calm and volatile gold regimes.",
        direction="Higher means the sensitivity is less stable across regimes.",
    ),
    "tool_a_asymmetry": ColumnHelp(
        meaning="Whether the stock reacts more to gold rising than to gold falling (or vice versa).",
        calculation="Up-regime beta minus down-regime beta.",
        direction="Positive means it captures more upside than downside.",
    ),
    "tool_a_confidence": ColumnHelp(
        meaning=(
            "How trustworthy this row's sensitivity estimate is, based on history "
            "depth and fit quality. Low-confidence names are held out of the ranking."
        ),
        direction="Higher is more reliable.",
    ),
    "tool_a_volatility": ColumnHelp(
        meaning=(
            "How noisy the stock is around its gold relationship — total, residual "
            "(stock-specific), and downside volatility."
        ),
        direction="Lower residual volatility means a cleaner gold play.",
    ),
    "tool_a_score": ColumnHelp(
        meaning="The overall gold-sensitivity score that sets the rank on this page.",
        direction="Higher ranks as a stronger gold play.",
    ),
    # ---- Tool C: Gold Downside / Upside ----
    "tool_c_downside_rank": ColumnHelp(
        meaning="Rank by how the stock behaves when gold falls (1 = most resilient).",
        direction="Lower rank number is more resilient on the downside.",
    ),
    "tool_c_upside_rank": ColumnHelp(
        meaning="Rank by how the stock behaves when gold rises (1 = most upside capture).",
        direction="Lower rank number captures more upside.",
    ),
    "tool_c_down_beta": ColumnHelp(
        meaning="The stock's gold beta measured using only weeks when gold fell.",
        direction="Lower means it falls less than gold on down weeks.",
    ),
    "tool_c_up_beta": ColumnHelp(
        meaning="The stock's gold beta measured using only weeks when gold rose.",
        direction="Higher means it rises more than gold on up weeks.",
    ),
    "tool_c_down_hit_rate": ColumnHelp(
        meaning="Share of big gold-down weeks where the stock also fell sharply.",
        thresholds=_hit_rate_thresholds,
        direction="Lower is better — it held up when gold dropped.",
    ),
    "tool_c_up_hit_rate": ColumnHelp(
        meaning="Share of big gold-up weeks where the stock also rose sharply.",
        thresholds=_hit_rate_thresholds,
        direction="Higher is better — it participated when gold rose.",
    ),
    # ---- Tool B: Corporate Finance ----
    "tool_b_score": ColumnHelp(
        meaning="Percent of the corporate-finance quality checks this name passed.",
        direction="Higher is healthier.",
    ),
    "tool_b_enterprise_value": ColumnHelp(
        meaning="Market value of equity plus net debt — what it would cost to buy the whole company.",
        calculation="Market cap + net debt.",
    ),
    "tool_b_aisc": ColumnHelp(
        meaning="All-in sustaining cost to produce one ounce of gold — the industry-standard cost measure.",
        direction="Lower means a cheaper, more resilient producer.",
    ),
    "tool_b_cash_margin": ColumnHelp(
        meaning="Cash earned per ounce at the current gold price.",
        calculation="Gold price minus AISC.",
        direction="Higher is better.",
    ),
    "tool_b_forward_ebitda": ColumnHelp(
        meaning="Estimated forward earnings before interest, tax, depreciation and amortization at the current gold price.",
        direction="Higher is better.",
    ),
    "tool_b_forward_pe": ColumnHelp(
        meaning="Share price divided by estimated forward earnings per share — how many years of earnings you pay for the stock.",
        direction="Lower is cheaper.",
    ),
    "tool_b_ev_ebitda": ColumnHelp(
        meaning="Enterprise value divided by forward EBITDA — the standard valuation multiple for miners.",
        calculation="(Market cap + net debt) / forward EBITDA.",
        direction="Lower is cheaper.",
    ),
    "tool_b_fcf_yield": ColumnHelp(
        meaning="Estimated free cash flow as a percent of market value.",
        direction="Higher means more cash generation for the price.",
    ),
    "tool_b_leverage": ColumnHelp(
        meaning="Net debt divided by EBITDA — how many years of earnings it would take to repay debt.",
        thresholds=_debt_stress_thresholds,
        direction="Lower is safer.",
    ),
    "tool_b_reserve_life": ColumnHelp(
        meaning="Years of production left at the current rate, from stated reserves.",
        direction="Higher means a longer runway.",
    ),
    # ---- Tool D: Corporate Resilience (moved from hard-coded titles) ----
    "tool_d_quality_rank": ColumnHelp(
        meaning="Percentile rank of the transparent resilience components (survival, cost, fragility, balance sheet).",
        direction="Lower rank number is more resilient.",
    ),
    "tool_d_gold_used": ColumnHelp(
        meaning="The gold price used for every stress figure in this row.",
    ),
    "tool_d_interest_cover": ColumnHelp(
        meaning="The gold price at which modeled EBITDA would just equal interest expense.",
        direction="Lower is safer — more room before earnings can't cover interest.",
    ),
    "tool_d_survival_distance": ColumnHelp(
        meaning="How far today's gold price sits above the interest-cover line.",
        calculation="(Gold used − interest-cover line) / gold used.",
        direction="Higher is safer.",
    ),
    "tool_d_breakeven": ColumnHelp(
        meaning="The gold price where mine margin reaches zero (AISC breakeven).",
        direction="Lower is safer.",
    ),
    "tool_d_fcf_breakeven": ColumnHelp(
        meaning="The gold price needed to cover AISC plus sustaining capex per ounce.",
        direction="Lower is safer.",
    ),
    "tool_d_debt_stress": ColumnHelp(
        meaning="The gold price where Net Debt / EBITDA reaches the danger band.",
        thresholds=_debt_stress_thresholds,
        direction="Lower is safer.",
    ),
    "tool_d_cost_curve": ColumnHelp(
        meaning="Where this name's AISC sits across the universe (cost-curve percentile).",
        direction="Lower percentile is a cheaper, more resilient producer.",
    ),
    "tool_d_fragility": ColumnHelp(
        meaning="Modeled EBITDA loss for a 10% gold fall, as a share of EBITDA at the selected gold price.",
        direction="Lower means less fragile to a gold drop.",
    ),
    "tool_d_leverage": ColumnHelp(
        meaning="Net Debt / EBITDA at the selected gold price.",
        thresholds=_debt_stress_thresholds,
        direction="Lower is safer.",
    ),
    "tool_d_ev_ebitda_context": ColumnHelp(
        meaning="EV/EBITDA shown for context only — it is not used in the resilience rank.",
        thresholds=_ev_ebitda_cap_thresholds,
        direction="Lower is cheaper.",
    ),
    "tool_d_fcf_yield_context": ColumnHelp(
        meaning="FCF yield shown for context only — it is not used in the resilience rank.",
        direction="Higher means more cash generation for the price.",
    ),
    # ---- Lab: Conditional Dial analog table ----
    "lab_p_beat_shrunk": ColumnHelp(
        meaning=(
            "How often this miner beat the GDX benchmark in the chosen gold "
            "scenario, nudged toward the group average so thin histories aren't "
            "over-trusted (empirical-Bayes shrinkage)."
        ),
        direction="Higher means more reliably outperforms in that scenario.",
    ),
    "lab_p_beat_raw": ColumnHelp(
        meaning="The plain count: share of matching historical episodes where the miner beat GDX.",
        direction="Higher is better; read the shrunk column for the ranking.",
    ),
    "lab_wilson": ColumnHelp(
        meaning=(
            "A 95% confidence range for the beat rate, using the episode-adjusted "
            "sample count (overlapping weekly windows are not independent)."
        ),
    ),
    "lab_median_alpha": ColumnHelp(
        meaning="Typical (median) out- or under-performance versus GDX across the matching episodes.",
        direction="Positive means it tended to beat GDX in that scenario.",
    ),
    "lab_alpha_range": ColumnHelp(
        meaning="The 10th-to-90th-percentile spread of performance versus GDX — the realistic range, not just the middle.",
    ),
    "lab_episodes": ColumnHelp(
        meaning=(
            "How many historical weeks matched the scenario, with the effective "
            "(independent) count in brackets."
        ),
        direction="More episodes means a more trustworthy estimate.",
    ),
    "lab_history": ColumnHelp(
        meaning=(
            "Whether there were enough independent episodes to report numbers. "
            "Thin rows say 'insufficient history' instead of an unreliable figure."
        ),
    ),
    "lab_p_beat_gdxj": ColumnHelp(
        meaning=(
            "How often this miner beat the GDXJ junior-miner benchmark in the chosen "
            "scenario, nudged toward the group average (same shrinkage as the GDX column)."
        ),
        calculation=(
            "Shown for comparison only — the ranking follows GDX. GDXJ history starts "
            "later (2009) so it has its own, usually smaller, sample; a blank means too "
            "few independent GDXJ episodes to count."
        ),
        direction="Higher means more reliably beats the junior-miner basket in that scenario.",
    ),
    "lab_benchmark_gdx": ColumnHelp(
        meaning=(
            "GDX is the broad gold-miner ETF — the large, established producers. It is "
            "the default yardstick and the one the table is ranked by."
        ),
    ),
    "lab_benchmark_gdxj": ColumnHelp(
        meaning=(
            "GDXJ is the junior-miner ETF — smaller, more volatile names that swing "
            "harder both ways. Beating GDXJ is usually easier when gold rises and harder "
            "when gold falls."
        ),
    ),
    "lab_horizon": ColumnHelp(
        meaning=(
            "How many weeks forward each episode looks. 13 weeks (one quarter) is the "
            "default; longer windows leave far fewer independent episodes, so many cells "
            "honestly read 'insufficient history'."
        ),
    ),
}
