"""M3b: corporate finance section, gold dial payload, and safe JSON embedding.

Everything here is fixture-driven — no test reads a real ``data/`` artifact.

**Recorded contract gap** (see the lane notes; not worked around by computing
anything in serve): there is no EV/EBITDA screening check at all (no threshold,
no code, no column), so no EV/EBITDA sentence can exist.

The forward-P/E gap is CLOSED. ``screening/verdicts.py`` now persists
``fundamental_check_fail_codes`` (+ ``_official``), so ``FORWARD_PE_FAIL`` is a
real machine-readable code and the notice renders it through the same registry
as the layer-1 codes. The column is absent on artifacts built before that
change, which must render silently rather than crash — locked below.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.ticker_page_state import TickerPageArtifactState
from golden_vector.contracts.ticker_page import (
    GOLD_RESPONSE_CONSTANT_COLUMNS,
    GOLD_RESPONSE_LINE_METRICS,
)
from golden_vector.contracts.tool_d import YAHOO_TOOL_D_REBUILD_REQUIRED_REASON
from golden_vector.serve.embed import embed_json_payload
from golden_vector.serve.fundamentals_provenance import FundamentalsStatementPeriod
from tests.test_chart_data_tables import assert_every_rug_strip_has_a_data_table
from golden_vector.serve.ticker_page import (
    GOLD_DIAL_PAYLOAD_ID,
    TickerPageData,
    render_corporate_finance_section,
    render_gold_dial_control,
)
from golden_vector.contracts.config_models import TickerPageDialConfig
from golden_vector.serve.ticker_page.corporate import _slider_value_attr, format_metric

PARITY_FIXTURE = Path(__file__).parent / "fixtures" / "gold_dial_parity.json"


def _app_config():
    return load_app_config(ProjectPaths.discover()).app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _gold_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "finance_source": "our",
        "line_slope_forward_revenue_musd": 5.9,
        "line_intercept_forward_revenue_musd": 0.0,
        "line_slope_forward_ebitda_musd": 5.723,
        "line_intercept_forward_ebitda_musd": -6962.0,
        "line_slope_forward_net_income_musd": 4.12056,
        "line_intercept_forward_net_income_musd": -6956.64,
        "line_slope_forward_eps": 0.003911,
        "line_intercept_forward_eps": -6.602155,
        "line_slope_aisc_margin_est_musd": 5.9,
        "line_intercept_aisc_margin_est_musd": -9239.4,
        "market_cap_musd": 123866.0,
        "enterprise_value_musd": 124362.0,
        "net_debt_musd": 500.0,
        "interest_expense_musd": 200.0,
        "share_price_usd": 117.57,
        "aisc_usd_per_oz": 1566.0,
        "cash_cost_usd_per_oz": 1180.0,
        "production_oz": 5900000.0,
        "ebitda_ltm_musd": 11850.0,
        "spot_gold_usd": 4452.0,
        "spot_gold_date": "2026-08-11",
        "spot_forward_revenue_musd": 26266.8,
        "spot_forward_ebitda_musd": 18517.0,
        "spot_forward_net_income_musd": 11387.0,
        "spot_forward_eps": 10.81,
        "spot_aisc_margin_est_musd": 17027.4,
        "spot_margin_usd_per_oz": 2886.0,
        "spot_margin_pct": 0.648248,
        "spot_aisc_margin_yield": 0.137465,
        "spot_ev_ebitda": 6.716432,
        "spot_forward_pe": 10.876869,
        "spot_leverage_stressed": 0.027003,
        "spot_margin_basis": "aisc",
        "gold_response_status": "OK",
        "gold_response_reason": None,
        "linearity_max_residual": 0.01,
        "schema_version": 2,
        "source_run_id": "run-1",
        "snapshot_refresh_run_id": "run-1",
        "parent_refresh_id": "run-1",
        "config_hash": "hash",
    }
    row.update(overrides)
    return row


def _data(
    *rows: dict[str, object],
    artifact_status: str = "OK",
    artifact_reason: str | None = None,
    percentile_rows: list[dict[str, object]] | None = None,
) -> TickerPageData:
    frame = pd.DataFrame(list(rows) or [_gold_row()])
    blank = TickerPageArtifactState(status="OK", reason=None, frame=pd.DataFrame())
    percentiles = (
        TickerPageArtifactState(
            status="OK", reason=None, frame=pd.DataFrame(percentile_rows)
        )
        if percentile_rows
        else blank
    )
    return TickerPageData(
        gold_response=TickerPageArtifactState(
            status=artifact_status, reason=artifact_reason, frame=frame
        ),
        percentiles=percentiles,
        performance=blank,
        research_series=blank,
        fx_attribution=blank,
    )


def _tool_b_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "as_of_date": "2026-08-11",
        "gold_price_assumption": 4452.0,
        "aisc_usd_per_oz": 1566.0,
        "margin_pct": 0.648248,
        "aisc_margin_yield": 0.137465,
        "reserve_life_years": 22.0,
        "leverage": 0.042,
        "forward_pe": 10.876869,
        "layer1_fail_reasons": None,
        "layer1_status": "PASS",
        # Present-and-null is the modern artifact's healthy state; the
        # absent-column case is built by popping these (older artifacts).
        "fundamental_check_fail_codes": None,
        "fundamental_check_fail_codes_official": None,
        "financial_data_status": "OK",
        "snapshot_as_of_date": "2026-08-11",
        "snapshot_normalization_status": "OK",
        "fx_staleness_days": 0.0,
    }
    row.update(overrides)
    return row


def _tool_d_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "as_of_date": "2026-08-11",
        "breaks_even_at_gold_usd": 1566.0,
        "interest_cover_gold_usd": 1251.44,
        "debt_stress_gold_usd": 1245.62,
        "survival_distance_to_interest_cover_pct": 0.718903,
        "fragility_ebitda_pct_per_10pct_gold": 0.137598,
        "cost_curve_aisc_percentile": 31.111,
        "resilience_data_status": "OK",
    }
    row.update(overrides)
    return row


def _render(
    *,
    data: TickerPageData | None = None,
    finance_source: str = "our",
    tool_b_row: dict[str, object] | None = None,
    tool_d_row: dict[str, object] | None = None,
    tool_d_reason: str | None = None,
    statement_period: FundamentalsStatementPeriod | None = None,
    app_config=None,
) -> str:
    return render_corporate_finance_section(
        data if data is not None else _data(),
        ticker="NEM",
        finance_source=finance_source,
        tool_b_row=_tool_b_row() if tool_b_row is None else tool_b_row,
        tool_d_row=_tool_d_row() if tool_d_row is None else tool_d_row,
        tool_d_reason=tool_d_reason,
        statement_period=statement_period,
        app_config=app_config if app_config is not None else _app_config(),
    )


_RESILIENCE_TITLE = "Resilience — at what gold price does this break?"


def _resilience_html(html: str) -> str:
    """Just the Resilience disclosure, so section-scoped assertions cannot be
    satisfied (or defeated) by unrelated parts of the page."""
    start = html.index(_RESILIENCE_TITLE)
    return html[start : html.index("</details>", start)]


def _payload(html: str) -> dict[str, object]:
    marker = f'<script type="application/json" id="{GOLD_DIAL_PAYLOAD_ID}">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


# ---------------------------------------------------------------------------
# embed_json_payload — hostile strings must round-trip, never break out
# ---------------------------------------------------------------------------


def test_embed_json_payload_neutralises_hostile_strings():
    hostile = {
        "close": "</script><img src=x onerror=alert(1)>",
        "mixed_case": "</ScRiPt >",
        "comment": "<!-- <script> -->",
        "separators": "line\u2028paragraph\u2029end",
        "amp": "Tom & Jerry &amp; friends",
        "quotes": 'he said "hi" and \'bye\'',
        "cdata": "<![CDATA[x]]>",
    }
    html = embed_json_payload("hostile-payload", hostile)

    assert html.startswith('<script type="application/json" id="hostile-payload">')
    assert html.endswith("</script>")
    body = html[len('<script type="application/json" id="hostile-payload">') : -len("</script>")]

    # nothing that can terminate the block or start markup survives literally
    assert "</script" not in body.lower()
    assert "<" not in body and ">" not in body and "&" not in body
    assert "\u2028" not in body and "\u2029" not in body

    # ...and it is still exactly the same data
    assert json.loads(body) == hostile


def test_embed_json_payload_rejects_a_non_token_id():
    for bad in ("", "has space", '"><script>', "1leading-digit"):
        try:
            embed_json_payload(bad, {})
        except ValueError:
            continue
        raise AssertionError(f"payload_id {bad!r} should have been rejected")


def test_embed_json_payload_is_deterministic_and_rejects_nan():
    first = embed_json_payload("p", {"b": 1, "a": 2})
    assert first == embed_json_payload("p", {"a": 2, "b": 1})
    try:
        embed_json_payload("p", {"x": float("nan")})
    except ValueError:
        return
    raise AssertionError("NaN must not be embedded — JSON.parse would reject it")


# ---------------------------------------------------------------------------
# headline cards + scenario cells
# ---------------------------------------------------------------------------


def test_headline_cards_render_the_persisted_spot_values_verbatim():
    html = _render()
    # Each formatted string is the artifact column, formatted — never recomputed.
    assert "$2,886/oz" in html  # spot_margin_usd_per_oz
    assert "64.8%" in html  # spot_margin_pct
    assert "13.7%" in html  # spot_aisc_margin_yield
    assert "6.72×" in html  # spot_ev_ebitda
    assert "10.88×" in html  # spot_forward_pe
    assert "0.03×" in html  # spot_leverage_stressed
    assert 'id="corporate-headline"' in html
    assert html.count('<article class="data-card') == 6
    assert "metric-card-label" not in html
    assert "metric-card-value" not in html
    for metric in (
        "margin_usd_per_oz",
        "margin_pct",
        "aisc_margin_yield",
        "ev_ebitda",
        "forward_pe",
        "leverage_stressed",
    ):
        assert f'data-metric-card="{metric}"' in html


def test_corporate_finance_uses_one_shared_basis_strip_not_six_card_dates():
    html = _render()

    assert '<section class="panel" id="corporate-finance" data-scenario-active="0">' in html
    assert html.count('class="basis-strip"') == 1
    assert '<span class="basis-strip__value">Our View</span>' in html
    assert 'id="corporate-finance-gold-basis"' in html
    assert "Spot gold $4,452.00/oz as of 2026-08-11" in html
    assert html[: html.index("<details")].count("2026-08-11") == 1

    headline_start = html.index('id="corporate-headline"')
    headline = html[headline_start : html.index("<details", headline_start)]
    assert "2026-08-11" not in headline
    assert "fwd @ spot" not in headline


def test_yahoo_basis_strip_names_the_selected_source_without_fallback():
    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row=_tool_d_row(finance_source="yahoo"),
    )

    assert '<span class="basis-strip__value">Yahoo Fundamentals</span>' in html
    assert "Yahoo financials · Our View mining assumptions" in html


def test_first_view_status_keeps_the_yahoo_rollup_source_correct_in_both_modes():
    stale = _tool_b_row(financial_data_status="STALE")

    our_html = _render(tool_b_row=stale)
    assert 'aria-label="Corporate finance data status"' in our_html
    assert '<span class="status-item-label">Yahoo reference</span>' in our_html
    assert "STALE — Yahoo fundamentals are stale" in our_html
    assert "Our View data</span>" not in our_html

    yahoo_html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_b_row=stale,
        tool_d_row=_tool_d_row(finance_source="yahoo"),
    )
    assert '<span class="status-item-label">Yahoo data</span>' in yahoo_html
    assert "STALE — Yahoo fundamentals are stale" in yahoo_html


def test_first_view_status_explains_persisted_fx_degradation_plainly():
    html = _render(
        tool_b_row=_tool_b_row(
            snapshot_normalization_status="STALE_FX",
            fx_staleness_days=8,
        )
    )

    assert '<span class="status-item-label">Market data / FX</span>' in html
    assert "STALE_FX — the market snapshot uses stale FX (8 days)" in html


def test_missing_headline_value_carries_a_visible_reason():
    html = _render(data=_data(_gold_row(spot_forward_pe=None)))

    assert html.count("data-card--warning") == 1
    assert html.count("No valid spot value was published") == 1


def test_gold_driven_cards_and_rows_are_marked_and_fixed_rows_are_not():
    """The mock's defining rule: gold marks "this moves with the dial".

    Rendered with a healthy row, so the marking is proved against a page that
    also contains fixed rows — the control. A page where nothing were marked,
    or everything were, would fail here.
    """
    html = _render()

    # Every headline card is a dial-driven ratio, so all six carry the edge.
    assert html.count("data-card--gold-linked") == 6
    # Eleven dial-driven table rows: five persisted lines + six ratios.
    assert html.count('<tr class="moves-with-gold">') == 11
    assert html.count('class="gold-linked-marker"') == 11 + 1  # + the legend
    # The control: fixed rows (balance sheet, cost and scale) carry neither.
    fixed_start = html.index('id="corporate-balance-sheet"')
    fixed = html[fixed_start : html.index("</table>", fixed_start)]
    assert "moves-with-gold" not in fixed
    assert "gold-linked-marker" not in fixed
    assert '<tr><th scope="row">' in fixed
    # The legend names the symbol it is explaining.
    assert "Rows marked with a gold diamond" in html


def test_the_marker_is_derived_from_the_basis_so_the_two_cannot_disagree():
    """A row wearing the diamond while its Basis column says the value is fixed
    is exactly the twin-drift bug the derivation exists to prevent."""
    from golden_vector.serve.ticker_page.corporate import (
        GOLD_BASIS,
        _gold_marker,
        _gold_row_attrs,
    )

    assert _gold_marker(GOLD_BASIS) != ""
    assert _gold_row_attrs(GOLD_BASIS) == ' class="moves-with-gold"'
    assert _gold_marker(f"{GOLD_BASIS} · evaluated from the persisted line") != ""
    for fixed_basis in ("fixed", "reported", "as reported · not gold-driven"):
        assert _gold_marker(fixed_basis) == "", fixed_basis
        assert _gold_row_attrs(fixed_basis) == "", fixed_basis


def test_a_degraded_card_keeps_its_warning_edge_over_the_gold_marking():
    """Both classes apply; the cascade decides. Condition beats nature."""
    html = _render(data=_data(_gold_row(spot_forward_pe=None)))
    assert 'class="data-card data-card--gold-linked data-card--warning"' in html

    components = Path("golden_vector/serve/static/css/components.css").read_text(
        encoding="utf-8"
    )
    assert components.index(".data-card--gold-linked") < components.index(
        ".data-card--warning"
    ), "state modifiers must be declared after the gold marking to win the edge"


def test_every_scenario_cell_is_hidden_by_default_and_carries_its_metric():
    html = _render()
    for metric in (
        "forward_revenue_musd",
        "forward_ebitda_musd",
        "forward_net_income_musd",
        "forward_eps",
        "aisc_margin_est_musd",
        "margin_usd_per_oz",
        "margin_pct",
        "aisc_margin_yield",
        "ev_ebitda",
        "forward_pe",
        "leverage_stressed",
    ):
        cell = f'data-metric="{metric}" data-basis="scenario" hidden'
        assert cell in html, metric
    # the scenario column heads are hidden too — clean by default (Q43)
    assert 'data-scenario-head="1" hidden' in html
    # ...and no scenario cell ships pre-filled content
    assert 'data-basis="scenario" hidden></td>' in html


def test_line_metric_spot_cells_are_server_complete_from_persisted_values():
    """No-JS spot cells read the v2 persisted values, never client arithmetic."""
    html = _render()
    assert 'data-metric="forward_revenue_musd" data-basis="spot"' in html
    assert 'data-basis="spot">$26,267m</td>' in html
    assert 'data-basis="spot">$10.81</td>' in html
    assert "needs the gold dial (JavaScript)" not in html
    assert ">$0m<" not in html


def test_state_a_line_cells_do_not_claim_javascript_can_supply_the_value():
    reason = "the source-specific response pack is unavailable"
    html = _render(
        data=_data(
            _gold_row(
                gold_response_status="DEGRADED_INPUTS",
                gold_response_reason=reason,
            )
        )
    )

    assert "$26,267m" in html
    assert "needs the gold dial (JavaScript)" not in html
    assert reason in html


# ---------------------------------------------------------------------------
# failing-checks notice — persisted codes only, fixed at spot (D-4)
# ---------------------------------------------------------------------------


def test_failing_check_sentence_names_the_measured_value_and_your_threshold():
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_MARGIN_YIELD_FAIL",
            aisc_margin_yield=0.126,
            layer1_status="FAIL",
        )
    )
    assert "AISC margin yield 12.6% is below your 15.0% floor." in html
    # The fixture's screening run WAS judged at this spot, so the price is named
    # once — see the pair of tests below for both halves of that rule.
    assert "These screening checks fail at spot gold $4,452/oz:" in html
    assert "do not move with the dial" in html


def test_the_failing_check_notice_names_one_price_when_spot_is_the_screening_basis():
    """"…fail at spot gold · $4,468/oz · screening basis $4,468/oz" reads like a
    discrepancy between two numbers that are the same number. When the screening
    run was judged at the spot the page is showing, the price is stated once."""

    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_MARGIN_YIELD_FAIL",
            aisc_margin_yield=0.126,
            layer1_status="FAIL",
            gold_price_assumption=4452.0,
        )
    )
    assert "These screening checks fail at spot gold $4,452/oz:" in html
    assert "screening basis" not in html.split("</ul>")[0]
    assert "$4,452/oz · screening basis" not in html


def test_the_failing_check_notice_keeps_both_prices_when_they_differ():
    """The second price exists to disclose that the checks were judged at a
    DIFFERENT gold price than the one on screen. That case must still say so."""

    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_MARGIN_YIELD_FAIL",
            aisc_margin_yield=0.126,
            layer1_status="FAIL",
            gold_price_assumption=4000.0,
        )
    )
    assert (
        "These screening checks fail at spot gold · $4,452/oz · "
        "screening basis $4,000/oz:" in html
    )


def test_multiple_failing_codes_each_get_their_own_sentence():
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_FAIL;LEVERAGE_NON_POSITIVE_EBITDA;RESERVE_LIFE_FAIL",
            aisc_usd_per_oz=2100.0,
            reserve_life_years=4.0,
            layer1_status="FAIL",
        )
    )
    assert "AISC $2,100/oz is above your $1,850/oz cap." in html
    assert "Reserve life 4.0 years is below your 6.0 years floor." in html
    assert (
        "Trailing EBITDA is not positive, so net debt / EBITDA (LTM) cannot be measured."
        in html
    )


def test_healthy_control_row_renders_no_failing_check_notice():
    """The control: an otherwise identical row with no persisted FAIL code."""
    html = _render(tool_b_row=_tool_b_row(layer1_fail_reasons=None))
    assert "These screening checks fail" not in html
    assert 'id="corporate-failing-checks"' not in html
    # ...and an empty string must not be treated as a code either
    assert (
        "These screening checks fail"
        not in _render(tool_b_row=_tool_b_row(layer1_fail_reasons=""))
    )


def test_nullable_failure_code_cells_render_as_no_codes():
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons=pd.NA,
            fundamental_check_fail_codes=pd.NA,
        )
    )

    assert "These screening checks fail" not in html


def test_forward_pe_is_not_judged_without_a_persisted_code():
    """Serve must never compare forward P/E to a threshold on its own.

    A row that carries the VALUE but no failing code gets no sentence — the
    code is the only thing that may put a check on this page.
    """
    html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=10.9,
            layer1_fail_reasons=None,
            fundamental_check_fail_codes=None,
            layer1_status="PASS",
        )
    )
    assert "Forward P/E 10.9" not in html
    assert "is above your" not in html
    assert 'id="corporate-failing-checks"' not in html
    # the banned composite strings never appear either
    assert "fundamental_check_summary" not in html
    assert "screening_verdict" not in html


# ---------------------------------------------------------------------------
# M3f: the fundamental-check codes (forward P/E is the only NEW check)
# ---------------------------------------------------------------------------


def _forward_pe_cutoff() -> str:
    """The configured cut-off, formatted exactly as the page formats a ratio."""
    from golden_vector.serve.ticker_page.corporate import format_metric

    return format_metric(
        float(
            _app_config().screening_params.verdict_thresholds.strong_candidate_forward_pe_max
        ),
        "ratio",
    )


def test_forward_pe_fail_code_names_the_value_and_the_configured_cutoff():
    html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        )
    )
    assert f"Forward P/E 12.60× is above your {_forward_pe_cutoff()} cut-off." in html
    # ...and it sits under the same "at spot gold" header as its siblings.
    assert "These screening checks fail at spot gold" in html


def test_serve_reads_one_materialized_codes_column_and_never_the_official_one():
    """Source resolution happens ONCE, upstream (``materialize_tool_b_finance_source``
    via ``OPTIONAL_YAHOO_FINANCE_SOURCE_COLUMN_MAP``). Serve reads the single
    resolved column in either mode and never inspects an ``_official`` twin."""
    yahoo_data = _data(_gold_row(finance_source="yahoo"))
    # the materialized row: the resolved column carries the Yahoo codes
    html = _render(
        data=yahoo_data,
        finance_source="yahoo",
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            fundamental_check_fail_codes_official="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        ),
    )
    assert f"Forward P/E 12.60× is above your {_forward_pe_cutoff()} cut-off." in html

    # The control: only the RAW ``_official`` column says it failed. Serve must
    # stay silent — reading that column would be the per-source picker again.
    quiet = _render(
        data=yahoo_data,
        finance_source="yahoo",
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes=None,
            fundamental_check_fail_codes_official="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        ),
    )
    assert 'id="corporate-failing-checks"' not in quiet
    assert "is above your" not in quiet

    # ...and serve does not name the raw variant at all.
    source = Path("golden_vector/serve/ticker_page/corporate.py").read_text(
        encoding="utf-8"
    )
    assert "fundamental_check_fail_codes_official" not in source


def test_healthy_control_with_null_fundamental_codes_gets_no_sentence():
    """An otherwise-identical row whose codes column is present but null."""
    html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes=None,
            layer1_fail_reasons=None,
        )
    )
    assert 'id="corporate-failing-checks"' not in html
    assert "is above your" not in html


def test_absent_fundamental_codes_column_renders_without_a_sentence():
    """Pre-existing artifacts have no such column at all — that is not an error
    and must never be a guess."""
    row = _tool_b_row(forward_pe=12.6, layer1_fail_reasons=None)
    row.pop("fundamental_check_fail_codes", None)
    row.pop("fundamental_check_fail_codes_official", None)
    html = _render(tool_b_row=row)
    assert 'id="corporate-failing-checks"' not in html
    # the rest of the section still renders
    assert 'id="corporate-headline"' in html
    assert "Forward P/E" in html  # the card label, not a failing sentence
    assert "is above your" not in html


def test_non_positive_earnings_sentence_is_chosen_by_the_persisted_code():
    """A P/E built on non-positive earnings is not a multiple. WHICH failure it
    was is decided upstream and persisted as its own code — serve routes on the
    code and compares nothing, so the value in the row cannot change the words.
    """
    from golden_vector.screening.verdicts import FORWARD_PE_NON_POSITIVE_CODE

    expected = "Forward P/E is not meaningful here (forward earnings are not positive)."
    for value in (-4.2, 0.0):
        html = _render(
            tool_b_row=_tool_b_row(
                forward_pe=value,
                fundamental_check_fail_codes=FORWARD_PE_NON_POSITIVE_CODE,
                layer1_fail_reasons=None,
            )
        )
        assert expected in html, value
        assert "is above your" not in html, value

    # The control: the SAME non-positive value under the THRESHOLD code prints
    # the threshold sentence. Serve does not second-guess the producer.
    threshold_html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=-4.2,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        )
    )
    assert expected not in threshold_html
    assert f"is above your {_forward_pe_cutoff()} cut-off." in threshold_html


def test_a_fired_code_with_no_measured_value_says_so_instead_of_guessing():
    """The code fired but the column it names is absent. Serve states WHICH
    check failed and that the measurement is missing — it never invents a
    reason (the fabricated "earnings are not positive" claim) and never prints
    a comparison against a value it does not have."""
    missing = _tool_b_row(
        fundamental_check_fail_codes="FORWARD_PE_FAIL", layer1_fail_reasons=None
    )
    missing.pop("forward_pe", None)
    html = _render(tool_b_row=missing)
    assert (
        "Forward P/E failed this check, but the measured value is unavailable." in html
    )
    assert "forward earnings are not positive" not in html
    assert "is above your" not in html
    assert "n/a is above" not in html

    # the healthy control: the same code WITH the value prints the comparison
    present = _render(
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        )
    )
    assert "the measured value is unavailable" not in present


def test_fundamental_codes_never_double_report_a_layer1_check():
    """Both columns can name the same failure. It must be printed ONCE, by the
    layer-1 sentence that owns it."""
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_FAIL",
            aisc_usd_per_oz=2100.0,
            fundamental_check_fail_codes="AISC_FAIL;DATA_COMPLETE_FAIL;FORWARD_PE_FAIL",
            forward_pe=12.6,
            layer1_status="FAIL",
        )
    )
    assert html.count("AISC $2,100/oz is above your") == 1
    assert html.count("Forward P/E 12.60× is above your") == 1
    # DATA_COMPLETE_FAIL restates layer 1's precise MISSING_* codes -> not shown.
    assert "DATA_COMPLETE" not in html


def test_every_upstream_fundamental_check_is_accounted_for():
    """Guardrail: a NEW check added to ``screening/verdicts.py`` must either
    gain a sentence here or be explicitly recorded as a layer-1 duplicate —
    it can never be added upstream and then silently never render."""
    from golden_vector.screening.verdicts import (
        FORWARD_PE_NON_POSITIVE_CODE,
        FUNDAMENTAL_CHECK_ORDER,
        LAYER1_CHECK_LABELS,
    )
    from golden_vector.serve.ticker_page import corporate as C

    #: Codes whose CONCEPT layer 1 already reports, built from LAYER 1's OWN
    #: vocabulary (plus data-completeness, which layer 1 states per missing
    #: input). Building this from the render registry instead makes the check
    #: vacuous: that registry now holds fundamental-only codes too, so every
    #: code would satisfy it and a forgotten wiring would still pass.
    layer1_duplicates = {"DATA_COMPLETE_FAIL"} | {
        f"{key.upper()}_FAIL" for key in LAYER1_CHECK_LABELS
    }

    for key in FUNDAMENTAL_CHECK_ORDER:
        code = f"{key.upper()}_FAIL"
        assert (
            code in C._FUNDAMENTAL_ONLY_CODES or code in layer1_duplicates
        ), f"unhandled fundamental check code: {code}"

    # ...and the codes we DO consume really are new to this page.
    assert C._FUNDAMENTAL_ONLY_CODES == {
        "FORWARD_PE_FAIL",
        FORWARD_PE_NON_POSITIVE_CODE,
    }
    # every consumed code can actually produce a sentence
    for code in C._FUNDAMENTAL_ONLY_CODES:
        assert code in C._FAIL_SENTENCES or code in C._FAIL_STATEMENTS, code
    # ...and every threshold sentence can degrade honestly when its column is gone
    assert set(C._CHECK_NAMES) == set(C._FAIL_SENTENCES)


# ---------------------------------------------------------------------------
# groups: leverage naming, resilience, data quality
# ---------------------------------------------------------------------------


def test_trailing_and_stressed_leverage_are_two_distinct_labelled_rows():
    html = _render()
    assert "Stressed forward leverage" in html
    assert "Net debt / EBITDA (LTM)" in html
    assert "last twelve months (LTM)" in html
    # the trailing value comes from Tool B, the stressed one from the artifact
    assert "0.04×" in html  # tool_b leverage 0.042
    assert "0.03×" in html  # spot_leverage_stressed 0.027003


def test_ev_ebitda_and_forward_pe_help_text_explain_the_inversion():
    html = _render()
    assert "RISES as gold FALLS" in html
    assert "earnings shrink" in html or "forward earnings shrink" in html
    assert "more expensive, not cheaper" in html.replace("MORE", "more")
    # both metrics carry an explainer button
    assert 'data-help-title="EV / EBITDA (forward)"' in html
    assert 'data-help-title="Forward P/E"' in html


def test_resilience_renders_selected_yahoo_row_with_hybrid_basis():
    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row=_tool_d_row(
            finance_source="yahoo",
            interest_cover_gold_usd=987.0,
        ),
    )
    assert "Yahoo financials · Our View mining assumptions" in html
    assert "Interest-cover gold" in html
    assert "$987/oz" in html
    assert "$1,251/oz" not in html


def test_resilience_yahoo_degradation_stays_source_specific_and_explained():
    reason = "Yahoo interest expense is missing"
    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row=_tool_d_row(
            finance_source="yahoo",
            # W6: its OWN sentinel. Reusing the healthy Our View value (1251.44)
            # made a cross-source leak under the unavailable notice invisible.
            interest_cover_gold_usd=888.0,
            resilience_data_status="INSUFFICIENT_INTEREST_DATA",
            tool_d_explanation=reason,
        ),
    )

    assert "Yahoo financials · Our View mining assumptions" in html
    assert "Resilience is unavailable for the selected financial source" in html
    assert reason in html
    assert "resilience is computed on Our View inputs" not in html
    # the degraded row's own value renders; the healthy Our View sentinel must
    # NOT appear anywhere on the page
    assert "$888/oz" in html
    assert "$1,251/oz" not in html


def test_degraded_resilience_names_the_missing_inputs_in_plain_english():
    """W8/W9: the explanation used to WIN over the persisted missing-input list,
    so the user never learned which inputs were absent — and the appended period
    doubled up on a reason that already ended in one."""

    html = _render(
        tool_d_row=_tool_d_row(
            finance_source="our",
            interest_cover_gold_usd=888.0,
            resilience_data_status="INSUFFICIENT_INTEREST_DATA",
            tool_d_explanation="Not scored because the survival inputs are incomplete.",
            missing_inputs="interest_expense_musd;net_debt_musd;forward_ebitda_musd_at_g",
        ),
    )

    resilience = _resilience_html(html)
    assert "Missing: interest expense, net debt, forward EBITDA (at gold)." in resilience
    # the raw column tokens never reach the reader (the gold-dial JSON payload
    # legitimately carries them as data keys, so this is scoped to the section)
    for token in ("interest_expense_musd", "net_debt_musd", "forward_ebitda_musd_at_g"):
        assert token not in resilience
    # exactly one period ends the explanation sentence
    assert "incomplete.." not in html
    assert "are incomplete.</p>" in html


def test_degraded_resilience_falls_back_to_the_raw_token_it_cannot_name():
    """An unmapped token is shown as-is: an unexplained gap is worse than an
    ugly one, and silently dropping it would understate what is missing."""

    html = _render(
        tool_d_row=_tool_d_row(
            resilience_data_status="INSUFFICIENT_DATA",
            tool_d_explanation="Not scored because the survival inputs are incomplete.",
            missing_inputs="production_oz;brand_new_column",
        ),
    )

    assert "Missing: production, brand_new_column." in html


def test_resilience_refuses_a_row_labelled_for_the_other_source():
    """W5 tripwire: the basis label is derived from the REQUESTED source, so a
    row carrying the other source must render the unavailable path — never the
    wrong source's numbers under a confident basis line. Unreachable through
    current wiring (the route resolves the exact composite key first); this
    proves the renderer does not simply trust its caller."""

    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row=_tool_d_row(finance_source="our", interest_cover_gold_usd=1251.44),
    )

    assert (
        "the published resilience row is labelled Our View, not the selected "
        "Yahoo Fundamentals source" in html
    )
    # No basis line: it would describe the provenance of numbers that are being
    # refused. The healthy path below proves the label still renders where
    # there ARE numbers to attribute.
    assert "Yahoo financials · Our View mining assumptions" not in html
    assert "$1,251/oz" not in html
    assert "Interest-cover gold" not in html


def test_a_finance_source_alias_is_normalized_once_and_reaches_every_label():
    """Legacy surfaces still emit ``official``/``market`` for Yahoo. The section
    normalizes at its entry, so the row lookup (which keys on an EXACT
    finance_source match), the source label, the status-strip label and the
    resilience basis all resolve to Yahoo together. Before, the row lookup found
    nothing and the labels disagreed with each other."""

    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="official",
        tool_d_row=_tool_d_row(finance_source="yahoo"),
    )

    assert "Yahoo Fundamentals" in html  # the Financials basis label
    assert "Yahoo data" in html  # the status strip, not "Yahoo reference"
    assert "Yahoo financials · Our View mining assumptions" in html
    assert _payload(html)["finance_source"] == "yahoo"
    # ...and the gold-response row was actually found, so nothing degraded.
    assert "Spot gold unavailable" not in html
    assert "no gold-response row was published" not in html


def test_resilience_states_no_basis_above_an_empty_section():
    """A basis describes numbers. With no published row there are none, so
    "Yahoo financials · Our View mining assumptions" above "no data" claimed a
    provenance for data that does not exist."""

    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row={},
    )

    assert "No resilience row has been published for this ticker and source." in html
    assert "Yahoo financials · Our View mining assumptions" not in html
    assert "Our View financials · Our View mining assumptions" not in html


def test_resilience_still_labels_its_basis_when_it_has_numbers():
    """Healthy control for the two absence tests above — the basis line is
    removed from the empty branch only, never from the populated one."""

    html = _render()
    assert "Our View financials · Our View mining assumptions" in html
    assert "Operating breakeven gold" in html


def test_resilience_missing_legacy_yahoo_row_shows_contract_rebuild_reason():
    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row={},
        tool_d_reason=YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
    )

    assert YAHOO_TOOL_D_REBUILD_REQUIRED_REASON in html
    assert "Interest-cover gold" not in html


def test_resilience_renders_persisted_tool_d_values_in_our_view_mode():
    html = _render()
    assert "Operating breakeven gold" in html
    assert "$1,566/oz" in html
    assert "$1,251/oz" in html  # interest cover
    assert "71.9%" in html  # survival distance (a fraction column)
    assert "13.8%" in html  # EBITDA fragility
    assert "Resilience data status" in html


def test_data_quality_group_labels_every_basis():
    html = _render()
    assert "Data quality and sources" in html
    assert "Screening gold basis" in html
    assert "Margin cost basis" in html
    assert "Gold response artifact" in html
    assert "Our View mining assumption" in html
    # The run dates this table has always carried are untouched.
    assert "Tool B as of" in html
    assert "Market snapshot as of" in html


def test_data_quality_states_the_yahoo_statement_period_beside_the_run_dates():
    """The table used to show run dates only — all "today" — while the source
    tooltip already knew the statements ended 2025-12-31. A reader with only run
    dates has no way to tell how old the financials themselves are."""

    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row=_tool_d_row(finance_source="yahoo"),
        statement_period=FundamentalsStatementPeriod(
            period_ends=("2025-12-31",),
            fetched_at=("2026-08-12T06:15:00Z",),
        ),
    )

    assert "Statement period end" in html
    assert "2025-12-31" in html
    assert "the period the Yahoo financials describe — not a run date" in html
    assert "Yahoo fundamentals fetched" in html
    assert "2026-08-12T06:15:00Z" in html
    # and the run-date rows are unchanged
    assert "Tool B as of" in html
    assert "Market snapshot as of" in html


def test_data_quality_reports_disagreeing_statement_periods_rather_than_picking_one():
    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row=_tool_d_row(finance_source="yahoo"),
        statement_period=FundamentalsStatementPeriod(
            period_ends=("2025-12-31", "2025-09-30"), fetched_at=()
        ),
    )

    assert "2025-12-31; 2025-09-30" in html
    assert "Yahoo fundamentals fetched" in html
    assert "not published" in html


def test_data_quality_never_stands_a_run_date_in_for_a_missing_statement_period():
    """No provenance published for this ticker: the row says so. Falling back to
    a Tool B run date would be presenting a run date as a statement period."""

    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
        tool_d_row=_tool_d_row(finance_source="yahoo"),
        statement_period=None,
    )

    quality = html[html.index("Data quality and sources") :]
    start = quality.index("Statement period end")
    period_row = quality[start : quality.index("</tr>", start)]
    assert "not published" in period_row
    # ...and no run date was quietly substituted for the missing period.
    assert "2026-08-11" not in period_row
    assert "2026-08-12" not in period_row


def test_our_view_says_its_manual_inputs_carry_no_statement_period():
    html = _render()
    assert "Statement period" in html
    assert "entered by hand and carry no statement period" in html
    assert "Yahoo fundamentals fetched" not in html


# ---------------------------------------------------------------------------
# degraded states
# ---------------------------------------------------------------------------


def test_degraded_gold_response_row_disables_the_dial_with_its_persisted_reason():
    reason = "linearity residual 41.2 exceeded tolerance at $6,000"
    data = _data(
        _gold_row(gold_response_status="DEGRADED_NONLINEAR", gold_response_reason=reason)
    )
    html = _render(data=data)
    assert "The gold dial is disabled for NEM" in html
    assert reason in html
    # the persisted spot values that DO exist are still shown
    assert "$2,886/oz" in html
    payload = _payload(html)
    assert payload["enabled"] is False
    assert payload["disabled_reason"] == reason
    # no artifact means no scenario either, and the reason is the same one
    assert payload["scenario_enabled"] is False
    assert payload["scenario_reason"] == reason
    assert payload["gold_response_status"] == "DEGRADED_NONLINEAR"
    assert payload["gold_response_reason"] == reason
    assert 'data-basis="scenario"' not in html
    assert 'data-scenario-head="1"' not in html

    control = render_gold_dial_control(
        data, ticker="NEM", finance_source="our", app_config=_app_config()
    )
    assert "disabled>" in control
    assert reason in control


def test_missing_gold_response_row_is_reported_not_faked():
    data = _data(_gold_row(ticker="AEM"))
    html = _render(data=data)
    assert "The gold dial is disabled for NEM" in html
    assert "no gold-response row was published" in html
    assert "n/a" in html  # unavailable cells say so
    assert ">$0m<" not in html and ">0.00×<" not in html


def test_pending_artifact_renders_one_honest_degraded_notice():
    data = _data(
        artifact_status="PENDING_FIRST_PUBLISH",
        artifact_reason="the ticker-page stage has not published yet",
    )
    html = _render(data=data)
    assert "PENDING_FIRST_PUBLISH" in html
    assert "the ticker-page stage has not published yet" in html
    assert "nothing is estimated to fill the gap" in html
    assert _payload(html)["enabled"] is False


@pytest.mark.parametrize(
    "spot",
    [None, float("nan"), float("inf"), float("-inf")],
    ids=("missing", "nan", "positive-infinity", "negative-infinity"),
)
def test_non_finite_spot_is_one_honest_disabled_state(spot):
    """Missing/non-finite spot is State A and must always stay JSON-safe."""

    reason = "no finite spot gold price is published for this ticker and source"
    data = _data(_gold_row(spot_gold_usd=spot))

    control = render_gold_dial_control(
        data, ticker="NEM", finance_source="our", app_config=_app_config()
    )
    assert 'aria-describedby="gold-dial-spot gold-dial-reason" disabled>' in control
    assert reason in control
    assert 'aria-valuetext="spot gold unavailable"' in control

    html = _render(data=data)
    assert "The gold dial is disabled for NEM" in html
    assert reason in html
    assert "$inf" not in html and "-$inf" not in html
    assert '<th scope="row">Spot gold used</th><td class="spot-cell">n/a</td>' in html
    payload = _payload(html)  # Regression: +/-Infinity used to crash JSON embedding.
    assert payload["spot_gold_usd"] is None
    assert payload["enabled"] is False
    assert payload["disabled_reason"] == reason
    assert payload["scenario_enabled"] is False
    assert payload["scenario_reason"] == reason


# ---------------------------------------------------------------------------
# dial control + payload
# ---------------------------------------------------------------------------


def test_dial_control_takes_its_range_from_config_and_defaults_to_spot():
    app_config = _app_config()
    control = render_gold_dial_control(
        _data(), ticker="NEM", finance_source="our", app_config=app_config
    )
    dial = app_config.ticker_page.dial
    assert f'min="{dial.min_gold_usd:g}"' in control
    assert f'max="{dial.max_gold_usd:g}"' in control
    assert f'step="{dial.step_usd:g}"' in control
    assert 'value="4452"' in control  # the artifact's spot, not a config scenario
    assert 'aria-describedby="gold-dial-spot" disabled>' in control
    assert "$4,000" not in control  # never Tool B's configured default scenario
    assert '<output class="gold-dial-output"' in control
    assert 'id="gold-dial-reset"' in control
    assert 'class="control control--quiet" id="gold-dial-reset"' in control
    assert "button-like" not in control
    assert 'aria-live="polite"' in control
    assert '<span id="gold-dial-basis">spot</span> · range ' in control
    assert "2026-08-11" not in control


def test_compact_dial_fragment_uses_the_command_bar_label_without_duplication():
    control = render_gold_dial_control(
        _data(),
        ticker="NEM",
        finance_source="our",
        app_config=_app_config(),
        compact_label=True,
    )

    assert '<label class="gold-dial-label"' not in control
    assert 'aria-label="Gold price scenario"' in control
    assert 'class="gold-dial-help"' in control


def test_slider_value_is_step_aligned_while_the_payload_keeps_exact_spot():
    """A range control snaps ``value`` onto ``min + k*step`` before any script

    runs, so emitting the exact fractional spot ships a position the browser
    rewrites — and a client baseline that starts life in a false scenario
    (plan §4.3, D9). The EXACT spot still owns evaluation, display and
    provenance; only the control's own position is aligned."""
    data = _data(_gold_row(spot_gold_usd=4477.4))
    control = render_gold_dial_control(
        data, ticker="NEM", finance_source="our", app_config=_app_config()
    )

    assert 'step="1"' in control
    assert 'value="4477"' in control  # the position the control can actually hold
    assert 'value="4477.4"' not in control
    # ...while every human-readable basis keeps the true price, cents and all
    assert '<span id="gold-dial-basis">spot</span> · range ' in control
    assert "2026-08-11" not in control
    assert 'aria-valuetext="$4,477.40 per ounce, spot"' in control
    assert ">$4,477.40</output>" in control
    # Nothing to reset FROM at rest: rendered, disabled, out of the tab order.
    assert 'id="gold-dial-reset" disabled>' in control

    payload = _payload(_render(data=data))
    assert payload["spot_gold_usd"] == 4477.4


def test_a_spot_outside_the_configured_range_disables_the_dial_with_a_reason():
    """§4.3 State A: never silently clamp an out-of-range spot into a slider —

    a control pinned at a bound the price does not occupy would present every
    position as a scenario the model never anchored. The SCENARIO is withheld
    with one visible reason; the position still emits the bound the browser
    would hold, and the payload plus every human-readable basis keep the TRUE
    spot.

    The ARTIFACT is untouched by this: ``enabled`` stays True, because the
    published lines were verified at true spot and the client must still
    evaluate the five line-metric cells there. Blanking them would throw away
    five values the artifact stands behind — hence two separate flags."""
    dial = _app_config().ticker_page.dial
    for spot, bound in ((7000.0, dial.max_gold_usd), (1000.0, dial.min_gold_usd)):
        data = _data(_gold_row(spot_gold_usd=spot))
        control = render_gold_dial_control(
            data, ticker="NEM", finance_source="our", app_config=_app_config()
        )
        exact = format_metric(spot, "usd2")
        assert "is outside the configured dial range $2,000–$6,000" in control, spot
        # the disabled range names its own explanation and says so in its value
        assert 'aria-describedby="gold-dial-spot gold-dial-reason" disabled>' in control, spot
        assert 'id="gold-dial-reason"' in control, spot
        assert f'aria-valuetext="{exact} per ounce, spot — scenario unavailable"' in control, spot
        assert f'value="{bound:g}"' in control, spot
        assert f">{exact}</output>" in control, spot
        assert "2026-08-11" not in control, spot
        payload = _payload(_render(data=data))
        assert payload["spot_gold_usd"] == spot
        # artifact availability is NOT what failed here
        assert payload["enabled"] is True
        assert payload["disabled_reason"] is None
        assert payload["scenario_enabled"] is False
        assert "outside the configured dial range" in payload["scenario_reason"]
        # ...and the section says only the scenario is withheld
        section = _render(data=data)
        assert "The gold dial cannot run a scenario for NEM" in section
        assert "The values below are unaffected and stay at spot." in section
        assert "Spot values below are the published ones" not in section
        assert 'data-basis="scenario"' not in section
        assert 'data-scenario-head="1"' not in section

    # a spot exactly ON a bound is inside the range and keeps the dial live
    data = _data(_gold_row(spot_gold_usd=float(dial.max_gold_usd)))
    control = render_gold_dial_control(
        data, ticker="NEM", finance_source="our", app_config=_app_config()
    )
    assert "outside the configured dial range" not in control
    live = _payload(_render(data=data))
    assert live["enabled"] is True
    assert live["scenario_enabled"] is True
    assert live["scenario_reason"] == ""


def test_slider_value_attr_lands_on_the_grid_for_every_step_shape():
    """The grid math lives ONCE in ``common.numeric.align_to_step``; this

    formatter emits its result at the step's own decimal precision, so exotic
    steps (25, 0.25) align exactly instead of falling back to the raw spot."""
    cases = (
        (1.0, 4477.4, "4477"),
        (10.0, 4477.4, "4480"),
        (0.1, 4477.44, "4477.4"),
        (25.0, 4477.4, "4475"),
        (0.25, 4477.4, "4477.50"),
    )
    for step, spot, expected in cases:
        cfg = TickerPageDialConfig(min_gold_usd=2000.0, max_gold_usd=6000.0, step_usd=step)
        assert _slider_value_attr(spot, cfg) == expected, (step, spot)
    fractional_origin = TickerPageDialConfig(
        min_gold_usd=2000.5,
        max_gold_usd=6000.5,
        step_usd=1.0,
        probe_gold_usd=[2000.5, 4000.5, 6000.5],
    )
    assert _slider_value_attr(4477.4, fractional_origin) == "4477.5"
    uneven_range = TickerPageDialConfig(
        min_gold_usd=0.0,
        max_gold_usd=10.0,
        step_usd=6.0,
        probe_gold_usd=[0.0, 5.0, 10.0],
    )
    assert _slider_value_attr(9.0, uneven_range) == "6"
    assert _slider_value_attr(10.0, uneven_range) == "6"
    assert _slider_value_attr(None, TickerPageDialConfig()) == ""


def test_headline_cards_show_the_real_value_with_the_scenario_beneath_it():
    """The card contract, per the mock and Victor 2026-08-14: BOTH numbers.

    The old contract (plan §4.4) hid the spot value whenever a scenario was
    active, so a card never stacked two *unlabelled* numbers. Victor asked to
    see the actual and the scenario together, which the mock shows as the real
    value on top with the scenario under it. The objection is answered by
    labelling rather than by hiding: the scenario slot is marked
    ``data-headline-scenario``, which is what makes gold-dial.js append the
    "at $X" price it assumes. Drop that marker and the card really would show
    two bare numbers, so it is asserted here.
    """

    html = _render()
    for metric in (
        "margin_usd_per_oz",
        "margin_pct",
        "aisc_margin_yield",
        "ev_ebitda",
        "forward_pe",
        "leverage_stressed",
    ):
        # a BLOCK beneath the value, marked so the price suffix is written
        assert (
            f'data-metric="{metric}" data-basis="scenario"'
            ' data-headline-scenario="1" hidden></p>'
        ) in html, metric
    assert html.count('class="spot-cell" data-headline-spot="1"') == 6
    # the marker exists ONLY on the cards — expanded tables keep both columns
    assert html.count("data-headline-spot") == 6
    assert html.count('data-headline-scenario="1"') == 6


def test_dial_payload_carries_the_artifact_row_and_nothing_computed():
    frame = pd.DataFrame([_gold_row()])
    html = _render(data=_data())
    payload = _payload(html)

    row = frame.iloc[0]
    for metric in GOLD_RESPONSE_LINE_METRICS:
        assert payload["lines"][metric]["slope"] == row[f"line_slope_{metric}"]
        assert payload["lines"][metric]["intercept"] == row[f"line_intercept_{metric}"]
    for column in GOLD_RESPONSE_CONSTANT_COLUMNS:
        assert payload["constants"][column] == row[column]
    assert payload["spot_gold_usd"] == 4452.0
    assert payload["spot_gold_date"] == "2026-08-11"
    assert payload["margin_basis"] == "aisc"
    assert payload["enabled"] is True
    assert payload["scenario_enabled"] is True
    assert payload["scenario_reason"] == ""

    assert set(payload["lines"]) == set(GOLD_RESPONSE_LINE_METRICS)
    assert set(payload["constants"]) == set(GOLD_RESPONSE_CONSTANT_COLUMNS)
    assert payload["gold_response_status"] == "OK"
    assert payload["gold_response_reason"] is None
    assert set(payload) == {
        "ticker",
        "finance_source",
        "gold_response_status",
        "gold_response_reason",
        "enabled",
        "disabled_reason",
        "scenario_enabled",
        "scenario_reason",
        "spot_gold_usd",
        "spot_gold_date",
        "margin_basis",
        "lines",
        "constants",
        "spot_display",
        "formats",
    }


# ---------------------------------------------------------------------------
# backend/JS parity: the formula contract the real-JS gate verifies at M4
# ---------------------------------------------------------------------------

_PROBE_GOLDS = (2000.0, 4000.0, 6000.0)


def _mirror_line(payload: dict, metric: str, gold: float):
    line = payload["lines"].get(metric)
    if not line or line["slope"] is None or line["intercept"] is None:
        return None, "no published line here"
    return line["slope"] * gold + line["intercept"], None


def _mirror_ratio(numerator, denominator, guard_reason):
    if numerator is None or denominator is None:
        return None, "input unavailable here"
    if not denominator > 0:
        return None, guard_reason
    return numerator / denominator, None


def mirror_evaluate(payload: dict, metric: str, gold: float):
    """Python mirror of gold-dial.js ``evaluate`` — same guards, same order.

    The guards are the ones in ``screening/layer1.py`` (market cap > 0) and
    ``screening/layer2.py`` (forward EBITDA > 0, forward EPS > 0).
    """
    if metric in payload["lines"]:
        return _mirror_line(payload, metric, gold)
    constants = payload["constants"]
    if metric == "margin_usd_per_oz":
        column = {"aisc": "aisc_usd_per_oz", "cash_cost": "cash_cost_usd_per_oz"}.get(
            payload["margin_basis"]
        )
        if column is None:
            return None, "margin cost basis unavailable"
        cost = constants.get(column)
        if cost is None:
            return None, "cost basis unavailable here"
        return gold - cost, None
    if metric == "margin_pct":
        margin, reason = mirror_evaluate(payload, "margin_usd_per_oz", gold)
        if margin is None:
            return None, reason
        return _mirror_ratio(margin, gold, "Not meaningful — gold price ≤ 0")
    if metric == "aisc_margin_yield":
        value, reason = mirror_evaluate(payload, "aisc_margin_est_musd", gold)
        if value is None:
            return None, reason
        return _mirror_ratio(
            value,
            constants.get("market_cap_musd"),
            "Not meaningful — market cap ≤ 0",
        )
    if metric == "ev_ebitda":
        ebitda, reason = mirror_evaluate(payload, "forward_ebitda_musd", gold)
        if ebitda is None:
            return None, reason
        return _mirror_ratio(
            constants.get("enterprise_value_musd"),
            ebitda,
            "Not meaningful — EBITDA ≤ 0",
        )
    if metric == "forward_pe":
        eps, reason = mirror_evaluate(payload, "forward_eps", gold)
        if eps is None:
            return None, reason
        return _mirror_ratio(
            constants.get("share_price_usd"),
            eps,
            "Not meaningful — EPS ≤ 0",
        )
    if metric == "leverage_stressed":
        ebitda, reason = mirror_evaluate(payload, "forward_ebitda_musd", gold)
        if ebitda is None:
            return None, reason
        return _mirror_ratio(
            constants.get("net_debt_musd"),
            ebitda,
            "Not meaningful — EBITDA ≤ 0",
        )
    raise AssertionError(f"unknown metric {metric}")


def _parity_expectations(payload: dict) -> dict:
    from golden_vector.serve.ticker_page.corporate import METRIC_FORMATS, format_metric

    out: dict[str, dict[str, dict[str, object]]] = {}
    for gold in _PROBE_GOLDS:
        per_gold: dict[str, dict[str, object]] = {}
        for metric, unit in METRIC_FORMATS.items():
            value, reason = mirror_evaluate(payload, metric, gold)
            per_gold[metric] = {
                "value": None if value is None else round(value, 9),
                "reason": reason,
                "formatted": reason if value is None else format_metric(value, unit),
            }
        out[f"{gold:.0f}"] = per_gold
    return out


def _stressed_gold_row() -> dict[str, object]:
    """A high-cost miner whose forward EBITDA and EPS go NEGATIVE at $2,000 and

    recover by $6,000 — the exclusion subject plus its own healthy control."""
    return _gold_row(
        ticker="NEM",
        line_slope_forward_ebitda_musd=1.0,
        line_intercept_forward_ebitda_musd=-5000.0,
        line_slope_forward_eps=0.001,
        line_intercept_forward_eps=-3.0,
    )


def _parity_cases() -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for name, row in (("healthy", _gold_row()), ("stressed", _stressed_gold_row())):
        payload = _payload(_render(data=_data(row)))
        cases[name] = {"payload": payload, "expected": _parity_expectations(payload)}
    return cases


def test_gold_dial_backend_parity_fixture_pins_the_formula_contract():
    """The formula contract the real-browser M4 gate re-verifies against the

    actual JS. If gold-dial.js and this mirror ever disagree, the fixture is
    the record of which one changed."""
    cases = _parity_cases()

    if os.environ.get("GV_WRITE_PARITY_FIXTURE") == "1":
        PARITY_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        PARITY_FIXTURE.write_text(
            json.dumps({"cases": cases}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    assert PARITY_FIXTURE.exists(), (
        "tests/fixtures/gold_dial_parity.json is missing — regenerate deliberately "
        "with GV_WRITE_PARITY_FIXTURE=1"
    )
    stored = json.loads(PARITY_FIXTURE.read_text(encoding="utf-8"))
    assert stored["cases"] == cases, (
        "the embedded payload or the client formula chain drifted from the pinned "
        "backend/JS parity fixture"
    )


def test_ratio_guards_mirror_layer1_and_layer2_exactly():
    """Exclusion subject + healthy control, in the same fixture.

    Guards are ``forward EBITDA > 0`` (EV/EBITDA, stressed leverage, both from
    ``screening/layer2.py`` and Tool D), ``forward EPS > 0`` (forward P/E,
    ``layer2.py``) and ``market cap > 0`` (AISC margin yield, ``layer1.py``)."""
    payload = _payload(_render(data=_data(_stressed_gold_row())))

    for metric, reason in (
        ("ev_ebitda", "Not meaningful — EBITDA ≤ 0"),
        ("leverage_stressed", "Not meaningful — EBITDA ≤ 0"),
        ("forward_pe", "Not meaningful — EPS ≤ 0"),
    ):
        value, got = mirror_evaluate(payload, metric, 2000.0)
        assert value is None and got == reason, metric
        # the healthy control: the SAME miner at a gold price that clears the guard
        healthy_value, healthy_reason = mirror_evaluate(payload, metric, 6000.0)
        assert healthy_value is not None and healthy_reason is None, metric

    # market cap ≤ 0 excludes the yield rather than dividing by it
    zero_cap = _payload(_render(data=_data(_gold_row(market_cap_musd=0.0))))
    value, reason = mirror_evaluate(zero_cap, "aisc_margin_yield", 4452.0)
    assert value is None and reason == "Not meaningful — market cap ≤ 0"


def test_spot_evaluation_reproduces_the_persisted_spot_display_values():
    """The client formula must agree with the backend at spot, or the two

    columns on screen would disagree about the same gold price."""
    payload = _payload(_render())
    spot = payload["spot_gold_usd"]
    for metric, persisted in payload["spot_display"].items():
        value, reason = mirror_evaluate(payload, metric, spot)
        assert value is not None, (metric, reason)
        assert abs(value - persisted) <= max(1e-4, abs(persisted) * 1e-4), metric


# ---------------------------------------------------------------------------
# distribution strips (plan D4)
# ---------------------------------------------------------------------------

#: In the score catalog AND rendered by this section.
_STRIP_METRIC = "ev_ebitda"
#: Rendered by this section but with no percentiles row in the fixture below.
_NO_ROW_METRIC = "reserve_life"
_STRIP_CONTROL_PEER = "KGC"
_STRIP_DEGRADED_PEER = "ZZZ"


def _percentile_row(ticker: str, *, raw_value, strip_pos, **overrides) -> dict:
    row: dict[str, object] = {
        "ticker": ticker,
        "finance_source": "our",
        "metric_key": _STRIP_METRIC,
        "raw_value": raw_value,
        "strip_pos": strip_pos,
        "universe_min": 5.0,
        "universe_max": 25.0,
        "pct_high_good": 30.0,
        "pct_low_good": 70.0,
        "metric_available": True,
        "rank_eligible": True,
    }
    row.update(overrides)
    return row


def _strip_rows() -> list[dict]:
    """Subject, a healthy control peer, and a peer degraded ONLY by its verdict."""

    return [
        _percentile_row("NEM", raw_value=15.0, strip_pos=0.5),
        _percentile_row(_STRIP_CONTROL_PEER, raw_value=5.0, strip_pos=0.0),
        _percentile_row(
            _STRIP_DEGRADED_PEER,
            raw_value=25.0,
            strip_pos=1.0,
            rank_eligible=False,
        ),
    ]


def test_a_catalog_metric_row_carries_its_distribution_strip():
    html = _render(data=_data(percentile_rows=_strip_rows()))

    # A DIV wrapper, by name: the strip carries a <details>/<table> disclosure,
    # which phrasing content (a span) may not legally contain.
    assert '<div class="cf-metric-strip">' in html
    assert "<title>KGC · 5.00×</title>" in html
    # EV/EBITDA is lower-is-better, so the subject label reads the low-good
    # percentile — the same direction default the Compare section uses.
    assert "NEM 15.00× · 70th percentile" in html


def test_every_corporate_strip_carries_its_chart_data_table():
    """GV-RD-FINAL-002: rug-tooltip.js deletes the <title> nodes, so the peer
    ticker+value pairs must ALSO exist as a plain table under every strip.

    Two metrics, so the helper's per-strip id-uniqueness guard has a second id
    to compare against — one strip can never collide with itself."""

    rows = _strip_rows() + [
        _percentile_row("NEM", raw_value=15.0, strip_pos=0.5, metric_key="forward_pe"),
        _percentile_row(
            _STRIP_CONTROL_PEER, raw_value=5.0, strip_pos=0.0, metric_key="forward_pe"
        ),
    ]
    html = _render(data=_data(percentile_rows=rows))

    count = assert_every_rug_strip_has_a_data_table(html, minimum=2)
    assert count == 2
    # The REAL call site wires section="corporate" into the table id.
    assert 'id="chart-data-strip-corporate-ev-ebitda-nem-our"' in html
    # The table is named after the metric AND the section (empty axis label,
    # so the fallback title is all that names it).
    assert (
        "<caption>EV/EBITDA (Corporate finance) — "
        "every eligible miner</caption>" in html
    )


def test_compare_and_corporate_strips_for_one_metric_never_collide():
    """``section``/``section_title`` exist because ``ev_ebitda`` draws in BOTH
    page sections, and detail_page renders them into one document. Rendered
    through the REAL call sites — not hand-fed namespaces — the combined page
    must keep the two table ids AND the two region landmark names distinct;
    mis-wiring either section argument fails the shared guard's collision
    checks."""

    from golden_vector.serve.ticker_page.compare import render_compare_section

    data = _data(percentile_rows=_strip_rows())
    page = render_compare_section(
        data, ticker="NEM", finance_source="our", app_config=_app_config()
    ) + _render(data=data)

    assert 'id="chart-data-strip-compare-ev-ebitda-nem-our"' in page
    assert 'id="chart-data-strip-corporate-ev-ebitda-nem-our"' in page
    # The shared guard sees both sections at once: duplicate ids AND duplicate
    # region names both fail here.
    assert assert_every_rug_strip_has_a_data_table(page, minimum=2) == 2
    assert "EV/EBITDA (Compare on your own terms) — chart data table" in page
    assert "EV/EBITDA (Corporate finance) — chart data table" in page


def test_a_degraded_peer_is_absent_from_the_rug_while_the_control_is_drawn():
    html = _render(data=_data(percentile_rows=_strip_rows()))

    assert f"<title>{_STRIP_CONTROL_PEER} · 5.00×</title>" in html
    assert _STRIP_DEGRADED_PEER not in html


def test_a_metric_with_no_percentiles_row_renders_exactly_as_before():
    with_rows = _render(data=_data(percentile_rows=_strip_rows()))
    without = _render()

    assert "Reserve life" in with_rows and "Reserve life" in without
    # Only the one catalog metric with a published cohort gained a strip.
    assert with_rows.count("cf-metric-strip") == 1
    assert "cf-metric-strip" not in without
