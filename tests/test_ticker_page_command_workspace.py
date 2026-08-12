"""Phase 4 contracts for the ticker command bar and manual workspace."""

from __future__ import annotations

import re

from golden_vector.serve.detail_page import _ticker_quote_html
from tests.helpers import call_wsgi_app
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
    assert 'class="ticker-quote__value">US$100.00</span>' in body
    assert "Market date 22 Apr 2026" in body
    assert 'aria-current="page"' not in body
    assert '<span class="app-header-title">NEM · Newmont Corporation</span>' in body


def test_usd_normalized_quote_is_never_mislabeled_as_listing_currency():
    html = _ticker_quote_html(
        {"share_price_usd": 42.5, "as_of_date": "2026-08-12"}
    )

    assert "US$42.50" in html
    assert "AUD" not in html
    assert "CAD" not in html


def test_command_bar_omits_missing_quote_fields_instead_of_guessing():
    assert _ticker_quote_html({}) == ""
    html = _ticker_quote_html({"share_price_usd": 42.5})
    assert "US$42.50" in html
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

    jumped = call_wsgi_app(
        app,
        method="GET",
        path="/ticker?ticker=nem&fundamentals_source=yahoo&gold_price=9999",
    )
    assert jumped["status"].startswith("303")
    assert jumped["headers"]["Location"] == "/ticker/NEM?fundamentals_source=yahoo"

    unknown = call_wsgi_app(app, method="GET", path="/ticker?ticker=BOGUS")
    assert unknown["status"].startswith("404")
    assert "BOGUS is not an active Corporate Finance ticker" in unknown["body"]


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
