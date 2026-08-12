"""Phase 4 contracts for the ticker command bar and manual workspace."""

from __future__ import annotations

import re
from decimal import Decimal

import pandas as pd

from golden_vector.app.ticker_page_state import TickerPageArtifactState
from golden_vector.contracts.ticker_page import GOLD_RESPONSE_LINE_METRICS
from golden_vector.serve.detail_page import _ticker_quote_html
from golden_vector.serve.ticker_page import GOLD_DIAL_PAYLOAD_ID, TickerPageData
from tests.helpers import call_wsgi_app
from tests.test_ticker_page_corporate import _gold_row
from tests.test_ticker_page_sections import _performance_rows
from tests.test_workspace_app import _m3b_app


def _details_tag(body: str, element_id: str) -> str:
    match = re.search(rf'<details\b[^>]*\bid="{re.escape(element_id)}"[^>]*>', body)
    assert match, f"missing details#{element_id}"
    return match.group(0)


def test_ticker_command_bar_uses_configured_identity_quote_and_neutral_shell(tmp_path):
    _paths, app = _m3b_app(tmp_path)

    body = call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]

    assert 'data-page="ticker_detail"' in body
    assert '<div class="terminal-density">' in body
    assert 'class="command-bar ticker-command-bar"' in body
    assert '<h1 class="ticker-identity__symbol">NEM</h1>' in body
    assert "Newmont Corporation" in body
    assert "USD listing" in body
    assert "Jurisdiction tier 2" in body
    # The house money convention (format_metric "usd2"), not the page's one
    # "US$": the identity line right above already says "USD listing".
    assert 'class="ticker-quote__value">$100.00</span>' in body
    assert "US$" not in body
    assert "Market date 22 Apr 2026" in body
    assert 'aria-current="page"' not in body
    assert '<span class="app-header-title">NEM · Newmont Corporation</span>' in body


def test_usd_normalized_quote_is_never_mislabeled_as_listing_currency():
    html = _ticker_quote_html(
        {"share_price_usd": 42.5, "as_of_date": "2026-08-12"}
    )

    # One money convention on this page: the shared format_metric "$" style.
    assert '<span class="ticker-quote__value">$42.50</span>' in html
    assert "US$" not in html
    # ...and the USD-normalized number still never borrows a listing currency.
    assert "AUD" not in html
    assert "CAD" not in html


def test_command_bar_omits_missing_quote_fields_instead_of_guessing():
    assert _ticker_quote_html({}) == ""
    html = _ticker_quote_html({"share_price_usd": 42.5})
    assert "$42.50" in html
    assert "Market date" not in html


def test_ticker_jump_lists_only_route_allowed_tickers_and_preserves_source(tmp_path):
    _paths, app = _m3b_app(tmp_path)

    body = call_wsgi_app(
        app,
        method="GET",
        path="/ticker/NEM?fundamentals_source=yahoo",
    )["body"]

    form = body[body.index('<form class="ticker-jump-form"') :]
    form = form[: form.index("</form>")]
    assert 'method="get" action="/ticker"' in form
    assert 'name="ticker"' in form
    assert '<option value="NEM">' in form
    assert '<option value="AEM">' not in form
    assert 'name="fundamentals_source" value="yahoo"' in form
    # W7: the form carries the page it was submitted FROM, so a mistyped jump
    # can offer a way back instead of a workspace-only dead end.
    assert 'name="from" value="NEM"' in form

    jumped = call_wsgi_app(
        app,
        method="GET",
        path="/ticker?ticker=nem&fundamentals_source=yahoo&gold_price=9999",
    )
    assert jumped["status"].startswith("303")
    assert jumped["headers"]["Location"] == "/ticker/NEM?fundamentals_source=yahoo"

    unknown = call_wsgi_app(app, method="GET", path="/ticker?ticker=BOGUS")
    assert unknown["status"].startswith("404")
    assert "BOGUS is not one of your tracked tickers." in unknown["body"]
    assert "Corporate Finance ticker" not in unknown["body"]


def test_unknown_jump_offers_the_originating_ticker_page_with_its_source(tmp_path):
    """W7: a mistyped jump is an honest 404, but not a dead end — it links back
    to the ticker page the jump came from, keeping the active financials
    source."""
    _paths, app = _m3b_app(tmp_path)

    unknown = call_wsgi_app(
        app,
        method="GET",
        path="/ticker?ticker=BOGUS&from=nem&fundamentals_source=yahoo",
    )

    assert unknown["status"].startswith("404")
    assert 'href="/ticker/NEM?fundamentals_source=yahoo"' in unknown["body"]
    assert ">Back to NEM</a>" in unknown["body"]
    assert '<a href="/">Back to workspace</a>' in unknown["body"]

    # an unknown origin is ignored rather than rendering a link to a 404
    bogus_origin = call_wsgi_app(
        app,
        method="GET",
        path="/ticker?ticker=BOGUS&from=ZZZZ",
    )
    assert bogus_origin["status"].startswith("404")
    assert "Back to ZZZZ" not in bogus_origin["body"]


def test_source_control_is_segmented_and_preserves_unrelated_query_state(tmp_path):
    _paths, app = _m3b_app(tmp_path)

    body = call_wsgi_app(
        app,
        method="GET",
        path="/ticker/NEM?chart_h=3Y&chart_view=price&window=6M&sb=marker",
    )["body"]

    assert "Financials source" in body
    assert body.count('aria-label="Financials source"') == 1
    source_control = body[body.index('aria-label="Financials source"') :]
    source_control = source_control[: source_control.index("</div>")]
    assert source_control.count('aria-current="true"') == 1
    assert ">Our View</a>" in source_control
    assert ">Yahoo Fundamentals</a>" in source_control
    yahoo_href = re.search(r'href="([^"]+)"[^>]*>Yahoo Fundamentals</a>', source_control)
    assert yahoo_href
    href = yahoo_href.group(1)
    for state in (
        "chart_h=3Y",
        "chart_view=price",
        "window=6M",
        "sb=marker",
        "fundamentals_source=yahoo",
    ):
        assert state in href


def test_manual_workspace_is_closed_by_default_with_four_child_disclosures(tmp_path):
    _paths, app = _m3b_app(tmp_path)

    body = call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]

    assert " open" not in _details_tag(body, "inputs")
    assert '<summary><span class="ticker-inputs__summary-copy">' in body
    assert (
        '<span class="ticker-inputs__title" role="heading" '
        'aria-level="2">Your inputs and notes</span>'
    ) in body
    assert (
        '<span class="hint">Company data, reporting, verification and research notes</span>'
        '</span></summary>'
    ) in body
    for element_id in ("company-inputs", "reporting", "verification", "notes"):
        tag = _details_tag(body, element_id)
        assert 'class="disclosure ticker-inputs__section"' in tag
        assert " open" not in tag
    for endpoint in ("company", "reporting", "verification", "note"):
        assert f'action="/ticker/NEM/{endpoint}"' in body


def test_rejected_form_opens_parent_and_relevant_child_and_focuses_summary(tmp_path):
    _paths, app = _m3b_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "not-a-date",
            "notes": "typed marker",
            "return_to": "/ticker/NEM?fundamentals_source=yahoo",
        },
    )

    assert response["status"].startswith("400")
    body = response["body"]
    assert " open" in _details_tag(body, "inputs")
    assert " open" in _details_tag(body, "reporting")
    for element_id in ("company-inputs", "verification", "notes"):
        assert " open" not in _details_tag(body, element_id)
    assert 'id="inputs-error-summary" tabindex="-1" data-focus-on-load' in body
    assert "typed marker" in body
    assert 'name="return_to" value="/ticker/NEM?fundamentals_source=yahoo"' in body


def test_empty_rejected_verification_post_still_opens_verification_region(tmp_path):
    _paths, app = _m3b_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        data={},
    )

    assert response["status"].startswith("400")
    body = response["body"]
    assert " open" in _details_tag(body, "inputs")
    assert " open" in _details_tag(body, "verification")


# ---------------------------------------------------------------------------
# whole-page composition
# ---------------------------------------------------------------------------


def _drawable_ticker_page_data():
    """One generation with a FINITE spot and drawable performance rows.

    Every other full-page fixture leaves the ticker-page artifacts unpublished,
    so those pages render "Spot gold unavailable" and the scenario markup and
    chart controls count ZERO at page level. Section tests cover each renderer
    in isolation; nothing was checking that the assembled page carries exactly
    one of each shared thing, which is where duplicate payload scripts and
    orphaned cells hide.
    """

    blank = TickerPageArtifactState(status="OK", reason=None, frame=pd.DataFrame())
    performance = _performance_rows()
    performance["ticker"] = "NEM"
    return TickerPageData(
        gold_response=TickerPageArtifactState(
            status="OK", reason=None, frame=pd.DataFrame([_gold_row()])
        ),
        percentiles=blank,
        performance=TickerPageArtifactState(
            status="OK", reason=None, frame=performance
        ),
        research_series=blank,
        fx_attribution=blank,
    )


def test_whole_page_carries_exactly_one_of_each_shared_element(tmp_path, monkeypatch):
    _paths, app = _m3b_app(tmp_path)
    monkeypatch.setattr(
        "golden_vector.serve.workspace.load_ticker_page_data",
        lambda paths: _drawable_ticker_page_data(),
    )

    body = call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]

    # The premise: this page really did resolve a spot, so the counts below are
    # counting present markup rather than a uniformly absent section.
    assert "Spot gold unavailable" not in body
    assert "$4,452.00/oz" in body

    # ONE dial payload for the whole page. The control bar and the section both
    # build a dial from the same helper; a second <script> would mean the two
    # states could diverge, and gold-dial.js reads exactly one by id.
    assert body.count(f'id="{GOLD_DIAL_PAYLOAD_ID}"') == 1

    # Six headline cards, each with exactly one visible value.
    assert body.count('data-headline-spot="1"') == 6
    # Five line metrics evaluated client-side at spot (the ratio metrics are
    # persisted spot columns and are NOT in this set).
    assert body.count('data-basis="spot"') == len(GOLD_RESPONSE_LINE_METRICS) == 5

    # The performance chart and its series controls both rendered.
    assert body.count("data-performance-chart") == 1
    assert body.count("data-performance-series-input") >= 1

    # The dial input opens on a value the stepped control can actually hold, so
    # the page does not boot into a scenario nobody asked for.
    value = re.search(r'id="gold-dial-input"[^>]*\bvalue="([^"]+)"', body)
    assert value is not None
    step = re.search(r'id="gold-dial-input"[^>]*\bstep="([^"]+)"', body)
    minimum = re.search(r'id="gold-dial-input"[^>]*\bmin="([^"]+)"', body)
    assert step is not None and minimum is not None
    offset = Decimal(value.group(1)) - Decimal(minimum.group(1))
    assert offset % Decimal(step.group(1)) == 0
