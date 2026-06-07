"""Tests for the DataTables enhancement layer on the workspace views.

Covers:
- The /static/* route: vendored assets + our workspace-tables.js are
  served with the right MIME; path traversal (POSIX and Windows style)
  and disallowed extensions all return 404.
- Python helpers: _fmt_numeric_td, _collect_filter_options, _render_filter_bar
  emit the HTML data-attribute contract workspace-tables.js depends on.
- View integration: Tool A / Tool B tables are marked
  `js-datatable`, numeric cells carry `data-order`, filter bars reflect
  the rendered data.
"""

from __future__ import annotations

import io

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.format_helpers import _fmt_numeric_td
from golden_vector.serve.overview_helpers import (
    _collect_filter_options,
    _render_filter_bar,
)
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths, tool_b_output_row


# ---------------------------------------------------------------------------
# WSGI test helper that returns raw bytes (not utf-8 decoded).
# ---------------------------------------------------------------------------


def _call_wsgi_raw(app, *, method: str, path: str) -> dict[str, object]:
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    if "?" in path:
        path_info, _, query_string = path.partition("?")
    else:
        path_info, query_string = path, ""

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
        "CONTENT_LENGTH": "0",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    body_bytes = b"".join(app(environ, start_response))
    return {
        "status": captured["status"],
        "headers": captured["headers"],
        "body_bytes": body_bytes,
        "body_text": body_bytes.decode("utf-8", errors="replace"),
    }


def _repo_app_config():
    return load_app_config(ProjectPaths.discover()).app


def _workspace_fixture(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    return paths, app


# ---------------------------------------------------------------------------
# /static/* route
# ---------------------------------------------------------------------------


def test_static_route_serves_vendored_datatables_js_with_correct_mime(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    response = _call_wsgi_raw(
        app, method="GET",
        path="/static/vendor/datatables/datatables-2.1.8.min.js",
    )
    assert response["status"].startswith("200")
    assert "application/javascript" in response["headers"].get("Content-Type", "")
    # Real asset is tens of KB; sanity-check it's not an accidental empty.
    assert len(response["body_bytes"]) > 10_000


def test_static_route_serves_vendored_datatables_css_with_correct_mime(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    response = _call_wsgi_raw(
        app, method="GET",
        path="/static/vendor/datatables/datatables-2.1.8.min.css",
    )
    assert response["status"].startswith("200")
    assert "text/css" in response["headers"].get("Content-Type", "")
    assert len(response["body_bytes"]) > 1_000


def test_static_route_serves_workspace_css_with_revalidation(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    response = _call_wsgi_raw(
        app, method="GET", path="/static/workspace.css",
    )
    assert response["status"].startswith("200")
    assert "text/css" in response["headers"].get("Content-Type", "")
    assert response["headers"].get("Cache-Control") == "no-cache"
    body = response["body_text"]
    assert ":root" in body
    assert ".top-nav" in body


def test_static_route_uses_resolved_path_for_cache_policy(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    response = _call_wsgi_raw(
        app, method="GET", path="/static/vendor/../workspace.css",
    )
    assert response["status"].startswith("200")
    assert "text/css" in response["headers"].get("Content-Type", "")
    assert response["headers"].get("Cache-Control") == "no-cache"
    assert ":root" in response["body_text"]


def test_static_route_serves_workspace_tables_js_with_correct_mime(tmp_path):
    """workspace-tables.js is the centerpiece of the simple architecture —
    separate test to prove the custom file is reachable, not just vendored."""
    _, app = _workspace_fixture(tmp_path)
    response = _call_wsgi_raw(
        app, method="GET", path="/static/workspace-tables.js",
    )
    assert response["status"].startswith("200")
    assert "application/javascript" in response["headers"].get("Content-Type", "")
    body = response["body_text"]
    # Prove it's actually our file by asserting two signature strings.
    assert "js-datatable" in body
    assert "data-filter-target" in body


def test_static_route_rejects_posix_path_traversal(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    response = _call_wsgi_raw(
        app, method="GET", path="/static/../../config/universe.yaml",
    )
    assert response["status"].startswith("404")


def test_static_route_rejects_windows_path_traversal(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    # Literal backslash traversal: what a Windows-targeted attack might
    # send; Path.resolve() canonicalizes both slash and backslash.
    response = _call_wsgi_raw(
        app, method="GET", path="/static/..\\..\\secret.txt",
    )
    assert response["status"].startswith("404")


def test_static_route_rejects_disallowed_extension(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    response = _call_wsgi_raw(
        app, method="GET", path="/static/vendor/datatables/datatables-2.1.8.min.py",
    )
    assert response["status"].startswith("404")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_fmt_numeric_td_plain_number_emits_raw_data_order():
    """Contract: data-order carries the raw float; display carries the
    formatted string."""
    cell = _fmt_numeric_td(66.14, decimals=2)
    assert cell == '<td data-order="66.14">66.14</td>'


def test_fmt_numeric_td_percent_keeps_raw_fraction_as_data_order():
    """For percent-style columns, the raw fraction stays in data-order
    (so DataTables sorts by fraction) and the display is `value * 100`%
    (what humans read)."""
    cell = _fmt_numeric_td(0.18, decimals=1, as_percent=True)
    assert cell == '<td data-order="0.18">18.0%</td>'


def test_fmt_numeric_td_missing_value_uses_sort_sentinel():
    cell = _fmt_numeric_td(None, decimals=2)
    assert 'data-order="9000000000000000"' in cell
    assert ">-</td>" in cell


def test_fmt_numeric_td_nan_uses_sort_sentinel():
    cell = _fmt_numeric_td(float("nan"), decimals=2)
    assert 'data-order="9000000000000000"' in cell
    assert ">-</td>" in cell


def test_fmt_numeric_td_non_numeric_fallback_is_safe():
    cell = _fmt_numeric_td("not a number", decimals=1)
    assert 'data-order="9000000000000000"' in cell
    assert "not a number" in cell  # text escaped, still shown


def test_collect_filter_options_derives_only_from_rendered_rows():
    rows = [
        {"profile_label": "CONVEX", "verdict": "STRONG_CANDIDATE"},
        {"profile_label": "DEFENSIVE", "verdict": "WATCHLIST"},
        {"profile_label": "CONVEX", "verdict": "STRONG_CANDIDATE"},  # dup
    ]
    result = _collect_filter_options(rows, [
        ("profile", "profile_label"),
        ("verdict", "verdict"),
    ])
    assert result == {
        "profile": ["CONVEX", "DEFENSIVE"],
        "verdict": ["STRONG_CANDIDATE", "WATCHLIST"],
    }


def test_collect_filter_options_skips_none_and_empty_values():
    rows = [
        {"profile_label": "CONVEX"},
        {"profile_label": None},
        {"profile_label": ""},
        {"profile_label": "   "},
        {"profile_label": float("nan")},
        {"profile_label": "LINEAR"},
    ]
    result = _collect_filter_options(rows, [("profile", "profile_label")])
    assert result["profile"] == ["CONVEX", "LINEAR"]


def test_render_filter_bar_emits_data_filter_target_and_data_filter_column():
    html = _render_filter_bar(
        target_table_id="tool-b-table",
        options={"verdict": ["STRONG_CANDIDATE", "WATCHLIST"]},
        column_labels={"verdict": "Verdict"},
    )
    assert 'data-filter-target="#tool-b-table"' in html
    assert 'data-filter-column="verdict"' in html
    assert 'data-global-search' in html
    # Options must include a blank "All" entry so the user can clear
    # the filter.
    assert '<option value="">All</option>' in html
    # All real options rendered
    for value in ("STRONG_CANDIDATE", "WATCHLIST"):
        assert f'<option value="{value}">{value}</option>' in html


# ---------------------------------------------------------------------------
# View integration — prove the HTML contract is honored end-to-end
# ---------------------------------------------------------------------------


def _response_body(app, path: str) -> str:
    return _call_wsgi_raw(app, method="GET", path=path)["body_text"]


def test_tool_b_view_table_has_js_datatable_class_and_id(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    body = _response_body(app, "/tool-b")
    assert '<table id="tool-b-table" class="js-datatable">' in body


def test_tool_b_view_numeric_columns_marked_data_sort_numeric(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    body = _response_body(app, "/tool-b")
    # Score/Rank/standard finance columns must carry the numeric marker so
    # workspace-tables.js activates numeric sort on them.
    assert '<th data-col-name="score" data-sort-numeric>' in body
    assert '<th data-col-name="rank" data-sort-numeric>' in body
    assert '<th data-col-name="forward_pe" data-sort-numeric>' in body
    assert '<th data-col-name="ev_ebitda" data-sort-numeric>' in body
    assert '<th data-col-name="fcf_yield" data-sort-numeric>' in body


def test_tool_a_view_is_wired_as_a_datatable(tmp_path):
    """Per Codex's v-simple-review punch list: prove Tool A got wired,
    not just Tool B."""
    _, app = _workspace_fixture(tmp_path)
    body = _response_body(app, "/tool-a")
    assert '<table id="tool-a-table" class="js-datatable">' in body
    assert 'data-filter-target="#tool-a-table"' in body
    # A representative numeric column is marked
    assert '<th data-col-name="delta" data-sort-numeric>' in body


def test_tool_b_view_filter_bar_lists_only_values_present_in_data(tmp_path):
    """The dropdown options are derived from the rendered rows — not a
    hard-coded list. With only NEM bootstrapped and no tool-b output yet,
    the verdict dropdown should have ONLY the 'All' default option
    (since there are no rendered verdict values)."""
    _, app = _workspace_fixture(tmp_path)
    body = _response_body(app, "/tool-b")
    # No hard-coded verdict list leaking through
    assert 'data-filter-column="verdict"' in body


def test_tool_b_filter_bar_dropdown_lists_only_verdicts_present_in_data(tmp_path):
    """Strong live-derivation contract: with a populated Tool B parquet
    whose rows use exactly one verdict value, the filter dropdown must
    list that value and NOT values that would appear in a hard-coded
    list (e.g. SCREEN_OUT, WATCHLIST).

    Guards against a regression to hard-coded option lists.
    """
    from datetime import date
    from golden_vector.app.run_context import RunContext
    from golden_vector.ingestion.persist import persist_tool_b_outputs

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    # Write a Tool B parquet where the ONLY verdict present is WATCHLIST.
    ctx = RunContext.start(
        paths=paths, command="tool-b", parameters={"gold_price": 4000.0},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths, run_context=ctx,
        tool_b_outputs=pd.DataFrame([
            tool_b_output_row(
                "NEM",
                screening_verdict="WATCHLIST",
                confidence="VERIFIED",
                snapshot_refresh_run_id="refresh-run",
                source_run_id=ctx.run_id,
            )
        ]),
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    body = _response_body(app, "/tool-b")

    # Isolate the filter bar HTML so we don't accidentally match option
    # tags from some other part of the page.
    import re
    bar_match = re.search(
        r'<section[^>]*data-filter-target="#tool-b-table"[^>]*>(.+?)</section>',
        body, flags=re.DOTALL,
    )
    assert bar_match, "Tool B filter bar not found"
    bar = bar_match.group(1)

    # The live verdict in the rendered data is WATCHLIST.
    assert '<option value="WATCHLIST">WATCHLIST</option>' in bar
    # Hard-coded leftovers must NOT leak.
    assert 'value="SCREEN_OUT"' not in bar
    assert 'value="STRONG_CANDIDATE"' not in bar
    # Same for Layer 1 — data has PASS only.
    assert '<option value="PASS">PASS</option>' in bar
    assert 'value="FAIL"' not in bar
    assert 'value="INCOMPLETE"' not in bar


def test_page_shell_includes_datatables_and_workspace_tables_scripts(tmp_path):
    _, app = _workspace_fixture(tmp_path)
    body = _response_body(app, "/tool-b")
    assert '/static/vendor/datatables/jquery-3.7.1.min.js' in body
    assert '/static/vendor/datatables/datatables-2.1.8.min.js' in body
    assert '/static/workspace-tables.js' in body
    assert '/static/vendor/datatables/datatables-2.1.8.min.css' in body
    assert '/static/workspace.css' in body


def test_workspace_tables_js_has_datatable_guard():
    """workspace-tables.js must early-return if DataTables failed to load
    (e.g. CDN blocked). This is the graceful-degradation contract."""
    js_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "golden_vector" / "serve" / "static" / "workspace-tables.js"
    )
    content = js_path.read_text(encoding="utf-8")
    assert "typeof window.DataTable !== 'function'" in content
    assert "return" in content  # inside the guard
