"""Render tests for the redesigned ticker-page sections (M2 spine + M3a/M3b)."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.ticker_page_state import TickerPageArtifactState
from golden_vector.serve.ticker_page import (
    render_cost_downside_card,
    render_currency_attribution_block,
    render_performance_section,
)


def _app_config():
    return load_app_config(ProjectPaths.discover()).app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _fx_row(**overrides) -> pd.DataFrame:
    row = {
        "ticker": "AAR.AX",
        "horizon": "1Y",
        "quote_currency": "AUD",
        "start_date": pd.Timestamp("2025-08-08"),
        "end_date": pd.Timestamp("2026-08-07"),
        "local_start_value": 10.0,
        "local_end_value": 9.12,
        "local_return": -0.088,
        "fx_start_rate": 0.65,
        "fx_end_rate": 0.7046,
        "fx_start_source_date": pd.Timestamp("2025-08-08"),
        "fx_end_source_date": pd.Timestamp("2026-08-07"),
        "fx_source_symbol": "AUDUSD=X",
        "fx_return": 0.084,
        "usd_start_value": 6.5,
        "usd_end_value": 6.426,
        "usd_return": -0.0114,
        "fx_contribution_pp": 7.66,
        "relationship": "OFFSET",
        "share_of_usd_move": None,
        "offset_of_local_move": 0.87,
        "attribution_status": "OK",
        "attribution_reason": None,
        "price_basis": "return_basis_usd",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _performance_rows() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=5)
    rows = []
    for series, base in (("stock", 100.0), ("gold", 100.0)):
        for index, date in enumerate(dates):
            for view, value in (("rebased", base + index), ("price", 50.0 + index)):
                rows.append(
                    {
                        "ticker": "AAR.AX",
                        "series": series,
                        "view": view,
                        "horizon": "1Y",
                        "date": date,
                        "value": value,
                        "rebase_date": dates[0],
                        "late_start": False,
                        "series_status": "OK",
                        "series_reason": None,
                        "series_as_of_date": dates[-1],
                        "source_last_date": dates[-1],
                        "common_end_date": dates[-1],
                        "trim_reason": None,
                        "price_basis": "return_basis_usd",
                        "series_source_run_id": "run",
                        "currency_basis": "USD" if view == "price" else "INDEX_100",
                    }
                )
    for view in ("rebased", "price"):
        rows.append(
            {
                "ticker": "AAR.AX",
                "series": "gdx",
                "view": view,
                "horizon": "1Y",
                "date": dates[-1],
                "value": None,
                "rebase_date": pd.NaT,
                "late_start": False,
                "series_status": "STALE_OMITTED",
                "series_reason": "gdx last observation is 9 trading day(s) behind",
                "series_as_of_date": dates[-1],
                "source_last_date": dates[-1],
                "common_end_date": dates[-1],
                "trim_reason": None,
                "price_basis": "adj_close_local",
                "series_source_run_id": "run",
                "currency_basis": "USD" if view == "price" else "INDEX_100",
            }
        )
    return pd.DataFrame(rows)


def _healthy_four_series_performance_rows() -> pd.DataFrame:
    """A happy-path Compare artifact with every supported visible series."""

    rows = _performance_rows()
    stock = rows.loc[
        rows["series"].eq("stock") & rows["view"].eq("rebased")
    ].copy()
    healthy = [rows.loc[~rows["series"].isin(["gdx", "gdxj"])]]
    for series, offset in (("gdx", 10.0), ("gdxj", 20.0)):
        benchmark = stock.copy()
        benchmark["series"] = series
        benchmark["value"] = benchmark["value"] + offset
        healthy.append(benchmark)
    return pd.concat(healthy, ignore_index=True)


def _metric_row(**overrides) -> pd.Series:
    row = {
        "ticker": "AAR.AX",
        "finance_source": "our",
        "metric_key": "aisc",
        "raw_value": 1419.0,
        "basis": "Our View mining assumption",
        "metric_available": True,
        "metric_reason": None,
        "pct_low_good": 72.0,
        "pct_high_good": 28.0,
        "eligible_observation_count": None,
        "hit_count": None,
        "source_period_start": None,
        "source_period_end": None,
        "source_verification_status": "VERIFIED",
        "source_verification_date": "2026-06-30",
    }
    row.update(overrides)
    return pd.Series(row)


def _peers(metric_key: str, values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "finance_source": "our",
                "metric_key": metric_key,
                "raw_value": value,
                "metric_available": True,
            }
            for ticker, value in values.items()
        ]
    )


# ---------------------------------------------------------------------------
# performance section
# ---------------------------------------------------------------------------


def test_performance_controls_are_visible_url_backed_and_preserve_query_state():
    html = render_performance_section(
        _healthy_four_series_performance_rows(),
        ticker="AAR.AX",
        horizon="3Y",
        view="price",
        app_config=_app_config(),
        query_params={
            "fundamentals_source": "yahoo",
            "lens": "option-trading",
            "chart_h": "3Y",
            "chart_view": "price",
        },
    )

    assert '<span class="performance-controls__label">View</span>' in html
    assert '<span class="performance-controls__label">Horizon</span>' in html
    assert 'aria-label="Performance view"' in html
    assert 'aria-label="Performance horizon"' in html
    assert '>Compare</a>' in html
    assert '>Share price</a>' in html
    assert '>1Y</a>' in html and '>3Y</a>' in html and '>5Y</a>' in html
    assert 'href="/ticker/AAR.AX?' in html

    hrefs = [unescape(value) for value in re.findall(r'href="([^"]+)"', html)]
    compare_href = next(value for value in hrefs if "chart_view=rebased" in value)
    one_year_href = next(value for value in hrefs if "chart_h=1Y" in value)
    for href in (compare_href, one_year_href):
        query = parse_qs(urlsplit(href).query)
        assert query["fundamentals_source"] == ["yahoo"]
        assert query["lens"] == ["option-trading"]
    assert parse_qs(urlsplit(compare_href).query)["chart_h"] == ["3Y"]
    assert parse_qs(urlsplit(one_year_href).query)["chart_view"] == ["price"]

    selected = re.findall(
        r'<a class="segmented-control__item" href="[^"]+" aria-current="true">([^<]+)</a>',
        html,
    )
    assert selected == ["Share price", "3Y"]


def test_performance_controls_remain_available_when_artifact_is_degraded():
    state = TickerPageArtifactState(
        status="CORRUPT", reason="checksum mismatch", frame=pd.DataFrame()
    )

    html = render_performance_section(
        pd.DataFrame(),
        ticker="AAR.AX",
        horizon="1Y",
        app_config=_app_config(),
        artifact_state=state,
    )

    assert 'class="performance-controls"' in html
    assert '>Compare</a>' in html and '>Share price</a>' in html
    assert "checksum mismatch" in html


def test_compare_series_visibility_is_progressive_and_table_stays_complete():
    html = render_performance_section(
        _healthy_four_series_performance_rows(),
        ticker="AAR.AX",
        horizon="1Y",
        view="rebased",
    )

    assert '<fieldset class="performance-series" data-performance-series hidden>' in html
    chart_id = "performance-chart-aar-ax-1y-rebased"
    assert f'id="{chart_id}" data-performance-chart' in html
    for key, label in (("stock", "Stock"), ("gold", "Gold"), ("gdx", "GDX"), ("gdxj", "GDXJ")):
        assert f'data-performance-series-input="{key}"' in html
        assert f'aria-controls="{chart_id}"' in html
        assert f'>{label}</label>' in html
        assert f'class="series-{key}"' in html
        assert f'<th scope="col" class="numeric">{label}</th>' in html
    assert html.count('type="checkbox"') == 4
    assert html.count(" checked") == 4
    assert html.index("legend-swatch-stock") < html.index("legend-swatch-gold")
    assert html.index("legend-swatch-gold") < html.index("legend-swatch-gdx")
    assert html.index("legend-swatch-gdx") < html.index("legend-swatch-gdxj")


def test_share_price_has_no_compare_series_visibility_controls():
    html = render_performance_section(
        _healthy_four_series_performance_rows(),
        ticker="AAR.AX",
        horizon="1Y",
        view="price",
    )

    assert "data-performance-series" not in html
    assert 'data-performance-chart' in html


def test_currency_attribution_composes_inside_performance_section():
    attribution = (
        '<div class="fx-attribution" id="currency-attribution">FX sentinel</div>'
    )

    html = render_performance_section(
        _performance_rows(),
        ticker="AAR.AX",
        horizon="1Y",
        currency_attribution_html=attribution,
    )

    assert html.count(attribution) == 1
    assert html.index(attribution) < html.rindex("</section>")


@pytest.mark.parametrize(
    ("rows", "state"),
    (
        (pd.DataFrame(), None),
        (
            pd.DataFrame(),
            TickerPageArtifactState(
                status="CORRUPT", reason="checksum mismatch", frame=pd.DataFrame()
            ),
        ),
    ),
)
def test_currency_attribution_remains_inside_degraded_or_empty_performance(
    rows, state
):
    attribution = (
        '<div class="fx-attribution" id="currency-attribution">FX sentinel</div>'
    )

    html = render_performance_section(
        rows,
        ticker="AAR.AX",
        horizon="1Y",
        artifact_state=state,
        currency_attribution_html=attribution,
    )

    assert html.count(attribution) == 1
    assert html.index(attribution) < html.rindex("</section>")


def test_performance_section_renders_series_basis_and_markers():
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="rebased"
    )
    assert "<h2>Performance" in html
    assert "Performance — AAR.AX" not in html
    assert "Compare (indexed to 100)" in html
    assert "indexed to 100 on 2026-01-05" in html
    assert "return_basis_usd" not in html
    assert "series bases: Stock/Gold" in html
    assert "USD-normalized price (adjusted close where available)" in html
    # a non-OK series renders a marker, never a silent absence
    assert "gdx last observation is 9 trading day(s) behind" in html.lower() or "GDX:" in html


def test_performance_section_preserves_degraded_artifact_reason():
    state = TickerPageArtifactState(
        status="CORRUPT", reason="checksum mismatch", frame=pd.DataFrame()
    )

    html = render_performance_section(
        pd.DataFrame(),
        ticker="AAR.AX",
        horizon="1Y",
        artifact_state=state,
    )

    assert "CORRUPT" in html
    assert "checksum mismatch" in html
    assert "No performance data has been published for this ticker" not in html


def test_performance_chart_uses_distinct_semantic_series_colours():
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="rebased"
    )

    assert 'class="series-stock"' in html
    assert 'class="series-gold"' in html
    assert 'legend-swatch-stock' in html
    assert 'legend-swatch-gold' in html


def test_performance_markers_accept_nullable_reason_text():
    rows = _performance_rows()
    rows.loc[rows["series_status"].ne("OK"), "series_reason"] = pd.NA

    html = render_performance_section(
        rows, ticker="AAR.AX", horizon="1Y", view="rebased"
    )

    assert "STALE_OMITTED" in html


def test_performance_chart_has_an_accessible_data_table_twin():
    """Every chart on this page carries a text equivalent; the performance
    chart was the last one without. The twin must print the PUBLISHED values
    verbatim — one row per drawn date, no recomputation, nothing truncated."""
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="rebased"
    )
    assert "chart-data-details" in html
    assert 'id="chart-data-performance-aar-ax-1y-rebased"' in html
    assert "<summary>Chart data (table)</summary>" in html
    # the fixture's five business days are all listed, none dropped
    dates = [str(value.date()) for value in pd.bdate_range("2026-01-05", periods=5)]
    for date in dates:
        assert f"<th scope=\"row\">{date}</th>" in html
    # ...and each cell is the fixture's own value, formatted once
    for index, date in enumerate(dates):
        value = 100.0 + index
        label = "0%" if index == 0 else f"+{index}%"
        assert f'<td class="numeric">{value:.1f} ({label})</td>' in html, date
    # both drawn series get a column; the omitted one is not invented
    assert '<th scope="col" class="numeric">Stock</th>' in html
    assert '<th scope="col" class="numeric">Gold</th>' in html
    assert '<th scope="col" class="numeric">GDX</th>' not in html


def test_performance_section_price_view_shows_stock_alone():
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="price"
    )
    assert "Share price (USD)" in html
    assert "basis: USD-normalized price (adjusted close where available)" in html
    assert "return_basis_usd" not in html
    assert "Gold" not in html.split("chart-axis")[0] or "Stock" in html


def test_performance_compare_discloses_every_distinct_drawn_series_basis():
    rows = _healthy_four_series_performance_rows()
    basis_by_series = {
        "stock": "return_basis_usd",
        "gold": "close_usd",
        "gdx": "adj_close_local",
        "gdxj": "close_local",
    }
    for series, basis in basis_by_series.items():
        rows.loc[
            rows["series"].eq(series) & rows["view"].eq("rebased"),
            "price_basis",
        ] = basis

    html = render_performance_section(
        rows, ticker="AAR.AX", horizon="1Y", view="rebased"
    )

    assert "Stock — USD-normalized price (adjusted close where available)" in html
    assert "Gold — USD-normalized close" in html
    assert "GDX — local-currency adjusted close" in html
    assert "GDXJ — local-currency close" in html
    for token in basis_by_series.values():
        assert token not in html


def test_performance_price_view_hides_compare_benchmark_notices():
    rows = _performance_rows()
    stale_gdx_reason = "gdx last observation is 9 trading day(s) behind"

    price = render_performance_section(rows, ticker="AAR.AX", horizon="1Y", view="price")
    compare = render_performance_section(
        rows, ticker="AAR.AX", horizon="1Y", view="rebased"
    )

    assert stale_gdx_reason not in price.lower()
    assert stale_gdx_reason in compare.lower()


def test_performance_stock_notice_remains_visible_in_both_views():
    rows = _performance_rows()
    stock_rows = rows["series"].eq("stock")
    stale_stock_reason = "stock last observation is 4 trading day(s) behind"
    rows.loc[stock_rows, "series_status"] = "STALE_OMITTED"
    rows.loc[stock_rows, "series_reason"] = stale_stock_reason

    price = render_performance_section(rows, ticker="AAR.AX", horizon="1Y", view="price")
    compare = render_performance_section(
        rows, ticker="AAR.AX", horizon="1Y", view="rebased"
    )

    assert stale_stock_reason in price.lower()
    assert stale_stock_reason in compare.lower()


def test_performance_price_view_is_currency_true_end_to_end():
    """The share-price view draws currency levels, so every user-facing string
    from the hint down to the accessible cell must say currency — and none of
    them may repeat the Compare view's indexed-to-100 language."""
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="price"
    )

    chart = html[html.index("<svg") : html.index("</details>")]
    # hint + chart identity
    assert "Share price (USD)" in html
    assert 'aria-label="Share price over time (USD)"' in chart
    # axis labels are the fixture's own price levels (50.0 .. 54.0), in USD
    assert 'class="chart-label">USD 50.00</text>' in chart
    assert 'class="chart-label">USD 54.00</text>' in chart
    # the crosshair reads pre-formatted strings from the embed — currency included,
    # so the pointer tooltip cannot disagree with the axis or the table
    overlay = json.loads(unescape(re.search(r'data-overlay="([^"]+)"', chart).group(1)))
    stock = overlay["series"][0]
    assert stock["label"] == "Stock"
    assert stock["byDate"]["2026-01-05"] == [pytest.approx(212.0, abs=40.0), 50.0, "USD 50.00"]
    assert "base" not in overlay  # no base-100 anchor travels to a currency chart
    # accessible twin: caption states the unit, cells carry it, every date listed
    assert "<caption>Share price over time — USD per share</caption>" in chart
    assert 'aria-label="Share price over time — chart data table"' in chart
    for index, date in enumerate(pd.bdate_range("2026-01-05", periods=5)):
        assert f"<th scope=\"row\">{date.date()}</th>" in chart
        assert f'<td class="numeric">USD {50.0 + index:.2f}</td>' in chart
    # nothing in the chart claims an index or a percent change
    for wrong in ("indexed", "Rebased", "rebase", "%"):
        assert wrong not in chart, wrong


def test_performance_price_view_degrades_when_the_artifact_states_no_currency():
    """Currency comes from the artifact's ``currency_basis``, never from the
    ticker. Without a usable one the chart is withheld and the gap is stated —
    an unlabelled price axis would be an invented unit."""
    rows = _performance_rows()
    rows.loc[rows["view"].eq("price"), "currency_basis"] = pd.NA

    html = render_performance_section(rows, ticker="AAR.AX", horizon="1Y", view="price")

    assert "does not state a currency basis" in html
    assert "Share price (currency basis unavailable)" in html
    assert "Share price (USD)" not in html
    assert "<svg" not in html  # no chart drawn with a guessed unit
    # ...and the control: the same artifact still renders the Compare view
    compare = render_performance_section(
        rows, ticker="AAR.AX", horizon="1Y", view="rebased"
    )
    assert "<svg" in compare
    assert "does not state a currency basis" not in compare


def test_performance_price_view_withholds_the_chart_when_the_rows_disagree():
    """Two currencies in one drawn window is not a currency basis at all.

    Picking either would mislabel half the line, and picking "the first one" is
    a guess — the chart is withheld and the gap stated, exactly as for a missing
    basis. Neither code may reach the screen."""
    rows = _performance_rows()
    price_stock = rows["view"].eq("price") & rows["series"].eq("stock")
    rows.loc[price_stock, "currency_basis"] = "USD"
    rows.loc[rows.index[price_stock][0], "currency_basis"] = "CAD"

    html = render_performance_section(rows, ticker="AAR.AX", horizon="1Y", view="price")

    assert "does not state a currency basis" in html
    assert "Share price (currency basis unavailable)" in html
    assert "<svg" not in html  # no chart drawn under a guessed unit
    assert "Share price (USD)" not in html
    assert "Share price (CAD)" not in html
    assert "CAD" not in html  # the disagreeing codes are not printed anywhere
    # ...and the control: Compare is indexed, so it is unaffected by the clash
    compare = render_performance_section(rows, ticker="AAR.AX", horizon="1Y", view="rebased")
    assert "<svg" in compare
    assert "does not state a currency basis" not in compare


def test_performance_price_view_with_nothing_drawable_claims_no_currency():
    """Nothing drawn is not the same failure as nothing labelled: with every
    price row non-OK there is no line to mislabel, so the section says the
    window is empty and the hint stays a plain "Share price" — it must not
    accuse the artifact of withholding a currency basis it was never asked for."""
    rows = _performance_rows()
    price = rows["view"].eq("price")
    rows.loc[price, "series_status"] = "MISSING_HISTORY"
    rows.loc[price, "series_reason"] = "no price history published for this window"

    html = render_performance_section(rows, ticker="AAR.AX", horizon="1Y", view="price")

    assert "No drawable series in this window." in html
    assert "Share price · horizon 1Y" in html
    assert "currency basis unavailable" not in html
    assert "does not state a currency basis" not in html
    assert "<svg" not in html
    # the reason each series is absent is still stated, never a silent gap
    assert "no price history published for this window" in html


def test_performance_price_view_rejects_a_non_currency_basis_value():
    rows = _performance_rows()
    rows.loc[rows["view"].eq("price"), "currency_basis"] = "INDEX_100"

    html = render_performance_section(rows, ticker="AAR.AX", horizon="1Y", view="price")

    assert "does not state a currency basis" in html
    assert "INDEX_100" not in html


def test_performance_rebased_view_keeps_the_indexed_chart_contract():
    """Back-compat control for the display-mode work: Compare is untouched."""
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="rebased"
    )

    assert 'aria-label="Rebased price comparison"' in html
    assert (
        "<caption>Rebased price comparison — indexed value "
        "(change vs the rebase start)</caption>"
    ) in html
    assert '<td class="numeric">100.0 (0%)</td>' in html


# ---------------------------------------------------------------------------
# currency attribution
# ---------------------------------------------------------------------------


def test_currency_attribution_offset_headline_and_components():
    html = render_currency_attribution_block(_fx_row(), ticker="AAR.AX", horizon="1Y")
    assert "Currency attribution" in html
    assert "FX changed the USD return by +7.7 percentage points." in html
    assert "AUD strength offset about 87% of AAR.AX&#x27;s local-currency decline." in html
    assert "Local share return (AUD)" in html
    assert "-8.8%" in html
    assert "+8.4%" in html
    assert "USD-investor return" in html
    assert "-1.1%" in html
    assert html.count('<td class="numeric">') == 4
    assert '<th scope="row">Local share return (AUD)</th>' in html
    assert "AUDUSD=X" in html
    assert "2025-08-08 to 2026-08-07" in html
    assert "price basis USD-normalized price (adjusted close where available)" in html
    assert "return_basis_usd" not in html
    assert "adj_close_" not in html
    # the rejected device must never appear
    assert "$100" not in html


def test_currency_attribution_hides_usd_listings_entirely():
    frame = _fx_row(
        quote_currency="USD",
        relationship="NOT_APPLICABLE_USD",
        attribution_status="NOT_APPLICABLE_USD",
    )
    assert render_currency_attribution_block(frame, ticker="NEM", horizon="1Y") == ""


def test_currency_attribution_preserves_degraded_artifact_reason():
    state = TickerPageArtifactState(
        status="STALE", reason="refresh ids disagree", frame=pd.DataFrame()
    )

    html = render_currency_attribution_block(
        pd.DataFrame(), ticker="AAR.AX", horizon="1Y", artifact_state=state
    )

    assert "STALE" in html
    assert "refresh ids disagree" in html


def test_currency_attribution_unavailable_states_its_reason():
    frame = _fx_row(
        attribution_status="UNAVAILABLE",
        relationship="UNAVAILABLE",
        attribution_reason="start endpoint 2025-08-08 lacks a usable local value or FX rate",
    )
    html = render_currency_attribution_block(frame, ticker="AAR.AX", horizon="1Y")
    assert "lacks a usable local value or FX rate" in html
    assert "FX changed the USD return" not in html  # no fabricated attribution


def test_currency_attribution_never_headlines_a_blind_fx_over_usd_ratio():
    """Near-cancelling legs: the OFFSET headline uses offset_of_local_move,

    never fx/usd (which would read ~-670%)."""
    frame = _fx_row(usd_return=-0.0011, offset_of_local_move=0.99)
    html = render_currency_attribution_block(frame, ticker="AAR.AX", horizon="1Y")
    assert "offset about 99%" in html
    assert "-670" not in html and "670%" not in html


# ---------------------------------------------------------------------------
# cost position and downside record
# ---------------------------------------------------------------------------


def test_cost_downside_card_shows_exact_evidence_and_caveat():
    downside = _metric_row(
        metric_key="downside_hit_rate",
        raw_value=0.0526,
        pct_low_good=61.0,
        eligible_observation_count=57,
        hit_count=3,
        source_period_start=pd.Timestamp("2016-02-05"),
        source_period_end=pd.Timestamp("2026-07-31"),
        source_verification_status=None,
        source_verification_date=None,
    )
    config = _app_config()
    html = render_cost_downside_card(
        ticker="AAR.AX",
        aisc_row=_metric_row(),
        downside_row=downside,
        aisc_peers=_peers("aisc", {"AAR.AX": 1419.0, "BBB": 1800.0, "CCC": 1200.0}),
        downside_peers=_peers(
            "downside_hit_rate", {"AAR.AX": 0.0526, "BBB": 0.20, "CCC": 0.10}
        ),
        app_config=config,
    )
    assert "Cost position and downside record" in html
    assert "$1,419/oz" in html
    assert "Our View mining assumption" in html
    assert "verification: VERIFIED (2026-06-30)" in html
    # exact numerator/denominator — never a bare rounded rate
    assert "3 large falls in 57 qualifying weak-gold weeks" in html
    assert "5.3%" in html
    assert "Period 2016-02-05 to 2026-07-31" in html
    # The large-fall cut-off is stated ONCE, resolved from config by the help
    # registry — the card carries no hardcoded twin of that number.
    cutoff = (
        f"A large fall is a weekly price return of "
        f"{config.tool_c.downside_hit_rate_threshold_pct:.0f}% or worse."
    )
    assert cutoff in html
    # ...and the deleted hardcoded twin (its own wording, with a typographic
    # minus) is really gone rather than merely duplicated somewhere else.
    assert "ordinary weekly price return of −10% or worse" not in html
    # peer disclosure closed by default with its accessible table twin
    assert "<details" in html and "Peer relationship" in html
    assert "no fitted line" in html
    assert "does not establish" in html  # the required caveat
    assert '<th scope="col">Ticker</th>' in html
    assert '<th scope="col" class="numeric">Reported AISC</th>' in html
    assert '<th scope="col" class="numeric">Large-fall rate</th>' in html
    assert '<td>AAR.AX</td><td class="numeric">$1,419/oz</td>' in html
    assert '<td class="numeric">5.3%</td>' in html
    # no composite score and no causal wording
    assert "score" not in html.lower() or "no combined score" in html.lower()


def test_cost_downside_card_accepts_nullable_parquet_metadata():
    html = render_cost_downside_card(
        ticker="AAR.AX",
        aisc_row=_metric_row(
            basis=pd.NA,
            source_verification_status=pd.NA,
            source_verification_date=pd.NA,
        ),
        downside_row=None,
        aisc_peers=pd.DataFrame(),
        downside_peers=pd.DataFrame(),
        app_config=_app_config(),
    )

    assert "$1,419/oz" in html
    assert "verification:" not in html


def test_cost_downside_card_accepts_nullable_availability_flags():
    html = render_cost_downside_card(
        ticker="AAR.AX",
        aisc_row=_metric_row(metric_available=pd.NA, metric_reason=pd.NA),
        downside_row=_metric_row(metric_available=pd.NA, metric_reason=pd.NA),
        aisc_peers=pd.DataFrame(),
        downside_peers=pd.DataFrame(),
        app_config=_app_config(),
    )

    assert "AISC is unavailable: not available" in html
    assert "downside record is unavailable: not available" in html


def test_cost_downside_card_missing_sides_render_reasons_not_conclusions():
    html = render_cost_downside_card(
        ticker="AAR.AX",
        aisc_row=_metric_row(metric_available=False, metric_reason="value_missing"),
        downside_row=None,
        aisc_peers=pd.DataFrame(),
        downside_peers=pd.DataFrame(),
    )
    assert "AISC is unavailable: value_missing" in html
    assert "The downside record is unavailable" in html
    assert "No eligible paired producers to plot." in html


# ---------------------------------------------------------------------------
# guardrail: the new serve package computes nothing
# ---------------------------------------------------------------------------


def test_ticker_page_serve_package_has_no_backend_arithmetic():
    """Clone of the Tool-D serve-arithmetic guardrail for serve/ticker_page/.

    The sections render persisted columns only. Formatting multiplies by 100
    for display; no ratio math, coalescing, or eligibility logic may creep in.
    """
    for name in (
        "sections.py",
        "data.py",
        "corporate.py",
        "behaviour.py",
        "compare.py",
        "__init__.py",
    ):
        source = Path(f"golden_vector/serve/ticker_page/{name}").read_text(encoding="utf-8")
        for forbidden in (
            ".fillna(",
            ".combine_first(",
            "usd_return -",          # contribution is persisted, never re-derived
            "/ base_value",
            "log1p",
            "oriented_percentile",
            "np.",
            "import numpy",
        ):
            assert forbidden not in source, f"{name}: {forbidden}"


def test_corporate_section_contains_no_arithmetic_at_all():
    """Stricter than the token sweep, because corporate.py is where the gold

    maths WANTS to leak in: the dial's scenario values must come from
    gold-dial.js evaluating persisted lines, never from the request path.

    An AST scan is used rather than string matching so a rename or a clever
    one-liner cannot slip past. String concatenation (``+``) stays legal —
    that is markup assembly; every other binary operator is banned.
    """
    import ast

    path = Path("golden_vector/serve/ticker_page/corporate.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = (ast.Mult, ast.Div, ast.FloorDiv, ast.Sub, ast.Pow, ast.Mod, ast.MatMult)
    offenders = [
        f"line {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, banned)
    ]
    assert not offenders, "arithmetic in serve/ticker_page/corporate.py: " + "; ".join(
        offenders
    )


def test_gold_dial_js_guards_mirror_the_screening_layers():
    """The client module is the sanctioned exception (plan §3.1) — it must carry

    the SAME guards the backend screens on, spelled out, so a reviewer can
    diff them against screening/layer1.py and layer2.py."""
    source = Path("golden_vector/serve/static/gold-dial.js").read_text(encoding="utf-8")
    assert "screening/layer1.py" in source and "screening/layer2.py" in source
    for reason in (
        "Not meaningful — EBITDA ≤ 0",
        "Not meaningful — EPS ≤ 0",
        "Not meaningful — market cap ≤ 0",
    ):
        assert reason in source, reason
    # no network, no third-party libraries, no shared mutable state
    for forbidden in ("fetch(", "XMLHttpRequest", "import ", "require(", "localStorage"):
        assert forbidden not in source, forbidden
    # the dial position is ephemeral by design — it must never touch the URL
    for forbidden in ("history.pushState", "history.replaceState", "location.search"):
        assert forbidden not in source, forbidden
    # a disabled dial replaces the no-JavaScript fallback with the real reason
    assert "payload.disabled_reason" in source
    assert 'setAttribute("data-unavailable", "1")' in source
    # reduced motion is honoured, and the live region is polite and single
    assert "prefers-reduced-motion: reduce" in source
    assert source.count('var STATUS_ID = "gold-dial-status"') == 1


# ---------------------------------------------------------------------------
# M3f: help-key integrity across the five ticker-page render modules
# ---------------------------------------------------------------------------


def _referenced_help_keys() -> dict[str, set[str]]:
    """Every registry key the five render modules ask for, by module.

    The negative lookbehind keeps ``metric_key=`` (a DATA lookup) out — only
    ``key=`` / ``help_key=`` name a help entry.
    """
    import re

    found: dict[str, set[str]] = {}
    for module in sorted(Path("golden_vector/serve/ticker_page").glob("*.py")):
        source = module.read_text(encoding="utf-8")
        keys = set(
            re.findall(r'(?<!\w)(?:help_key|key)\s*=\s*"([a-z0-9_]+)"', source)
        )
        if keys:
            found[module.name] = keys
    return found


def test_every_help_key_the_ticker_page_asks_for_actually_exists():
    """``help_icon`` returns "" for an unknown key — silently, with no error.

    So a renamed or deleted registry entry does not fail anywhere: it just
    deletes a "?" from the page. This is the test that makes that loud.
    """
    from golden_vector.serve.column_help import COLUMN_HELP

    referenced = _referenced_help_keys()
    assert referenced, "no help keys found — the scan itself is broken"

    unknown = {
        (module, key)
        for module, keys in referenced.items()
        for key in keys
        if key not in COLUMN_HELP
    }
    assert not unknown, sorted(unknown)

    # The indirection tables resolve too — they are the easiest to let rot.
    from golden_vector.serve.ticker_page.compare import METRIC_HELP_KEYS
    from golden_vector.serve.ticker_page.corporate import _METRIC_HELP_KEYS

    for table_name, table in (
        ("compare.METRIC_HELP_KEYS", METRIC_HELP_KEYS),
        ("corporate._METRIC_HELP_KEYS", _METRIC_HELP_KEYS),
    ):
        missing = sorted(k for k in table.values() if k not in COLUMN_HELP)
        assert not missing, f"{table_name}: {missing}"


def test_help_entries_the_ticker_page_uses_are_not_empty():
    """An entry with no ``meaning`` renders no icon at all — same silent failure
    as a missing key, so it is held to the same standard."""
    from golden_vector.serve.column_help import COLUMN_HELP

    thin = []
    for keys in _referenced_help_keys().values():
        for key in keys:
            entry = COLUMN_HELP.get(key)
            if entry is None:
                continue
            if not str(getattr(entry, "meaning", "") or "").strip():
                thin.append(key)
    assert not thin, sorted(set(thin))
