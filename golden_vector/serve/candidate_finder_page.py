"""Workspace UI for the Candidate Finder screen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from urllib.parse import quote, urlencode

from golden_vector.common.windows import ALL_WINDOWS, SCORING_WINDOWS, WINDOW_LABELS
from golden_vector.contracts.config_models import (
    AppConfig,
    CandidateFinderConfig,
    CandidateFinderCriterion,
)
from golden_vector.model.candidate_finder import (
    CandidateScore,
    CriterionTopEntry,
    ResolvedCriterion,
)
from golden_vector.serve.candidate_finder_data import (
    CandidateFinderData,
    CandidateFinderScreen,
    run_candidate_finder_screen,
)
from golden_vector.serve.column_help import help_term, help_th
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_numeric_td,
    _metric_card,
)
from golden_vector.serve.fundamentals_provenance import ticker_provenance_icon
from golden_vector.serve.http_helpers import _flash_message
from golden_vector.serve.metric_formula import metric_value_text
from golden_vector.serve.model_state_banner import (
    render_model_state_banner,
    render_option_freshness_box,
)
from golden_vector.serve.option_refresh import (
    OptionRefreshStatus,
    render_option_refresh_control,
)
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import page_header, section_heading
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.url_helpers import build_page_url

_DEFAULT_PRESET_ID = "bull"
_PRESET_ALIASES = {
    "bearish_put": "bear",
    "bullish_call": "bull",
    "strong_corporate_finance": "bull",
}

# Each Candidate Finder criterion maps to the SAME rich column-help entry that explains the
# metric everywhere else (detail / Tool B / Tool C / Tool D / Option pages). This lets the
# "Value" info button on the top-list cards and the criterion columns in the Fit Ranking table
# describe the actual metric (meaning + formula + units/sign) instead of a generic "raw value"
# line. Criteria with no rich entry fall back to their config description (help_th text=).
_CRITERION_HELP_KEYS: dict[str, str] = {
    "down_beta": "tool_c_down_beta",
    "up_beta": "tool_c_up_beta",
    "gold_beta_core": "tool_a_delta",
    "downside_volatility": "tool_a_volatility",
    "confidence": "tool_a_confidence",
    "aisc": "tool_b_aisc",
    "leverage": "tool_b_leverage",
    "ev_ebitda": "tool_b_ev_ebitda",
    "forward_pe": "tool_b_forward_pe",
    "aisc_margin_yield": "tool_b_aisc_margin_yield",
    "margin_pct": "tool_b_margin_pct",
    "reserve_life": "tool_b_reserve_life",
    "market_cap": "tool_b_market_cap",
    "interest_cover_gold": "tool_d_interest_cover",
    "debt_stress_gold": "tool_d_debt_stress",
    "cost_curve": "tool_d_cost_curve",
    "iv_percentile": "iv_percentile",
    "iv_skew": "skew_vs_benchmark",
    "name_iv_skew": "option_name_skew",
    "tool_c_downside_rank": "tool_c_downside_rank",
    "tool_c_upside_rank": "tool_c_upside_rank",
    "tool_d_quality_rank": "tool_d_quality_rank",
}

# Beta criteria show the cross-window BLEND by default (source_field ending in `_core`) and a
# single window when the user picks one via the horizon control. The blend variants spell out the
# basis ("a weighted median of 6M/1Y/3Y") so the info button never mislabels a blended number as a
# per-window beta — matching the Portfolio / Option Trading surfaces that also show the `_core` beta.
_BLEND_HELP_KEYS: dict[str, str] = {
    "down_beta": "tool_c_down_beta_blend",
    "up_beta": "tool_c_up_beta_blend",
    "gold_beta_core": "tool_a_delta_blend",
}

def _criterion_help_key(criterion: ResolvedCriterion) -> str | None:
    """Rich help key for a criterion's Value column. For the beta criteria, pick the blend-basis
    entry when the displayed value is the cross-window `_core` blend, and the plain per-window
    entry when a single window is active — so the basis label always matches the number shown."""
    if criterion.id in _BLEND_HELP_KEYS and criterion.source_field.endswith("_core"):
        return _BLEND_HELP_KEYS[criterion.id]
    return _CRITERION_HELP_KEYS.get(criterion.id)


def _fmt_criterion_value(criterion: ResolvedCriterion, value: object) -> str:
    """Format a top-list raw value using the shared metric formatter when available."""

    metric_text = metric_value_text(criterion.id, value)
    if metric_text is not None:
        return metric_text
    return _fmt_number(value, decimals=2)


def render_candidate_finder_page(
    data: CandidateFinderData,
    *,
    query: Mapping[str, Sequence[str]] | None = None,
    base_path: str = "/candidate-finder",
    refresh_status: OptionRefreshStatus | None = None,
    app_config: AppConfig | None = None,
    error_message: str | None = None,
) -> str:
    """Render the Candidate Finder workspace page."""

    query = query or {}
    spec = _screen_spec_from_query(query, data.criteria_config)
    screen = run_candidate_finder_screen(data, spec=spec)
    active_preset_id = _active_preset_id(query, data.criteria_config)
    # Manual-input saves redirect back here with ?saved=...; confirm with the same
    # wording the ticker page uses.
    saved_flash = _flash_message(_first(query, "saved"))
    saved_notice = notice("success", saved_flash) if saved_flash else ""
    # D6: a rejected gold-price scenario still renders this screen (computed without the
    # scenario); the danger notice explains why the request was refused.
    error_notice = notice("danger", escape(error_message)) if error_message else ""
    # D9 / GV-RD-FINAL-005: "Refresh all model data" posts from this screen and
    # redirects back with ?refresh=already-running. Render the same info notice
    # the Option Trading overview renders (wording duplicated verbatim from
    # overview_option_trading.py, where it lives inline -- no shared constant).
    refresh_notice = (
        notice("info", "A data refresh is already running; no new refresh was started.")
        if _first(query, "refresh") == "already-running"
        else ""
    )

    body = "\n".join(
        (
            "<section class=\"workspace-section\">",
            page_header(
                "Candidate Finder",
                lead_html=(
                    "<p class=\"lead\">Choose a lens, then decide whether to "
                    "scan every stock or only optionable names.</p>"
                ),
            ),
            error_notice,
            saved_notice,
            refresh_notice,
            render_model_state_banner(data.model_state_manifest),
            render_option_freshness_box(data.model_state_manifest, only_when_stale=True),
            render_option_refresh_control(
                refresh_status or OptionRefreshStatus(),
                return_to=base_path,
            ),
            _render_gold_scenario_control(data, query, base_path=base_path),
            _render_beta_window_control(data, query, base_path=base_path),
            _render_preset_bar(
                data,
                active_preset_id,
                query=query,
                base_path=base_path,
            ),
            _render_active_preset_description(data, active_preset_id),
            _render_warning_banner(screen.warnings),
            _render_summary_cards(screen),
            _render_builder(data, screen, query, base_path=base_path),
            _render_top_lists(screen, fundamentals_source=data.fundamentals_source, app_config=app_config),
            _render_ranking_tables(
                screen,
                app_config=app_config,
                fundamentals_source=data.fundamentals_source,
                fundamentals_provenance=data.fundamentals_provenance or {},
            ),
            "</section>",
        )
    )
    return _page_shell(
        "Candidate Finder - Golden Vector Workspace",
        body,
        active_nav="candidate_finder",
    )


def _screen_spec_from_query(
    query: Mapping[str, Sequence[str]],
    config: CandidateFinderConfig,
) -> dict[str, object]:
    custom = _first(query, "custom") == "1"
    spec: dict[str, object] = {}

    if not custom:
        preset_id = _valid_preset_id(_first(query, "preset"), config)
        spec["preset"] = preset_id

    options_side = _first(query, "options_side")
    if options_side:
        spec["options_side"] = options_side

    top_n = _first(query, "top_n")
    if top_n:
        spec["top_n"] = top_n

    selected_ids = [item.strip() for item in query.get("criteria", ()) if item.strip()]
    if custom or selected_ids:
        known_ids = {criterion.id for criterion in config.criteria}
        criteria: list[dict[str, object]] = []
        for criterion_id in selected_ids:
            if criterion_id not in known_ids:
                criteria.append({"id": criterion_id})
                continue
            raw_item: dict[str, object] = {"id": criterion_id}
            direction = _first(query, f"direction_{criterion_id}")
            weight = _first(query, f"weight_{criterion_id}")
            if direction:
                raw_item["direction"] = direction
            if weight:
                raw_item["weight"] = weight
            criteria.append(raw_item)
        spec["criteria"] = criteria

    return spec


def _render_preset_bar(
    data: CandidateFinderData,
    active_preset_id: str,
    *,
    query: Mapping[str, Sequence[str]],
    base_path: str,
) -> str:
    links: list[str] = []
    for preset in data.criteria_config.presets:
        href = _preset_href(
            base_path=base_path,
            preset_id=preset.id,
            query=query,
        )
        active = " is-active" if preset.id == active_preset_id else ""
        links.append(
            (
                f"<a class=\"candidate-preset{active}\" href=\"{escape(href, quote=True)}\">"
                f"{escape(preset.label)}</a>"
            )
        )
    return (
        "<div class=\"candidate-preset-bar\" aria-label=\"Candidate Finder presets\">"
        + "".join(links)
        + "</div>"
    )


def _preset_href(
    *,
    base_path: str,
    preset_id: str,
    query: Mapping[str, Sequence[str]],
) -> str:
    params: list[tuple[str, str]] = [("preset", preset_id)]
    gold_price = _first(query, "gold_price")
    if gold_price:
        params.append(("gold_price", gold_price))
    fundamentals_source = _first(query, "fundamentals_source")
    if fundamentals_source:
        params.append(("fundamentals_source", fundamentals_source))
    # Carry the gold-beta horizon so switching preset never silently reverts the screen from a
    # selected window back to the cross-window blend (the same state-loss class as gold_price).
    beta_window = _first(query, "beta_window")
    if beta_window:
        params.append(("beta_window", beta_window))
    return base_path + "?" + urlencode(params)


def _render_gold_scenario_control(
    data: CandidateFinderData,
    query: Mapping[str, Sequence[str]],
    *,
    base_path: str,
) -> str:
    current_value = (
        ""
        if data.scenario_requested_gold_price is None
        else f"{float(data.scenario_requested_gold_price):.0f}"
    )
    hidden = _hidden_query_inputs(query, exclude={"gold_price", "fundamentals_source"})
    reset_query = _query_without(query, {"gold_price"})
    reset_href = base_path + (f"?{reset_query}" if reset_query else "")
    yahoo_selected = " selected" if data.fundamentals_source == "yahoo" else ""
    our_selected = " selected" if data.fundamentals_source != "yahoo" else ""
    if data.scenario_active and data.scenario_requested_gold_price is None:
        status = (
            "Yahoo Fundamentals recalculates finance-dependent ranking at spot gold. "
            "Persisted model artifacts are unchanged."
        )
    elif data.scenario_active:
        status = (
            f"Scenario ranks gold-dependent fundamentals at ${data.gold_price_used:,.0f}/oz. "
            "Persisted model artifacts are unchanged."
        )
    elif data.scenario_requested_gold_price is not None and data.scenario_error:
        status = "Scenario failed; this page is showing the persisted spot-ranked screen."
    elif data.spot_gold_usd is not None:
        status = f"Current screen uses persisted spot gold at ${data.spot_gold_usd:,.0f}/oz."
    else:
        status = "Current screen uses the persisted model run."
    return f"""
<section class="panel candidate-gold-scenario-panel">
  <form method="get" action="{escape(base_path, quote=True)}" class="candidate-finder-form">
    {hidden}
    <div class="candidate-form-row">
      <label>
        Gold price for ranking
        <input type="number" name="gold_price" min="1" step="1" value="{escape(current_value)}">
      </label>
      <label>
        Financials source
        <select name="fundamentals_source">
          <option value="our"{our_selected}>Our View</option>
          <option value="yahoo"{yahoo_selected}>Yahoo Fundamentals</option>
        </select>
      </label>
      <button type="submit">Apply Gold Scenario</button>
      <a href="{escape(reset_href, quote=True)}">Reset gold price to spot</a>
    </div>
    <p class="hint">{escape(status)}</p>
  </form>
</section>
"""


def _render_beta_window_control(
    data: CandidateFinderData,
    query: Mapping[str, Sequence[str]],
    *,
    base_path: str,
) -> str:
    """Pick the gold-beta horizon the Gold-Sensitivity criteria screen on.

    Default is the cross-window blend (`*_core`, a weighted median of the scoring windows),
    so existing rankings never shift unless the user opts into a single window. Mirrors the
    gold-scenario GET form; preserves every other query param via hidden inputs.
    """
    current = data.beta_window or ""
    hidden = _hidden_query_inputs(query, exclude={"beta_window"})
    scoring_labels = " / ".join(WINDOW_LABELS[w] for w in SCORING_WINDOWS)
    blend_selected = " selected" if not current else ""
    options = [f'<option value=""{blend_selected}>Blend ({escape(scoring_labels)})</option>']
    for window in ALL_WINDOWS:
        selected = " selected" if current == window else ""
        options.append(
            f'<option value="{escape(window.lower())}"{selected}>'
            f"{escape(WINDOW_LABELS.get(window, window))}</option>"
        )
    if current:
        basis = (
            "Gold-Sensitivity criteria (Up beta / Down beta / Gold beta) rank on the "
            f"{escape(WINDOW_LABELS.get(current, current))} window. Other criteria are unchanged."
        )
    else:
        basis = (
            "Gold-Sensitivity criteria (Up beta / Down beta / Gold beta) rank on the "
            f"cross-window blend (weighted median of {escape(scoring_labels)}). "
            "Pick a single window to screen on that horizon instead."
        )
    return f"""
<section class="panel candidate-beta-window-panel">
  <form method="get" action="{escape(base_path, quote=True)}" class="candidate-finder-form">
    {hidden}
    <div class="candidate-form-row">
      <label>
        Gold beta horizon
        <select name="beta_window">{''.join(options)}</select>
      </label>
      <button type="submit">Apply Horizon</button>
    </div>
    <p class="hint">{basis}</p>
  </form>
</section>
"""


def _render_active_preset_description(
    data: CandidateFinderData,
    active_preset_id: str,
) -> str:
    if not active_preset_id:
        return ""
    for preset in data.criteria_config.presets:
        if preset.id == active_preset_id and preset.description:
            return f"<p class=\"hint candidate-preset-description\">{escape(preset.description)}</p>"
    return ""


def _render_warning_banner(warnings: Sequence[str]) -> str:
    if not warnings:
        return ""
    items = "".join(f"<li>{escape(warning)}</li>" for warning in warnings)
    return notice(
        "warning",
        "<strong>Review this screen before using it.</strong>"
        f"<ul class=\"candidate-warning-list\">{items}</ul>",
    )


def _render_summary_cards(screen: CandidateFinderScreen) -> str:
    eligible = sum(
        1
        for row in screen.ranking.rows
        if row.rank_eligible and row.score is not None
    )
    low_coverage = max(0, len(screen.ranking.rows) - eligible)
    selected = len(screen.ranking.selected_criteria)
    cards = "\n".join(
        (
            _metric_card("Universe", _side_label(screen.options_side)),
            _metric_card("Selected Criteria", str(selected)),
            _metric_card("Eligible Rows", str(eligible)),
            _metric_card("Low Coverage Rows", str(low_coverage)),
            _metric_card("Per-Criterion List Size", str(screen.top_n)),
        )
    )
    return f"<div class=\"metric-grid candidate-summary-grid\">{cards}</div>"


def _builder_form_controls(data: CandidateFinderData) -> set[str]:
    """Query parameters the Screen Builder form owns (and re-emits itself)."""

    controls = {"custom", "options_side", "top_n", "criteria"}
    for criterion in data.criteria_config.criteria:
        controls.add(f"direction_{criterion.id}")
        controls.add(f"weight_{criterion.id}")
    return controls


def _render_builder(
    data: CandidateFinderData,
    screen: CandidateFinderScreen,
    query: Mapping[str, Sequence[str]],
    *,
    base_path: str,
) -> str:
    selected_by_id = {
        criterion.id: criterion for criterion in screen.ranking.selected_criteria
    }
    options = "\n".join(
        _option_tag(value, label, value == screen.options_side)
        for value, label in (
            ("none", "All stocks"),
            ("either", "Only stocks with puts or calls"),
            ("puts", "Only stocks with puts"),
            ("calls", "Only stocks with calls"),
        )
    )
    groups = "\n".join(
        _render_builder_group(
            group_label,
            criteria,
            selected_by_id=selected_by_id,
            group_index=index,
        )
        for index, (group_label, criteria) in enumerate(
            _criteria_groups(data.criteria_config.criteria)
        )
    )
    active_custom = _first(query, "custom") == "1"
    custom_note = (
        "<p class=\"hint\">Custom criteria are active for this screen.</p>"
        if active_custom
        else ""
    )
    # Preserve query state the builder form does NOT own -- especially gold_price --
    # so applying criteria does not silently reset an active gold scenario.
    hidden = _hidden_query_inputs(query, exclude=_builder_form_controls(data))
    heading = section_heading(
        "Screen Builder",
        actions_html=(
            f"<a class=\"btn btn-tertiary\" href=\"{escape(base_path, quote=True)}\">Reset</a>"
        ),
    )
    return f"""
<section class="panel candidate-builder-panel">
  {heading}
  {custom_note}
  <form method="get" action="{escape(base_path, quote=True)}" class="candidate-finder-form">
    <input type="hidden" name="custom" value="1">
    {hidden}
    <div class="candidate-form-row">
      <label>
        Universe
        <select name="options_side">{options}</select>
      </label>
      <label>
        Top rows per criterion
        <input type="number" name="top_n" min="1" max="25" step="1" value="{screen.top_n}">
      </label>
      <button type="submit" class="btn btn-primary">Apply Screen</button>
    </div>
    <div class="candidate-criteria-groups">{groups}</div>
  </form>
</section>
"""


def _criteria_groups(
    criteria: Sequence[CandidateFinderCriterion],
) -> list[tuple[str, list[CandidateFinderCriterion]]]:
    grouped: dict[str, list[CandidateFinderCriterion]] = {}
    order: list[str] = []
    for criterion in criteria:
        label = str(criterion.group or "Other").strip() or "Other"
        if label not in grouped:
            grouped[label] = []
            order.append(label)
        grouped[label].append(criterion)
    return [(label, grouped[label]) for label in order]


def _render_builder_group(
    group_label: str,
    criteria: Sequence[CandidateFinderCriterion],
    *,
    selected_by_id: Mapping[str, ResolvedCriterion],
    group_index: int,
) -> str:
    selected_count = sum(1 for criterion in criteria if criterion.id in selected_by_id)
    open_attr = " open" if selected_count else ""
    summary_meta = (
        f"{selected_count}/{len(criteria)} selected"
        if selected_count
        else f"{len(criteria)} criteria"
    )
    rows = "\n".join(
        _render_builder_row(criterion, selected_by_id.get(criterion.id))
        for criterion in criteria
    )
    table_html = f"""<table class="candidate-criteria-table">
      <thead>
        <tr>
          <th scope="col">Use</th>
          <th scope="col">Criterion</th>
          <th scope="col">Direction</th>
          <th scope="col">Weight</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""
    # One shared, labelled, keyboard-reachable scroll region per criteria group
    # (GV-RD-FINAL-008); the group index keeps the id page-unique.
    region = table_region(
        table_html,
        region_id=f"candidate-builder-criteria-table-region-{group_index}",
        label=f"{group_label} screen criteria",
    )
    return f"""
<details class="candidate-criteria-group"{open_attr}>
  <summary>
    <span>{escape(group_label)}</span>
    <span class="hint">{escape(summary_meta)}</span>
  </summary>
  {region}
</details>
"""


def _render_builder_row(
    criterion: CandidateFinderCriterion,
    selected: ResolvedCriterion | None,
) -> str:
    checked = selected is not None
    direction = selected.direction if selected else criterion.default_direction
    weight = selected.weight if selected else 1.0
    direction_phrase = (
        "Higher values rank higher." if direction == "high_good"
        else "Lower values rank higher."
    )
    label_help = f"{criterion.description} {direction_phrase}"
    criterion_id = escape(criterion.id, quote=True)
    checkbox_label = escape(f"Use {criterion.label}", quote=True)
    direction_name = escape(f"direction_{criterion.id}", quote=True)
    weight_name = escape(f"weight_{criterion.id}", quote=True)
    return f"""
<tr>
  <td><input type="checkbox" name="criteria" value="{criterion_id}" aria-label="{checkbox_label}"{" checked" if checked else ""}></td>
  <td>{help_term(criterion.label, text=label_help)}</td>
  <td>
    <select name="{direction_name}">
      {_option_tag("high_good", "High values fit", direction == "high_good")}
      {_option_tag("low_good", "Low values fit", direction == "low_good")}
    </select>
  </td>
  <td><input type="number" name="{weight_name}" min="0" max="10" step="0.25" value="{_fmt_weight(weight)}"></td>
  <td>{escape(criterion.description)}</td>
</tr>
"""


def _render_top_lists(
    screen: CandidateFinderScreen,
    *,
    fundamentals_source: str,
    app_config: AppConfig | None = None,
) -> str:
    if not screen.ranking.selected_criteria:
        return ""
    cards = "\n".join(
        _render_top_list_card(
            criterion,
            screen.ranking.top_lists.get(criterion.id, ()),
            fundamentals_source=fundamentals_source,
            fundamentals_provenance=screen.data.fundamentals_provenance or {},
            app_config=app_config,
        )
        for criterion in screen.ranking.selected_criteria
    )
    return f"""
<section class="candidate-view-section">
  <h2>View 1: Top Rows By Criterion</h2>
  <div class="candidate-top-list-grid">{cards}</div>
</section>
"""


def _render_top_list_card(
    criterion: ResolvedCriterion,
    rows: Sequence[CriterionTopEntry],
    *,
    fundamentals_source: str,
    fundamentals_provenance: dict[tuple[str, str], str],
    app_config: AppConfig | None = None,
) -> str:
    body = "\n".join(
        f"""
<tr>
  <td>{_ticker_link(row.ticker, fundamentals_source=fundamentals_source, fundamentals_provenance=fundamentals_provenance)}</td>
  <td class="numeric">{_fmt_criterion_value(criterion, row.raw_value)}</td>
  <td class="numeric">{_fmt_number(row.percentile, decimals=1)}</td>
</tr>
"""
        for row in rows
    )
    if not body:
        body = "<tr><td colspan=\"3\">No rows found.</td></tr>"
    direction = "High" if criterion.direction == "high_good" else "Low"
    table = (
        "<table><thead>"
        f"<tr>{help_th('Ticker', key='ticker_symbol')}"
        f"{help_th('Value', key=_criterion_help_key(criterion), text=criterion.description, app_config=app_config)}"
        f"{help_th('Percentile', key='candidate_finder_top_list_percentile')}</tr>"
        f"</thead><tbody>{body}</tbody></table>"
    )
    region = table_region(
        table,
        region_id=f"top-list-{criterion.id}-region",
        label=f"{criterion.label} top rows",
    )
    return f"""
<article class="nested-panel candidate-top-list-card">
  <h3>{escape(criterion.label)}</h3>
  <p class="hint">{escape(criterion.description)} {direction} values rank higher. Weight {_fmt_weight(criterion.weight)}.</p>
  {region}
</article>
"""


def _render_ranking_tables(
    screen: CandidateFinderScreen,
    *,
    app_config: AppConfig | None = None,
    fundamentals_source: str,
    fundamentals_provenance: dict[tuple[str, str], str],
) -> str:
    eligible = [row for row in screen.ranking.rows if _is_ranked(row)]
    low_coverage = [row for row in screen.ranking.rows if not _is_ranked(row)]
    return f"""
<section class="candidate-view-section">
  <h2>View 2: Fit Ranking</h2>
  {_render_score_table("Eligible Ranking", eligible, screen.ranking.selected_criteria, "candidate-eligible-ranking", app_config=app_config, fundamentals_source=fundamentals_source, fundamentals_provenance=fundamentals_provenance)}
  {_render_score_table("Low-Coverage Rows", low_coverage, screen.ranking.selected_criteria, "candidate-low-coverage-ranking", app_config=app_config, fundamentals_source=fundamentals_source, fundamentals_provenance=fundamentals_provenance)}
</section>
"""


def _render_score_table(
    title: str,
    rows: Sequence[CandidateScore],
    criteria: Sequence[ResolvedCriterion],
    table_id: str,
    *,
    app_config: AppConfig | None = None,
    fundamentals_source: str,
    fundamentals_provenance: dict[tuple[str, str], str],
) -> str:
    # Each criterion column explains its own metric (rich registry help), not a generic
    # "percentile" line; falls back to the criterion's config description if unmapped.
    criterion_headers = "".join(
        help_th(
            criterion.label,
            key=_criterion_help_key(criterion),
            text=criterion.description,
            app_config=app_config,
            col_name=f"criterion_{criterion.id}",
            sort_numeric=True,
        )
        for criterion in criteria
    )
    body_rows: list[str] = []
    for row in rows:
        criterion_cells = "".join(
            (
                _fmt_numeric_td(row.percentiles.get(criterion.id), decimals=1)
            )
            for criterion in criteria
        )
        body_rows.append(
            f"""
<tr>
  <td>{_ticker_link(row.ticker, fundamentals_source=fundamentals_source, fundamentals_provenance=fundamentals_provenance)}</td>
  {_fmt_numeric_td(row.score, decimals=2)}
  {_coverage_td(row)}
  {_fmt_numeric_td(row.top_n_tally, decimals=0)}
  {criterion_cells}
  <td>{escape(_coverage_status(row))}</td>
</tr>
"""
        )
    if not body_rows:
        colspan = 5 + len(criteria)
        body = f"<tr><td colspan=\"{colspan}\">No rows found.</td></tr>"
    else:
        body = "\n".join(body_rows)
    table_class = (
        "js-datatable candidate-ranking-table"
        if body_rows
        else "candidate-ranking-table"
    )
    table = f"""<table id="{escape(table_id, quote=True)}" class="{table_class}">
      <thead>
        <tr>
          {help_th("Ticker", key="ticker_symbol", app_config=app_config, col_name="ticker")}
          {help_th("Fit Score", key="candidate_finder_fit_score", app_config=app_config, col_name="score", sort_numeric=True)}
          {help_th("Coverage", key="candidate_finder_coverage", app_config=app_config, col_name="coverage", sort_numeric=True)}
          {help_th("Top-N Hits", key="candidate_finder_top_n_hits", app_config=app_config, col_name="top_n_hits", sort_numeric=True)}
          {criterion_headers}
          {help_th("Status", key="candidate_finder_status", app_config=app_config, col_name="status")}
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>"""
    region = table_region(table, region_id=f"{table_id}-region", label=title)
    return f"""
<section class="nested-panel candidate-ranking-panel">
  <h3>{escape(title)}</h3>
  {region}
</section>
"""


def _ticker_link(
    ticker: str,
    *,
    fundamentals_source: str,
    fundamentals_provenance: dict[tuple[str, str], str],
) -> str:
    clean = escape(ticker)
    href = build_page_url(
        f"/ticker/{quote(str(ticker), safe='')}",
        {"lens": "option-trading"},
        set_params=(
            {"fundamentals_source": "yahoo"}
            if fundamentals_source == "yahoo"
            else {}
        ),
    )
    href = f"{href}#option-trading"
    icon = (
        ticker_provenance_icon(ticker, fundamentals_provenance)
        if fundamentals_source == "yahoo"
        else ""
    )
    return f"<a href=\"{escape(href, quote=True)}\">{clean}</a>{icon}"


def _option_tag(value: str, label: str, selected: bool) -> str:
    selected_attr = " selected" if selected else ""
    return (
        f"<option value=\"{escape(value, quote=True)}\"{selected_attr}>"
        f"{escape(label)}</option>"
    )


def _side_label(side: str) -> str:
    return {
        "puts": "Only stocks with puts",
        "calls": "Only stocks with calls",
        "either": "Only stocks with puts or calls",
        "none": "All stocks",
    }.get(side, side)


def _coverage_status(row: CandidateScore) -> str:
    if _is_ranked(row):
        return "Eligible"
    if row.score is None:
        return "No score"
    return "Low coverage"


def _is_ranked(row: CandidateScore) -> bool:
    return row.rank_eligible and row.score is not None


def _coverage_td(row: CandidateScore) -> str:
    value = f"{row.criteria_fraction:.6f}"
    display = f"{row.present_criteria_count}/{row.selected_criteria_count}"
    return f"<td data-order=\"{escape(value, quote=True)}\">{escape(display)}</td>"


def _active_preset_id(
    query: Mapping[str, Sequence[str]],
    config: CandidateFinderConfig,
) -> str:
    if _first(query, "custom") == "1":
        return ""
    return _valid_preset_id(_first(query, "preset"), config)


def _valid_preset_id(raw_preset_id: str, config: CandidateFinderConfig) -> str:
    raw_preset_id = str(raw_preset_id or "").strip().lower()
    raw_preset_id = _PRESET_ALIASES.get(raw_preset_id, raw_preset_id)
    preset_ids = {preset.id for preset in config.presets}
    if raw_preset_id in preset_ids:
        return raw_preset_id
    if _DEFAULT_PRESET_ID in preset_ids:
        return _DEFAULT_PRESET_ID
    if config.presets:
        return config.presets[0].id
    return ""


def _first(query: Mapping[str, Sequence[str]], key: str) -> str:
    values = query.get(key)
    if not values:
        return ""
    return str(values[0]).strip()


def _hidden_query_inputs(
    query: Mapping[str, Sequence[str]],
    *,
    exclude: set[str],
) -> str:
    fields: list[str] = []
    for key, values in query.items():
        if key in exclude:
            continue
        for value in values:
            fields.append(
                f'<input type="hidden" name="{escape(str(key), quote=True)}" '
                f'value="{escape(str(value), quote=True)}">'
            )
    return "\n".join(fields)


def _query_without(query: Mapping[str, Sequence[str]], exclude: set[str]) -> str:
    params: list[tuple[str, str]] = []
    for key, values in query.items():
        if key in exclude:
            continue
        for value in values:
            params.append((str(key), str(value)))
    return urlencode(params)


def _fmt_weight(value: float) -> str:
    return f"{value:g}"
