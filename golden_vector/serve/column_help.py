"""Site-wide column-help registry: click-to-explain headers with config thresholds.

One registry owns every header/metric explanation so the wording can never
diverge across pages and templates never hard-code threshold numbers.
Threshold values are resolved at render time from the loaded ``AppConfig`` —
change the config and the explanation changes with it.

Default header transport (``help_th``) is a clickable ``ⓘ`` button that opens a
persistent panel: meaning + formula first, with details/thresholds/direction
behind "Read more" (``help-popover.js`` builds and positions it; ``workspace.css``
styles ``.help-icon`` / ``.help-panel``). The click is captured before the header
sort, so clicking the title still sorts. The legacy dotted-underline ``.help-term``
hover span (``data-help`` attribute, shared ``.help-pop`` box) remains for inline,
non-header affordances and for ``help_th(panel=False)``. The registry keeps the
explanation in separate parts (meaning / calculation / thresholds / direction) so
wording never diverges and templates never hard-code threshold numbers.
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
    # Deeper explanation shown only behind the panel's "Read more" (the meaning +
    # formula are shown first; details/thresholds/direction expand on demand).
    details: str | None = None


def column_help_parts(key: str, *, app_config: AppConfig | None = None) -> dict[str, str] | None:
    """Return the help broken into the click-panel's three sections:
    ``meaning`` + ``formula`` (shown immediately) and ``more`` (behind "Read more":
    the deeper details, the config-resolved thresholds, and the direction). Empty
    sections are returned as "" so the renderer can omit them.
    """

    spec = COLUMN_HELP.get(key)
    if spec is None:
        return None
    more: list[str] = []
    if spec.details:
        more.append(spec.details)
    if spec.thresholds is not None and app_config is not None:
        try:
            more.append(spec.thresholds(app_config))
        except Exception:
            # Never fail a render because one tooltip can't resolve a config attr.
            pass
    if spec.direction:
        more.append(spec.direction)
    return {
        "meaning": spec.meaning.strip(),
        "formula": (spec.calculation or "").strip(),
        "more": "\n".join(part.strip() for part in more if part and part.strip()),
    }


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


def help_icon(
    label: str,
    *,
    key: str | None = None,
    app_config: AppConfig | None = None,
    text: str | None = None,
) -> str:
    """A small clickable ``ⓘ`` button carrying the help split into meaning / formula /
    more, for the click-to-open explanation panel (``help-popover.js``). Returns ``""``
    when there is nothing to explain. Use beside a header label; clicking it opens the
    panel without triggering the header's sort (the script stops propagation)."""

    parts = column_help_parts(key, app_config=app_config) if key else None
    if parts is None and text:
        parts = {"meaning": text, "formula": "", "more": ""}
    if not parts or not parts.get("meaning"):
        return ""
    return (
        "<button type=\"button\" class=\"help-icon\" aria-expanded=\"false\" "
        f"aria-label=\"Explain {escape(label)}\" "
        f"data-help-title=\"{escape(label)}\" "
        f"data-help-meaning=\"{escape(parts['meaning'])}\" "
        f"data-help-formula=\"{escape(parts.get('formula') or '')}\" "
        f"data-help-more=\"{escape(parts.get('more') or '')}\">i</button>"
    )


def help_th(
    label: str,
    *,
    key: str | None = None,
    app_config: AppConfig | None = None,
    col_name: str | None = None,
    sort_numeric: bool = False,
    text: str | None = None,
    panel: bool = True,
) -> str:
    """Render a ``<th>`` whose label carries a registry-driven help affordance.

    ``panel=True`` (default) renders the header text plain plus a clickable ``ⓘ``
    that opens the persistent explanation panel (meaning + formula + Read more) —
    header-click still sorts. ``panel=False`` keeps the legacy dotted hover tooltip
    (the inline, non-header affordance still lives in ``help_term``).
    """

    attrs: list[str] = []
    if col_name:
        attrs.append(f" data-col-name=\"{escape(col_name)}\"")
    if sort_numeric:
        attrs.append(" data-sort-numeric")
    if panel:
        icon = help_icon(label, key=key, app_config=app_config, text=text)
        inner = (
            f"{escape(label)}<span class=\"help-anchor\">{icon}</span>" if icon else escape(label)
        )
    else:
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


def _candidate_status_thresholds(config: AppConfig) -> str:
    hedge = config.hedge_readiness
    return (
        "The badge is the SELECTED contract's overall liquidity tier: Tradable when its "
        f"relative spread is within {_percent(hedge.option_liquidity_tradable_spread_pct)} "
        "(with enough open interest, a mid premium of at least "
        f"{hedge.option_liquidity_min_premium:g}, and a usable two-sided quote), Watch up to "
        f"{_percent(hedge.option_liquidity_watch_spread_pct)}, otherwise No liquid candidate. "
        "To be selected at all, a contract must first clear the per-bucket slot gates "
        "(bucket-specific spread, open interest, a minimum mid price, and usable implied "
        "volatility, at a strict or relaxed tier) — so a contract can clear a wider bucket cap "
        "yet still show Watch by its overall tier."
    )


def _candidate_finder_coverage_thresholds(config: AppConfig) -> str:
    return (
        "Rank-eligible only when coverage is at or above "
        f"{_percent(config.candidate_finder.min_criteria_fraction)} of the selected criteria."
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


def _tool_b_leverage_thresholds(config: AppConfig) -> str:
    return (
        "Measured on trailing (LTM) EBITDA. The screen fails this check above "
        f"{config.screening_params.layer1_thresholds.leverage_max:g}x."
    )


def _ev_ebitda_cap_thresholds(config: AppConfig) -> str:
    return (
        "Values above "
        f"{config.tool_d.max_reasonable_ev_ebitda:g}x are treated as not "
        "meaningful and shown blank."
    )


COLUMN_HELP: dict[str, ColumnHelp] = {
    "tool_b_verdict": ColumnHelp(
        meaning=(
            "The screen's plain verdict for this name: STRONG_CANDIDATE, WATCHLIST, SCREEN_OUT, "
            "or INCOMPLETE (missing inputs)."
        ),
        calculation=(
            "INCOMPLETE if confidence or Layer 1 is incomplete; STRONG_CANDIDATE if Layer 1 "
            "passes and forward P/E is below the strong cutoff; WATCHLIST if forward P/E is "
            "below the watchlist cutoff; otherwise SCREEN_OUT."
        ),
    ),
    "tool_b_rank": ColumnHelp(
        meaning=(
            "This name's place in the corporate-finance ranking, by how many quality checks it "
            "passed."
        ),
        calculation=(
            "Dense rank on the Checks Passed % score, highest score first, within each date and "
            "gold-price assumption; names with no score are left unranked."
        ),
        direction="Rank 1 is the top (most checks passed); higher numbers rank lower.",
    ),
    "tool_b_share_price": ColumnHelp(
        meaning="The company's share price in US dollars, taken from the latest market snapshot.",
        calculation=(
            "Raw market input (share_price_usd) from the foundation snapshot, not a "
            "calculation."
        ),
    ),
    "tool_b_market_cap": ColumnHelp(
        meaning=(
            "The company's total stock-market value (market capitalisation) in millions of US "
            "dollars."
        ),
        calculation=(
            "Raw market input (market_cap_musd) from the foundation snapshot, not a "
            "calculation."
        ),
    ),
    "tool_b_margin_pct": ColumnHelp(
        meaning=(
            "Cash margin per ounce as a percent of the gold price at the current gold "
            "assumption."
        ),
        calculation="Cash margin per ounce (gold price minus AISC) divided by the gold price.",
        direction=(
            "Higher is better; the screen fails the margin check below the configured minimum."
        ),
    ),
    "tool_b_financial_data_status": ColumnHelp(
        meaning=(
            "Whether the market (official) financial fields used for the comparison were fully "
            "available for this name."
        ),
        calculation=(
            "Rolls up the per-field official statuses: OK only when every dual-source field is "
            "OK, otherwise the worst status by precedence (down to MISSING)."
        ),
    ),
    "tool_b_divergent_field_count": ColumnHelp(
        meaning=(
            "How many financial fields where your manual input differs from the market "
            "(official) value."
        ),
        calculation=(
            "Count of dual-source fields where the official value is OK, our value came from "
            "manual entry, and the two are not numerically equal."
        ),
    ),
    "tool_b_layer1_status": ColumnHelp(
        meaning=(
            "The result of the Layer 1 mining-quality gate: PASS, FAIL, or INCOMPLETE when "
            "required inputs are missing."
        ),
        calculation=(
            "INCOMPLETE if any required mining input is missing; otherwise PASS when no "
            "threshold check fails (AISC, margin, FCF yield, reserve life, leverage), else "
            "FAIL."
        ),
        direction="PASS is best; INCOMPLETE means missing inputs.",
    ),
    "tool_b_check_summary": ColumnHelp(
        meaning=(
            "The per-check breakdown behind the score: how many of the visible checks passed "
            "and each check's PASS/FAIL/N/A result."
        ),
        calculation=(
            "passed/total followed by each check's status (Data complete, AISC, Margin, FCF "
            "yield, Reserve life, Net Debt/EBITDA, Forward P/E)."
        ),
    ),
    "tool_d_resilience_flip": ColumnHelp(
        meaning=(
            "Which survival statuses this name newly flips into at the stressed gold price (it "
            "was fine at spot but crosses a line under the stress)."
        ),
        calculation=(
            "Compares stressed-gold vs spot-gold values and flags transitions: "
            "flips_margin_negative (margin <0 at G but >=0 at spot), flips_thin_margin "
            "(breakeven headroom falls into 0-10% at G from >=10% at spot), "
            "flips_leverage_undefined (forward EBITDA <=0 at G but >0 at spot), "
            "flips_over_debt_stress_line (debt-stress gold line sits between G and spot with "
            "worse leverage)."
        ),
        direction=(
            "Empty / fewer is better - any flip means the name crosses a survival line only "
            "under the stressed gold price; blank means it does not newly flip."
        ),
    ),
    "tool_d_headroom": ColumnHelp(
        meaning=(
            "Cash-margin cushion above AISC breakeven at the selected stress gold price, as a "
            "percent of the gold price."
        ),
        calculation="(gold price used - AISC per ounce) / gold price used, shown as a percent.",
        direction=(
            "Higher is safer - more cushion above the AISC breakeven before margin turns "
            "negative."
        ),
    ),
    "option_signal_horizon": ColumnHelp(
        meaning=(
            "The option signal horizon in days (e.g. 60d) — the days-to-expiry window the skew "
            "is measured at."
        ),
        calculation="Horizons the persisted signal row carries, parsed from name_skew_<h>d keys.",
    ),
    "option_name_skew": ColumnHelp(
        meaning=(
            "This stock's own 25-delta volatility skew at the horizon — how much richer its "
            "25-delta put implied volatility is than its 25-delta call implied volatility."
        ),
        calculation="25-delta put IV minus 25-delta call IV (iv_skew_<h>d) for the name itself.",
        direction=(
            "More positive means downside puts are priced richer than calls, so more crash risk "
            "is priced in. Context, not a forecast."
        ),
    ),
    "option_sector_skew": ColumnHelp(
        meaning=(
            "The sector benchmark ETF's (GDX/GDXJ) own 25-delta volatility skew at the horizon "
            "— the baseline the name's skew is compared against."
        ),
        calculation=(
            "25-delta put IV minus 25-delta call IV (iv_skew_<h>d) measured on the benchmark "
            "ETF chain."
        ),
        direction=(
            "More positive means the sector's downside puts are priced richer than calls. "
            "Context, not a forecast."
        ),
    ),
    "option_candidate_label": ColumnHelp(
        meaning=(
            "Which option candidate this row is — its side and strike bucket, e.g. Put Near-ATM "
            "or Call Directional."
        ),
        calculation="Side (Put/Call) plus the bucket label (Near-ATM / Directional).",
    ),
    "option_expiry_dte": ColumnHelp(
        meaning=(
            "The option's listed expiry date and how many calendar days remain until it expires "
            "(DTE = days to expiry)."
        ),
        calculation="Contract expiration date and days_to_expiry from the cached option chain.",
    ),
    "option_strike": ColumnHelp(
        meaning="The option's strike price — the price at which the contract can be exercised.",
        calculation="Strike of the selected option contract from the cached chain.",
    ),
    "option_mid_price": ColumnHelp(
        meaning=(
            "The option's mid price — the midpoint between the current bid and ask. A rough "
            "per-share premium estimate, not a live executable quote."
        ),
        calculation="(bid + ask) / 2 from the cached option-chain snapshot.",
    ),
    "option_rel_spread": ColumnHelp(
        meaning=(
            "The option's relative bid/ask spread — how wide the quote is as a fraction of its "
            "mid price. Wider spreads cost more to enter and exit."
        ),
        calculation="Relative spread = (ask - bid) / mid for this contract.",
        direction="Lower is better.",
    ),
    "option_open_interest": ColumnHelp(
        meaning=(
            "Open interest for this contract — the number of contracts currently outstanding. A "
            "liquidity proxy."
        ),
        calculation="Open interest reported on the cached option-chain snapshot for this contract.",
        direction="Higher usually means deeper liquidity.",
    ),
    "option_proxy_basis_risk": ColumnHelp(
        meaning=(
            "Why a sector-ETF proxy contract is being shown instead of a single-name contract, "
            "and the warning that the ETF does not track this stock one-for-one (basis risk)."
        ),
        calculation="The proxy-fallback reason string explaining the GDX/GDXJ substitution.",
    ),
    "option_strike_expiry": ColumnHelp(
        meaning=(
            "The candidate option's strike price together with its expiry date and days-to- "
            "expiry (DTE)."
        ),
        calculation=(
            "Strike plus the contract expiration date and days_to_expiry from the cached chain."
        ),
    ),
    "option_actions": ColumnHelp(
        meaning=(
            "Quick actions for this candidate — Select to load it into the sizing calculator "
            "(tradable rows only) and a link to open the Yahoo option chain for its expiry."
        ),
    ),
    "option_scenario_gold_move": ColumnHelp(
        meaning=(
            "The hypothetical gold-price move for this scenario row, used to model the stock "
            "and option outcome."
        ),
        calculation=(
            "Each modeled percentage change in the gold price (gold_pct_change) in the scenario "
            "grid."
        ),
    ),
    "option_scenario_modeled_stock": ColumnHelp(
        meaning=(
            "The stock price implied by the scenario's gold move, used to reprice the option. A "
            "model estimate, not a forecast."
        ),
        calculation="current_stock_price x (1 + scenario_beta x gold_pct_change), floored at 0.",
    ),
    "option_scenario_model_note": ColumnHelp(
        meaning=(
            "A caveat shown for extreme scenarios where the linear beta model is unreliable "
            "(e.g. deep gold-down moves where operating/balance-sheet leverage can make the "
            "stock move non-linearly)."
        ),
        calculation=(
            "scenario_model_note flags scenarios at or below the extreme-downside threshold."
        ),
    ),
    "tool_a_structural_window": ColumnHelp(
        meaning=(
            "The trailing time window (6M, 12M, or 3Y) over which these structural metrics were "
            "estimated; marked Anchor (the ticker's canonical window) and/or Active (the window "
            "currently selected)."
        ),
        calculation="One row per configured structural window.",
    ),
    "tool_a_r_squared": ColumnHelp(
        meaning=(
            "How well the gold-beta regression fits this window — the share of the stock's "
            "weekly return variance explained by gold's weekly returns."
        ),
        calculation=(
            "R-squared of weekly stock log-returns regressed on weekly gold log-returns over "
            "the window."
        ),
        direction="Higher means a tighter, more reliable gold relationship.",
    ),
    "tool_a_window_weeks": ColumnHelp(
        meaning=(
            "The number of weekly observations used to estimate this window's metrics. Thin "
            "samples are less trustworthy."
        ),
        calculation="Count of weeks in the trailing window (week_count).",
        direction="More weeks generally mean a more reliable estimate.",
    ),
    "tool_a_window_status": ColumnHelp(
        meaning=(
            "Whether this window has enough weekly observations to be eligible (ELIGIBLE) or "
            "too few (LOW_OBSERVATION)."
        ),
        calculation=(
            "ELIGIBLE if week_count >= the minimum observations setting, otherwise "
            "LOW_OBSERVATION."
        ),
        direction=(
            "ELIGIBLE windows feed the published metrics; LOW_OBSERVATION windows are not "
            "trusted."
        ),
    ),
    "exploratory_horizon": ColumnHelp(
        meaning=(
            "The lookback horizon for this exploratory ladder row (e.g. 1y, 3y). Tactical "
            "context only — it does not drive the Gold Sensitivity score."
        ),
        calculation="The parsed horizon id from the returns ladder.",
    ),
    "exploratory_equity_return": ColumnHelp(
        meaning=(
            "The stock's total simple return over the horizon (single period, start to end). "
            "Tactical context only."
        ),
        calculation="(equity price at end / equity price at start) - 1 over the horizon.",
    ),
    "exploratory_gold_return": ColumnHelp(
        meaning=(
            "Gold's total simple return over the same horizon (single period, start to end). "
            "Tactical context only."
        ),
        calculation="(gold price at end / gold price at start) - 1 over the horizon.",
    ),
    "exploratory_single_period_ratio": ColumnHelp(
        meaning=(
            "The stock's horizon return divided by gold's horizon return — a single-period "
            "return ratio, NOT a structural beta, and it does not drive the Gold Sensitivity "
            "score."
        ),
        calculation=(
            "equity_return / gold_return over the horizon (suppressed when gold's move is near "
            "zero)."
        ),
        direction="Higher means the stock moved more than gold over the period; descriptive only.",
    ),
    "exploratory_coverage_status": ColumnHelp(
        meaning=(
            "Whether the horizon had enough clean price history and a usable gold move to "
            "compute a ratio: PASS or FAIL."
        ),
        calculation=(
            "coverage_flag — PASS when both equity and gold return basis are available, "
            "otherwise FAIL."
        ),
        direction="PASS rows are usable; FAIL rows lack sufficient history or basis.",
    ),
    "option_data_source": ColumnHelp(
        meaning=(
            "Where the cached option data came from — a provenance label (e.g. cached Yahoo "
            "Finance data via yfinance)."
        ),
        calculation="Source label recorded on the option-trading source context.",
    ),
    "option_risk_free_rate": ColumnHelp(
        meaning=(
            "The risk-free interest rate used to discount the Black-Scholes scenario option "
            "prices. Marked 'fallback' (0%) when it was missing from the options manifest."
        ),
        calculation="Risk-free rate from the options manifest, or a 0% fallback if absent.",
    ),
    "option_refresh_run": ColumnHelp(
        meaning=(
            "The refresh run id that produced this option snapshot — a provenance/audit "
            "identifier."
        ),
        calculation="refresh_run_id recorded on the option-trading source context.",
    ),
    "portfolio_data_issue_code": ColumnHelp(
        meaning=(
            "A short machine code naming the kind of portfolio data problem found for this row "
            "(e.g. missing_price, benchmark_beta_not_publishable)."
        ),
    ),
    "portfolio_data_issue_message": ColumnHelp(
        meaning="A plain-English explanation of why this data issue matters and what is wrong.",
    ),
    "portfolio_exposure_bucket": ColumnHelp(
        meaning=(
            "The gold-beta exposure category a position falls into: Measured beta, Low/negative "
            "beta, Low-confidence beta, Missing beta, Missing price, or Degraded data."
        ),
        calculation=(
            "Each position is assigned a bucket from its down-beta availability, confidence, "
            "and price/data status, then positions are grouped by bucket."
        ),
    ),
    "portfolio_exposure_position_count": ColumnHelp(
        meaning="How many of your positions fall in this exposure bucket.",
        calculation="Count of positions whose effective_exposure_bucket equals this bucket.",
    ),
    "portfolio_exposure_value_usd": ColumnHelp(
        meaning="Combined current USD value of all positions in this exposure bucket.",
        calculation="Sum of each position's value_usd within the bucket.",
    ),
    "portfolio_exposure_nav_weight": ColumnHelp(
        meaning=(
            "This exposure bucket's combined value as a share of your whole portfolio's net "
            "asset value (NAV)."
        ),
        calculation="Bucket value_usd / total NAV.",
    ),
    "portfolio_currency_code": ColumnHelp(
        meaning=(
            "The trading currency the value and P&L below are denominated in (positions are "
            "grouped by their buy/quote currency)."
        ),
    ),
    "portfolio_currency_value_usd": ColumnHelp(
        meaning="Combined current USD value of all positions held in this currency.",
        calculation="Sum of each lot's value_usd within the currency bucket.",
    ),
    "portfolio_currency_pnl_usd": ColumnHelp(
        meaning=(
            "Unrealized profit/loss in USD for positions in this currency, valued at current "
            "FX; it blends security moves and currency moves. Blank unless every valued lot in "
            "the bucket has a recorded cost."
        ),
        calculation=(
            "Bucket value_usd minus bucket cost_usd at current FX (null if any cost is "
            "missing)."
        ),
        direction="Higher is better.",
    ),
    "portfolio_hedge_proxy": ColumnHelp(
        meaning=(
            "The sector ETF used as a hedging proxy for the book's measured gold exposure (e.g. "
            "GDX or GDXJ)."
        ),
    ),
    "portfolio_hedge_proxy_label": ColumnHelp(
        meaning="The human-readable name of the hedging proxy ETF.",
    ),
    "portfolio_hedge_status": ColumnHelp(
        meaning=(
            "Whether a hedge size could be modeled for this proxy: OK, NO_MEASURED_EXPOSURE "
            "(nothing to hedge), or UNAVAILABLE (the proxy's beta or price is "
            "missing/unusable)."
        ),
        calculation=(
            "Derived from the proxy's benchmark status, its down-beta, its price, and whether "
            "the book has any measured gold exposure."
        ),
    ),
    "portfolio_hedge_proxy_price": ColumnHelp(
        meaning="The proxy ETF's latest USD share price used to size the hedge.",
        calculation="Latest USD close from the cached benchmark history.",
    ),
    "portfolio_hedge_effective_exposure": ColumnHelp(
        meaning=(
            "The book's modeled USD gold exposure to be hedged — the total dollar loss your "
            "covered positions would take if gold fell 10%."
        ),
        calculation=(
            "Sum over covered positions of value_usd x down-beta x 10% (only positions whose "
            "down-beta clears the minimum gate contribute)."
        ),
    ),
    "portfolio_hedge_short_notional": ColumnHelp(
        meaning=(
            "The modeled dollar amount of the proxy ETF you would short to offset the book's "
            "gold exposure."
        ),
        calculation="Effective gold exposure divided by the proxy's gold-down beta.",
    ),
    "portfolio_hedge_modeled_puts": ColumnHelp(
        meaning=(
            "The modeled number of put-option contracts on the proxy that would cover the short "
            "notional."
        ),
        calculation="Round up of short notional / (proxy price x 100 shares per contract).",
    ),
    "portfolio_hedge_basis_note": ColumnHelp(
        meaning=(
            "A plain-English caveat that GDX/GDXJ are sector proxies that can under-cover high- "
            "beta small-caps, and that this is a modeled hedge size, not a recommendation."
        ),
    ),
    "portfolio_corr_pair": ColumnHelp(
        meaning="The two covered holdings whose return correlation this row reports.",
    ),
    "portfolio_corr_pair_weight": ColumnHelp(
        meaning="How much of your portfolio NAV these two holdings make up together.",
        calculation="Sum of the two holdings' NAV weight fractions.",
    ),
    "portfolio_corr_correlation": ColumnHelp(
        meaning=(
            "How closely the two holdings' daily USD returns have moved together over their "
            "overlapping history (-1 to +1)."
        ),
        calculation=(
            "Pearson correlation of the two daily return series over their overlapping dates."
        ),
        direction=(
            "Lower (less correlated) means more diversification; in a gold selloff correlations "
            "often rise toward 1.0."
        ),
    ),
    "portfolio_corr_overlap_days": ColumnHelp(
        meaning=(
            "The number of overlapping daily-return observations the correlation was computed "
            "from."
        ),
        calculation=(
            "Count of dates where both holdings have a return; the pair needs at least 30 to "
            "report a correlation."
        ),
        direction="More overlapping days means a more trustworthy correlation.",
    ),
    "portfolio_corr_status": ColumnHelp(
        meaning=(
            "Whether the correlation for this pair could be computed: OK, INSUFFICIENT_HISTORY "
            "(fewer than 30 overlapping days), or UNAVAILABLE."
        ),
    ),
    "portfolio_value_history_date": ColumnHelp(
        meaning="The historical date for this covered-portfolio market-value point.",
    ),
    "portfolio_covered_market_value": ColumnHelp(
        meaning=(
            "The USD market value on this date of today's holdings for the covered names (those "
            "with price history) — a value series, not profit/loss."
        ),
        calculation=(
            "On each date, sum across covered holdings of close_usd x current shares; only "
            "dates where every included holding has a price are kept."
        ),
    ),
    "portfolio_covered_book_weight": ColumnHelp(
        meaning="What share of your portfolio NAV the covered (price-history) holdings represent.",
        calculation=(
            "Sum of the included holdings' NAV weight fractions, shown only when total NAV is "
            "positive."
        ),
    ),
    "portfolio_lot_buy_date": ColumnHelp(
        meaning="The date you bought this individual lot.",
    ),
    "portfolio_lot_shares": ColumnHelp(
        meaning="The number of shares bought in this lot.",
    ),
    "portfolio_lot_buy_price": ColumnHelp(
        meaning="The price per share you paid for this lot, in the lot's buy currency.",
    ),
    "portfolio_lot_cost": ColumnHelp(
        meaning="The total cost of this lot in its cost currency.",
        calculation="Shares x buy price for the lot.",
    ),
    "portfolio_lot_note": ColumnHelp(
        meaning="Any free-text note you saved against this lot.",
    ),
    "portfolio_current_price_local": ColumnHelp(
        meaning="The latest snapshot share price for this position, in its own trading currency.",
        calculation="Latest local-currency close from the most recent price snapshot.",
    ),
    "portfolio_value_local": ColumnHelp(
        meaning="The current market value of this position, in its own trading currency.",
        calculation="Total shares x current local price.",
    ),
    "portfolio_pnl_local": ColumnHelp(
        meaning="Unrealized profit or loss on this position so far, in its own trading currency.",
        calculation="Current local value minus local cost.",
        direction="Higher is better.",
    ),
    "tool_a_profile": ColumnHelp(
        meaning=(
            "A plain-language label for the shape of this stock's gold sensitivity — how "
            "convex, asymmetric, or delta-driven its response to gold is — summarised from "
            "its betas, gamma, and asymmetry."
        ),
    ),
    "tool_a_rank": ColumnHelp(
        meaning="This stock's place in the Gold Sensitivity ranking.",
        calculation="Dense rank on the Gold Sensitivity Score; low-confidence names are held out of the ranking.",
        direction="Rank 1 is the top of the ranking (highest Gold Sensitivity Score); higher numbers rank lower.",
    ),
    "user_notes_count": ColumnHelp(
        meaning="How many notes you have saved on this ticker.",
    ),
    "tool_c_downside_tags": ColumnHelp(
        meaning=(
            "Short flags describing this stock's downside-to-gold behaviour — for example a "
            "steep down beta, frequent deep drops, or persistent relative weakness."
        ),
    ),
    "tool_c_upside_tags": ColumnHelp(
        meaning="Short flags describing this stock's upside-to-gold behaviour on weeks when gold rises.",
    ),
    "lab_rank": ColumnHelp(
        meaning="This stock's place in the Lab ranking.",
        calculation="Ranked by the shrunk historical beat rate vs GDX across the matching past episodes.",
        direction="Rank 1 has the highest historical beat rate vs GDX (descriptive, not a forecast).",
    ),
    "candidate_finder_coverage": ColumnHelp(
        meaning="How many of your selected criteria have a value for this stock, shown as present / total.",
        thresholds=_candidate_finder_coverage_thresholds,
        direction="Higher is better; a row is rank-eligible only at or above the configured minimum.",
    ),
    "candidate_finder_top_n_hits": ColumnHelp(
        meaning="How many of your selected criteria this stock lands in the top-N for.",
        direction="Higher means the stock ranks highly across more of your chosen criteria.",
    ),
    "candidate_finder_status": ColumnHelp(
        meaning=(
            "Eligibility of this row: Eligible (ranked), No score (no criteria data), or "
            "Low coverage (below the coverage minimum)."
        ),
        direction="Eligible is best; No-score and Low-coverage rows rank below eligible ones.",
    ),
    "candidate_finder_fit_score": ColumnHelp(
        meaning=(
            "Your weighted-average percentile across the criteria you chose (0-100) — how "
            "well the stock fits your lens. Higher is a better fit; it is not a return forecast."
        ),
        calculation=(
            "Sum of (criterion weight x percentile) over the criteria with data, divided by "
            "the total weight of those criteria."
        ),
    ),
    "candidate_finder_criterion_percentile": ColumnHelp(
        meaning="This stock's 0-100 percentile versus peers for this single criterion.",
        direction="Higher percentile means it ranks better on this criterion (after the criterion's chosen direction).",
    ),
    "candidate_finder_top_list_value": ColumnHelp(
        meaning="The stock's raw value for this criterion (its underlying metric).",
    ),
    "candidate_finder_top_list_percentile": ColumnHelp(
        meaning="Where this stock's value falls versus peers for this criterion, as a 0-100 percentile.",
        direction="Higher percentile means it ranks better on this criterion (after the criterion's chosen direction).",
    ),
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
    "ticker_symbol": ColumnHelp(
        meaning="The company's stock ticker symbol. Click it to open that name's detail page.",
    ),
    "option_stock_price": ColumnHelp(
        meaning="The stock's share price at the time of the cached options snapshot (screening data, not a live quote).",
        calculation="Underlying price recorded on the option-chain snapshot used for this screen.",
    ),
    "option_direction_signal": ColumnHelp(
        meaning=(
            "The option market's directional read for this stock — DOWNSIDE (puts priced "
            "richer than calls), UPSIDE (calls priced richer), or NEUTRAL — from its "
            "25-delta skew versus its gold-miner benchmark."
        ),
        thresholds=_skew_thresholds,
        direction=(
            "Context, not a forecast. UPSIDE is only published when call-side option volume "
            "also shows a pulse (the evidence bar is higher for a bullish read)."
        ),
    ),
    "option_activity": ColumnHelp(
        meaning=(
            "Whether option volume is elevated relative to open interest on one side — a "
            "'volume pulse'. It flags attention, not confirmed new positioning (high volume "
            "can be traders closing as easily as opening)."
        ),
        direction="Context only; it can support a skew read but does not confirm positioning.",
    ),
    "option_candidate_status": ColumnHelp(
        meaning=(
            "Whether this side (put or call) has a liquid option contract you could actually "
            "trade. Contracts are first selected into a strike bucket by a slot rule "
            "(bucket-specific relative spread, open interest, a minimum mid price, and usable "
            "implied volatility); the badge then reports the SELECTED contract's overall "
            "liquidity tier: Tradable, Watch, or No liquid candidate."
        ),
        thresholds=_candidate_status_thresholds,
        direction="Tradable is best; Watch is usable with care; No liquid candidate means skip.",
    ),
    "option_notes": ColumnHelp(
        meaning="Plain-English caveats for this row — for example why a candidate is only Watch tier, or why the data is degraded.",
    ),
    "option_cost_signal": ColumnHelp(
        meaning="Whether option protection currently looks cheap or rich for this name.",
        calculation=(
            "Based on the implied-to-realized volatility ratio (IV/RV) and the IV rank "
            "versus this name's own stored history."
        ),
        direction=(
            "CHEAP means options are low versus this model's IV/RV and IV-rank history "
            "checks; RICH means they are high. It is context, not a trade recommendation."
        ),
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
            "— its gold beta over the core window (all weeks, up and down)."
        ),
        calculation=(
            "The slope β of a straight line fit to the weekly data: stock_weekly_return = "
            "α + β × gold_weekly_return (an ordinary least-squares regression of weekly stock "
            "log-returns on weekly gold log-returns). The same line gives the alpha (intercept) "
            "and the R² (fit quality)."
        ),
        details=(
            "Units: roughly the % the stock moves per 1% weekly gold move (1.5 ≈ moves 1.5% per "
            "1% gold). Usually positive for miners, often ~1–2.5×. It CAN be negative — meaning "
            "the stock tends to move OPPOSITE to gold. Down beta and up beta split this same "
            "regression by whether gold fell or rose; gamma (down − up) is the asymmetry. Shorter "
            "windows (6M) are noisier than longer ones (3Y)."
        ),
        direction="Higher means more leveraged to gold (both up and down).",
    ),
    "tool_a_gamma": ColumnHelp(
        meaning="The gap between how the stock moves when gold falls and when gold rises — its down-gold beta minus its up-gold beta.",
        calculation="Down-regime gold beta − up-regime gold beta.",
        direction="Negative is favorable (it rises more with gold than it falls); positive means it falls harder than it rises. Lower is better.",
    ),
    "tool_a_asymmetry": ColumnHelp(
        meaning="Whether the stock reacts more to gold rising than to gold falling (or vice versa).",
        calculation="Up-regime gold beta ÷ down-regime gold beta (a ratio).",
        direction="Above 1 means it captures more upside than downside; below 1 means more downside than upside. Higher is better.",
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
        meaning="A 0–100 score for how the stock behaves when gold falls, versus peers — built from down-beta, downside volatility, relative weakness and downside hit-rate.",
        calculation="Percentile of the blended downside-weakness components across the universe, ×100.",
        direction="Higher means it falls harder when gold drops (more fragile); lower is more resilient. 0 = most resilient, 100 = most fragile. It is a percentile score, not a 1-2-3 ranking, and the table lists the most fragile names first by default.",
    ),
    "tool_c_upside_rank": ColumnHelp(
        meaning="A 0–100 score for how much upside the stock captures when gold rises, versus peers — built from up-beta, relative strength and upside hit-rate.",
        calculation="Percentile of the blended upside-strength components across the universe, ×100.",
        direction="Higher captures more upside when gold rises (0 = least, 100 = most). It is a percentile score, not a 1-2-3 ranking.",
    ),
    "tool_c_down_beta": ColumnHelp(
        meaning=(
            "How much the stock moves per 1% gold move, measured on the weeks when gold FELL "
            "— its gold beta in down markets."
        ),
        calculation=(
            "The slope β of the line stock_weekly_return = α + β × gold_weekly_return, fit using "
            "only the weeks gold's weekly return was negative (the same regression as the Delta, "
            "restricted to down weeks). α is the alpha; R² is the fit quality."
        ),
        details=(
            "Units: ≈ % the stock moves per 1% gold move on down weeks. Usually positive for "
            "miners (they amplify gold's fall, often ~1–2.5×); it CAN be negative — meaning the "
            "stock tends to rise when gold falls. If the down beta is bigger than the up beta, the "
            "stock falls more with gold than it rises (a fragile, asymmetric profile). Shorter "
            "windows (6M) are noisier than longer ones (3Y)."
        ),
        direction="Lower means it falls less than gold on down weeks (more resilient).",
    ),
    "tool_c_up_beta": ColumnHelp(
        meaning=(
            "How much the stock moves per 1% gold move, measured on the weeks when gold ROSE "
            "— its gold beta in up markets."
        ),
        calculation=(
            "The slope β of the line stock_weekly_return = α + β × gold_weekly_return, fit using "
            "only the weeks gold's weekly return was positive (the same regression as the Delta, "
            "restricted to up weeks). α is the alpha; R² is the fit quality."
        ),
        details=(
            "Units: ≈ % the stock moves per 1% gold move on up weeks. Usually positive for miners "
            "(often ~1–2.5×); it CAN be negative — meaning the stock tends to fall when gold rises. "
            "Compare with the down beta: down bigger than up means it falls more than it rises with "
            "gold (fragile). Shorter windows (6M) are noisier than longer ones (3Y)."
        ),
        direction="Higher means it rises more than gold on up weeks.",
    ),
    "benchmark_gold_beta": ColumnHelp(
        meaning=(
            "Where this stock's gold beta sits versus GDX, GDXJ, and the whole miner universe — "
            "all measured over the SAME window you pick, so the numbers are directly comparable."
        ),
        calculation=(
            "Each beta is the same OLS slope (stock_weekly_return = α + β × gold_weekly_return). "
            "GDX/GDXJ betas are computed over the selected window in the backend; the percentile is "
            "the share of the scored miners whose beta is at or below this stock's, for that window."
        ),
        details=(
            "Switching the window re-bases all three (stock, ETFs, universe) together — never mix "
            "windows. The orange marker is this stock; dashed blue ticks are the ETFs; the bar spans "
            "the miner universe. A beta can be negative (moves opposite to gold)."
        ),
        direction="Higher = more gold-sensitive than the benchmark/peers for that window.",
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
        meaning="Net debt divided by trailing (LTM) EBITDA — roughly how many years of earnings it would take to repay debt.",
        thresholds=_tool_b_leverage_thresholds,
        direction="Lower is safer.",
    ),
    "tool_b_reserve_life": ColumnHelp(
        meaning="Years of production left at the current rate, from stated reserves.",
        direction="Higher means a longer runway.",
    ),
    # ---- Tool D: Corporate Resilience (moved from hard-coded titles) ----
    "tool_d_quality_rank": ColumnHelp(
        meaning="A 0–100 resilience score — where this miner sits across the universe on the four resilience components (survival, cost, fragility, balance sheet).",
        calculation="Percentile rank of the average of the four resilience components, ×100. Only fully-scored, data-OK names are scored.",
        direction="Higher is more resilient (0 = weakest, 100 = strongest); the table sorts highest-first. It is a percentile score, not a 1-2-3 ranking.",
    ),
    "tool_d_gold_used": ColumnHelp(
        meaning="The gold price used for every stress figure in this row.",
        calculation="The stress gold price you selected (a raw input, not a calculation).",
    ),
    "tool_d_interest_cover": ColumnHelp(
        meaning="The gold price at which modeled EBITDA would just equal interest expense.",
        calculation="Solve modeled EBITDA(gold) = interest expense, where EBITDA(gold) = slope×gold + intercept is fit from two gold points.",
        direction="Lower is safer — more room before earnings can't cover interest.",
    ),
    "tool_d_survival_distance": ColumnHelp(
        meaning="How far the selected stress gold price (G) sits above the interest-cover line.",
        calculation="(Gold used − interest-cover line) ÷ gold used, shown as a percent.",
        direction="Higher is safer.",
    ),
    "tool_d_breakeven": ColumnHelp(
        meaning="The gold price where mine margin reaches zero (AISC breakeven).",
        calculation="Equals AISC per ounce (cash margin = gold − AISC = 0 there).",
        direction="Lower is safer.",
    ),
    "tool_d_fcf_breakeven": ColumnHelp(
        meaning="The gold price needed to cover AISC plus sustaining capex per ounce.",
        calculation="AISC + sustaining capex per ounce (floored at AISC).",
        direction="Lower is safer.",
    ),
    "tool_d_debt_stress": ColumnHelp(
        meaning="The gold price where Net Debt / EBITDA reaches the danger band.",
        calculation="The gold price where modeled EBITDA = net debt ÷ the danger leverage multiple.",
        thresholds=_debt_stress_thresholds,
        direction="Lower is safer.",
    ),
    "tool_d_cost_curve": ColumnHelp(
        meaning="Where this name's AISC sits across the universe (cost-curve percentile).",
        calculation="This name's AISC ranked as a percentile across all miners, ×100.",
        direction="Lower percentile is a cheaper, more resilient producer.",
    ),
    "tool_d_fragility": ColumnHelp(
        meaning="Modeled EBITDA loss for a 10% gold fall, as a share of EBITDA at the selected gold price.",
        calculation="(EBITDA slope × gold × 10%) ÷ forward EBITDA at the selected gold price.",
        direction="Lower means less fragile to a gold drop.",
    ),
    "tool_d_leverage": ColumnHelp(
        meaning="Net Debt / EBITDA at the selected gold price.",
        calculation="Net debt ÷ forward EBITDA at the selected gold price (blank if EBITDA ≤ 0).",
        thresholds=_debt_stress_thresholds,
        direction="Lower is safer.",
    ),
    "tool_d_ev_ebitda_context": ColumnHelp(
        meaning="EV/EBITDA shown for context only — it is not used in the resilience score.",
        calculation="(Market cap + net debt) ÷ forward EBITDA at the selected gold price.",
        thresholds=_ev_ebitda_cap_thresholds,
        direction="Lower is cheaper.",
    ),
    "tool_d_fcf_yield_context": ColumnHelp(
        meaning="FCF yield shown for context only — it is not used in the resilience score.",
        calculation="Free cash flow ÷ market value (from the spot valuation).",
        direction="Higher means more cash generation for the price.",
    ),
    "tool_d_failure_ladder": ColumnHelp(
        meaning="The order in which this miner runs into trouble as gold falls — its survival lines from the highest gold price to the lowest.",
        calculation="The breakeven, FCF-breakeven and interest-cover gold prices that exist for the name, sorted from highest to lowest.",
        direction="A higher first rung means trouble starts sooner if gold drops.",
    ),
    "tool_d_resilience_flags": ColumnHelp(
        meaning="Risk and missing-data tags that apply at the selected gold price.",
        details="Possible tags: negative margin, leverage undefined (EBITDA ≤ 0), thin headroom (<10%), past the debt-stress line, or missing AISC / production / debt / interest inputs.",
        direction="No flags is best; flags point to the specific stress or data gap.",
    ),
    "tool_d_data_status": ColumnHelp(
        meaning="Whether the row has enough data to be scored and ranked.",
        details="OK means fully scored; otherwise INSUFFICIENT_DATA (no production/AISC), INSUFFICIENT_INTEREST_DATA, or INSUFFICIENT_EBITDA_MODEL — those names are held out of the rank.",
    ),
    "tool_d_survival_component": ColumnHelp(
        meaning="Score for how far the miner sits above its interest-cover line.",
        calculation="Percentile rank of Distance-to-line across the universe, ×100 (higher distance scores higher).",
        direction="Higher is more resilient.",
    ),
    "tool_d_cost_component": ColumnHelp(
        meaning="Score rewarding low-cost (low-AISC) producers.",
        calculation="Percentile rank of AISC across the universe, ×100, with low cost scoring higher.",
        direction="Higher is more resilient.",
    ),
    "tool_d_fragility_component": ColumnHelp(
        meaning="Score rewarding miners whose EBITDA is least fragile to a gold drop.",
        calculation="Percentile rank of Fragility slope across the universe, ×100, with low fragility scoring higher.",
        direction="Higher is more resilient.",
    ),
    "tool_d_balance_sheet_component": ColumnHelp(
        meaning="Score rewarding lower Net Debt / EBITDA at the selected gold price.",
        calculation="Percentile rank of Leverage @ G across the universe, ×100, with low leverage scoring higher.",
        direction="Higher is more resilient.",
    ),
    # ---- Lab: Conditional Dial analog table ----
    "lab_p_beat_shrunk": ColumnHelp(
        meaning=(
            "How often this miner beat the GDX benchmark in the chosen gold "
            "scenario, nudged toward the group average so thin histories aren't "
            "over-trusted (empirical-Bayes shrinkage)."
        ),
        direction="Higher means a higher historical beat rate in that scenario (descriptive, not a forecast).",
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
        direction="Higher means a higher historical beat rate vs the junior-miner basket in that scenario.",
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
    # ---- Portfolio: holdings (Positions) table ----
    "portfolio_avg_cost": ColumnHelp(
        meaning=(
            "Your average purchase price per share, in the position's own currency. "
            "Shown only when you paid in that same currency; for a holding bought in a "
            "different currency (e.g. GBP cost on an Australian-listed share) this is "
            "intentionally blank and the USD/GBP figures are used instead."
        ),
        calculation="Total cost of all lots ÷ total shares held.",
    ),
    "portfolio_pnl_pct": ColumnHelp(
        meaning=(
            "Profit or loss on this position so far, as a percent of what you paid (in "
            "local currency). Shown only when cost and trading currency match; for a "
            "cross-currency holding it is intentionally blank — use the USD/GBP P&L."
        ),
        calculation="(Current value − cost) ÷ cost.",
        direction="Higher is better.",
    ),
    "portfolio_equity_weight": ColumnHelp(
        meaning="How big this position is as a share of your equity holdings only.",
        calculation="Position value ÷ total value of all equity positions.",
        direction="Higher means a larger slice of your stock book.",
    ),
    "portfolio_nav_weight": ColumnHelp(
        meaning="How big this position is as a share of your whole portfolio's net asset value (NAV).",
        calculation="Position value ÷ total NAV.",
        details="Today NAV is just your entered stock positions; broker cash and hedge value fold in once the import milestone lands.",
        direction="Higher means a larger slice of the whole portfolio.",
    ),
    "portfolio_gold_down_loss": ColumnHelp(
        meaning="A rough USD loss on this position if the gold price fell 10%.",
        calculation="Position value × gold down-beta × 10%, a straight-line estimate.",
        details="Only positions with a usable gold down-beta above the minimum gate are modeled; low- or negative-beta names are left blank (marked 'Low/negative beta') rather than force-modeled. The estimate can never exceed the position's value.",
        direction="Lower is safer — it is a smaller modeled loss.",
    ),
    "portfolio_loss_share": ColumnHelp(
        meaning="This position's share of the portfolio's total modeled loss if gold fell 10%.",
        calculation="This position's gold-down loss ÷ the sum of that loss across all positions.",
        direction="Higher means this position drives more of your downside.",
    ),
    "portfolio_resilience": ColumnHelp(
        meaning="A plain-language band for how resilient the company is, taken from its Tool D resilience score.",
        calculation="Strong resilience = score 75 or above, Average = 50 to 74, Weak = below 50; shows 'Unavailable'/'Missing Tool D' when there is no score.",
        direction="Strong is best.",
    ),
    "portfolio_position_status": ColumnHelp(
        meaning="Whether this position's valuation data (price, FX, currency, and manual-lot validity) is complete and current.",
        details="A degraded status holds back this row's gold-down loss estimate. Beta availability and Tool D resilience are tracked separately — a position can read OK here yet still be missing a beta or a Tool D resilience reading.",
    ),
    "option_candidate_delta": ColumnHelp(
        meaning=(
            "The option's Black-Scholes delta — roughly how much its price moves per $1 "
            "move in the stock (and an approximate chance of finishing in-the-money). It is a "
            "fit/shape signal used to pick the best contract WITHIN a strike bucket, not what "
            "assigns the bucket: the Near-ATM / Directional buckets are set by how far "
            "out-of-the-money the strike is."
        ),
        calculation=(
            "Black-Scholes delta from spot, strike, time, the risk-free rate, and implied "
            "volatility — assuming zero dividend yield / cost-of-carry."
        ),
        details=(
            "That zero dividend/carry assumption biases the delta (and the modeled option prices "
            "below) for dividend-paying miners or ETFs and long-dated options — treat them as "
            "estimates, not live quotes."
        ),
    ),
    "option_scenario_pnl": ColumnHelp(
        meaning="Modeled profit/loss per share (and total) for the selected option under each gold-move scenario.",
        calculation=(
            "From Black-Scholes option prices (assuming zero dividend yield / carry) at the scenario "
            "stock price; net figures scale by your contract count."
        ),
        details=(
            "These are MODEL prices, not live market quotes — they can drift from executable prices, "
            "more so for dividend payers and long-dated options."
        ),
    ),
}
