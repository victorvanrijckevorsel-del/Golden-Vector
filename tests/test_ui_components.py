"""Contracts for the pure presentation primitives (plan sections 10.3, 10.5, 11.1)."""

from __future__ import annotations

import pytest

import golden_vector.serve.page_shell as page_shell_facade
import golden_vector.serve.ui.shell as ui_shell
from golden_vector.serve.ui import components, status, tables


def test_page_shell_facade_reexports_the_shell_implementation():
    """The facade must stay a pure alias — one shell, two import paths."""
    assert page_shell_facade._page_shell is ui_shell._page_shell
    assert page_shell_facade._NAV_LINKS is ui_shell._NAV_LINKS
    assert page_shell_facade._NAV_GROUPS is ui_shell._NAV_GROUPS


def test_page_header_escapes_title_and_places_fragments():
    html = components.page_header(
        'A <"scary"> & title',
        lead_html="<p>lead copy</p>",
        actions_html='<a class="btn btn-secondary" href="/x">Act</a>',
    )
    assert "A &lt;&quot;scary&quot;&gt; &amp; title" in html
    assert "<script" not in html
    assert '<div class="page-lead"><p>lead copy</p></div>' in html
    assert '<div class="page-actions"><a class="btn btn-secondary"' in html
    assert html.startswith('<header class="page-header">')
    assert html.count("<h1>") == 1


def test_page_header_omits_empty_slots():
    html = components.page_header("T")
    assert "page-lead" not in html
    assert "page-actions" not in html


def test_section_heading_levels_help_and_actions():
    html = components.section_heading(
        "Metrics", help_html='<button class="help-icon">i</button>'
    )
    assert html.count("<h2>") == 1
    assert 'class="help-icon"' in html
    assert "section-actions" not in html
    with_actions = components.section_heading("Sub", level=3, actions_html="<a>x</a>")
    assert "<h3>" in with_actions and 'class="section-actions"' in with_actions
    with pytest.raises(ValueError):
        components.section_heading("Bad", level=7)


def test_toolbar_role_group_and_escaped_label():
    html = components.toolbar("<button>Go</button>", label='Scenario "controls"')
    assert 'role="group"' in html
    assert 'aria-label="Scenario &quot;controls&quot;"' in html
    assert "<button>Go</button>" in html


def test_empty_state_escapes_title_and_keeps_body():
    html = components.empty_state("No rows <yet>", body_html="<p>Run tool-a.</p>")
    assert 'class="empty-state"' in html
    assert "No rows &lt;yet&gt;" in html
    assert "<p>Run tool-a.</p>" in html


def test_disclosure_expanded_flag_and_class():
    closed = components.disclosure("<span>More</span>", "<p>Body</p>")
    assert closed.startswith('<details class="disclosure">')
    assert "<summary><span>More</span></summary>" in closed
    assert " open>" not in closed
    opened = components.disclosure("s", "b", expanded=True, class_name="pilot-x")
    assert '<details class="disclosure pilot-x" open>' in opened


def test_notice_tones_roles_and_legacy_flash_class():
    html = status.notice("success", "<p>Saved gold price.</p>")
    assert '<div class="flash notice notice-success" role="status">' in html
    assert status.notice("danger", "x").count('role="alert"') == 1
    assert 'role="status"' in status.notice("info", "x")
    assert 'role="alert"' in status.notice("degraded", "x")
    with pytest.raises(ValueError):
        status.notice("shiny", "x")


def test_notice_covers_the_section_10_5_tones():
    assert set(status.NOTICE_TONES) == {
        "success",
        "info",
        "warning",
        "danger",
        "degraded",
        "neutral",
    }


def test_table_region_contract():
    html = tables.table_region(
        "<table><tbody><tr><td>1</td></tr></tbody></table>",
        region_id="cf-results-region",
        label='Candidate "results"',
    )
    assert html.startswith('<div class="table-region" id="cf-results-region" role="region"')
    assert 'aria-label="Candidate &quot;results&quot;"' in html
    assert 'tabindex="0"' in html
    assert html.endswith("</table></div>")
