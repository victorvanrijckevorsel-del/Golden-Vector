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


def test_section_nav_is_anchor_only_and_escaped():
    html = components.section_nav(
        [("gold-sensitivity", "Gold Sensitivity"), ("notes", "No<tes>")]
    )
    assert html.startswith('<nav class="section-nav" aria-label="On this page">')
    assert '<a class="section-nav-link" href="#gold-sensitivity">Gold Sensitivity</a>' in html
    assert "No&lt;tes&gt;" in html
    assert 'href="/' not in html  # anchors, never routes


def test_section_tabs_is_the_compact_section_nav_variant():
    links = [("performance", "Performance"), ("inputs", "Inputs & notes")]
    html = components.section_tabs(links, label='Ticker "sections"')
    assert html.startswith(
        '<nav class="section-nav section-nav--compact" aria-label="Ticker &quot;sections&quot;">'
    )
    assert '<a class="section-nav-link" href="#performance">Performance</a>' in html
    assert "Inputs &amp; notes" in html
    assert 'href="/' not in html


def test_command_bar_escapes_labels_and_preserves_resolved_fragments():
    html = components.command_bar(
        '<strong class="company-name">NEM</strong>',
        navigation_html='<form action="/ticker"><input name="ticker"></form>',
        groups=(
            ("Financials <source>", '<a href="?source=our">Our View</a>'),
            ("Gold scenario", '<input type="range">'),
        ),
        label='Company "command" bar',
    )
    assert html.startswith(
        '<div class="command-bar" role="region" aria-label="Company &quot;command&quot; bar">'
    )
    assert '<div class="command-bar__identity"><strong class="company-name">NEM</strong>' in html
    assert '<div class="command-bar__navigation"><form action="/ticker">' in html
    assert html.count('class="command-bar__group"') == 2
    assert "Financials &lt;source&gt;" in html
    assert '<a href="?source=our">Our View</a>' in html
    assert '<input type="range">' in html


def test_command_bar_omits_empty_navigation_slot():
    html = components.command_bar("<strong>NEM</strong>")
    assert "command-bar__navigation" not in html
    assert "command-bar__group" not in html


def test_command_bar_accepts_only_safe_optional_class_tokens():
    html = components.command_bar(
        "<strong>NEM</strong>", class_name="ticker-command-bar compact_bar"
    )
    assert 'class="command-bar ticker-command-bar compact_bar"' in html
    with pytest.raises(ValueError, match="CSS class tokens"):
        components.command_bar("<strong>NEM</strong>", class_name='bad" onclick="x')


def test_command_bar_requires_identity_and_an_accessible_label():
    with pytest.raises(ValueError, match="requires identity_html"):
        components.command_bar("", label="Company controls")
    with pytest.raises(ValueError, match="non-empty accessible label"):
        components.command_bar("<strong>NEM</strong>", label="  ")


def test_segmented_control_uses_links_and_exactly_one_current_item():
    html = components.segmented_control(
        (
            ("Our <View>", "/ticker/NEM?source=our&view=price", True),
            ('Yahoo "official"', "/ticker/NEM?source=yahoo&view=price", False),
        ),
        label='Financials "source"',
    )
    assert html.startswith(
        '<div class="segmented-control" role="group" aria-label="Financials &quot;source&quot;">'
    )
    assert html.count('class="segmented-control__item"') == 2
    assert html.count('aria-current="true"') == 1
    assert 'role="tab"' not in html
    assert "Our &lt;View&gt;" in html
    assert "Yahoo &quot;official&quot;" in html
    assert 'href="/ticker/NEM?source=our&amp;view=price" aria-current="true"' in html


@pytest.mark.parametrize(
    "items",
    [
        (("Our View", "?source=our", False), ("Yahoo", "?source=yahoo", False)),
        (("Our View", "?source=our", True), ("Yahoo", "?source=yahoo", True)),
    ],
)
def test_segmented_control_rejects_missing_or_multiple_selected_items(items):
    with pytest.raises(ValueError, match="exactly one selected"):
        components.segmented_control(items, label="Financials source")


def test_segmented_control_requires_an_accessible_label():
    with pytest.raises(ValueError, match="non-empty accessible label"):
        components.segmented_control((("Our View", "?source=our", True),), label="")


def test_data_card_new_contract_escapes_label_and_keeps_resolved_slots():
    html = components.data_card(
        "Cash margin <per oz>",
        '<span data-value="3017">$3,017/oz</span>',
        help_html='<button class="help-icon">i</button>',
        basis_html="Forward at spot",
        state="warning",
        state_label="Watch threshold",
    )
    assert html.startswith('<article class="data-card data-card--warning">')
    assert '<h3 class="data-card__label">Cash margin &lt;per oz&gt;' in html
    assert '<button class="help-icon">i</button></h3>' in html
    assert '<p class="data-card__value"><span data-value="3017">$3,017/oz</span></p>' in html
    assert '<p class="data-card__state">Watch threshold</p>' in html
    assert '<p class="data-card__basis">Forward at spot</p>' in html
    assert "metric-card" not in html


def test_data_card_rejects_ambiguous_or_unsafe_options():
    with pytest.raises(ValueError, match="requires a label"):
        components.data_card("", "1")
    with pytest.raises(ValueError, match="unknown data-card state"):
        components.data_card("Label", "1", state='warning" onclick="x')
    with pytest.raises(ValueError, match="visible state_label"):
        components.data_card("Label", "1", state="warning")
    with pytest.raises(ValueError, match="requires a semantic state"):
        components.data_card("Label", "1", state_label="Warning")
    with pytest.raises(ValueError, match="unknown data-card state"):
        components.data_card("Label", "1", state="sparkly")


def test_basis_strip_escapes_labels_and_preserves_resolved_values():
    html = components.basis_strip(
        (
            ("Financials <source>", "Yahoo financials"),
            ("As of", '<time datetime="2026-08-12">12 Aug 2026</time>'),
        ),
        label='Corporate finance "basis"',
    )
    assert html.startswith(
        '<div class="basis-strip" role="group" aria-label="Corporate finance &quot;basis&quot;">'
    )
    assert html.count('class="basis-strip__item"') == 2
    assert "Financials &lt;source&gt;" in html
    assert '<time datetime="2026-08-12">12 Aug 2026</time>' in html


def test_basis_strip_rejects_an_empty_data_family():
    with pytest.raises(ValueError, match="at least one item"):
        components.basis_strip((), label="Corporate finance basis")
    with pytest.raises(ValueError, match="non-empty accessible label"):
        components.basis_strip((("Source", "Yahoo"),), label=" ")


def test_terminal_density_is_an_opt_in_bounded_wrapper():
    assert components.terminal_density("<section>Dense</section>") == (
        '<div class="terminal-density"><section>Dense</section></div>'
    )


def test_toolbar_role_group_and_escaped_label():
    html = components.toolbar(
        "<button>Go</button>",
        label='Scenario "controls"',
        visible_label="Financials source",
    )
    assert 'role="group"' in html
    assert 'aria-label="Scenario &quot;controls&quot;"' in html
    assert "<button>Go</button>" in html
    assert '<span class="toolbar__label">Financials source</span>' in html


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


def test_notice_tones_and_roles():
    html = status.notice("success", "<p>Saved gold price.</p>")
    assert '<div class="notice notice-success" role="status">' in html
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
    assert 'class="notice notice-warning option-freshness option-freshness-stale"' in html
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

    # Context-local display strings are presentation, not database/model state.
    # Keep application/storage imports forbidden even for the visitor header.
    allowed_roots = {"__future__", "html", "re", "contextvars"}
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


def test_ui_package_contains_no_computation_constructs():
    """GV-RD-FINAL-007: import isolation alone cannot stop `sum(x)/len(x)`-style
    logic written with builtins. This ratchet (green at introduction) forbids the
    AST constructs computation needs: numeric/ordering operators, numeric
    builtins, and numeric-literal arithmetic. String concatenation with `+` stays
    allowed. Semantic purity beyond this (e.g. `or`-fallback state resolution)
    remains a review rule — see serve/ui/README.md.
    """
    import ast
    from pathlib import Path

    forbidden_binops = (ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    ordering_cmpops = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    forbidden_calls = {"sum", "min", "max", "sorted", "round", "abs", "divmod", "int", "float"}

    def is_numeric_const(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, (int, float, complex))

    for path in sorted(Path("golden_vector/serve/ui").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp):
                assert not isinstance(node.op, forbidden_binops), (
                    f"{path.name}:{node.lineno} uses arithmetic operator "
                    f"{type(node.op).__name__} — compute in the model layer, not ui/"
                )
                if isinstance(node.op, ast.Add):
                    assert not (is_numeric_const(node.left) or is_numeric_const(node.right)), (
                        f"{path.name}:{node.lineno} adds a numeric literal — "
                        "compute in the model layer, not ui/"
                    )
            elif isinstance(node, ast.Compare):
                for op in node.ops:
                    assert not isinstance(op, ordering_cmpops), (
                        f"{path.name}:{node.lineno} uses ordering comparison "
                        f"{type(op).__name__} — thresholds live in the model layer"
                    )
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, (
                    f"{path.name}:{node.lineno} calls {node.func.id}() — "
                    "numeric builtins are computation, not presentation"
                )
            elif isinstance(node, ast.AugAssign):
                assert isinstance(node.op, ast.Add), (
                    f"{path.name}:{node.lineno} augmented-assigns with "
                    f"{type(node.op).__name__} — compute in the model layer"
                )


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
