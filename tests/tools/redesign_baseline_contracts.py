"""Machine-readable route/form/table contract matrix for the visual redesign.

Phase 0 tasks 10-11 of GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md: extract the
semantic DOM contract (routes, statuses, redirects, downloads, form
actions/controls, table headers/keys, navigation, warning labels) from
deterministic fixture-backed workspace apps, before any markup migration.
Phases 3/8 re-run this and diff the JSON to prove contracts survived.

Run from the repository root::

    python tests/tools/redesign_baseline_contracts.py [--out PATH]

Uses only fixture stores under a temporary directory — never real data.
Output is deliberately timestamp-free so re-runs diff cleanly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from golden_vector.screening.manual_data import bootstrap_manual_screening_data  # noqa: E402
from golden_vector.serve.workspace import create_workspace_app  # noqa: E402
from tests.helpers import build_test_paths, call_wsgi_app  # noqa: E402
from tests.test_portfolio_m1 import _portfolio_config, _write_foundation_snapshot  # noqa: E402
from tests.test_workspace_app import (  # noqa: E402
    _repo_app_config,
    _write_latest_foundation_snapshot,
    _write_latest_outputs,
)

_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


class ContractParser(HTMLParser):
    """Collects the semantic contract of one rendered page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.headings: list[dict[str, str]] = []
        self.nav_links: list[dict[str, object]] = []
        self.forms: list[dict[str, object]] = []
        self.tables: list[dict[str, object]] = []
        self.flashes: list[dict[str, str]] = []
        self.help_icon_count = 0
        self.details_count = 0
        self._text_target: list[str] | None = None
        self._in_nav = False
        self._open_form: dict[str, object] | None = None
        self._open_table: dict[str, object] | None = None
        self._open_select: dict[str, object] | None = None
        self._flash_depth = 0
        self._flash_buffer: list[str] = []
        self._flash_class = ""

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _attr_map(attrs) -> dict[str, str]:
        return {name: (value if value is not None else "") for name, value in attrs}

    def _start_text(self) -> list[str]:
        target: list[str] = []
        self._text_target = target
        return target

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = self._attr_map(attrs)
        classes = a.get("class", "")

        if tag == "title":
            self._start_text()
        elif tag in {"h1", "h2", "h3"}:
            self.headings.append({"tag": tag, "text": ""})
            self._start_text()
        elif tag == "nav":
            self._in_nav = True
        elif tag == "a" and self._in_nav:
            link = {
                "href": a.get("href", ""),
                "class": classes,
                "active": "active" in classes.split() or "aria-current" in a,
                "label": "",
            }
            self.nav_links.append(link)
            self._start_text()
        elif tag == "form":
            self._open_form = {
                "action": a.get("action", ""),
                "method": a.get("method", "get").lower(),
                "class": classes,
                "controls": [],
            }
        elif tag in {"input", "button"} and self._open_form is not None:
            control = {
                "tag": tag,
                "type": a.get("type", "text" if tag == "input" else "submit"),
                "name": a.get("name", ""),
                "value": a.get("value", ""),
            }
            if "checked" in a:
                control["checked"] = True
            if "required" in a:
                control["required"] = True
            if "disabled" in a:
                control["disabled"] = True
            self._open_form["controls"].append(control)
        elif tag == "select" and self._open_form is not None:
            self._open_select = {
                "tag": "select",
                "name": a.get("name", ""),
                "options": [],
            }
            if "disabled" in a:
                self._open_select["disabled"] = True
            self._open_form["controls"].append(self._open_select)
        elif tag == "option" and self._open_select is not None:
            option = {"value": a.get("value", "")}
            if "selected" in a:
                option["selected"] = True
            if "disabled" in a:
                option["disabled"] = True
            self._open_select["options"].append(option)
        elif tag == "textarea" and self._open_form is not None:
            self._open_form["controls"].append(
                {"tag": "textarea", "name": a.get("name", "")}
            )
        elif tag == "table":
            self._open_table = {
                "id": a.get("id", ""),
                "class": classes,
                "headers": [],
                "has_tfoot": False,
            }
            self.tables.append(self._open_table)
        elif tag == "th" and self._open_table is not None:
            self._open_table["headers"].append(
                {
                    "data_col_name": a.get("data-col-name", ""),
                    "numeric": "data-sort-numeric" in a,
                }
            )
        elif tag == "tfoot" and self._open_table is not None:
            self._open_table["has_tfoot"] = True
        elif tag == "div" and "flash" in classes.split():
            pass  # plain success/info flash without modifier
        if tag == "div" and any(c.startswith("flash") for c in classes.split()):
            if self._flash_depth == 0:
                self._flash_class = classes
                self._flash_buffer = []
            self._flash_depth += 1
        elif self._flash_depth:
            self._flash_depth += 1
        if tag == "button" and "help-icon" in classes.split():
            self.help_icon_count += 1
        if tag == "details":
            self.details_count += 1

    def handle_endtag(self, tag):
        if tag == "title" and self._text_target is not None:
            self.title = _clean("".join(self._text_target))
            self._text_target = None
        elif tag in {"h1", "h2", "h3"} and self._text_target is not None:
            self.headings[-1]["text"] = _clean("".join(self._text_target))
            self._text_target = None
        elif tag == "a" and self._in_nav and self._text_target is not None:
            self.nav_links[-1]["label"] = _clean("".join(self._text_target))
            self._text_target = None
        elif tag == "nav":
            self._in_nav = False
        elif tag == "form" and self._open_form is not None:
            self.forms.append(self._open_form)
            self._open_form = None
        elif tag == "select":
            self._open_select = None
        elif tag == "table":
            self._open_table = None
        if self._flash_depth:
            self._flash_depth -= 1
            if self._flash_depth == 0:
                self.flashes.append(
                    {
                        "class": self._flash_class,
                        "text": _clean("".join(self._flash_buffer))[:240],
                    }
                )

    def handle_data(self, data):
        if self._text_target is not None:
            self._text_target.append(data)
        if self._flash_depth:
            self._flash_buffer.append(data)


def extract_contract(html: str) -> dict[str, object]:
    parser = ContractParser()
    parser.feed(html)
    return {
        "title": parser.title,
        "headings": parser.headings,
        "nav_links": parser.nav_links,
        "forms": parser.forms,
        "tables": parser.tables,
        "flashes": parser.flashes,
        "help_icon_count": parser.help_icon_count,
        "details_count": parser.details_count,
    }


def _record(app, method: str, path: str, *, parse: bool = True, data=None) -> dict[str, object]:
    response = call_wsgi_app(app, method=method, path=path, data=data)
    status = str(response["status"])
    headers = response["headers"]
    entry: dict[str, object] = {
        "method": method,
        "path": path,
        "status": status,
        "content_type": headers.get("Content-Type", ""),
    }
    if "Location" in headers:
        entry["location"] = headers["Location"]
    if "Content-Disposition" in headers:
        entry["content_disposition"] = headers["Content-Disposition"]
    if "Cache-Control" in headers:
        entry["cache_control"] = headers["Cache-Control"]
    if parse and status.startswith("200") and "text/html" in entry["content_type"]:
        entry["contract"] = extract_contract(response["body"])
    return entry


WORKSPACE_GET_ROUTES = (
    "/",
    "/candidate-finder",
    "/tool-a",
    "/tool-a?window=6M",
    "/tool-b",
    "/tool-b?differences_only=1&fundamentals_source=yahoo",
    "/tool-c",
    "/tool-d",
    "/option-trading",
    "/lab",
    "/lab/dial/NEM",
    "/scorecard",
    "/ticker/NEM",
    "/ticker/NEM?lens=option-trading",
    "/ticker/NEM?window=6M&fundamentals_source=yahoo",
)

ERROR_ROUTES = (
    ("GET", "/combined"),
    ("GET", "/ticker/ZZZZ"),
    ("GET", "/favicon.ico"),
    ("GET", "/hedge-readiness"),
    ("POST", "/tool-a"),
    ("GET", "/refresh"),
    ("PUT", "/ticker/NEM"),
    ("GET", "/ticker/NEM/company"),
)


def build_matrix() -> dict[str, object]:
    matrix: dict[str, object] = {"fixture": "tests.helpers fixture stores (no real data)"}

    with tempfile.TemporaryDirectory() as tmp:
        paths = build_test_paths(Path(tmp))
        paths.ensure_runtime_dirs()
        bootstrap_manual_screening_data(paths, tickers=["NEM"])
        _write_latest_foundation_snapshot(paths)
        _write_latest_outputs(paths)
        app = create_workspace_app(
            paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"]
        )
        matrix["workspace_routes"] = [
            _record(app, "GET", path) for path in WORKSPACE_GET_ROUTES
        ]
        matrix["error_routes"] = [
            _record(app, method, path, parse=False) for method, path in ERROR_ROUTES
        ]

    with tempfile.TemporaryDirectory() as tmp:
        paths = build_test_paths(Path(tmp))
        paths.ensure_runtime_dirs()
        app_config = _portfolio_config(enabled=True)
        _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
        app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
        call_wsgi_app(
            app,
            method="POST",
            path="/portfolio/lots",
            data={
                "ticker": "NEM",
                "shares": "2",
                "buy_price": "50",
                "buy_currency": "USD",
                "buy_date": "2026-01-02",
                "note": "fixture lot",
            },
        )
        matrix["portfolio_routes"] = [
            _record(app, "GET", "/portfolio"),
            _record(app, "GET", "/portfolio?saved=portfolio"),
            _record(app, "GET", "/portfolio/reconciliation.csv", parse=False),
            _record(app, "GET", "/portfolio/lots", parse=False),
        ]

    with tempfile.TemporaryDirectory() as tmp:
        paths = build_test_paths(Path(tmp))
        paths.ensure_runtime_dirs()
        app_config = _portfolio_config(enabled=False)
        app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
        matrix["portfolio_disabled_routes"] = [
            _record(app, "GET", "/portfolio", parse=False),
            _record(app, "GET", "/portfolio/reconciliation.csv", parse=False),
            _record(app, "GET", "/portfolio/lots", parse=False),
            _record(app, "GET", "/hedge-readiness/latest.md", parse=False),
        ]

    return matrix


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="reviews/codex/milestones/visual_redesign/baseline_contracts.json",
        help="Output JSON path (relative to the repository root).",
    )
    args = parser.parse_args(argv)
    matrix = build_matrix()
    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(matrix, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    route_count = sum(
        len(matrix[key])
        for key in ("workspace_routes", "error_routes", "portfolio_routes", "portfolio_disabled_routes")
    )
    print(f"Wrote {route_count} route contracts to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
