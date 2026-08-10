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


def test_table_region_rejects_bad_id_and_empty_label():
    """GV-RD-P34-4/5: ids are code constants — fail loud, never emit broken attrs."""
    with pytest.raises(ValueError):
        tables.table_region("<table></table>", region_id="", label="x")
    with pytest.raises(ValueError):
        tables.table_region("<table></table>", region_id='a" onfocus="1', label="x")
    with pytest.raises(ValueError):
        tables.table_region("<table></table>", region_id="ok-id", label="   ")


def test_notice_extra_classes_are_validated_class_tokens():
    """GV-RD-P34-4: extra_classes can never break out of the class attribute."""
    html = status.notice("warning", "x", extra_classes="option-freshness option-freshness-stale")
    assert 'class="flash notice notice-warning option-freshness option-freshness-stale"' in html
    for hostile in ('a" onmouseover="1', "a<b>", 'x="y"', "a\nb"):
        with pytest.raises(ValueError):
            status.notice("warning", "x", extra_classes=hostile)


def test_status_strip_escapes_labels_and_passes_value_fragments():
    html = status.status_strip(
        (('Refresh <"Run">', "<code>run-1</code>"),),
        label='Snapshot "status"',
    )
    assert 'aria-label="Snapshot &quot;status&quot;"' in html
    assert "Refresh &lt;&quot;Run&quot;&gt;" in html  # label escaped here
    assert '<span class="status-item-value"><code>run-1</code></span>' in html  # trusted fragment
    assert 'role="group"' in html


def test_ui_package_imports_stay_presentation_pure():
    """GV-RD-P34-5: serve/ui may import only stdlib presentation basics — never
    app/model/workspace/data modules, so no state decision can migrate in."""
    import ast
    from pathlib import Path

    allowed_roots = {"__future__", "html", "re"}
    for path in sorted(Path("golden_vector/serve/ui").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root in allowed_roots, f"{path.name} imports {name!r}"


def test_refresh_summary_missing_manifest_keeps_visible_context():
    """GV-RD-P34-6: the missing-snapshot branch keeps its visible section
    context, and the populated branch renders the same three labelled values."""
    from golden_vector.serve.overview_helpers import _render_refresh_summary

    empty = _render_refresh_summary(None)
    assert "notice-neutral" in empty
    assert "Latest Market Snapshot." in empty
    assert "No validated local market-data snapshot is available yet." in empty

    populated = _render_refresh_summary(
        {
            "refresh_run_id": "run-42",
            "snapshot_as_of_date": "2026-08-08",
            "foundation_status": "VALIDATED",
        }
    )
    assert 'class="status-strip"' in populated
    for label in ("Refresh Run", "Snapshot As Of", "Foundation Status"):
        assert label in populated
    for value in ("run-42", "2026-08-08", "VALIDATED"):
        assert value in populated
