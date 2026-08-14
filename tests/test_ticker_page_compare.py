"""Render + payload tests for "Compare on your own terms" (ticker-page M3e).

Everything here is fixture-driven: the percentiles frame is built in the test,
never read from ``data/``. The catalog, the labels, the directions and the five
engine scalars are read from ``config/ticker_page.yaml`` through the app config
so a config edit is caught here instead of silently disagreeing with the page.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.ticker_page_state import TickerPageArtifactState
from golden_vector.serve.detail_page import render_detail_page
from golden_vector.serve.ticker_page import (
    TickerPageData,
    build_score_builder_payload,
    render_compare_section,
)
from golden_vector.serve.workspace_state import WorkspaceState
from tests.test_chart_data_tables import assert_every_rug_strip_has_a_data_table

SUBJECT = "NEM"

#: Peers that exist in the artifact with ordinary, eligible rows. Deliberately
#: NOT in alphabetical order so the "ticker ascending" rule has to do work.
HEALTHY_PEERS = ("KGC", "AEM", "GOLD", "AU", "EGO", "IAG", "BTG", "OR", "PAAS", "WPM")

#: Present in the artifact but with nothing usable — must still be listed.
INELIGIBLE_PEER = "ZZZ"

#: Missing one metric row entirely (a real data gap, not an exclusion).
GAPPY_PEER = "AAA"

#: The subject metric whose row is absent altogether.
ABSENT_METRIC = "fragility"

#: The subject metric whose row is present but marked unavailable.
UNAVAILABLE_METRIC = "survival_distance"
UNAVAILABLE_REASON = "resilience is computed on Our View inputs"

#: The subject metric that is available but NOT rank-eligible: it keeps its
#: percentiles in ``metrics[]`` and must vanish from ``peers[]``.
INELIGIBLE_METRIC = "aisc"

#: The metric row GAPPY_PEER simply does not have.
GAPPY_METRIC = "ev_ebitda"

LATEST_AS_OF = "2026-08-07"
EARLIER_AS_OF = "2026-08-05"

#: Not in the catalog (plan §7 drops it so AISC is weighted once). Carries a
#: later date on purpose: the H2 label must ignore it.
DECOY_METRIC = "cost_curve_aisc_percentile"
DECOY_AS_OF = "2027-01-01"


@pytest.fixture(scope="module")
def app_config():
    return load_app_config(ProjectPaths.discover()).app


@pytest.fixture(scope="module")
def catalog(app_config):
    return list(app_config.ticker_page.score_builder.metrics)


def _row(
    ticker: str,
    metric_key: str,
    *,
    finance_source: str = "our",
    pct_high_good: float | None = 60.0,
    pct_low_good: float | None = 40.0,
    metric_available: bool = True,
    metric_reason: object = pd.NA,
    rank_eligible: bool = True,
    rank_exclusion_reason: object = pd.NA,
    source_as_of_date: object = EARLIER_AS_OF,
    raw_value: float | None = None,
    strip_pos: float | None = None,
    universe_min: float | None = None,
    universe_max: float | None = None,
) -> dict:
    # Strip geometry defaults to absent, so the payload fixtures below describe
    # exactly the same cohort they always did and the strip tests build their
    # own frame with it present.
    return {
        "ticker": ticker,
        "finance_source": finance_source,
        "metric_key": metric_key,
        "pct_high_good": pct_high_good,
        "pct_low_good": pct_low_good,
        "raw_value": raw_value,
        "strip_pos": strip_pos,
        "universe_min": universe_min,
        "universe_max": universe_max,
        "metric_available": metric_available,
        "metric_reason": metric_reason,
        "rank_eligible": rank_eligible,
        "rank_exclusion_reason": rank_exclusion_reason,
        "source_as_of_date": source_as_of_date,
    }


def _percentile_frame(catalog) -> pd.DataFrame:
    keys = [spec.key for spec in catalog]
    rows: list[dict] = []

    for index, key in enumerate(keys):
        if key == ABSENT_METRIC:
            continue  # no row at all for the subject
        if key == UNAVAILABLE_METRIC:
            rows.append(
                _row(
                    SUBJECT,
                    key,
                    metric_available=False,
                    metric_reason=UNAVAILABLE_REASON,
                    rank_eligible=False,
                    # Percentiles present on an unavailable row: they must be
                    # dropped, not leaked.
                    pct_high_good=99.0,
                    pct_low_good=1.0,
                )
            )
            continue
        if key == INELIGIBLE_METRIC:
            rows.append(
                _row(
                    SUBJECT,
                    key,
                    rank_eligible=False,
                    rank_exclusion_reason="stale manual input",
                    pct_high_good=12.0,
                    pct_low_good=88.0,
                )
            )
            continue
        rows.append(
            _row(
                SUBJECT,
                key,
                pct_high_good=float(index),
                pct_low_good=float(100 - index),
                # One row carries the latest date; another carries none.
                source_as_of_date=(
                    LATEST_AS_OF
                    if key == keys[0]
                    else (pd.NA if key == keys[1] else EARLIER_AS_OF)
                ),
            )
        )

    # A non-catalog metric with a much later date — never read.
    rows.append(_row(SUBJECT, DECOY_METRIC, source_as_of_date=DECOY_AS_OF))

    for peer_index, peer in enumerate(HEALTHY_PEERS):
        for key_index, key in enumerate(keys):
            rows.append(
                _row(
                    peer,
                    key,
                    pct_high_good=float((peer_index * 7 + key_index) % 101),
                    pct_low_good=float(100 - ((peer_index * 7 + key_index) % 101)),
                )
            )

    # Present, but every row is excluded — the peer must still be listed.
    for key in keys:
        rows.append(
            _row(
                INELIGIBLE_PEER,
                key,
                rank_eligible=False,
                rank_exclusion_reason="degraded inputs",
            )
        )

    # Present with a genuine gap on exactly one metric.
    for key in keys:
        if key == GAPPY_METRIC:
            continue
        rows.append(_row(GAPPY_PEER, key, pct_high_good=55.0, pct_low_good=45.0))

    # The other finance source: different numbers, and one ticker that exists
    # ONLY there, so a source leak is impossible to miss.
    for key in keys:
        rows.append(
            _row(SUBJECT, key, finance_source="yahoo", pct_high_good=5.0, pct_low_good=95.0)
        )
        rows.append(_row("YHO", key, finance_source="yahoo"))

    return pd.DataFrame(rows)


def _data(catalog, *, status: str = "OK", reason: str | None = None) -> TickerPageData:
    frame = _percentile_frame(catalog) if status == "OK" else pd.DataFrame()
    empty = TickerPageArtifactState(status="MISSING", reason="not built", frame=pd.DataFrame())
    return TickerPageData(
        gold_response=empty,
        percentiles=TickerPageArtifactState(status=status, reason=reason, frame=frame),
        performance=empty,
        research_series=empty,
        fx_attribution=empty,
    )


def _payload(html: str) -> dict:
    marker = '<script type="application/json" id="score-builder-payload">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def _metric_row_html(html: str, key: str) -> str:
    marker = f'data-metric-key="{key}"'
    start = html.index(marker)
    return html[start : html.index("</li>", start)]


def _render(catalog, app_config, *, finance_source: str = "our", **kwargs) -> str:
    return render_compare_section(
        _data(catalog, **kwargs),
        ticker=SUBJECT,
        finance_source=finance_source,
        app_config=app_config,
    )


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------


def test_payload_lists_the_whole_catalog_in_config_order(catalog, app_config):
    payload = _payload(_render(catalog, app_config))

    assert [entry["key"] for entry in payload["metrics"]] == [
        spec.key for spec in catalog
    ]
    assert len(payload["metrics"]) == 19
    for entry, spec in zip(payload["metrics"], catalog):
        assert entry["label"] == spec.label
        assert entry["category"] == spec.category
        assert entry["unit"] == spec.unit
        assert entry["basis"] == spec.basis
        assert entry["default_high_good"] is bool(spec.default_high_good)


def test_payload_scalars_are_the_config_values(catalog, app_config):
    payload = _payload(_render(catalog, app_config))
    config = app_config.ticker_page.score_builder

    assert payload["subject"] == SUBJECT
    assert payload["budget_points"] == config.budget_points
    assert payload["min_eligible_peers"] == config.min_eligible_peers
    assert payload["min_active_metric_coverage"] == config.min_active_metric_coverage
    assert payload["rank_stability_shift_points"] == config.rank_stability_shift_points
    assert (
        payload["rank_stability_alert_positions"] == config.rank_stability_alert_positions
    )


def test_subject_percentiles_are_the_persisted_values_verbatim(catalog, app_config):
    data = _data(catalog)
    payload = build_score_builder_payload(
        data, ticker=SUBJECT, finance_source="our", app_config=app_config
    )
    entries = {entry["key"]: entry for entry in payload["metrics"]}

    for spec in catalog:
        row = data.metric_row(SUBJECT, metric_key=spec.key, finance_source="our")
        entry = entries[spec.key]
        if row is None or not bool(row["metric_available"]):
            continue
        assert entry["pct_high_good"] == pytest.approx(float(row["pct_high_good"]))
        assert entry["pct_low_good"] == pytest.approx(float(row["pct_low_good"]))


def test_absent_row_is_unavailable_with_a_reason_and_no_percentiles(catalog, app_config):
    payload = _payload(_render(catalog, app_config))
    entries = {entry["key"]: entry for entry in payload["metrics"]}

    absent = entries[ABSENT_METRIC]
    assert absent["available"] is False
    assert absent["reason"] == "not published for this ticker"
    assert absent["pct_high_good"] is None and absent["pct_low_good"] is None


def test_unavailable_row_keeps_its_reason_and_drops_its_percentiles(catalog, app_config):
    """The fixture row carries 99/1 — an unavailable metric must not leak them."""
    payload = _payload(_render(catalog, app_config))
    entry = {item["key"]: item for item in payload["metrics"]}[UNAVAILABLE_METRIC]

    assert entry["available"] is False
    assert entry["reason"] == UNAVAILABLE_REASON
    assert entry["pct_high_good"] is None and entry["pct_low_good"] is None


def test_peer_cell_needs_both_available_and_rank_eligible(catalog, app_config):
    payload = _payload(_render(catalog, app_config))
    peers = {peer["ticker"]: peer for peer in payload["peers"]}

    # available + eligible -> real cell (healthy control, so this cannot pass
    # by everything being null)
    healthy = peers["AEM"]["values"]["ev_ebitda"]
    assert healthy is not None
    assert healthy["pct_high_good"] is not None

    # available but NOT rank-eligible -> no cell, even for the subject itself
    assert peers[SUBJECT]["values"][INELIGIBLE_METRIC] is None
    # unavailable -> no cell
    assert peers[SUBJECT]["values"][UNAVAILABLE_METRIC] is None
    # no row at all -> no cell
    assert peers[SUBJECT]["values"][ABSENT_METRIC] is None
    assert peers[GAPPY_PEER]["values"][GAPPY_METRIC] is None
    assert peers[GAPPY_PEER]["values"]["margin_pct"] is not None
    # every row excluded -> listed, with nothing usable
    assert set(peers[INELIGIBLE_PEER]["values"].values()) == {None}


def test_peers_are_every_artifact_ticker_for_this_source_ticker_ascending(
    catalog, app_config
):
    payload = _payload(_render(catalog, app_config))
    tickers = [peer["ticker"] for peer in payload["peers"]]

    expected = sorted({SUBJECT, INELIGIBLE_PEER, GAPPY_PEER, *HEALTHY_PEERS})
    assert tickers == expected
    assert SUBJECT in tickers, "the subject is a peer of itself — the JS reads it there"
    assert "YHO" not in tickers, "the other finance source must not leak in"


def test_peer_values_cover_every_catalog_key(catalog, app_config):
    """Every peer carries a cell (or an explicit null) for every catalog metric.

    Key ORDER is not asserted: ``embed_json_payload`` sorts object keys so the
    payload is byte-stable, and the client looks metrics up by key. The
    order-bearing parts of the contract are the two ARRAYS, covered above.
    """
    payload = _payload(_render(catalog, app_config))
    keys = sorted(spec.key for spec in catalog)

    for peer in payload["peers"]:
        assert sorted(peer["values"].keys()) == keys, peer["ticker"]


def test_detail_urls_carry_the_source_only_when_it_is_not_the_default(catalog, app_config):
    ours = _payload(_render(catalog, app_config))
    yahoo = _payload(_render(catalog, app_config, finance_source="yahoo"))

    ours_by_ticker = {peer["ticker"]: peer["detail_url"] for peer in ours["peers"]}
    assert ours_by_ticker["AEM"] == "/ticker/AEM"
    assert ours_by_ticker[SUBJECT] == f"/ticker/{SUBJECT}"

    yahoo_by_ticker = {peer["ticker"]: peer["detail_url"] for peer in yahoo["peers"]}
    assert yahoo_by_ticker["YHO"] == "/ticker/YHO?fundamentals_source=yahoo"
    assert yahoo_by_ticker[SUBJECT] == f"/ticker/{SUBJECT}?fundamentals_source=yahoo"


def test_yahoo_mode_reads_the_yahoo_rows(catalog, app_config):
    payload = _payload(_render(catalog, app_config, finance_source="yahoo"))
    entries = {entry["key"]: entry for entry in payload["metrics"]}

    assert entries["margin_pct"]["pct_high_good"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# DOM contract (frozen by score-builder.js)
# ---------------------------------------------------------------------------


def test_every_selector_of_the_frozen_js_contract_is_present(catalog, app_config):
    html = _render(catalog, app_config)

    assert '<script type="application/json" id="score-builder-payload">' in html
    assert 'id="score-builder"' in html
    assert 'id="score-builder-result"' in html
    for role in (
        "opt-in",
        "message",
        "subject-score",
        "subject-rank",
        "subject-note",
        "contributions",
        "ranked-list",
        "stability-warning",
        "live",
        "reset",
    ):
        assert f'data-role="{role}"' in html, role
    assert 'aria-live="polite"' in html

    for spec in catalog:
        row = _metric_row_html(html, spec.key)
        assert '<input type="checkbox"' in row
        assert 'data-role="activate"' in row
        assert 'data-role="direction"' in row
        assert "aria-pressed=" in row
        assert 'type="range"' in row and 'data-role="weight"' in row
        assert 'data-role="weight-points"' in row


def test_weight_sliders_span_the_config_budget_in_single_points(catalog, app_config):
    html = _render(catalog, app_config)
    budget = app_config.ticker_page.score_builder.budget_points

    for spec in catalog:
        row = _metric_row_html(html, spec.key)
        assert f'min="0" max="{budget}" step="1" value="0"' in row, spec.key


def test_direction_buttons_start_on_the_config_default(catalog, app_config):
    html = _render(catalog, app_config)

    for spec in catalog:
        row = _metric_row_html(html, spec.key)
        expected = "true" if spec.default_high_good else "false"
        wording = "Higher is better" if spec.default_high_good else "Lower is better"
        assert f'aria-pressed="{expected}"' in row, spec.key
        assert wording in row, spec.key


def test_unavailable_metrics_are_disabled_with_their_reason_visible(catalog, app_config):
    html = _render(catalog, app_config)

    for key, reason in (
        (ABSENT_METRIC, "not published for this ticker"),
        (UNAVAILABLE_METRIC, UNAVAILABLE_REASON),
    ):
        row = _metric_row_html(html, key)
        assert reason in row, key
        assert 'data-role="activate" disabled' in row, key
        assert "Lower is better</button>" in row or "Higher is better</button>" in row
        assert 'data-role="direction" aria-pressed="' in row and " disabled>" in row, key

    # A healthy control: available metrics keep their controls enabled.
    healthy = _metric_row_html(html, "margin_pct")
    assert 'data-role="activate">' in healthy
    assert "sb-unavailable" not in healthy


def test_both_categories_render_with_their_product_titles(catalog, app_config):
    html = _render(catalog, app_config)

    assert "<legend>Trading behaviour</legend>" in html
    assert "<legend>Corporate finance</legend>" in html
    for spec in catalog:
        group_start = html.index(f'data-category="{spec.category}"')
        group_end = html.index("</fieldset>", group_start)
        assert f'data-metric-key="{spec.key}"' in html[group_start:group_end], spec.key


def test_result_region_is_server_rendered_in_its_opt_in_state(catalog, app_config):
    html = _render(catalog, app_config)

    assert "Nothing is scored until you build it — pick a metric to start." in html
    # The client only ever un-hides these three; the rest are written by
    # setText/appendChild and must NOT start hidden or they never appear.
    assert '<p class="hint" data-role="message" hidden>' in html
    assert '<p class="hint" data-role="subject-note" hidden>' in html
    assert 'data-role="stability-warning" hidden>' in html
    assert 'data-role="subject-score"></span>' in html
    assert 'data-role="contributions" aria-label="What carries the score"></ul>' in html
    assert 'data-role="ranked-list" aria-label="Every miner, ranked"></ul>' in html


def test_script_is_mounted_once_after_the_dom_and_the_payload(catalog, app_config):
    html = _render(catalog, app_config)
    tag = '<script src="/static/score-builder.js" defer></script>'

    assert html.count(tag) == 1
    assert html.index(tag) > html.index('id="score-builder"')
    assert html.index(tag) > html.index('id="score-builder-result"')
    assert html.index(tag) > html.index('id="score-builder-payload"')


def _basis_label(html: str) -> str:
    marker = '<p class="hint sb-basis">'
    start = html.index(marker) + len(marker)
    return html[start : html.index("</p>", start)]


def test_section_carries_the_at_spot_label_with_the_latest_as_of_date(catalog, app_config):
    html = _render(catalog, app_config)

    assert (
        _basis_label(html)
        == f"at spot, as of {LATEST_AS_OF} — the gold dial does not move these ranks"
    )
    assert DECOY_AS_OF not in html, "a non-catalog metric must not set the label date"
    assert EARLIER_AS_OF not in _basis_label(html), "the label carries the LATEST date"


def test_label_omits_the_date_clause_when_no_row_carries_one(catalog, app_config):
    frame = _percentile_frame(catalog)
    frame["source_as_of_date"] = pd.NA
    empty = TickerPageArtifactState(status="MISSING", reason="not built", frame=pd.DataFrame())
    data = TickerPageData(
        gold_response=empty,
        percentiles=TickerPageArtifactState(status="OK", reason=None, frame=frame),
        performance=empty,
        research_series=empty,
        fx_attribution=empty,
    )

    html = render_compare_section(
        data, ticker=SUBJECT, finance_source="our", app_config=app_config
    )

    assert _basis_label(html) == "at spot — the gold dial does not move these ranks"


def test_help_icons_cover_every_metric_and_the_section_explainers(catalog, app_config):
    html = _render(catalog, app_config)

    for spec in catalog:
        row = _metric_row_html(html, spec.key)
        # TWO icons per row: the metric explainer and the direction toggle's.
        # A bare "at least one" check was satisfied by the pre-existing metric
        # icon alone, so the newer per-row direction explainer could vanish.
        assert row.count('class="help-icon"') == 2, f"{spec.key} explainers"
    assert 'data-help-title="Compare on your own terms"' in html
    # The result-region explainers: assert the icon, because the bare LABEL is
    # also a pre-existing aria-label and would pass with no explainer at all.
    for title in (
        "What carries the score",
        "The ranked list",
        "When a ranking is fragile",
        "Which way is good",
    ):
        assert f'data-help-title="{title}"' in html, title
    assert "How the percentiles work" in html
    assert "How the weight budget works" in html
    assert "Metrics this company lacks" in html
    # the average-tie policy is stated, not implied
    assert "AVERAGE of the places they span" in html


def test_thin_cohort_still_renders_and_leaves_the_message_to_the_client(
    catalog, app_config
):
    """Below ``min_eligible_peers`` the SERVER must not gate the section."""
    keys = [spec.key for spec in catalog]
    rows = [_row(SUBJECT, key) for key in keys] + [_row("AEM", key) for key in keys]
    empty = TickerPageArtifactState(status="MISSING", reason="not built", frame=pd.DataFrame())
    data = TickerPageData(
        gold_response=empty,
        percentiles=TickerPageArtifactState(
            status="OK", reason=None, frame=pd.DataFrame(rows)
        ),
        performance=empty,
        research_series=empty,
        fx_attribution=empty,
    )

    html = render_compare_section(
        data, ticker=SUBJECT, finance_source="our", app_config=app_config
    )
    payload = _payload(html)

    assert len(payload["peers"]) == 2
    assert len(payload["peers"]) < app_config.ticker_page.score_builder.min_eligible_peers
    assert '<script src="/static/score-builder.js" defer></script>' in html
    assert "not enough comparable miners" not in html


def test_subject_absent_from_the_artifact_is_honest_not_empty(catalog, app_config):
    """A ticker the producer has not covered yet still gets the section: every
    metric says why it is missing, and the cohort is still listed so the user
    can see what they would be compared against."""
    html = render_compare_section(
        _data(catalog), ticker="NOTPUBLISHED", finance_source="our", app_config=app_config
    )
    payload = _payload(html)

    assert payload["subject"] == "NOTPUBLISHED"
    assert all(entry["available"] is False for entry in payload["metrics"])
    assert all(
        entry["reason"] == "not published for this ticker" for entry in payload["metrics"]
    )
    assert "NOTPUBLISHED" not in {peer["ticker"] for peer in payload["peers"]}
    assert len(payload["peers"]) > 1, "the cohort is still shown"
    assert _basis_label(html) == "at spot — the gold dial does not move these ranks"


# ---------------------------------------------------------------------------
# degraded states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("MISSING", "percentiles have not been published yet"),
        ("STALE", "published 9 days ago"),
        ("CORRUPT", "schema mismatch on pct_high_good"),
    ],
)
def test_degraded_artifact_states_its_reason_and_mounts_nothing(
    catalog, app_config, status, reason
):
    html = _render(catalog, app_config, status=status, reason=reason)

    assert 'id="compare"' in html
    assert "notice-degraded" in html
    assert status in html and reason in html
    assert "score-builder.js" not in html
    assert "score-builder-payload" not in html
    assert 'id="score-builder"' not in html


def test_missing_config_is_a_notice_not_a_guess(catalog):
    html = render_compare_section(
        _data(catalog), ticker=SUBJECT, finance_source="our", app_config=None
    )

    assert 'id="compare"' in html
    assert "notice-degraded" in html
    assert "score-builder.js" not in html


# ---------------------------------------------------------------------------
# page composition
# ---------------------------------------------------------------------------


def _empty_workspace_state() -> WorkspaceState:
    empty = pd.DataFrame()
    return WorkspaceState(
        tool_b_tickers=[SUBJECT],
        foundation_manifest=None,
        company_inputs=empty,
        source_verification=empty,
        reporting_calendar=empty,
        stock_notes=empty,
        latest_tool_a=empty,
        latest_tool_b=empty,
        latest_tool_c=empty,
        latest_tool_d=empty,
        tool_a_alias_present=False,
        tool_b_alias_present=False,
        tool_c_alias_present=False,
        tool_d_alias_present=False,
        model_state_manifest=None,
    )


def _page(catalog, app_config, **kwargs) -> str:
    return render_detail_page(
        _empty_workspace_state(),
        ticker=SUBJECT,
        tool_a_detail=None,
        flash=None,
        app_config=app_config,
        ticker_page_data=_data(catalog, **kwargs),
        financials_source="our",
    )


def test_compare_sits_between_options_and_inputs(catalog, app_config):
    page = _page(catalog, app_config)

    assert page.index('id="compare"') > page.index('id="market-behaviour"')
    assert page.index('id="compare"') < page.index('id="inputs"')
    if 'id="options"' in page:
        assert page.index('id="compare"') > page.index('id="options"')


def test_nav_lists_compare_between_options_and_inputs(catalog, app_config):
    page = _page(catalog, app_config)
    nav_start = page.index('<nav class="section-nav section-nav--compact"')
    nav = page[nav_start : page.index("</nav>", nav_start)]

    assert '<a class="section-nav-link" href="#compare">Compare</a>' in nav
    assert nav.index("#compare") < nav.index("#inputs")


def test_nav_still_lists_compare_when_the_artifact_is_degraded(catalog, app_config):
    page = _page(catalog, app_config, status="MISSING", reason="not published")

    assert '<a class="section-nav-link" href="#compare">Compare</a>' in page
    assert 'id="compare"' in page


def test_option_vehicle_pages_have_no_comparison(catalog, app_config):
    """An ETF is not in the miner cohort — the section must not appear at all."""
    page = render_detail_page(
        _empty_workspace_state(),
        ticker=SUBJECT,
        tool_a_detail=None,
        flash=None,
        app_config=app_config,
        ticker_page_data=_data(catalog),
        show_workspace_panels=False,
        show_manual_sections=False,
        financials_source="our",
    )

    assert 'id="compare"' not in page
    assert 'href="#compare"' not in page


# ---------------------------------------------------------------------------
# distribution strips (plan D3)
# ---------------------------------------------------------------------------

#: default_high_good is FALSE for this one — its subject label must read the
#: low-good percentile.
STRIP_LOW_GOOD_METRIC = "ev_ebitda"
#: default_high_good is TRUE.
STRIP_HIGH_GOOD_METRIC = "up_beta_core"
#: Carries values but no cohort spread, so the artifact publishes no domain.
STRIP_NO_DOMAIN_METRIC = "reserve_life"

STRIP_CONTROL_PEER = "KGC"
STRIP_DEGRADED_PEER = "ZZZ"


def _strip_row(ticker, key, *, raw_value, strip_pos, **kwargs) -> dict:
    """A row that is healthy in every respect except what a test overrides."""

    return _row(
        ticker,
        key,
        raw_value=raw_value,
        strip_pos=strip_pos,
        universe_min=kwargs.pop("universe_min", 5.0),
        universe_max=kwargs.pop("universe_max", 25.0),
        **kwargs,
    )


def _strip_data(rows: list[dict]) -> TickerPageData:
    empty = TickerPageArtifactState(status="MISSING", reason="not built", frame=pd.DataFrame())
    return TickerPageData(
        gold_response=empty,
        percentiles=TickerPageArtifactState(
            status="OK", reason=None, frame=pd.DataFrame(rows)
        ),
        performance=empty,
        research_series=empty,
        fx_attribution=empty,
    )


def _strip_rows() -> list[dict]:
    """Subject + one healthy control peer + one degraded peer, on two metrics.

    The degraded peer is degraded ONLY by its persisted verdict: it carries a
    real value and a real ``strip_pos``, so an implementation that ignored
    ``rank_eligible`` would draw it.
    """

    rows = [
        _strip_row(SUBJECT, STRIP_LOW_GOOD_METRIC, raw_value=15.0, strip_pos=0.5,
                   pct_high_good=30.0, pct_low_good=70.0),
        _strip_row(STRIP_CONTROL_PEER, STRIP_LOW_GOOD_METRIC, raw_value=5.0, strip_pos=0.0),
        _strip_row(
            STRIP_DEGRADED_PEER,
            STRIP_LOW_GOOD_METRIC,
            raw_value=25.0,
            strip_pos=1.0,
            rank_eligible=False,
            rank_exclusion_reason="degraded inputs",
        ),
        _strip_row(SUBJECT, STRIP_HIGH_GOOD_METRIC, raw_value=15.0, strip_pos=0.5,
                   pct_high_good=30.0, pct_low_good=70.0),
        _strip_row(STRIP_CONTROL_PEER, STRIP_HIGH_GOOD_METRIC, raw_value=5.0, strip_pos=0.0),
    ]
    # Present, valued, but with no published domain: no strip may be drawn.
    rows.append(
        _row(SUBJECT, STRIP_NO_DOMAIN_METRIC, raw_value=22.0, strip_pos=None)
    )
    # An unavailable metric row, with its reason.
    rows.append(
        _strip_row(
            SUBJECT,
            UNAVAILABLE_METRIC,
            raw_value=0.4,
            strip_pos=0.4,
            metric_available=False,
            metric_reason=UNAVAILABLE_REASON,
            rank_eligible=False,
        )
    )
    return rows


def _strip_html(app_config, key: str) -> str:
    page = render_compare_section(
        _strip_data(_strip_rows()),
        ticker=SUBJECT,
        finance_source="our",
        app_config=app_config,
    )
    return _metric_row_html(page, key)


def test_metric_row_carries_a_strip_naming_every_eligible_miner(app_config):
    row = _strip_html(app_config, STRIP_LOW_GOOD_METRIC)

    # A DIV wrapper, by name: the strip carries a <details>/<table> disclosure,
    # which phrasing content (a span) may not legally contain.
    assert '<div class="sb-metric-strip">' in row
    # The hover title of one rug tick: ticker + the value in the metric's units.
    assert "<title>KGC · 5.00×</title>" in row
    # Subject marker label: value + the direction-default percentile.
    assert "NEM 15.00× · 70th percentile" in row
    # Domain ends, formatted with the same unit rule.
    assert ">5.00×</text>" in row and ">25.00×</text>" in row


def test_a_degraded_peer_has_no_tick_while_a_healthy_control_does(app_config):
    row = _strip_html(app_config, STRIP_LOW_GOOD_METRIC)

    assert f"<title>{STRIP_CONTROL_PEER} · 5.00×</title>" in row
    assert STRIP_DEGRADED_PEER not in row


def test_a_high_good_metric_labels_the_subject_with_the_high_good_percentile(app_config):
    row = _strip_html(app_config, STRIP_HIGH_GOOD_METRIC)

    assert "NEM 15.00× · 30th percentile" in row
    assert "70th percentile" not in row


def test_no_published_domain_means_no_strip_rather_than_an_invented_axis(app_config):
    row = _strip_html(app_config, STRIP_NO_DOMAIN_METRIC)

    assert "sb-metric-strip" not in row
    assert "No comparison data available." not in row


def test_an_unavailable_metric_row_keeps_its_reason_and_gains_no_strip(app_config):
    row = _strip_html(app_config, UNAVAILABLE_METRIC)

    assert "sb-unavailable" in row
    assert UNAVAILABLE_REASON in row
    assert "sb-metric-strip" not in row


def test_the_in_row_strip_is_named_for_assistive_tech(app_config):
    """The compact strip draws no axis text, so the SVG name must come from
    somewhere else — a bare " distribution" names nothing."""

    row = _strip_html(app_config, STRIP_LOW_GOOD_METRIC)

    assert 'aria-label="NEM 15.00× · 70th percentile distribution"' in row
    assert 'aria-label=" distribution"' not in row


def test_every_compare_strip_carries_its_chart_data_table(app_config):
    """GV-RD-FINAL-002: rug-tooltip.js deletes the <title> nodes, so the peer
    ticker+value pairs must ALSO exist as a plain table under every strip."""

    page = render_compare_section(
        _strip_data(_strip_rows()),
        ticker=SUBJECT,
        finance_source="our",
        app_config=app_config,
    )

    count = assert_every_rug_strip_has_a_data_table(page, minimum=2)
    # Exactly the two metrics with a drawable cohort — nothing extra, nothing lost.
    assert count == 2
    # The REAL call site wires section="compare" into the table id — the
    # namespace that keeps this id distinct from corporate's for the same metric.
    assert 'id="chart-data-strip-compare-ev-ebitda-nem-our"' in page
    # The table is NAMED (caption + region label) after the metric and section;
    # every strip passes an empty axis label, so without the fallback the caption
    # would open with a bare " — " and name nothing.
    assert (
        "<caption>EV/EBITDA (Compare on your own terms) — "
        "every eligible miner</caption>" in page
    )
    assert "EV/EBITDA (Compare on your own terms) — chart data table" in page
    assert "<caption> — every eligible miner</caption>" not in page


def test_strip_assembly_contains_no_arithmetic_at_all():
    """Same guardrail as compare.py: positions and domains are persisted, so the
    shared assembly module may not contain a single arithmetic operator."""

    path = Path("golden_vector/serve/ticker_page/strips.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = (ast.Mult, ast.Div, ast.FloorDiv, ast.Sub, ast.Pow, ast.Mod, ast.MatMult)
    offenders = [
        f"line {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, banned)
    ]
    assert not offenders, "arithmetic in serve/ticker_page/strips.py: " + "; ".join(
        offenders
    )


# ---------------------------------------------------------------------------
# guardrail
# ---------------------------------------------------------------------------


def test_compare_section_contains_no_arithmetic_at_all():
    """Canon: every new serve surface gets a static-scan guardrail.

    Stricter than the token sweep, because compare.py is where the score maths
    WANTS to leak in: the combine rule must exist exactly once, in the frozen
    client module. String concatenation stays legal (markup assembly); every
    other binary operator is banned.
    """
    path = Path("golden_vector/serve/ticker_page/compare.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = (ast.Mult, ast.Div, ast.FloorDiv, ast.Sub, ast.Pow, ast.Mod, ast.MatMult)
    offenders = [
        f"line {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, banned)
    ]
    assert not offenders, "arithmetic in serve/ticker_page/compare.py: " + "; ".join(
        offenders
    )


def test_compare_never_ranks_sorts_or_scores_server_side():
    source = Path("golden_vector/serve/ticker_page/compare.py").read_text(encoding="utf-8")

    for forbidden in (
        ".fillna(",
        ".combine_first(",
        "oriented_percentile",
        "rank(",
        "sort_values",
        "nlargest",
        "import numpy",
        "np.",
    ):
        assert forbidden not in source, forbidden
    # It obeys the persisted verdicts rather than deriving them.
    assert "rank_eligible" in source and "metric_available" in source
