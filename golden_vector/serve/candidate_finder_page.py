"""Workspace UI for the Candidate Finder screen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from urllib.parse import quote, urlencode

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
from golden_vector.serve.format_helpers import _fmt_number, _fmt_numeric_td, _metric_card
from golden_vector.serve.fundamentals_provenance import ticker_provenance_icon
from golden_vector.serve.model_state_banner import (
    render_model_state_banner,
    render_option_freshness_box,
)
from golden_vector.serve.option_refresh import (
    OptionRefreshStatus,
    render_option_refresh_control,
)
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.url_helpers import build_page_url

_DEFAULT_PRESET_ID = "bull"
_PRESET_ALIASES = {
    "bearish_put": "bear",
    "bullish_call": "bull",
    "strong_corporate_finance": "bull",
}


def render_candidate_finder_page(
    data: CandidateFinderData,
    *,
    query: Mapping[str, Sequence[str]] | None = None,
    base_path: str = "/candidate-finder",
    refresh_status: OptionRefreshStatus | None = None,
    app_config: AppConfig | None = None,
) -> str:
    """Render the Candidate Finder workspace page."""

    query = query or {}
    spec = _screen_spec_from_query(query, data.criteria_config)
    screen = run_candidate_finder_screen(data, spec=spec)
    active_preset_id = _active_preset_id(query, data.criteria_config)

    body = "\n".join(
        (
            "<section class=\"workspace-section\">",
            "<h1>Candidate Finder</h1>",
            "<p class=\"lead\">Choose a lens, then decide whether to scan every stock or only optionable names.</p>",
            render_model_state_banner(data.model_state_manifest),
            render_option_freshness_box(data.model_state_manifest, only_when_stale=True),
            render_option_refresh_control(
                refresh_status or OptionRefreshStatus(),
                return_to=base_path,
            ),
            _render_gold_scenario_control(data, query, base_path=base_path),
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
            _render_top_lists(screen, fundamentals_source=data.fundamentals_source),
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
    return (
        "<div class=\"flash flash-warning\">"
        "<strong>Review this screen before using it.</strong>"
        f"<ul class=\"candidate-warning-list\">{items}</ul>"
        "</div>"
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
        )
        for group_label, criteria in _criteria_groups(data.criteria_config.criteria)
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
    return f"""
<section class="panel candidate-builder-panel">
  <div class="candidate-panel-heading">
    <h2>Screen Builder</h2>
    <a href="{escape(base_path, quote=True)}">Reset</a>
  </div>
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
      <button type="submit">Apply Screen</button>
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
    return f"""
<details class="candidate-criteria-group"{open_attr}>
  <summary>
    <span>{escape(group_label)}</span>
    <span class="hint">{escape(summary_meta)}</span>
  </summary>
  <div class="table-scroll">
    <table class="candidate-criteria-table">
      <thead>
        <tr>
          <th>Use</th>
          <th>Criterion</th>
          <th>Direction</th>
          <th>Weight</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
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
) -> str:
    if not screen.ranking.selected_criteria:
        return ""
    cards = "\n".join(
        _render_top_list_card(
            criterion,
            screen.ranking.top_lists.get(criterion.id, ()),
            fundamentals_source=fundamentals_source,
            fundamentals_provenance=screen.data.fundamentals_provenance or {},
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
) -> str:
    body = "\n".join(
        f"""
<tr>
  <td>{_ticker_link(row.ticker, fundamentals_source=fundamentals_source, fundamentals_provenance=fundamentals_provenance)}</td>
  <td class="numeric">{_fmt_number(row.raw_value, decimals=2)}</td>
  <td class="numeric">{_fmt_number(row.percentile, decimals=1)}</td>
</tr>
"""
        for row in rows
    )
    if not body:
        body = "<tr><td colspan=\"3\">No rows found.</td></tr>"
    direction = "High" if criterion.direction == "high_good" else "Low"
    return f"""
<article class="nested-panel candidate-top-list-card">
  <h3>{escape(criterion.label)}</h3>
  <p class="hint">{escape(criterion.description)} {direction} values rank higher. Weight {_fmt_weight(criterion.weight)}.</p>
  <table>
    <thead>
      <tr>{help_th("Ticker", key="ticker_symbol")}{help_th("Value", key="candidate_finder_top_list_value")}{help_th("Percentile", key="candidate_finder_top_list_percentile")}</tr>
    </thead>
    <tbody>{body}</tbody>
  </table>
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
    criterion_headers = "".join(
        help_th(
            criterion.label,
            key="candidate_finder_criterion_percentile",
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
    return f"""
<section class="nested-panel candidate-ranking-panel">
  <h3>{escape(title)}</h3>
  <div class="table-scroll">
    <table id="{escape(table_id, quote=True)}" class="{table_class}">
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
    </table>
  </div>
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
