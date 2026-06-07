from __future__ import annotations

import io

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.serve.candidate_finder_data import (
    CandidateFinderAlignment,
    CandidateFinderCacheKey,
    CandidateFinderData,
)
from golden_vector.serve.candidate_finder_page import render_candidate_finder_page
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths


def test_candidate_finder_page_renders_default_strong_corporate_finance_screen():
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data)

    assert "Candidate Finder" in html
    assert "Strong Corporate Finance" in html
    assert "candidate-preset is-active" in html
    assert "Options Side" in html
    assert "No option filter" in html
    assert "Screen Builder" in html
    assert "Gold Sensitivity" in html
    assert "Corporate Finance" in html
    assert "Options" in html
    assert "Corporate Resilience" in html
    assert 'class="candidate-criteria-group" open' in html
    assert "View 1: Top Rows By Criterion" in html
    assert "View 2: Fit Ranking" in html
    assert "Eligible Ranking" in html
    assert "Low-Coverage Rows" in html
    assert "js-datatable candidate-ranking-table" in html
    assert 'data-col-name="score" data-sort-numeric' in html
    assert 'data-col-name="criterion_fundamental_check_score" data-sort-numeric' in html
    assert "Score = your weighted-average percentile" in html
    assert "Model build state needs attention" in html
    assert 'aria-label="Use Fundamental checks"' in html
    assert "Mixed refreshes in Candidate Finder sources" in html
    assert "/ticker/AEM?lens=option-trading#option-trading" in html
    assert "recommend" not in html.lower()
    assert "should buy" not in html.lower()


def test_candidate_finder_page_custom_query_preserves_side_direction_and_weight():
    data = _candidate_finder_data()

    html = render_candidate_finder_page(
        data,
        query={
            "custom": ["1"],
            "options_side": ["calls"],
            "top_n": ["1"],
            "criteria": ["up_beta"],
            "direction_up_beta": ["low_good"],
            "weight_up_beta": ["2"],
        },
    )

    assert "Custom criteria are active for this screen." in html
    assert '<option value="calls" selected>Calls</option>' in html
    assert '<option value="low_good" selected>Low values fit</option>' in html
    assert 'name="weight_up_beta" min="0" max="10" step="0.25" value="2"' in html
    assert "Invalid direction" not in html
    assert "candidate-preset is-active" not in html


def test_candidate_finder_page_invalid_preset_falls_back_to_default():
    data = _candidate_finder_data()

    html = render_candidate_finder_page(data, query={"preset": ["banana"]})

    assert "candidate-preset is-active" in html
    assert "Bearish put screen" in html
    assert "Pick at least one criterion" not in html
    assert "Unknown preset ignored" not in html


def test_candidate_finder_page_url_encodes_ticker_links():
    data = _candidate_finder_data()
    data.frame.loc[0, "ticker"] = "A&B"

    html = render_candidate_finder_page(data)

    assert ">A&amp;B</a>" in html
    assert "/ticker/A%26B?lens=option-trading#option-trading" in html


def test_candidate_finder_route_is_reachable(monkeypatch, tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()

    import golden_vector.serve.workspace as workspace_module

    monkeypatch.setattr(
        workspace_module,
        "load_candidate_finder_data",
        lambda _paths, *, app_config: _candidate_finder_data(),
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    response = _call_wsgi_app(app, method="GET", path="/candidate-finder")

    assert response["status"].startswith("200")
    assert "Candidate Finder" in response["body"]
    assert "Candidate Finder</a>" in response["body"]


def _candidate_finder_data() -> CandidateFinderData:
    frame = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "has_usable_put_candidate": True,
                "has_usable_call_candidate": True,
                "down_beta_core": 1.5,
                "up_beta_core": 1.2,
                "aisc_usd_per_oz": 1450.0,
                "leverage": 0.18,
                "margin_pct": 0.60,
                "ev_ebitda": 4.2,
                "forward_pe": 8.0,
                "iv_percentile_cross_sectional": 30.0,
                "confidence_score": 0.92,
                "fcf_yield": 0.05,
                "fundamental_check_score": 85.7143,
                "tool_c_downside_rank": 95.0,
                "tool_c_upside_rank": 80.0,
                "tool_d_quality_rank": 60.0,
                "score_eligible": True,
            },
            {
                "ticker": "NEM",
                "has_usable_put_candidate": True,
                "has_usable_call_candidate": False,
                "down_beta_core": 1.2,
                "up_beta_core": 1.0,
                "aisc_usd_per_oz": 1250.0,
                "leverage": 0.10,
                "margin_pct": 0.68,
                "ev_ebitda": 3.8,
                "forward_pe": 7.0,
                "iv_percentile_cross_sectional": 55.0,
                "confidence_score": 0.84,
                "fcf_yield": 0.03,
                "fundamental_check_score": 100.0,
                "tool_c_downside_rank": 70.0,
                "tool_c_upside_rank": 55.0,
                "tool_d_quality_rank": 85.0,
                "score_eligible": True,
            },
        ]
    )
    return CandidateFinderData(
        frame=frame,
        criteria_config=_repo_app_config().candidate_finder,
        alignment=CandidateFinderAlignment(
            status="WARN",
            message="Mixed refreshes in Candidate Finder sources.",
            tool_a_refresh_run_ids=("tool-a-run",),
            tool_b_refresh_run_ids=("tool-b-run",),
            tool_c_refresh_run_ids=("tool-c-run",),
            tool_d_refresh_run_ids=("tool-d-run",),
            options_refresh_run_id="options-run",
            manual_store_hash="manual-hash",
            manual_store_as_of="2026-06-04T09:00:00Z",
            messages=("Mixed refreshes in Candidate Finder sources.",),
        ),
        cache_key=CandidateFinderCacheKey(
            tool_a_refresh_run_ids=("tool-a-run",),
            tool_b_refresh_run_ids=("tool-b-run",),
            tool_c_refresh_run_ids=("tool-c-run",),
            tool_d_refresh_run_ids=("tool-d-run",),
            options_refresh_run_id="options-run",
            manual_store_hash="manual-hash",
            tool_a_latest_hash="tool-a-hash",
            tool_b_latest_hash="tool-b-hash",
            tool_c_latest_hash="tool-c-hash",
            tool_d_latest_hash="tool-d-hash",
        ),
    )


def _repo_app_config():
    return load_app_config(ProjectPaths.discover()).app


def _call_wsgi_app(app, *, method: str, path: str) -> dict[str, str]:
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
    body = b"".join(app(environ, start_response)).decode("utf-8")
    return {"status": str(captured["status"]), "body": body}
