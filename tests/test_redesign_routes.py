"""Pre-migration route characterization tests (visual redesign plan, Phase 0 task 13).

These pin CURRENT behaviour before any shared markup is extracted, covering the
gaps the 2026-08-10 audit confirmed: no WSGI coverage for /scorecard, the
reporting POST, Portfolio lot edit/delete, unknown ticker/action pages, and
unsupported-method requests. The app has no 405 or HEAD handling — method
mismatches fall through to a 404 in one of two flavours — and that reality is
pinned exactly. Tests marked ``known-defect`` characterize behaviour recorded
in reviews/codex/milestones/visual_redesign/defect_register.md; they document
what the app DOES today, not the desired contract.
"""

from __future__ import annotations

import re

import pytest

from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths, call_wsgi_app
from tests.test_portfolio_m1 import _portfolio_config, _write_foundation_snapshot
from tests.test_workspace_app import (
    _repo_app_config,
    _write_latest_foundation_snapshot,
    _write_latest_outputs,
)


def _minimal_app(tmp_path):
    """App with a bootstrapped manual store and no model artifacts."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    app = create_workspace_app(paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"])
    return paths, app


def _full_app(tmp_path):
    """App with foundation snapshot and Tool A-D artifacts for NEM."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    app = create_workspace_app(paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"])
    return paths, app


def _portfolio_app(tmp_path, *, enabled: bool = True):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config(enabled=enabled)
    if enabled:
        _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    return paths, app


_LOT_PAYLOAD = {
    "ticker": "NEM",
    "shares": "2",
    "buy_price": "50",
    "buy_currency": "USD",
    "buy_date": "2026-01-02",
    "note": "initial-note-marker",
}


# ---------------------------------------------------------------- /scorecard


def test_scorecard_route_renders_not_built_state(tmp_path):
    _, app = _minimal_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/scorecard")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "<h1>Evidence Scorecard</h1>" in body
    assert "Scorecard is not built yet." in body
    assert '<a class="nav-link" aria-current="page" href="/scorecard">Scorecard</a>' in body


# ------------------------------------------------------- reporting POST route


def test_reporting_post_saves_dates_and_notes_and_redirects(tmp_path):
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "2026-09-15",
            "next_production_report_date": "2026-10-01",
            "notes": "Q3 update marker",
            "return_to": "/ticker/NEM?window=6M",
        },
    )

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/ticker/NEM?window=6M&saved=reporting"

    page = call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert 'value="2026-09-15"' in page["body"]
    assert 'value="2026-10-01"' in page["body"]
    assert "Q3 update marker" in page["body"]


def test_reporting_post_blank_clears_stored_values(tmp_path):
    _, app = _full_app(tmp_path)
    call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "2026-09-15",
            "next_production_report_date": "2026-10-01",
            "notes": "Q3 update marker",
        },
    )

    # Reporting deliberately differs from company inputs: blank means CLEAR.
    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "",
            "next_production_report_date": "",
            "notes": "",
        },
    )

    assert response["status"].startswith("303")
    page = call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert 'value="2026-09-15"' not in page["body"]
    assert 'value="2026-10-01"' not in page["body"]
    assert "Q3 update marker" not in page["body"]


def test_reporting_post_invalid_date_crashes_to_500_with_tool_a_data(tmp_path):
    """known-defect D1: with Tool A artifacts present (every real ticker), the
    validation-error re-render passes app_config=None, build_delta_explanation
    raises AttributeError, and the user sees the generic 500 page instead of a
    400 with their input context. Pinned as current behaviour; the fix is a
    post-Phase-8 defect-register commit, not part of the visual migration."""
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/reporting",
        data={
            "next_financial_report_date": "not-a-date",
            "next_production_report_date": "",
            "notes": "",
        },
    )

    assert response["status"].startswith("500")
    assert "The workspace hit an unexpected error." in response["body"]


# ------------------------------------------- Portfolio lot edit/delete routes


def _add_lot_and_get_id(app) -> str:
    added = call_wsgi_app(app, method="POST", path="/portfolio/lots", data=_LOT_PAYLOAD)
    assert added["status"].startswith("303")
    assert added["headers"]["Location"] == "/portfolio?saved=portfolio"
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    match = re.search(r'/portfolio/lots/([^/"]+)/edit', page["body"])
    assert match, "expected an edit form for the added lot"
    return match.group(1)


def test_portfolio_lot_edit_route_updates_lot_and_redirects(tmp_path):
    _, app = _portfolio_app(tmp_path)
    lot_id = _add_lot_and_get_id(app)

    response = call_wsgi_app(
        app,
        method="POST",
        path=f"/portfolio/lots/{lot_id}/edit",
        data={**_LOT_PAYLOAD, "shares": "3", "note": "edited-note-marker"},
    )

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/portfolio?saved=portfolio"
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    assert "edited-note-marker" in page["body"]
    assert "initial-note-marker" not in page["body"]


def test_portfolio_lot_delete_route_removes_lot_and_redirects(tmp_path):
    _, app = _portfolio_app(tmp_path)
    lot_id = _add_lot_and_get_id(app)

    response = call_wsgi_app(app, method="POST", path=f"/portfolio/lots/{lot_id}/delete")

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/portfolio?saved=portfolio"
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    assert f"/portfolio/lots/{lot_id}/edit" not in page["body"]
    assert "initial-note-marker" not in page["body"]


def test_portfolio_lot_edit_unknown_id_returns_400_with_error(tmp_path):
    _, app = _portfolio_app(tmp_path)
    _add_lot_and_get_id(app)

    response = call_wsgi_app(
        app,
        method="POST",
        path="/portfolio/lots/does-not-exist/edit",
        data=_LOT_PAYLOAD,
    )

    assert response["status"].startswith("400")
    # The portfolio page re-renders with the store error; the lot survives.
    page = call_wsgi_app(app, method="GET", path="/portfolio")
    assert "initial-note-marker" in page["body"]


def test_portfolio_lots_get_is_unsupported_route_404(tmp_path):
    _, app = _portfolio_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/portfolio/lots")

    assert response["status"].startswith("404")
    assert "Unsupported portfolio route." in response["body"]


def test_portfolio_lots_disabled_403_takes_precedence_over_method(tmp_path):
    _, app = _portfolio_app(tmp_path, enabled=False)

    # The enablement check runs before the method check on /portfolio/lots*.
    response = call_wsgi_app(app, method="GET", path="/portfolio/lots")

    assert response["status"].startswith("403")
    assert "Portfolio is disabled" in response["body"]


# --------------------------------------- unknown ticker / action / method 404s


def test_unknown_ticker_renders_scoped_404(tmp_path):
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="GET", path="/ticker/ZZZZ")

    assert response["status"].startswith("404")
    assert "ZZZZ is not an active Corporate Finance ticker." in response["body"]


def test_unknown_ticker_action_renders_unsupported_route_404(tmp_path):
    _, app = _full_app(tmp_path)

    response = call_wsgi_app(app, method="POST", path="/ticker/NEM/bogus-action")

    assert response["status"].startswith("404")
    assert "Unsupported workspace route." in response["body"]


@pytest.mark.parametrize(
    ("method", "path", "expected_snippet"),
    [
        ("POST", "/tool-a", "Page not found."),
        ("POST", "/", "Page not found."),
        ("GET", "/refresh", "Page not found."),
        ("GET", "/option-trading/refresh", "Page not found."),
        ("DELETE", "/tool-b", "Page not found."),
        ("HEAD", "/", "Page not found."),
        ("POST", "/portfolio", "Page not found."),
        ("POST", "/static/workspace.css", "Page not found."),
        ("PUT", "/ticker/NEM", "Unsupported workspace route."),
        ("GET", "/ticker/NEM/company", "Unsupported workspace route."),
    ],
)
def test_method_mismatches_fall_through_to_404_not_405(tmp_path, method, path, expected_snippet):
    """The app has no 405 and no HEAD handling; every mismatch is a 404 page."""
    _, app = _minimal_app(tmp_path)

    response = call_wsgi_app(app, method=method, path=path)

    assert response["status"].startswith("404")
    assert "405" not in response["status"]
    assert expected_snippet in response["body"]


def test_ticker_detail_section_nav_lists_every_present_section(tmp_path):
    """Plan 15/23: sticky in-page anchors on the detail page — every anchor in
    the nav resolves to a real section id for the mining-ticker lens."""
    _paths, app = _full_app(tmp_path)
    body = call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]
    assert '<nav class="section-nav" aria-label="On this page">' in body
    for fragment, label in (
        ("gold-sensitivity", "Gold Sensitivity"),
        ("charts", "Charts"),
        ("corporate-finance", "Corporate Finance"),
        ("option-trading", "Option Trading"),
        ("inputs", "Inputs"),
        ("reporting", "Reporting"),
        ("verification", "Verification"),
        ("notes", "Notes"),
    ):
        assert f'href="#{fragment}">{label}</a>' in body
        assert f'id="{fragment}"' in body  # the anchor target really exists
