"""Accessible text equivalents for the pointer-only charts (GV-RD-FINAL-002).

The overlay crosshair and the rug tooltips are pointer-driven, so every value they reveal must
also exist as a plain, keyboard-reachable table on the same page. These tests pin the
table<->chart equivalence: the tables are built from the SAME payload the SVG is built from, so
row counts must match the chart exactly and no row may be truncated.
"""

from __future__ import annotations


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


def _disclosure_after(html: str, marker: str) -> str:
    """Return the details block that immediately follows the chart containing ``marker``."""
    idx = html.index(marker)
    end_svg = html.index("</svg>", idx) + len("</svg>")
    tail = html[end_svg:]
    assert tail.lstrip().startswith("<details"), tail[:120]
    start = end_svg + tail.index("<details")
    stop = html.index("</details>", start) + len("</details>")
    return html[start:stop]


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


def test_rug_strip_tables_match_the_tick_count(tmp_path):
    html = _detail_html(tmp_path)
    for axis in ("Down beta", "Up beta"):
        marker = f'aria-label="{axis}'
        idx = html.index(marker)
        svg = html[html.rindex("<svg", 0, idx) : html.index("</svg>", idx)]
        ticks = svg.count('class="rug-tick"')
        assert ticks > 0
        block = _disclosure_after(html, marker)
        assert "<summary>Chart data (table)</summary>" in block
        assert 'class="table-region"' in block
        assert _row_count(block) == ticks
