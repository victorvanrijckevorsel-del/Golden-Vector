"""Site-wide column-help registry: click-to-explain headers with config thresholds.

One registry owns every header/metric explanation so the wording can never
diverge across pages and templates never hard-code threshold numbers.
Threshold values are resolved at render time from the loaded ``AppConfig`` —
change the config and the explanation changes with it.

Default header transport (``help_th``) is a clickable ``i`` button that opens a
persistent panel: meaning + formula first, with details/thresholds/direction
behind "Read more" (``help-popover.js`` builds and positions it; ``workspace.css``
styles ``.help-icon`` / ``.help-panel``). The click is captured before the header
sort, so clicking the title still sorts. Inline labels, categorical values, and
ratio value cells use the same click panel; there is no separate hover tooltip
transport. The registry keeps the explanation in separate parts (meaning /
calculation / thresholds / direction) so wording never diverges and templates
never hard-code threshold numbers.
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
    """Inline label carrying the SAME click-to-open "i" panel used everywhere — one info
    affordance across the whole app (no separate hover tooltip). Use inside any cell, heading, or
    label. Pass an explicit ``text`` to explain something not in the registry. With no help the
    label renders plain (escaped)."""

    icon = help_icon(label, key=key, app_config=app_config, text=text)
    if not icon:
        return escape(label)
    return f"{escape(label)}<span class=\"help-anchor\">{icon}</span>"


def help_icon(
    label: str,
    *,
    key: str | None = None,
    app_config: AppConfig | None = None,
    text: str | None = None,
    values: str | None = None,
) -> str:
    """A small clickable ``ⓘ`` button carrying the help split into meaning / formula /
    "this stock" / more, for the click-to-open explanation panel (``help-popover.js``). This is
    the ONE info affordance — headers, categorical values, inline labels AND ratio value cells all
    use it. ``values`` is the per-row instantiation ("Gold price 4,173, AISC 2,080 → 2,093 $/oz")
    shown in a "This stock" section; pass it only for value cells. Returns ``""`` when there is
    nothing to explain. Clicking it opens the panel without triggering a header's sort."""

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
        f"data-help-values=\"{escape(values or '')}\" "
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
    scope: str = "col",
) -> str:
    """Render a ``<th>`` whose label carries a registry-driven help affordance.

    ``panel=True`` (default) renders the header text plain plus a clickable ``i``
    that opens the persistent explanation panel (meaning + formula + Read more) —
    header-click still sorts. ``panel=False`` is kept for old call sites, but still
    renders the same unified click panel through ``help_term``.

    ``scope`` declares the header relationship (plan 11.1): ``"col"`` (default)
    for column headers, ``"row"`` for row headers in label/value tables.
    """

    if scope not in ("col", "row"):
        raise ValueError(f"unsupported th scope: {scope!r}")
    attrs: list[str] = [f" scope=\"{scope}\""]
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


# --- Categorical VALUE glossary: explains what a cell VALUE means (LOW_LINKAGE,
# FRAGILE, MODERATE_NOISE, HIGH/MEDIUM/LOW confidence, ...) via the same click-to-open
# "i" the column headers use. One source of truth; wording kept consistent with
# golden_vector/model/{labels,explanations}.py. ---
VALUE_HELP: dict[str, str] = {
    # Profile (Tool A)
    "CONVEX": "Upside-skewed gold play — strong gold linkage and better up-gold participation than down-gold sensitivity (the favourable shape).",
    "FRAGILE": "Fragile gold exposure — meaningful linkage, but it has fallen harder with gold than it has risen.",
    "HIGH_DELTA": "High-delta gold exposure — strong weekly linkage, but a less favourable up-vs-down skew than the best names.",
    "LINEAR": "Clean linear gold exposure — strong linkage, fairly balanced up-vs-down, low residual noise.",
    "LOW_LINKAGE": "Barely tracks gold — the structural linkage is too weak to treat it as a core gold name, so its beta is unreliable.",
    "DEFENSIVE": "More defensive gold exposure — some linkage to gold, but less torque or a less favourable regime profile than the stronger names.",
    "SCORE_WITHHELD": "Score withheld — trailing FX or return-basis issues make the structural read untrustworthy until resolved.",
    # Volatility context (Tool A)
    "LOW_NOISE": "Low residual noise — a large share of its weekly moves is explained by gold rather than idiosyncratic noise (a cleaner gold play).",
    "MODERATE_NOISE": "Moderate residual noise and downside risk — between the low- and high-noise extremes.",
    "HIGH_NOISE": "High residual noise — much of its weekly movement is NOT explained by gold, so the exposure is noisy.",
    "HIGH_DOWNSIDE_RISK": "High downside risk — weekly drawdowns have been especially violent, making the exposure fragile even when gold linkage is strong.",
    # Confidence (Tool A)
    "HIGH": "High confidence — decent fit, enough weekly observations, and consistent behaviour across windows.",
    "MEDIUM": "Medium confidence — usable, but it shows some fit, stability, or regime-split weakness.",
    "LOW": "Low confidence — noisy, thin, or inconsistent; treat the rank cautiously.",
}


def help_value(value: object, *, app_config: AppConfig | None = None) -> str:
    """Render a categorical TABLE CELL (<td>) whose VALUE carries its own click-to-open
    "i" explanation (what ``LOW_LINKAGE`` means), reusing the header popup machinery.

    The cell's filter/sort data is the RAW value via ``data-search`` / ``data-order``
    (DataTables reads those), so the "i" button never pollutes the column's exact-regex
    filter (``^LOW_LINKAGE$``) or its sort order — Codex's blocking requirement. The
    button is a real, focusable ``<button>`` (keyboard/touch accessible, not hover-only).
    A missing value renders a plain em-dash cell; an unknown value renders clean text.
    """
    s = "" if value is None else str(value).strip()
    if not s or s.lower() == "nan":
        return "<td>—</td>"
    attrs = f" data-search=\"{escape(s)}\" data-order=\"{escape(s)}\""
    meaning = VALUE_HELP.get(s)
    if not meaning:
        return f"<td{attrs}>{escape(s)}</td>"
    icon = help_icon(s, text=meaning, app_config=app_config)
    inner = f"{escape(s)}<span class=\"help-anchor\">{icon}</span>" if icon else escape(s)
    return f"<td{attrs}>{inner}</td>"


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
            "threshold check fails (AISC, margin, AISC margin yield, reserve life, leverage), else "
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
            "passed/total followed by each check's status (Data complete, AISC, Margin, AISC margin yield, "
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
    # --- ticker-page Options section (M3d) ---------------------------------
    "option_section": ColumnHelp(
        meaning=(
            "What the listed option market is doing on this company: how the crowd is "
            "positioned, what volatility is priced, which contracts are actually "
            "tradable, and what a position would cost."
        ),
        calculation=(
            "Read from the option artifacts published by the last refresh — the daily "
            "chain history, the option signal history, and the selected candidate "
            "contracts. Nothing is computed while the page loads."
        ),
        direction=(
            "Context, not a recommendation. This section is only hidden when the "
            "company genuinely has no listed options."
        ),
    ),
    "option_put_call_ratio_total": ColumnHelp(
        meaning=(
            "The whole-chain put/call open-interest ratio: every open put contract "
            "divided by every open call contract."
        ),
        calculation=(
            "put_oi_total / call_oi_total, computed during the refresh over the whole "
            "captured chain and stored as put_call_oi_ratio_total."
        ),
        direction=(
            "Below 1 means calls outnumber puts, which usually reads as bullish "
            "positioning. Above 1 means puts outnumber calls — bearish or hedged. "
            "Read it together with the out-of-the-money ratio; they often disagree."
        ),
    ),
    "option_put_call_ratio_otm": ColumnHelp(
        meaning=(
            "The put/call open-interest ratio counting ONLY out-of-the-money strikes — "
            "where speculation and hedging actually live."
        ),
        calculation=(
            "put_oi_otm / call_oi_otm, computed during the refresh and stored as "
            "put_call_oi_ratio_otm."
        ),
        direction=(
            "Above 1 means out-of-the-money puts outnumber calls. This ratio "
            "disagreeing with the whole-chain one is the interesting case: the chain "
            "can lean bullish overall while the speculative strikes lean bearish."
        ),
    ),
    "option_oi_trend": ColumnHelp(
        meaning=(
            "Open interest over time, split into puts, calls and the total, so a change "
            "in the ratio can be traced to which side actually moved."
        ),
        calculation=(
            "One point per captured trading day from option_chain_history_daily. Days "
            "whose capture was incomplete are left as gaps rather than drawn."
        ),
        direction=(
            "Rising put open interest with flat calls means new downside positioning; "
            "a falling total usually means contracts expired."
        ),
    ),
    "option_daily_volume": ColumnHelp(
        meaning=(
            "Contracts traded on the snapshot day, split into puts, calls and the "
            "total. Volume is today's activity; open interest is the standing position."
        ),
        calculation="put_volume / call_volume / total_volume from the daily chain capture.",
        direction=(
            "High volume against low open interest means fresh activity rather than an "
            "established position."
        ),
    ),
    "option_signal_history": ColumnHelp(
        meaning=(
            "Implied volatility measured against its own history, the implied move it "
            "translates into, and how it compares with the stock's realised volatility."
        ),
        calculation=(
            "Persisted option_signal_history_points at the configured signal horizon; "
            "the tenor is named in the chart title because these are horizon-specific."
        ),
        direction=(
            "Implied above realised means options are pricing more movement than the "
            "stock has recently delivered, so protection and speculation both cost more."
        ),
    ),
    "option_most_liquid": ColumnHelp(
        meaning=(
            "The most tradable contract on each side for the chosen target window — "
            "near-the-money and directional."
        ),
        calculation=(
            "Selected during the refresh from the captured chain using the configured "
            "spread, open-interest and minimum-premium gates."
        ),
        direction=(
            "Puts and calls are selected independently, so the two tables can show "
            "different expiry dates. Each row states its own expiry and days to expiry."
        ),
    ),
    "option_target_window": ColumnHelp(
        meaning=(
            "Roughly how far out you want to be positioned. It selects a band of "
            "expiries, not one exact date."
        ),
        calculation=(
            "The configured display horizons; each maps to a days-to-expiry band, and "
            "the contract chosen inside that band is whichever listed expiry fits best."
        ),
        direction=(
            "Longer windows cost more premium but decay more slowly. Because it is a "
            "band, the put and call rows can land on different expiry dates."
        ),
    ),
    "option_bid_ask": ColumnHelp(
        meaning=(
            "The bid is what buyers currently show; the ask is what sellers show. You "
            "buy at the ask and sell at the bid."
        ),
        calculation="Bid and ask from the cached option-chain snapshot, not a live quote.",
        direction=(
            "The gap between them is your immediate cost of entering and exiting. A bid "
            "above the ask is a broken quote and disables sizing for that contract."
        ),
    ),
    "option_contract_volume": ColumnHelp(
        meaning="How many of this exact contract traded on the snapshot day.",
        calculation="Contract volume from the cached option chain.",
        direction=(
            "Low volume means you may struggle to get filled near the quoted price, "
            "even when open interest looks healthy."
        ),
    ),
    "option_crowd_positioning": ColumnHelp(
        meaning=(
            "Where open interest actually sits across strikes, and how implied "
            "volatility varies by strike (the skew)."
        ),
        calculation=(
            "Persisted open-interest-by-strike and skew-curve points from the last "
            "refresh."
        ),
        direction=(
            "Clusters of open interest mark the strikes traders care about. A steeper "
            "downside skew means puts are priced richer than calls."
        ),
    ),
    "option_sizing_tool": ColumnHelp(
        meaning=(
            "Turns a budget into a whole number of contracts and shows what they would "
            "be worth at expiry across a range of share prices."
        ),
        calculation=(
            "Contracts = budget divided by (ask x 100), rounded down. Value at expiry is "
            "intrinsic value only — no time value — so it is a floor, not a forecast. "
            "The share price is your input; it is never derived from a gold move."
        ),
        direction=(
            "Break-even is the strike plus the premium for calls, minus it for puts. "
            "Contracts with a missing, crossed or stale quote are disabled rather than "
            "priced off a substitute."
        ),
    ),
    "option_greeks": ColumnHelp(
        meaning=(
            "The sensitivity measures for the selected contracts, plus the provenance "
            "and liquidity detail behind the tables above."
        ),
        calculation=(
            "Computed during the refresh on the selected candidate rows only, using the "
            "quoted implied volatility, the actual days to expiry and the manifest "
            "risk-free rate."
        ),
    ),
    "option_greeks_units": ColumnHelp(
        meaning=(
            "Gamma is how fast delta changes; vega is sensitivity to implied volatility; "
            "theta is how much value time decay removes."
        ),
        calculation=(
            "Black-Scholes with a zero dividend yield. Units are fixed: gamma per $1 of "
            "share price, vega per volatility point, theta per calendar day. The model "
            "version is shown beneath the table."
        ),
        direction=(
            "Theta is normally negative for a bought option — that is the daily cost of "
            "holding it."
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
            "The trailing time window (6M, 1Y, or 3Y) over which these structural metrics were "
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
        meaning="This stock's place in the overall gold-sensitivity ranking.",
        calculation="Dense rank by overall gold sensitivity (across windows); low-confidence names are held out of the ranking.",
        direction="Rank 1 = strongest, most reliable gold play; higher numbers rank lower.",
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
    "tool_a_delta_blend": ColumnHelp(
        meaning=(
            "How much this stock tends to move for each 1% move in the gold price — its gold beta "
            "over all weeks (up and down). The value shown here is the cross-window blend: a "
            "weighted median of the 6M / 1Y / 3Y windows. Open a ticker's detail page for "
            "per-window betas."
        ),
        calculation=(
            "Per window, the slope β of stock_weekly_return = α + β × gold_weekly_return (OLS on "
            "weekly log-returns); the figure shown is the weighted-median blend across the scoring "
            "windows (6M / 1Y / 3Y) — the same robustness blend behind the Gold Sensitivity Score."
        ),
        details=(
            "Units: roughly the % the stock moves per 1% weekly gold move (1.5 ≈ moves 1.5% per "
            "1% gold). Usually positive for miners, often ~1–2.5×; it CAN be negative (moves "
            "OPPOSITE to gold). Down beta and up beta split the same regression by whether gold "
            "fell or rose; gamma (down − up) is the asymmetry."
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
    "tool_a_up_beta": ColumnHelp(
        meaning="How strongly the stock moves when gold RISES, over the selected beta window.",
        calculation="Regression slope of the stock's weekly return on gold's, on the weeks gold rose.",
        direction="Higher = more upside leverage to gold (e.g. 2.0 ≈ moves twice as much as gold).",
    ),
    "tool_a_down_beta": ColumnHelp(
        meaning="How strongly the stock moves when gold FALLS, over the selected beta window.",
        calculation="Regression slope of the stock's weekly return on gold's, on the weeks gold fell.",
        direction="Lower = better cushioned when gold drops; a value near 0 barely follows gold down.",
    ),
    "tool_a_gold_link": ColumnHelp(
        meaning=(
            "How much of the stock's movement gold actually explains in this window — i.e. whether "
            "its beta is even meaningful. A 'weak'/'none' name barely tracks gold, so don't trust its beta."
        ),
        calculation="R² of the gold regression. strong ≥40% · moderate ≥25% · weak ≥10% · none <10%.",
        direction="Higher = the beta is more trustworthy.",
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
    # Blend-basis variants for surfaces that show the cross-window `_core` beta (Candidate
    # Finder / Option Trading / Portfolio) rather than a single selected window. They state
    # the basis explicitly so the number is never mistaken for a per-window beta — the detail
    # page's per-window table keeps the plain `tool_c_*_beta` keys.
    "tool_c_down_beta_blend": ColumnHelp(
        meaning=(
            "How much the stock moves per 1% gold move on the weeks gold FELL — its gold beta "
            "in down markets. The value shown here is the cross-window blend: a weighted median "
            "of the 6M / 1Y / 3Y windows. Open a ticker's detail page for per-window betas."
        ),
        calculation=(
            "Per window, the slope β of stock_weekly_return = α + β × gold_weekly_return on the "
            "down weeks; the figure shown is the weighted-median blend across the scoring "
            "windows (6M / 1Y / 3Y) — the same robustness blend behind the Gold Sensitivity Score."
        ),
        details=(
            "Units: ≈ % the stock moves per 1% gold move on down weeks. Usually positive for "
            "miners (~1–2.5×); it CAN be negative (rises when gold falls). If the down beta is "
            "bigger than the up beta, the stock falls more with gold than it rises (fragile)."
        ),
        direction="Lower means it falls less than gold on down weeks (more resilient).",
    ),
    "tool_c_up_beta_blend": ColumnHelp(
        meaning=(
            "How much the stock moves per 1% gold move on the weeks gold ROSE — its gold beta "
            "in up markets. The value shown here is the cross-window blend: a weighted median "
            "of the 6M / 1Y / 3Y windows. Open a ticker's detail page for per-window betas."
        ),
        calculation=(
            "Per window, the slope β of stock_weekly_return = α + β × gold_weekly_return on the "
            "up weeks; the figure shown is the weighted-median blend across the scoring windows "
            "(6M / 1Y / 3Y) — the same robustness blend behind the Gold Sensitivity Score."
        ),
        details=(
            "Units: ≈ % the stock moves per 1% gold move on up weeks. Usually positive for miners "
            "(~1–2.5×); it CAN be negative. Compare with the down beta: down bigger than up means "
            "it falls more than it rises with gold (fragile)."
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
        calculation="Share price / forward EPS.",
        direction="Lower is cheaper.",
    ),
    "tool_b_ev_ebitda": ColumnHelp(
        meaning="Enterprise value divided by forward EBITDA — the standard valuation multiple for miners.",
        calculation="(Market cap + net debt) / forward EBITDA.",
        direction="Lower is cheaper.",
    ),
    "tool_b_aisc_margin_yield": ColumnHelp(
        meaning="AISC margin estimate as a percent of market value. It is a cost-margin proxy, not audited free cash flow.",
        calculation="(Gold price − reported AISC) × production / market cap. Reported AISC already includes sustaining capital, so it is charged once.",
        direction="Higher means more margin for the price.",
    ),
    "tool_b_leverage": ColumnHelp(
        meaning="Net debt divided by trailing (LTM) EBITDA — roughly how many years of earnings it would take to repay debt.",
        calculation="Net debt / trailing (LTM) EBITDA.",
        thresholds=_tool_b_leverage_thresholds,
        direction="Lower is safer.",
    ),
    "tool_b_reserve_life": ColumnHelp(
        meaning="Years of production left at the current rate, from stated reserves.",
        direction="Higher means a longer runway.",
    ),
    # ---- Tool D: Corporate Resilience (moved from hard-coded titles) ----
    "ticker_fx_attribution": ColumnHelp(
        meaning=(
            "How the listing currency's move changed this stock's USD return over the "
            "selected chart window. This is about the LISTING currency only — it does not "
            "measure where the company earns revenue or pays its costs."
        ),
        calculation=(
            "USD return = (1 + local return) × (1 + FX return) − 1, measured at the exact "
            "chart endpoint dates. The FX contribution is the USD return minus the local "
            "return, in percentage points."
        ),
    ),
    # --- ticker page: gold dial + corporate finance (M3b) --------------------
    "ticker_gold_dial": ColumnHelp(
        meaning=(
            "A what-if gold price. Moving it re-prices ONLY the Corporate finance "
            "section — the performance chart, market-behaviour betas, the failing-check "
            "sentences and every score stay at spot gold and visibly do not react."
        ),
        calculation=(
            "The backend fits each earnings line against gold and publishes its exact "
            "slope and intercept; your browser evaluates those published lines at the "
            "price you choose. Nothing is estimated in the page."
        ),
        details=(
            "The dial position is deliberately NOT saved in the URL — it is a scratch "
            "what-if, not a saved view, so a link you share always opens at spot. "
            "\"Reset to spot\" puts it back exactly."
        ),
        thresholds=lambda config: (
            f"Range {config.ticker_page.dial.min_gold_usd:,.0f} to "
            f"{config.ticker_page.dial.max_gold_usd:,.0f} USD/oz, step "
            f"{config.ticker_page.dial.step_usd:,.0f}."
        ),
    ),
    "ticker_cf_section": ColumnHelp(
        meaning=(
            "Everything held on the business, grouped by the question it answers. Rows "
            "marked \"moves with gold\" follow the dial; the rest are facts that do not "
            "depend on the gold price."
        ),
        calculation=(
            "Spot values are published by the backend at TRUE spot gold (not a rounded "
            "scenario); scenario values are the same published lines evaluated at your "
            "dial price."
        ),
    ),
    "ticker_cf_forward_revenue": ColumnHelp(
        meaning="Expected revenue over the next twelve months at this gold price.",
        calculation="Gold price × annual production ounces, from the published revenue line.",
    ),
    "ticker_cf_forward_ebitda": ColumnHelp(
        meaning=(
            "Expected forward EBITDA — earnings before interest, tax, depreciation and "
            "amortisation — at this gold price."
        ),
        calculation="The published forward-EBITDA line evaluated at the selected gold price.",
        direction="Higher is better.",
    ),
    "ticker_cf_forward_net_income": ColumnHelp(
        meaning="Expected forward net income at this gold price, after interest, D&A and tax.",
        calculation="The published forward-net-income line evaluated at the selected gold price.",
        direction="Higher is better.",
    ),
    "ticker_cf_forward_eps": ColumnHelp(
        meaning="Expected forward earnings per share at this gold price.",
        calculation="Forward net income ÷ shares outstanding, from the published EPS line.",
        direction="Higher is better.",
    ),
    "ticker_cf_aisc_margin": ColumnHelp(
        meaning=(
            "Estimated cash left after all-in sustaining costs across a year's production "
            "at this gold price."
        ),
        calculation="(Gold price − AISC per ounce) × annual production ounces.",
        details=(
            "This is an AISC-margin estimate, NOT reported free cash flow: it ignores "
            "working capital, growth capex, tax timing and financing."
        ),
        direction="Higher is better.",
    ),
    "ticker_cf_margin_usd_per_oz": ColumnHelp(
        meaning="Cash left on every ounce mined at this gold price.",
        calculation="Gold price − the cost basis named beside the number (AISC or cash cost).",
        direction="Higher is better.",
    ),
    "ticker_cf_margin_pct": ColumnHelp(
        meaning="The share of each ounce's gold price that survives as margin.",
        calculation="Cash margin per ounce ÷ gold price.",
        thresholds=lambda config: (
            f"Your screening floor is "
            f"{config.screening_params.layer1_thresholds.margin_min:.0%}."
        ),
        direction="Higher is better.",
    ),
    "ticker_cf_aisc_margin_yield": ColumnHelp(
        meaning=(
            "The AISC margin a full year of production would generate, measured against "
            "what the whole company costs to buy."
        ),
        calculation="AISC margin ($m at this gold price) ÷ market cap.",
        details=(
            "Named for what it is: an AISC-margin yield, not a reported free-cash-flow "
            "yield — it ignores working capital, growth capex, tax timing and financing."
        ),
        thresholds=lambda config: (
            f"Your screening floor is "
            f"{config.screening_params.layer1_thresholds.aisc_margin_yield_min:.0%}."
        ),
        direction="Higher is better (cheaper for the margin you get).",
    ),
    "ticker_cf_ev_ebitda": ColumnHelp(
        meaning=(
            "What the whole business costs (equity plus net debt) per dollar of forward "
            "earnings before interest, tax, depreciation and amortisation."
        ),
        calculation=(
            "Enterprise value ÷ forward EBITDA at the selected gold price. Shown blank "
            "when forward EBITDA is zero or negative — a multiple on negative earnings "
            "is meaningless."
        ),
        details=(
            "IMPORTANT — this multiple RISES as gold FALLS. The share price and net debt "
            "in the numerator do not move with your dial, while forward EBITDA in the "
            "denominator shrinks, so a lower gold price makes the company look MORE "
            "expensive, not cheaper. Read a rising number as deteriorating earnings, not "
            "as a re-rating."
        ),
        direction="Lower is cheaper.",
    ),
    "ticker_cf_forward_pe": ColumnHelp(
        meaning="What one share costs per dollar of expected forward earnings.",
        calculation=(
            "Share price ÷ forward earnings per share at the selected gold price. Shown "
            "blank when forward EPS is zero or negative."
        ),
        details=(
            "IMPORTANT — this multiple RISES as gold FALLS, for the same reason as "
            "EV/EBITDA: the share price in the numerator does not move with your dial "
            "while forward earnings shrink. A rising P/E here means earnings are being "
            "squeezed, not that the market re-rated the stock."
        ),
        thresholds=lambda config: (
            "Your screening cut-offs are "
            f"{config.screening_params.verdict_thresholds.strong_candidate_forward_pe_max:.0f}× "
            "for a strong candidate and "
            f"{config.screening_params.verdict_thresholds.watchlist_forward_pe_max:.0f}× "
            "for the watchlist."
        ),
        direction="Lower is cheaper.",
    ),
    "ticker_cf_leverage_stressed": ColumnHelp(
        meaning=(
            "Debt measured against the earnings the company would make at the gold price "
            "on the dial — how strained the balance sheet becomes in that world."
        ),
        calculation="Net debt ÷ FORWARD EBITDA at the selected gold price.",
        details=(
            "This is a different number from \"Net debt / EBITDA (LTM)\" in Balance sheet, "
            "cost and scale: that one divides by the last twelve months of REPORTED "
            "earnings and never moves with the dial. Two concepts, two rows, two labels."
        ),
        direction="Lower is safer.",
    ),
    "ticker_cf_leverage_trailing": ColumnHelp(
        meaning=(
            "Debt measured against the earnings the company actually reported over the "
            "last twelve months. It does not move with the gold dial."
        ),
        calculation=(
            "Net debt ÷ trailing-twelve-month EBITDA. Shown blank when trailing EBITDA is "
            "zero or negative."
        ),
        details=(
            "Distinct from \"Stressed forward leverage\" in the headline cards, which "
            "divides by FORWARD EBITDA at the dial's gold price."
        ),
        thresholds=lambda config: (
            f"Your screening cap is "
            f"{config.screening_params.layer1_thresholds.leverage_max:.1f}×."
        ),
        direction="Lower is safer.",
    ),
    "ticker_cf_resilience": ColumnHelp(
        meaning=(
            "The gold prices at which this company's economics break, and how far gold "
            "would have to fall to reach them."
        ),
        calculation=(
            "Published by the resilience model on Our View inputs at spot gold — these "
            "rows do not move with the dial."
        ),
        details=(
            "Disabled in Yahoo Fundamentals mode: resilience is computed on Our View "
            "inputs, and mixing the two sources would misstate the thresholds."
        ),
    ),
    "ticker_cf_data_quality": ColumnHelp(
        meaning=(
            "Where each number came from, when it was captured, and whether any stage "
            "reported a problem."
        ),
        calculation=(
            "Statuses and as-of dates are persisted columns — nothing here is inferred by "
            "the page."
        ),
    ),
    "ticker_cost_downside": ColumnHelp(
        meaning=(
            "Two pieces of evidence side by side: today's reported all-in sustaining cost, "
            "and how often the share actually fell 10%+ in past weak-gold weeks. They are "
            "shown together for context — no combined score, and no claim that one causes "
            "the other."
        ),
        calculation=(
            "AISC: company-reported (Our View mining assumption). Large-fall rate: exact "
            "hits ÷ qualifying weak-gold weeks (gold's rolling weakest 20%), where a hit is "
            "an ordinary weekly price return of −10% or worse."
        ),
    ),
    # --- ticker page: market behaviour (M3c) --------------------------------
    "ticker_behaviour_section": ColumnHelp(
        meaning=(
            "How this share has actually moved with gold: betas measured on weekly "
            "returns, its counted record against the gold-miner ETFs, and the history "
            "behind the disclosures."
        ),
        calculation=(
            "Every number is read from a published artifact. Nothing on this page is a "
            "compiled score or a verdict — the composites stay on the ranking pages."
        ),
    ),
    "ticker_up_down_beta": ColumnHelp(
        meaning=(
            "Gold beta measured separately on the weeks gold ROSE and the weeks gold "
            "FELL, over the beta window selected at the top of this section."
        ),
        calculation=(
            "Two regressions of the share's weekly log return on gold's, one per regime, "
            "over the selected window. Published per window; never re-fitted here."
        ),
        direction=(
            "A taller down bar than up bar means it falls more with gold than it rises — "
            "an asymmetric, fragile profile. Either beta can be negative."
        ),
    ),
    "ticker_beta_percentile_rug": ColumnHelp(
        meaning=(
            "Where this share's up and down gold beta sit inside the whole scored miner "
            "universe, on the same selected beta window."
        ),
        calculation=(
            "Each light tick is one scored miner's published beta for that window; the "
            "marked position is this share's. Positions are resolved in the model layer."
        ),
        direction=(
            "A higher down-beta percentile means it falls MORE with gold than most "
            "miners; a higher up-beta percentile means it rises more."
        ),
    ),
    "ticker_relative_record": ColumnHelp(
        meaning=(
            "The counted record against GDX: how often this share was stronger or "
            "weaker, how often the big weekly moves landed, and what the tails averaged."
        ),
        calculation=(
            "Shares of qualifying weeks over the Tool C window, each published with its "
            "own hit count and observation count. No ranking, no composite."
        ),
    ),
    "ticker_rel_strength_vs_gdx": ColumnHelp(
        meaning="Share of weeks this stock outperformed GDX over the Tool C window.",
        calculation="Weeks outperforming GDX ÷ eligible weeks in the window.",
        direction="Higher is stronger relative performance.",
    ),
    "ticker_rel_weakness_vs_gdx": ColumnHelp(
        meaning="Share of weeks this stock underperformed GDX over the Tool C window.",
        calculation="Weeks underperforming GDX ÷ eligible weeks in the window.",
        direction="Lower is better — it lagged the ETF less often.",
    ),
    "ticker_upside_hit_rate": ColumnHelp(
        meaning=(
            "How often this share posted a big UP week during qualifying strong-gold "
            "weeks."
        ),
        calculation="Hits ÷ qualifying weeks, with both counts shown as the evidence.",
        thresholds=lambda config: (
            f"A big up week is a weekly return of "
            f"{config.tool_c.upside_hit_rate_threshold_pct:+.0f}% or better."
        ),
        direction="Higher means it captured more of gold's strong weeks.",
    ),
    "ticker_downside_hit_rate": ColumnHelp(
        meaning=(
            "How often this share posted a big DOWN week during qualifying weak-gold "
            "weeks."
        ),
        calculation="Hits ÷ qualifying weeks, with both counts shown as the evidence.",
        thresholds=lambda config: (
            f"A big down week is a weekly return of "
            f"{config.tool_c.downside_hit_rate_threshold_pct:.0f}% or worse."
        ),
        direction="Lower is better — fewer violent falls in weak-gold weeks.",
    ),
    "ticker_tail_best10": ColumnHelp(
        meaning="The average weekly return across this share's best 10% of weeks.",
        calculation="Mean of the top decile of weekly returns over the Tool C window.",
        direction="Higher means a fatter upside tail.",
    ),
    "ticker_tail_worst10": ColumnHelp(
        meaning="The average weekly return across this share's worst 10% of weeks.",
        calculation="Mean of the bottom decile of weekly returns over the Tool C window.",
        direction="Closer to zero is better — a shallower downside tail.",
    ),
    "ticker_lab_history": ColumnHelp(
        meaning=(
            "Counted history: in past gold moves of the size you pick, how often did "
            "this share beat the ETF over the following weeks, and by how much?"
        ),
        calculation=(
            "Every scenario week is grouped by what gold WENT ON to do, then the share's "
            "forward return over the look-ahead is compared with the benchmark's. The "
            "grouping is hindsight, not a signal that was available on the date."
        ),
        details=(
            "Survivor-only: delisted miners are absent, so real beat-rates were probably "
            "lower. Overlapping look-ahead windows mean the effective (independent) "
            "sample is much smaller than the number of dots. Exploratory — not a forecast."
        ),
    ),
    "ticker_weekly_scatter": ColumnHelp(
        meaning=(
            "Every published weekly observation: gold's return on the x axis, this "
            "share's on the y axis."
        ),
        calculation=(
            "Read from the published weekly research series. No line is fitted in the "
            "page — the measured betas per window are in the table above the chart."
        ),
    ),
    "ticker_volatility_diagnostics": ColumnHelp(
        meaning=(
            "How volatile this share has been in total, after removing the part gold "
            "explains (residual), and on down weeks only (downside)."
        ),
        calculation=(
            "Annualized from weekly log returns and published for ONE canonical window "
            "per ticker. Other windows are never estimated in the page."
        ),
        direction="Lower residual volatility means gold explains more of the movement.",
    ),
    "ticker_research_detail": ColumnHelp(
        meaning=(
            "The raw research behind the charts above: the per-window fits, the weekly "
            "scatter, volatility diagnostics and the exploratory horizon ladder."
        ),
        calculation=(
            "All published artifact rows, shown unrounded and unblended. It is closed by "
            "default because it is reference material, not the headline read."
        ),
    ),
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
    "tool_d_aisc_margin_yield_context": ColumnHelp(
        meaning="AISC margin yield at the selected gold price — context only, not used in the resilience score.",
        calculation="(Gold − reported AISC) × production ÷ market value at the selected gold price. The spot-gold pair is kept alongside it (aisc_margin_yield_at_spot).",
        direction="Higher means more cash generation for the price.",
    ),
    "tool_d_failure_ladder": ColumnHelp(
        meaning="The order in which this miner runs into trouble as gold falls — its survival lines from the highest gold price to the lowest.",
        calculation="The breakeven (= reported AISC) and interest-cover gold prices that exist for the name, sorted from highest to lowest.",
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
