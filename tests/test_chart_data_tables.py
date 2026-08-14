"""Accessible text equivalents for the pointer-only charts (GV-RD-FINAL-002).

The overlay crosshair and the rug tooltips are pointer-driven, so every value they reveal must
also exist as a plain, keyboard-reachable table on the same page. These tests pin the
table<->chart equivalence: the tables are built from the SAME payload the SVG is built from, so
row counts must match the chart exactly and no row may be truncated.
"""

from __future__ import annotations

import re as _re

from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths, call_wsgi_app
from tests.test_workspace_app import (
    _repo_app_config,
    _write_latest_foundation_snapshot,
    _write_latest_outputs,
)


def _detail_html(tmp_path) -> str:
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    app = create_workspace_app(paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"])
    result = call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert str(result["status"]).startswith("200"), result["status"]
    return str(result["body"])


def _row_count(block: str) -> int:
    body = block[block.index("<tbody>") : block.index("</tbody>")]
    return body.count("<tr>")


# The crosshair overlay chart was removed with the ticker-page redesign (M3c):
# the locked requirements keep ONE performance chart, rendered by
# serve/ticker_page/sections.py from the persisted performance artifact. Its
# table<->chart equivalence is pinned at render level in
# tests/test_ticker_page_sections.py (the details twin is asserted cell-by-cell
# against the fixture rows), so the three route-level overlay tests that lived
# here tested removed markup and were deleted rather than retargeted — a
# route-level twin assertion needs a published five-artifact generation, which
# the post-refresh browser gate covers on the real page.


_RUG_LABEL = _re.compile(r'class="rug-tick" data-rug="([^"]*)"')
_TABLE_ROW = _re.compile(r"<tr><td>([^<]*)</td><td class=\"numeric\">([^<]*)</td></tr>")


def _rug_svgs(html: str) -> list[tuple[int, str]]:
    """(end-of-svg offset, svg markup) for EVERY strip on the page that has a rug."""

    found: list[tuple[int, str]] = []
    cursor = 0
    while True:
        start = html.find("<svg", cursor)
        if start < 0:
            return found
        stop = html.index("</svg>", start) + len("</svg>")
        cursor = stop
        svg = html[start:stop]
        if 'class="rug-tick"' in svg:
            found.append((stop, svg))


def assert_every_rug_strip_has_a_data_table(html: str, *, minimum: int = 1) -> int:
    """Shared invariant (GV-RD-FINAL-002), imported by the section-level tests.

    Strips are DISCOVERED in the markup, never enumerated, so a strip added
    without a table fails here without anyone remembering to list it.
    """

    strips = _rug_svgs(html)
    assert len(strips) >= minimum, len(strips)
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for end_svg, svg in strips:
        labels = _RUG_LABEL.findall(svg)
        assert labels
        tail = html[end_svg:]
        assert tail.lstrip().startswith("<details"), tail[:200]
        start = end_svg + tail.index("<details")
        block = html[start : html.index("</details>", start) + len("</details>")]
        assert "<summary>Chart data (table)</summary>" in block
        region = _re.search(
            r'class="table-region"[^>]*\bid="([^"]+)"[^>]*\baria-label="([^"]+)"',
            block,
        )
        assert region is not None, block[:200]
        region_id, region_name = region.group(1), region.group(2)
        assert region_id not in seen_ids, f"duplicate id {region_id}"
        seen_ids.add(region_id)
        # Two region landmarks with identical NAMES are as bad as duplicate ids
        # — a screen-reader's landmark list would show indistinguishable twins.
        assert region_name not in seen_names, f"duplicate region name {region_name}"
        seen_names.add(region_name)
        # 1:1 with the rug: same tickers, same pre-formatted value text, same order.
        rows = _TABLE_ROW.findall(block)
        assert _row_count(block) == len(labels)
        assert [f"{ticker} · {value}" for ticker, value in rows] == labels
    return len(strips)


def test_every_rug_strip_on_the_ticker_page_has_a_matching_chart_data_table(tmp_path):
    # The fixture page publishes the two behaviour beta strips; the compare and
    # corporate metric strips need a percentiles frame and are held to the SAME
    # invariant at section level (tests/test_ticker_page_{compare,corporate}.py).
    assert_every_rug_strip_has_a_data_table(_detail_html(tmp_path), minimum=2)
