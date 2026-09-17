"""Offline, read-only acceptance for a research publication, including all routes."""
from __future__ import annotations

import argparse
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch
from urllib.parse import urlsplit

import pyarrow.parquet as pq

from golden_vector.access.store import Session
from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import sha256_file
from golden_vector.serve.access_context import visitor_session
from golden_vector.serve.ticker_page import load_ticker_page_data
from golden_vector.serve.ui.shell import visitor_account
from golden_vector.serve.workspace import create_workspace_app
from golden_vector.serve.workspace_state import _load_workspace_state, _load_tool_a_detail

RESEARCH_ROUTES = (
    "/", "/candidate-finder", "/candidate-finder?fundamentals_source=official",
    "/tool-a", "/tool-b", "/tool-b?fundamentals_source=official", "/tool-c", "/tool-d",
    "/option-trading", "/ticker/NEM", "/ticker/AEM", "/ticker/NEM?fundamentals_source=official",
    "/ticker/NEM?lens=option-trading", "/lab", "/lab/dial/NEM", "/scorecard", "/api/data-status",
    "/candidate-finder?gold_price=4500", "/tool-b?gold_price=4500", "/tool-a?window=6M",
)


def check_bundle(root: Path, config: Path) -> dict:
    root, config = root.resolve(), config.resolve()
    publication = json.loads((root / "publication.json").read_text())
    for relative, entry in publication["files"].items():
        if sha256_file(root / relative) != entry["sha256"]:
            raise ValueError(f"Publication checksum mismatch: {relative}")
    model = json.loads((root / "data/intermediate/status/latest_model_state.json").read_text())
    artifact_rows = {}
    for name, entry in model["artifacts"].items():
        if sha256_file(root / entry["path"]) != entry["sha256"]:
            raise ValueError(f"Model checksum mismatch: {name}")
        if entry["kind"] == "parquet":
            metadata = pq.ParquetFile(root / entry["path"]).metadata
            if metadata.num_rows != entry["row_count"]:
                raise ValueError(f"Row-count mismatch: {name}")
            artifact_rows[name] = metadata.num_rows
    manual = root / "data/manual/screening/manual_screening.sqlite3"
    with sqlite3.connect(manual.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM stock_notes").fetchone()[0] == 0
        for table in ("source_verification", "reporting_calendar"):
            assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE notes IS NOT NULL").fetchone()[0] == 0
    data = root / "data"
    paths = replace(ProjectPaths.discover(), repo_root=root, config_dir=config, data_dir=data,
                    raw_dir=data / "raw", intermediate_dir=data / "intermediate", output_dir=data / "output",
                    manual_dir=data / "manual", runs_dir=data / "runs", reviews_dir=root / "reviews")
    app_config = load_app_config(paths).app
    app_config = app_config.model_copy(update={"portfolio": app_config.portfolio.model_copy(update={"enabled": False})})
    tickers = sorted(item.ticker for item in app_config.universe.tickers if item.active and item.tool_b_enabled)
    context = visitor_session.set(Session("acceptance@example.invalid", "test-only", int(time.time()) + 600))
    display = visitor_account.set(("acceptance@example.invalid", "test-only"))
    results = {}
    try:
        with patch("socket.socket.connect", side_effect=AssertionError("Research rendering must not fetch remote data")):
            state = _load_workspace_state(paths, tickers)
            assert state.stock_notes.empty
            for name in ("latest_tool_a", "latest_tool_b", "latest_tool_c", "latest_tool_d"):
                assert not getattr(state, name).empty, name
            detail = _load_tool_a_detail(paths, app_config=app_config, ticker="NEM", universe_tool_a=state.latest_tool_a)
            assert detail.foundation_error is None, detail.foundation_error
            assert detail.rebased_overlay_by_window
            for overlay in detail.rebased_overlay_by_window.values():
                assert {"GDX", "GDXJ"}.issubset(overlay), "Benchmark comparison chart is incomplete"
            ticker_data = load_ticker_page_data(paths)
            for name in ("gold_response", "percentiles", "performance", "research_series", "fx_attribution", "downside_context"):
                item = getattr(ticker_data, name)
                assert item.status == "OK", (name, item.status, item.reason)
            app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=tickers, read_only=True)
            for route in (*RESEARCH_ROUTES, "/portfolio", "/hedge-readiness/latest.md", "/download/holdings.csv"):
                parsed = urlsplit(route)
                response = {}
                def start_response(status, headers, exc_info=None):
                    response.update(status=status, headers=dict(headers))
                started = time.monotonic()
                body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": parsed.path,
                                     "QUERY_STRING": parsed.query, "wsgi.input": BytesIO()}, start_response)).decode()
                expected = 200 if route in RESEARCH_ROUTES else 403
                assert int(response["status"].split()[0]) == expected, (route, response["status"], body[:300])
                if expected == 200:
                    assert "unexpected error" not in body.lower(), route
                    assert 'action="/manual' not in body, route
                    if parsed.path != "/api/data-status":
                        assert len(body) > 1000, route
                results[route] = {"status": expected, "seconds": round(time.monotonic() - started, 3), "bytes": len(body)}
    finally:
        visitor_session.reset(context)
        visitor_account.reset(display)
    return {"files_verified": len(publication["files"]), "artifact_rows": artifact_rows,
            "refresh": publication["full_refresh_completed_at_utc"], "optional_surfaces": publication["optional_surfaces"],
            "routes": results, "privacy": "no private notes, portfolio blocked", "network": "rendering performed with connections prohibited"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check_bundle(args.root, args.config), indent=2))
