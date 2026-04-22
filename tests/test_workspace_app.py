from __future__ import annotations

import io
from datetime import date

import pandas as pd

from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.screening.manual_data import bootstrap_manual_screening_data, load_manual_screening_data
from golden_vector.screening.manual_store import add_stock_note
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths


def test_workspace_overview_renders_manual_and_latest_outputs(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD"])
    _write_latest_outputs(paths)
    add_stock_note(
        paths,
        ticker="NEM",
        note_text="Review next production report",
        note_tag="FOLLOW_UP",
        note_status="OPEN",
    )

    app = create_workspace_app(paths, tool_b_tickers=["NEM", "GOLD"])
    response = _call_wsgi_app(app, method="GET", path="/")

    assert response["status"].startswith("200")
    assert "Golden Vector Workspace" in response["body"]
    assert "/ticker/NEM" in response["body"]
    assert "STRONG_CANDIDATE" in response["body"]
    assert "FOLLOW_UP" not in response["body"]


def test_workspace_company_post_updates_store(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    app = create_workspace_app(paths, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body=(
            "production_oz=6100000"
            "&aisc_usd_per_oz=1395"
            "&cash_cost_usd_per_oz=900"
            "&royalty_rate=4.5"
            "&sustaining_capex_musd=120"
            "&da_musd=55"
            "&interest_expense_musd=20"
            "&tax_rate=28"
            "&reserve_life_years=9"
            "&net_debt_musd=450"
            "&ebitda_ltm_musd=980"
        ),
    )

    assert response["status"].startswith("303")
    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.company_inputs.loc[loaded.company_inputs["ticker"] == "NEM"].iloc[0]
    assert float(row["production_oz"]) == 6_100_000.0
    assert float(row["aisc_usd_per_oz"]) == 1395.0
    assert float(row["royalty_rate"]) == 0.045
    assert float(row["tax_rate"]) == 0.28


def test_workspace_note_post_adds_note_and_detail_page_renders_it(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    app = create_workspace_app(paths, tool_b_tickers=["NEM"])

    post_response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/note",
        body="note_text=Check+cost+guidance&note_tag=WATCH&note_status=OPEN",
    )

    assert post_response["status"].startswith("303")

    detail_response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert detail_response["status"].startswith("200")
    assert "Check cost guidance" in detail_response["body"]
    assert "Stock Notes" in detail_response["body"]


def test_workspace_company_post_returns_clean_validation_error_for_bad_numeric_input(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    app = create_workspace_app(paths, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="production_oz=not-a-number",
    )

    assert response["status"].startswith("400")
    assert "must be numeric" in response["body"]


def _write_latest_outputs(paths) -> None:
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "tool_a_score": 78.2,
                    "tool_a_rank": 1,
                    "regime_tag": "POSITIVE",
                    "core_delta": 0.62,
                    "stability_score": 0.81,
                    "gamma_proxy": 0.19,
                },
                {
                    "ticker": "GOLD",
                    "as_of_date": date(2026, 4, 22),
                    "tool_a_score": 66.4,
                    "tool_a_rank": 2,
                    "regime_tag": "POSITIVE",
                    "core_delta": 0.55,
                    "stability_score": 0.73,
                    "gamma_proxy": 0.15,
                },
            ]
        ),
    )
    tool_b_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000.0},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths,
        run_context=tool_b_context,
        tool_b_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "gold_price_assumption": 4000.0,
                    "tool_b_score": 72.5,
                    "tool_b_rank": 1,
                    "screening_verdict": "STRONG_CANDIDATE",
                    "confidence": "VERIFIED",
                    "best_upside_pct": 0.24,
                },
                {
                    "ticker": "GOLD",
                    "as_of_date": date(2026, 4, 22),
                    "gold_price_assumption": 4000.0,
                    "tool_b_score": 63.1,
                    "tool_b_rank": 2,
                    "screening_verdict": "WATCHLIST",
                    "confidence": "ESTIMATED",
                    "best_upside_pct": 0.11,
                },
            ]
        ),
    )


def _call_wsgi_app(app, *, method: str, path: str, body: str = "") -> dict[str, object]:
    payload = body.encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(payload),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    body_bytes = b"".join(app(environ, start_response))
    return {
        "status": captured["status"],
        "headers": dict(captured["headers"]),
        "body": body_bytes.decode("utf-8"),
    }
