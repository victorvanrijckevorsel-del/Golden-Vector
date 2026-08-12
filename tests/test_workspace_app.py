from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.contracts.tool_d import (
    TOOL_D_OUTPUT_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
    YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
    select_tool_d_source_rows,
)
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import add_stock_note
from golden_vector.serve.option_trading_data import clear_option_trading_cache
from golden_vector.serve.workspace import create_workspace_app
from golden_vector.serve.workspace_state import _load_tool_a_detail
from tests.helpers import build_test_paths, tool_b_output_row


def test_workspace_root_renders_candidate_finder_outputs(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    add_stock_note(
        paths,
        ticker="NEM",
        note_text="Review next production report",
        note_tag="FOLLOW_UP",
        note_status="OPEN",
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM", "GOLD"])
    response = _call_wsgi_app(app, method="GET", path="/")

    assert response["status"].startswith("200")
    assert "Golden Vector Workspace" in response["body"]
    assert "Candidate Finder" in response["body"]
    assert ">Bull</a>" in response["body"]
    assert ">Bear</a>" in response["body"]
    assert "Full model refresh" in response["body"]
    assert "/ticker/NEM" in response["body"]
    assert "Review next production report" not in response["body"]


def test_workspace_overview_shows_model_state_banner(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "generated_at_utc": "2026-06-05T10:00:00Z",
                "parent_refresh_id": None,
                "state": "incomplete",
                "alignment": {"status": "WARN"},
                "warnings": ["Required artifact is missing: tool_c."],
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/")

    assert response["status"].startswith("200")
    assert "Model build state needs attention" in response["body"]
    assert "Required artifact is missing: tool_c." in response["body"]


def test_workspace_favicon_returns_no_content(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/favicon.ico")

    assert response["status"].startswith("204")
    assert response["body"] == ""


def test_workspace_detail_page_renders_explanations_in_market_behaviour_section(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    # M3c: the section is "Market behaviour"; there is no "Gold Sensitivity" heading.
    assert 'id="market-behaviour"' in response["body"]
    assert "Market behaviour" in response["body"]
    # Regression guard: the workspace now regenerates narrative cards live from
    # numeric inputs + band thresholds (single source of truth = model/explanations.py).
    # With structural_delta_12m=1.9 and high_min=2.0, the builder picks the "moderately
    # high" band. The pre-baked `delta_explanation` field on the row is NOT read.
    assert (
        "Moderately high structural delta means this stock has shown strong gold sensitivity"
        in response["body"]
    )
    # The ladder now reads the separate research-series artifact, which these fixtures do
    # not write — so it must state that honestly instead of drawing anything.
    assert "Exploratory horizon ladder" in response["body"]
    assert (
        "No exploratory horizon rows are published for this ticker." in response["body"]
    )


def test_workspace_detail_page_honors_yahoo_fundamentals_source(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)
    tool_b = pd.read_parquet(paths.latest_tool_b_snapshot_parquet_path)
    tool_b["screening_verdict_official"] = "SCREEN_OUT"
    tool_b["fundamental_check_rank_official"] = 9
    tool_b["leverage_official"] = 8.88
    tool_b["confidence_official"] = "VERIFIED"
    tool_b.to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path="/ticker/NEM?fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    # M3b: the old "Latest Corporate Finance Snapshot" table is gone; the
    # redesigned Corporate finance section replaces it and the financials-source
    # switcher moved to the global control bar.
    assert "Latest Corporate Finance Snapshot" not in response["body"]
    assert 'id="corporate-finance"' in response["body"]
    assert "Financials source" in response["body"]
    assert "Yahoo Fundamentals" in response["body"]
    # Yahoo materialization still drives the numbers (leverage_official 8.88 is
    # the active trailing leverage) ...
    assert "8.88" in response["body"]
    assert "Yahoo financials · Our View mining assumptions" in response["body"]
    assert "$1,234/oz" in response["body"]
    assert "$2,345/oz" not in response["body"]
    # ... but the compiled verdict is BANNED from this page (requirements §3).
    assert "SCREEN_OUT" not in response["body"]
    assert 'href="/?fundamentals_source=yahoo"' in response["body"]
    # the 6M beta-window tab keeps the active source (W1 builds tab hrefs from
    # the page's real query params, so the key ORDER follows the request URL)
    assert "/ticker/NEM?fundamentals_source=yahoo&amp;window=6m" in response["body"]
    # M3d: the "open the Option Trading lens" teaser is gone. Options are a
    # section OF this page now (#options), so the page links to its own anchor
    # instead of routing away, and the section renders even with no option
    # artifacts published — degraded with a reason, never as "no options".
    assert "lens=option-trading" not in response["body"]
    assert '<a class="section-nav-link" href="#options">Options</a>' in response["body"]
    assert 'id="options"' in response["body"]
    assert "no options" not in response["body"].lower()
    assert "/ticker/NEM?fundamentals_source=yahoo" in response["body"]
    assert 'name="return_to" value="/ticker/NEM?fundamentals_source=yahoo"' in response["body"]


def test_workspace_detail_legacy_v3_yahoo_resilience_requires_rebuild(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    legacy_v3 = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "finance_source": "our",
                "tool_d_schema_version": 3,
                "interest_cover_gold_usd": 2345.0,
            }
        ]
    )
    write_parquet_atomic(legacy_v3, paths.latest_tool_d_snapshot_parquet_path)
    write_parquet_atomic(legacy_v3, paths.latest_tool_d_spot_snapshot_parquet_path)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path="/ticker/NEM?fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    assert YAHOO_TOOL_D_REBUILD_REQUIRED_REASON in response["body"]
    assert "$2,345/oz" not in response["body"]


def test_workspace_tool_a_detail_refuses_latest_foundation_when_model_state_corrupt(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    _write_latest_foundation_snapshot(paths)
    paths.latest_model_state_manifest_path.write_text("{not-json", encoding="utf-8")

    detail = _load_tool_a_detail(paths, app_config=app_config, ticker="NEM")

    assert detail.weekly_series.empty
    assert detail.foundation_error is not None
    assert "does not expose a usable immutable foundation artifact" in detail.foundation_error


def test_workspace_detail_lens_param_defaults_to_tool_a(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    default_response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    explicit_response = _call_wsgi_app(app, method="GET", path="/ticker/NEM?lens=tool-a")
    unknown_response = _call_wsgi_app(app, method="GET", path="/ticker/NEM?lens=banana")

    assert default_response["status"].startswith("200")
    assert explicit_response["status"].startswith("200")
    assert unknown_response["status"].startswith("200")
    assert explicit_response["body"] == default_response["body"]
    assert unknown_response["body"] == default_response["body"]


def test_workspace_detail_page_surfaces_normalization_issue_not_a_withheld_score(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 22),
                "anchor_window_id": "12M",
                "volatility_anchor_window_id": "12M",
                "structural_delta_6m": 1.8,
                "structural_delta_12m": 1.9,
                "structural_delta_3y": 1.7,
                "structural_delta_core": 1.9,
                "gamma_6m": -0.25,
                "gamma_12m": -0.22,
                "gamma_3y": -0.18,
                "structural_gamma_core": -0.22,
                "up_beta_6m": 2.2,
                "down_beta_6m": 1.6,
                "up_beta_12m": 2.1,
                "down_beta_12m": 1.5,
                "up_beta_3y": 1.9,
                "down_beta_3y": 1.4,
                "up_beta_core": 2.1,
                "down_beta_core": 1.5,
                "asymmetry_ratio_6m": 1.38,
                "asymmetry_ratio_12m": 1.4,
                "asymmetry_ratio_3y": 1.36,
                "asymmetry_ratio_core": 1.4,
                "r_squared_6m": 0.45,
                "r_squared_12m": 0.42,
                "r_squared_3y": 0.39,
                "weeks_6m": 26,
                "weeks_12m": 52,
                "weeks_3y": 156,
                "window_status_6m": "ELIGIBLE",
                "window_status_12m": "ELIGIBLE",
                "window_status_3y": "ELIGIBLE",
                "delta_stability_score": 0.88,
                "confidence_score": 0.82,
                "confidence_label": "WITHHELD",
                "total_volatility_52w": 0.36,
                "residual_volatility_52w": 0.28,
                "downside_volatility_52w": 0.24,
                "volatility_context": "LOW_NOISE",
                "profile_label": "SCORE_WITHHELD",
                "tool_a_score": None,
                "tool_a_rank": None,
                "score_eligible": False,
                "score_eligibility_reason": "UNACCEPTABLE_NORMALIZATION_STATUS",
                "eligible_structural_window_count": 3,
                "positive_delta_window_count": 3,
                "normalization_issue_summary": "STALE_FX",
                "snapshot_refresh_run_id": "refresh-run",
                "fx_policy_max_staleness_days": 5,
                "fx_policy_block_on_stale_fx": False,
                "delta_explanation": "Structural delta is withheld because trailing FX or return-basis issues block a trustworthy official read.",
                "gamma_explanation": "Gamma is withheld because the official structural sample is blocked by normalization issues.",
                "asymmetry_explanation": "Asymmetry is withheld because the official structural sample is blocked by normalization issues.",
                "volatility_explanation": "Low residual volatility means a relatively large share of annualized weekly log-return movement has been explained by gold rather than idiosyncratic noise.",
                "confidence_explanation": "Confidence is withheld because trailing FX or return-basis issues block a trustworthy official structural read.",
                "interaction_explanation": "Official Tool A score is withheld because trailing FX or return-basis issues make the structural signal untrustworthy.",
                "tool_a_summary_explanation": "Score withheld. Official Tool A score is withheld because trailing FX or return-basis issues make the structural signal untrustworthy.",
                "source_run_id": "tool-a-run",
            }
        ],
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    # Requirements §3: no compiled score/verdict on this page, so the old
    # "score is withheld" sentence is deleted by design ...
    assert "Gold Sensitivity score is withheld" not in response["body"]
    # ... but the DATA-quality status behind it survives, carried by
    # normalization_issue_summary.
    assert (
        "Observed normalization issues in the trailing sample: STALE_FX."
        in response["body"]
    )


def test_workspace_company_post_updates_store(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

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
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

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


def test_workspace_company_post_preserves_unfilled_fields(tmp_path):
    """Regression: submitting a partial form must not null every other numeric column."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body=(
            "production_oz=5900000"
            "&aisc_usd_per_oz=1566"
            "&cash_cost_usd_per_oz=1180"
            "&royalty_rate=3"
            "&sustaining_capex_musd=1400"
            "&da_musd=2500"
            "&interest_expense_musd=200"
            "&tax_rate=28"
            "&reserve_life_years=22"
            "&net_debt_musd=500"
            "&ebitda_ltm_musd=11850"
        ),
    )

    # Second submit: edit only production_oz, leave every other field blank.
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body=(
            "production_oz=6100000"
            "&aisc_usd_per_oz="
            "&cash_cost_usd_per_oz="
            "&royalty_rate="
            "&sustaining_capex_musd="
            "&da_musd="
            "&interest_expense_musd="
            "&tax_rate="
            "&reserve_life_years="
            "&net_debt_musd="
            "&ebitda_ltm_musd="
        ),
    )

    assert response["status"].startswith("303")
    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.company_inputs.loc[loaded.company_inputs["ticker"] == "NEM"].iloc[0]
    assert float(row["production_oz"]) == 6_100_000.0
    # Un-edited fields must still be present.
    assert float(row["aisc_usd_per_oz"]) == 1566.0
    assert float(row["cash_cost_usd_per_oz"]) == 1180.0
    assert float(row["ebitda_ltm_musd"]) == 11850.0


def test_workspace_detail_surfaces_normalization_notice_without_any_score_prose(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 22),
                "anchor_window_id": "12M",
                "volatility_anchor_window_id": "12M",
                "structural_delta_core": 1.9,
                "structural_gamma_core": -0.22,
                "asymmetry_ratio_core": 1.4,
                "up_beta_core": 2.1,
                "down_beta_core": 1.5,
                "confidence_score": None,
                "confidence_label": "WITHHELD",
                "total_volatility_52w": 0.36,
                "residual_volatility_52w": 0.28,
                "downside_volatility_52w": 0.24,
                "volatility_context": "LOW_NOISE",
                "profile_label": "SCORE_WITHHELD",
                "tool_a_score": None,
                "tool_a_rank": None,
                "score_eligible": False,
                "score_eligibility_reason": "UNACCEPTABLE_NORMALIZATION_STATUS",
                "eligible_structural_window_count": 3,
                "positive_delta_window_count": 3,
                "normalization_issue_summary": "STALE_FX",
                "snapshot_refresh_run_id": "refresh-run",
                "fx_policy_max_staleness_days": 5,
                "fx_policy_block_on_stale_fx": False,
                "delta_explanation": "Structural delta is withheld because trailing FX or return-basis issues block a trustworthy official read.",
                "gamma_explanation": "Gamma is withheld because the official structural sample is blocked by normalization issues.",
                "asymmetry_explanation": "Asymmetry is withheld because the official structural sample is blocked by normalization issues.",
                "volatility_explanation": "Low residual volatility means a relatively large share of annualized weekly log-return movement has been explained by gold rather than idiosyncratic noise.",
                "confidence_explanation": "Confidence is withheld because trailing FX or return-basis issues block a trustworthy official structural read.",
                "interaction_explanation": "Official Tool A score is withheld because trailing FX or return-basis issues make the structural signal untrustworthy.",
                "tool_a_summary_explanation": "Score withheld. Official Tool A score is withheld because trailing FX or return-basis issues make the structural signal untrustworthy.",
                "source_run_id": "tool-a-run",
            }
        ],
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    # The compiled-score sentence is gone by design (requirements §3); the
    # data-quality notice it used to sit beside is what survives.
    assert "Gold Sensitivity score is withheld" not in response["body"]
    assert (
        "Observed normalization issues in the trailing sample: STALE_FX."
        in response["body"]
    )


def test_workspace_detail_suppresses_foundation_backed_panels_when_refresh_is_out_of_sync(tmp_path):
    """Phase 1A / v3 §1 (M3c scope): when the foundation manifest has moved past the
    displayed Tool A row, the two foundation-backed panels must be replaced with visible
    fallback cards carrying a title, a reason, and a CLI suggestion. No blank space.
    The research-series panels are NOT foundation-backed and must keep rendering.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 17),
                "anchor_window_id": "12M",
                "volatility_anchor_window_id": "12M",
                "structural_delta_core": 1.9,
                "structural_gamma_core": -0.2,
                "asymmetry_ratio_core": 1.4,
                "up_beta_core": 2.0,
                "down_beta_core": 1.4,
                "confidence_score": 0.82,
                "confidence_label": "HIGH",
                "total_volatility_52w": 0.36,
                "residual_volatility_52w": 0.28,
                "downside_volatility_52w": 0.24,
                "volatility_context": "LOW_NOISE",
                "profile_label": "CONVEX",
                "tool_a_score": 87.2,
                "tool_a_rank": 1,
                "score_eligible": True,
                "score_eligibility_reason": "OK",
                "eligible_structural_window_count": 3,
                "positive_delta_window_count": 3,
                "normalization_issue_summary": None,
                # Deliberately different from the foundation manifest's "refresh-run".
                "snapshot_refresh_run_id": "earlier-refresh",
                "fx_policy_max_staleness_days": 5,
                "fx_policy_block_on_stale_fx": False,
                "delta_explanation": "Moderate structural delta means the stock has shown a meaningful weekly link to gold in the 1Y window.",
                "gamma_explanation": "Negative gamma means sensitivity has been stronger in up-gold weeks than in down-gold weeks.",
                "asymmetry_explanation": "High asymmetry means the stock has captured more upside gold sensitivity than downside gold sensitivity.",
                "volatility_explanation": "Low residual volatility.",
                "confidence_explanation": "High confidence.",
                "interaction_explanation": "Upside-skewed gold exposure.",
                "tool_a_summary_explanation": "Convex. Confidence is high.",
                "source_run_id": "tool-a-run",
            }
        ],
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    body = response["body"]
    # Detail-page alignment notice points the user at the fix.
    assert "foundation snapshot has moved ahead of the published beta row" in body
    # Exactly the two foundation-backed panels appear as suppressed cards.
    assert "Up vs Down Beta &mdash; Out of Sync" in body
    assert "Where its gold beta ranks vs the miner universe &mdash; Out of Sync" in body
    assert body.count("&mdash; Out of Sync") == 2
    assert body.count('<p class="hint">Run <code>python main.py tool-a</code> to realign.</p>') == 2
    # Per codex P2: each suppressed card must carry its own reason sentence
    # in addition to the title and CLI suggestion (the v3 fallback bar).
    expected_reason = "foundation snapshot on disk differs from the published beta row"
    assert body.count(expected_reason) == 2
    # The research-series panels carry their own provenance, so a foundation
    # misalignment must never blank them.
    assert "Weekly return scatter &mdash; Out of Sync" not in body
    assert "Exploratory horizon ladder &mdash; Out of Sync" not in body
    # Volatility panel is not foundation-backed and should still render.
    assert "Volatility diagnostics" in body


def test_workspace_detail_renders_foundation_backed_panels_when_refresh_is_aligned(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    body = response["body"]
    # Suppression language must NOT appear when refreshes align.
    assert "Out of Sync" not in body
    assert "foundation snapshot has moved ahead" not in body
    # Normal panel titles render.
    assert "Weekly return scatter" in body
    assert "Up vs Down Beta" in body
    assert "Where its gold beta ranks vs the miner universe" in body


def test_workspace_detail_suppresses_panels_when_foundation_manifest_is_missing(tmp_path):
    """Phase 1A correction (codex P1): the FOUNDATION_MISSING alignment state must use
    the same per-panel suppressed-card behavior as FOUNDATION_AHEAD, not a single generic
    error panel.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    # Deliberately do NOT call _write_latest_foundation_snapshot — we want
    # latest_foundation_manifest.json to be absent.
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    body = response["body"]
    # Page-level alignment notice for the missing-manifest state.
    assert "No validated foundation snapshot is available" in body
    # Exactly the two foundation-backed panels appear as out-of-sync cards.
    assert "Up vs Down Beta &mdash; Out of Sync" in body
    assert "Where its gold beta ranks vs the miner universe &mdash; Out of Sync" in body
    assert body.count("&mdash; Out of Sync") == 2
    # Per-card reason sentence specific to the missing-manifest state.
    expected_reason = "No validated foundation snapshot is available, so this panel cannot be rebuilt safely"
    assert body.count(expected_reason) == 2
    # CLI suggestion for this state is update-data, not tool-a.
    assert body.count('<p class="hint">Run <code>python main.py update-data</code> to realign.</p>') == 2
    # The research-series panels carry their own provenance and are not suppressed.
    assert "Weekly return scatter &mdash; Out of Sync" not in body
    assert "Exploratory horizon ladder &mdash; Out of Sync" not in body
    # Volatility panel still renders because it reads from the published Tool A row.
    assert "Volatility diagnostics" in body


def test_workspace_detail_suppresses_panels_when_tool_a_row_lacks_refresh_id(tmp_path):
    """Phase 1A correction (codex P2): the TOOL_A_MISSING_REFRESH alignment state must
    also use the per-panel suppressed-card behavior promised by plan v3.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 17),
                "anchor_window_id": "12M",
                "volatility_anchor_window_id": "12M",
                "structural_delta_core": 1.9,
                "structural_gamma_core": -0.2,
                "asymmetry_ratio_core": 1.4,
                "up_beta_core": 2.0,
                "down_beta_core": 1.4,
                "confidence_score": 0.82,
                "confidence_label": "HIGH",
                "total_volatility_52w": 0.36,
                "residual_volatility_52w": 0.28,
                "downside_volatility_52w": 0.24,
                "volatility_context": "LOW_NOISE",
                "profile_label": "CONVEX",
                "tool_a_score": 87.2,
                "tool_a_rank": 1,
                "score_eligible": True,
                "score_eligibility_reason": "OK",
                "eligible_structural_window_count": 3,
                "positive_delta_window_count": 3,
                "normalization_issue_summary": None,
                # Missing snapshot_refresh_run_id intentionally — this is the
                # TOOL_A_MISSING_REFRESH state.
                "snapshot_refresh_run_id": None,
                "fx_policy_max_staleness_days": 5,
                "fx_policy_block_on_stale_fx": False,
                "delta_explanation": "Moderate structural delta.",
                "gamma_explanation": "Negative gamma.",
                "asymmetry_explanation": "High asymmetry.",
                "volatility_explanation": "Low residual volatility.",
                "confidence_explanation": "High confidence.",
                "interaction_explanation": "Upside-skewed gold exposure.",
                "tool_a_summary_explanation": "Convex. Confidence is high.",
                "source_run_id": "tool-a-run",
            }
        ],
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "The published beta row does not carry a snapshot refresh identifier" in body
    assert "Up vs Down Beta &mdash; Out of Sync" in body
    assert "Where its gold beta ranks vs the miner universe &mdash; Out of Sync" in body
    assert body.count("&mdash; Out of Sync") == 2
    expected_reason = (
        "The published beta row does not carry a snapshot refresh identifier, so this panel"
    )
    assert body.count(expected_reason) == 2
    assert body.count('<p class="hint">Run <code>python main.py tool-a</code> to realign.</p>') == 2
    # The research-series panels carry their own provenance and are not suppressed.
    assert "Weekly return scatter &mdash; Out of Sync" not in body
    assert "Exploratory horizon ladder &mdash; Out of Sync" not in body
    assert "Volatility diagnostics" in body


def test_workspace_verification_post_rejects_oversized_notes_with_clean_400(tmp_path):
    """Codex P3 + smoke-check fix: server-side length caps prevent unbounded input."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    huge_notes = "x" * 5_000  # exceeds the 2,000-char verification cap
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            f"&notes={huge_notes}"
        ),
    )
    assert response["status"].startswith("400")
    assert "verification notes are too long" in response["body"]


def test_workspace_note_post_rejects_oversized_text_with_clean_400(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    huge_note = "x" * 6_000  # exceeds the 5,000-char note cap
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/note",
        body=f"note_text={huge_note}",
    )
    assert response["status"].startswith("400")
    assert "note_text is too long" in response["body"]


def test_workspace_company_post_clear_checkbox_wins_over_typed_value(tmp_path):
    """Codex P3 follow-up: when both `clear_<field>=1` and a typed value for the same
    field are submitted, the clear checkbox must win and the field is nulled.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    # Populate.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="production_oz=5900000",
    )
    # Submit conflicting clear + value.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="clear_production_oz=1&production_oz=99999",
    )

    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.company_inputs.loc[loaded.company_inputs["ticker"] == "NEM"].iloc[0]
    assert pd.isna(row["production_oz"])  # cleared, not 99999


def test_workspace_verification_post_clear_checkbox_wins_over_typed_value(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            "&source_url=https%3A%2F%2Fexample.com%2Foriginal"
        ),
    )
    # Conflicting submit: clear + new typed value for the same field.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            "&clear_source_url=1"
            "&source_url=https%3A%2F%2Fexample.com%2Fnew"
        ),
    )

    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.source_verification[
        (loaded.source_verification["ticker"] == "NEM")
        & (loaded.source_verification["field_name"] == "production_oz")
    ].iloc[0]
    assert pd.isna(row["source_url"])  # cleared, not the new URL


def test_workspace_note_post_accepts_exactly_max_length_note(tmp_path):
    """Codex P3 boundary test: a note exactly at MAX_NOTE_TEXT_LENGTH must be accepted."""
    from golden_vector.screening.manual_store import MAX_NOTE_TEXT_LENGTH

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    body = "x" * MAX_NOTE_TEXT_LENGTH
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/note",
        body=f"note_text={body}",
    )
    assert response["status"].startswith("303")  # accepted


def test_workspace_verification_post_rejects_oversized_source_url(tmp_path):
    from golden_vector.screening.manual_store import MAX_SOURCE_URL_LENGTH

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    huge_url = "https://example.com/" + ("x" * (MAX_SOURCE_URL_LENGTH + 100))
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            f"&source_url={huge_url}"
        ),
    )
    assert response["status"].startswith("400")
    assert "source_url is too long" in response["body"]


def test_workspace_note_post_rejects_oversized_note_tag(tmp_path):
    from golden_vector.screening.manual_store import MAX_NOTE_TAG_LENGTH

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    huge_tag = "T" * (MAX_NOTE_TAG_LENGTH + 5)
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/note",
        body=f"note_text=A+normal+note&note_tag={huge_tag}",
    )
    assert response["status"].startswith("400")
    assert "note_tag is too long" in response["body"]


def test_workspace_detail_performance_sits_above_market_behaviour_in_both_alignment_branches(
    tmp_path,
):
    """Consistent visual rhythm in BOTH alignment branches (ported from the old
    chart-above-volatility test): the Performance section always precedes the
    Market-behaviour section, and volatility always sits inside Market behaviour.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_structural_history_file(paths, "NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    def _assert_rhythm(body: str) -> None:
        performance = body.find('id="performance"')
        behaviour = body.find('id="market-behaviour"')
        volatility = body.find("Volatility diagnostics")
        assert performance >= 0
        assert behaviour >= 0
        assert volatility >= 0
        assert performance < behaviour
        # Volatility lives inside the market-behaviour section.
        assert behaviour < volatility

    # Aligned case.
    _assert_rhythm(_call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"])

    # Non-aligned case (foundation manifest's refresh != Tool A row's refresh).
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            _make_tool_a_row("NEM", delta=1.5, up=1.6, down=1.4, score=80.0, rank=1)
            | {"snapshot_refresh_run_id": "earlier-refresh", "source_run_id": "tool-a-run"}
        ],
    )
    _assert_rhythm(_call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"])


def test_workspace_detail_surfaces_corrupt_structural_metrics_at_page_level(tmp_path):
    """Codex follow-up to Fix #5: a corrupt structural-metrics file surfaces ONE
    page-level notice, so the scatter, up/down beta, and structural-window panels
    (which read those metrics) aren't silently degraded. The price-overlay chart no
    longer carries its own duplicate fallback — file health is told once, at page level.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    # Write garbage to the structural-metrics path.
    out_path = paths.latest_tool_a_structural_metrics_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"not a parquet file")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert "Could not read the structural metrics file" in body
    # The old per-chart duplicate of this message is gone (one consistent story).
    assert "Could not read the structural history file" not in body


def test_workspace_verification_post_returns_friendly_date_error_for_invalid_date(tmp_path):
    """Codex fix: invalid source_date should produce a friendly message naming the
    expected format (YYYY-MM-DD), not raw pandas error text.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            "&source_date=2026-13-99"
        ),
    )
    assert response["status"].startswith("400")
    assert "Date must be a real YYYY-MM-DD value" in response["body"]


def test_workspace_company_post_returns_clean_validation_error_for_bad_numeric_input(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="production_oz=not-a-number",
    )

    assert response["status"].startswith("400")
    assert "must be numeric" in response["body"]


def _write_latest_foundation_snapshot(paths) -> None:
    weekly_dates = pd.date_range("2024-01-05", periods=70, freq="W-FRI")
    gold_basis = 1800.0 + (weekly_dates.dayofyear.to_numpy(dtype=float) * 0.9)
    equity_basis = 10.0 + (weekly_dates.dayofyear.to_numpy(dtype=float) * 0.025)
    gold_history = pd.DataFrame(
        {
            "date": weekly_dates.date,
            "close_usd": gold_basis,
            "adj_close_usd": gold_basis,
        }
    )
    equity_history = pd.DataFrame(
        {
            "ticker": "NEM",
            "date": weekly_dates.date,
            "return_basis_usd": equity_basis,
            "normalization_status": "OK",
        }
    )
    gold_path = paths.runs_dir / "refresh-run" / "snapshots" / "raw_gold.parquet"
    equities_path = paths.runs_dir / "refresh-run" / "snapshots" / "usd_equities.parquet"
    market_snapshot_path = paths.runs_dir / "refresh-run" / "snapshots" / "market_snapshots_usd.parquet"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold_history.to_parquet(gold_path, index=False)
    equity_history.to_parquet(equities_path, index=False)
    pd.DataFrame().to_parquet(market_snapshot_path, index=False)

    repo_app_config = _repo_app_config()
    manifest_payload = {
        "refresh_run_id": "refresh-run",
        "command": "update-data",
        "foundation_status": "PASS",
        "foundation_signature": {
            "universe": sorted(
                [
                    {
                        "ticker": ticker.ticker,
                        "currency": ticker.currency,
                        "tool_a_enabled": ticker.tool_a_enabled,
                        "tool_b_enabled": ticker.tool_b_enabled,
                    }
                    for ticker in repo_app_config.universe.tickers
                    if ticker.active and (ticker.tool_a_enabled or ticker.tool_b_enabled)
                ],
                key=lambda item: str(item["ticker"]),
            ),
            "refresh_policy": {
                "max_fx_staleness_days": repo_app_config.qa.max_fx_staleness_days,
                "block_on_stale_fx": repo_app_config.qa.block_on_stale_fx,
            },
        },
        "raw_qa_summary": {"overall_status": "PASS"},
        "normalization_qa_summary": {"overall_status": "PASS"},
        "snapshot_as_of_date": str(weekly_dates.max().date()),
        "gold_history_path": gold_path.relative_to(paths.repo_root).as_posix(),
        "normalized_equities_snapshot_path": equities_path.relative_to(paths.repo_root).as_posix(),
        "normalized_market_snapshots_snapshot_path": market_snapshot_path.relative_to(paths.repo_root).as_posix(),
        "summary": {"foundation_marker": True},
    }
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_latest_outputs(paths, tool_a_rows=None) -> None:
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
            tool_a_rows
            or [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "anchor_window_id": "12M",
                    "volatility_anchor_window_id": "12M",
                    "structural_delta_6m": 1.8,
                    "structural_delta_12m": 1.9,
                    "structural_delta_3y": 1.7,
                    "structural_delta_core": 1.9,
                    "gamma_6m": -0.25,
                    "gamma_12m": -0.22,
                    "gamma_3y": -0.18,
                    "structural_gamma_core": -0.22,
                    "up_beta_6m": 2.2,
                    "down_beta_6m": 1.6,
                    "up_beta_12m": 2.1,
                    "down_beta_12m": 1.5,
                    "up_beta_3y": 1.9,
                    "down_beta_3y": 1.4,
                    "up_beta_core": 2.1,
                    "down_beta_core": 1.5,
                    "asymmetry_ratio_6m": 1.38,
                    "asymmetry_ratio_12m": 1.4,
                    "asymmetry_ratio_3y": 1.36,
                    "asymmetry_ratio_core": 1.4,
                    "r_squared_6m": 0.45,
                    "r_squared_12m": 0.42,
                    "r_squared_3y": 0.39,
                    "weeks_6m": 26,
                    "weeks_12m": 52,
                    "weeks_3y": 156,
                    "window_status_6m": "ELIGIBLE",
                    "window_status_12m": "ELIGIBLE",
                    "window_status_3y": "ELIGIBLE",
                    "delta_stability_score": 0.88,
                    "confidence_score": 0.82,
                    "confidence_label": "HIGH",
                    "total_volatility_52w": 0.36,
                    "residual_volatility_52w": 0.28,
                    "downside_volatility_52w": 0.24,
                    "volatility_context": "LOW_NOISE",
                    "profile_label": "CONVEX",
                    "tool_a_score": 87.2,
                    "tool_a_rank": 1,
                    "score_eligible": True,
                    "score_eligibility_reason": "OK",
                    "eligible_structural_window_count": 3,
                    "positive_delta_window_count": 3,
                    "normalization_issue_summary": None,
                    "snapshot_refresh_run_id": "refresh-run",
                    "fx_policy_max_staleness_days": 5,
                    "fx_policy_block_on_stale_fx": False,
                    "delta_explanation": "High structural delta means this stock has tended to move more than gold on a weekly basis in the 1Y window.",
                    "gamma_explanation": "Negative gamma means sensitivity has been stronger in up-gold weeks than in down-gold weeks in the 1Y window. That points to better upside regime participation.",
                    "asymmetry_explanation": "High asymmetry means the stock has captured more upside gold sensitivity than downside gold sensitivity.",
                    "volatility_explanation": "Low residual volatility means a relatively large share of annualized weekly log-return movement has been explained by gold rather than idiosyncratic noise.",
                    "confidence_explanation": "High confidence means the structural signal is supported by decent fit, enough weekly observations, and consistent window behaviour.",
                    "interaction_explanation": "This is an upside-skewed gold exposure: strong linkage, better up-gold participation than down-gold sensitivity, and manageable noise.",
                    "tool_a_summary_explanation": "Convex. Confidence is high. This is an upside-skewed gold exposure: strong linkage, better up-gold participation than down-gold sensitivity, and manageable noise.",
                    "source_run_id": "tool-a-run",
                }
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
                tool_b_output_row(
                    "NEM",
                    screening_verdict="STRONG_CANDIDATE",
                    confidence="VERIFIED",
                    fundamental_check_score=85.7143,
                    fundamental_check_rank=1,
                    snapshot_refresh_run_id="refresh-run",
                    source_run_id=tool_b_context.run_id,
                )
            ]
        ),
    )


def _write_latest_tool_c_output(paths) -> None:
    context = RunContext.start(
        paths=paths,
        command="tool-c",
        parameters={},
        config_hash="hash",
    )
    persist_tool_c_outputs(
        paths=paths,
        run_context=context,
        tool_c_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "tool_c_downside_rank": 82.0,
                    "tool_c_downside_score": 71.0,
                    "tool_c_upside_rank": 64.0,
                    "tool_c_upside_score": 58.0,
                    "down_beta_core": 1.5,
                    "up_beta_core": 2.1,
                    # Phase-3 display-only per-window betas for the Gold Downside selector
                    # (all 25: down/up beta, r², weeks, status × 6M/12M/2Y/3Y/5Y).
                    "down_beta_6m": 1.18, "up_beta_6m": 1.5, "r_squared_6m": 0.6,
                    "weeks_6m": 26, "window_status_6m": "ELIGIBLE",
                    "down_beta_12m": 1.6, "up_beta_12m": 2.0, "r_squared_12m": 0.5,
                    "weeks_12m": 52, "window_status_12m": "ELIGIBLE",
                    "down_beta_2y": 1.75, "up_beta_2y": 2.2, "r_squared_2y": 0.48,
                    "weeks_2y": 104, "window_status_2y": "ELIGIBLE",
                    "down_beta_3y": 1.85, "up_beta_3y": 2.3, "r_squared_3y": 0.4,
                    "weeks_3y": 156, "window_status_3y": "ELIGIBLE",
                    "down_beta_5y": 1.9, "up_beta_5y": 2.4, "r_squared_5y": 0.45,
                    "weeks_5y": 260, "window_status_5y": "ELIGIBLE",
                    "downside_hit_rate_10pct": 0.42,
                    "upside_hit_rate_10pct": 0.37,
                    "tool_c_downside_tags": "downside_sensitive",
                    "tool_c_upside_tags": "upside_participation",
                    "snapshot_refresh_run_id": "refresh-run",
                    "source_run_id": "tool-c-run",
                }
            ]
        ),
    )


def _write_latest_tool_d_output(paths, *, current_schema: bool = True) -> None:
    if not current_schema:
        # Preserve a real pre-v2 transition fixture without routing it through
        # the strict v4 writer: migration readers must be able to degrade an
        # old alias honestly, while new publication must reject this shape.
        legacy = pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "finance_source": "our",
                    "tool_d_schema_version": 1,
                    "aisc_margin_yield": 0.12,
                    "tool_d_quality_rank": 88.0,
                    "tool_d_quality_score": 76.0,
                    "gold_price_used": 4000.0,
                    "spot_gold_usd": 4000.0,
                    "spot_gold_date": "2026-06-01",
                    "snapshot_refresh_run_id": "refresh-run",
                    "source_run_id": "tool-d-run",
                }
            ]
        )
        write_parquet_atomic(legacy, paths.latest_tool_d_snapshot_parquet_path)
        write_parquet_atomic(legacy, paths.latest_tool_d_spot_snapshot_parquet_path)
        return

    context = RunContext.start(
        paths=paths,
        command="tool-d",
        parameters={},
        config_hash="hash",
    )

    def row(*, source: str, rank: float, score: float, interest_cover: float) -> dict:
        result = {column: None for column in TOOL_D_OUTPUT_COLUMNS}
        result.update(
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 22),
                "finance_source": source,
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                "tool_d_quality_rank": rank,
                "tool_d_quality_score": score,
                "gold_price_used": 4000.0,
                "spot_gold_usd": 4000.0,
                "spot_gold_date": "2026-06-01",
                "headroom_to_breakeven_pct_at_g": 0.62,
                "leverage_stressed_at_g": 0.7,
                "ev_ebitda_at_g": 4.5,
                "margin_per_oz_at_g": 2200.0,
                "aisc_margin_yield_at_g": 0.12,
                "aisc_margin_yield_at_spot": 0.11,
                "interest_cover_gold_usd": interest_cover,
                "screening_verdict": "STRONG_CANDIDATE",
                "resilience_data_status": "OK",
                "tool_d_tags": "strong_headroom",
                "snapshot_refresh_run_id": "refresh-run",
                "source_run_id": context.run_id,
            }
        )
        return result

    persist_tool_d_outputs(
        paths=paths,
        run_context=context,
        expected_tickers=["NEM"],
        tool_d_outputs=pd.DataFrame(
            [
                row(source="our", rank=88.0, score=76.0, interest_cover=2345.0),
                row(source="yahoo", rank=17.0, score=19.0, interest_cover=1234.0),
            ],
            columns=TOOL_D_OUTPUT_COLUMNS,
        ),
        publish_spot_latest_aliases=True,
    )


def _call_wsgi_app(app, *, method: str, path: str, body: str = "") -> dict[str, object]:
    payload = body.encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    if "?" in path:
        path_info, _, query_string = path.partition("?")
    else:
        path_info, query_string = path, ""

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
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


def _repo_app_config():
    return load_app_config(ProjectPaths.discover()).app


# ------------------------- Phase 1B.1 source-verification tests -------------------------


def test_workspace_detail_shows_editable_verification_row_for_every_required_field(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    body = response["body"]
    # Every REQUIRED_MANUAL_FIELD must have a hidden field_name input on the page.
    from golden_vector.screening.manual_data import REQUIRED_MANUAL_FIELDS
    for field in REQUIRED_MANUAL_FIELDS:
        assert f"name=\"field_name\" value=\"{field}\"" in body
    assert body.count("/ticker/NEM/verification") == len(REQUIRED_MANUAL_FIELDS)
    # Status <select> options render.
    for option in ("VERIFIED", "ESTIMATED", "INCOMPLETE"):
        assert f"<option value=\"{option}\"" in body


def test_workspace_verification_new_row_renders_disabled_placeholder_not_verified(tmp_path):
    """Codex P1 regression: a verification row with no existing record must render a
    disabled "Choose status" placeholder as the browser-default-selected option, so a
    user cannot accidentally save VERIFIED on a fresh row by clicking through.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    # No verification rows have been created yet for any field.
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert response["status"].startswith("200")
    # The placeholder must appear once per verification row (11 rows).
    assert body.count('<option value="" disabled selected hidden>Choose status</option>') == 11
    # And the <option value="VERIFIED"> must NOT carry "selected" anywhere on the page.
    assert '<option value="VERIFIED" selected' not in body
    assert '<option value="VERIFIED">' in body  # still present, just not pre-selected


def test_workspace_verification_existing_row_keeps_actual_status_selected(tmp_path):
    """Counterpart: when a verification record already exists for a field, the matching
    <option> must be pre-selected and the placeholder must NOT appear for that field.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    # Create a real verification record for production_oz.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body="field_name=production_oz&verification_status=ESTIMATED",
    )
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    # ESTIMATED is selected somewhere (production_oz row).
    assert '<option value="ESTIMATED" selected' in body
    # Placeholder count should be 10 now (one row has a real status).
    assert body.count('<option value="" disabled selected hidden>Choose status</option>') == 10


def test_workspace_verification_post_upserts_row_and_redirects(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            "&source_date=2026-02-18"
            "&source_url=https%3A%2F%2Fexample.com%2Freport"
            "&notes=Matches+Q4+2025+release"
        ),
    )
    assert response["status"].startswith("303")
    assert "saved=verification" in dict(response["headers"])["Location"]

    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.source_verification[
        (loaded.source_verification["ticker"] == "NEM")
        & (loaded.source_verification["field_name"] == "production_oz")
    ].iloc[0]
    assert row["verification_status"] == "VERIFIED"
    assert str(row["source_date"]) == "2026-02-18"
    assert row["source_url"] == "https://example.com/report"
    assert row["notes"] == "Matches Q4 2025 release"


def test_workspace_detail_post_redirect_preserves_yahoo_source_window_and_lens(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "return_to=%2Fticker%2FNEM%3Ffundamentals_source%3Dyahoo%26window%3D6m"
            "%26lens%3Doption-trading"
            "&field_name=production_oz"
            "&verification_status=VERIFIED"
        ),
    )

    assert response["status"].startswith("303")
    assert dict(response["headers"])["Location"] == (
        "/ticker/NEM?fundamentals_source=yahoo&window=6m&lens=option-trading"
        "&saved=verification"
    )


def test_workspace_verification_post_preserves_unfilled_optional_fields(tmp_path):
    """Null-on-blank guard: POSTing verification_status with blank optional inputs
    must not overwrite existing source_date / source_url / notes with NULL.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    # First write: complete payload.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=aisc_usd_per_oz"
            "&verification_status=VERIFIED"
            "&source_date=2026-02-18"
            "&source_url=https%3A%2F%2Fexample.com%2Fq4"
            "&notes=Q4+2025+AISC+1566"
        ),
    )
    # Second write: change only status; leave optional fields blank.
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=aisc_usd_per_oz"
            "&verification_status=ESTIMATED"
            "&source_date="
            "&source_url="
            "&notes="
        ),
    )
    assert response["status"].startswith("303")

    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.source_verification[
        (loaded.source_verification["ticker"] == "NEM")
        & (loaded.source_verification["field_name"] == "aisc_usd_per_oz")
    ].iloc[0]
    assert row["verification_status"] == "ESTIMATED"
    # Previously-populated optional fields must remain.
    assert str(row["source_date"]) == "2026-02-18"
    assert row["source_url"] == "https://example.com/q4"
    assert row["notes"] == "Q4 2025 AISC 1566"


def test_workspace_company_post_clear_checkbox_nulls_a_specific_field(tmp_path):
    """Codex P2 fix: a per-field "Clear on save" checkbox should null exactly that
    field without touching the others. No CLI dependency.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    # Populate two fields.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="production_oz=5900000&aisc_usd_per_oz=1566",
    )
    # Now clear production_oz via the checkbox; leave aisc untouched.
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="clear_production_oz=1&aisc_usd_per_oz=",
    )
    assert response["status"].startswith("303")

    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.company_inputs.loc[loaded.company_inputs["ticker"] == "NEM"].iloc[0]
    assert pd.isna(row["production_oz"])  # cleared
    assert float(row["aisc_usd_per_oz"]) == 1566.0  # untouched


def test_workspace_verification_post_clear_checkboxes_null_individual_fields(tmp_path):
    """Codex P2 fix: per-field clear checkboxes on the verification form must allow
    clearing source_date / source_url / notes individually without dropping to CLI.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            "&source_date=2026-02-18"
            "&source_url=https%3A%2F%2Fexample.com%2Freport"
            "&notes=Initial+notes"
        ),
    )
    # Clear only the URL.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body=(
            "field_name=production_oz"
            "&verification_status=VERIFIED"
            "&clear_source_url=1"
        ),
    )

    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.source_verification[
        (loaded.source_verification["ticker"] == "NEM")
        & (loaded.source_verification["field_name"] == "production_oz")
    ].iloc[0]
    assert str(row["source_date"]) == "2026-02-18"  # untouched
    assert pd.isna(row["source_url"])  # cleared
    assert row["notes"] == "Initial notes"  # untouched


def test_workspace_verification_post_rejects_invalid_status(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body="field_name=production_oz&verification_status=BOGUS",
    )
    assert response["status"].startswith("400")
    assert "verification_status must be" in response["body"]


def test_verification_section_collapses_edit_forms_for_compactness():
    # The Source Verification panel must be compact: each field's edit form is collapsed behind
    # a <details> (one row per field by default), expanding to the full form on click — while
    # every edit affordance is preserved.
    from golden_vector.serve.detail_forms import _render_verification_section

    html = _render_verification_section(
        ticker="NEM",
        verification_rows=[
            {
                "field_name": "production_oz",
                "verification_status": "VERIFIED",
                "updated_at_utc": "2026-04-24T15:24:12+00:00",
            }
        ],
    )

    # Edit forms are collapsed behind a per-field <details> (compact by default).
    assert '<details class="verification-edit">' in html
    assert "<summary>Edit" in html
    # The form and its controls are still present (editing preserved on expand).
    assert 'class="verification-form"' in html
    assert 'name="verification_status"' in html
    assert ">Save</button>" in html
    # The compact summary surfaces the last-updated date without expanding.
    assert "updated 2026-04-24T15:24:12+00:00" in html


def _write_structural_history_file(
    paths,
    ticker: str,
    *,
    source_run_id: str,
    n_weeks: int = 60,
    delta_offset: float = 1.5,
    extra_window_status: str = "ELIGIBLE",
):
    """Phase 2B test fixture: write a synthetic tool_a_structural_latest.parquet."""
    import numpy as np

    weeks = pd.date_range("2024-01-05", periods=n_weeks, freq="W-FRI")
    rows = []
    for w in weeks:
        delta = float(delta_offset + 0.1 * np.sin((w.dayofyear / 365.0) * 2 * np.pi))
        rows.append(
            {
                "ticker": ticker,
                "as_of_date": w.date(),
                "window_id": "12M",
                "week_count": 52,
                "window_status": extra_window_status,
                "window_reason": "OK",
                "structural_delta": delta,
                "intercept_alpha": 0.001,
                "r_squared": 0.5,
                "up_week_count": 25,
                "down_week_count": 25,
                "up_beta": 1.6,
                "down_beta": 1.4,
                "gamma_value": -0.2,
                "asymmetry_ratio": 1.14,
                "normalization_issue_summary": None,
                "source_run_id": source_run_id,
            }
        )
    frame = pd.DataFrame(rows)
    out_path = paths.latest_tool_a_structural_metrics_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_path, index=False)


def _write_overlay_benchmark_history(paths, ticker: str, *, scale: float) -> None:
    """Write a USD benchmark (GDX/GDXJ) cached history aligned to the foundation snapshot's
    weekly dates, so the rebased overlay can draw the benchmark line end-to-end.

    Mirrors the column shape that ``normalize_equity_history_to_usd`` →
    ``build_structural_weekly_series`` consume (same pipeline as the real benchmarks).
    """
    weekly_dates = pd.date_range("2024-01-05", periods=70, freq="W-FRI")
    prices = scale + (weekly_dates.dayofyear.to_numpy(dtype=float) * 0.03)
    frame = pd.DataFrame(
        {
            "ticker": ticker,
            "date": weekly_dates.date,
            "open_local": prices,
            "high_local": prices * 1.01,
            "low_local": prices * 0.99,
            "close_local": prices,
            "adj_close_local": prices,
            "volume": 1_000_000,
            "currency": "USD",
            "exchange": "BENCHMARK",
            "source": "test",
            "source_symbol": ticker,
            "feed_currency": "USD",
            "price_scale_factor": 1.0,
            "minor_unit_adjusted": False,
            "fetched_at_utc": pd.Timestamp("2026-06-08T00:00:00Z"),
        }
    )
    paths.benchmarks_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(paths.benchmarks_dir / f"{ticker}.parquet", index=False)


def test_workspace_detail_warns_when_structural_metrics_file_is_missing(tmp_path):
    """A missing structural-metrics file surfaces a section-level notice, because the
    beta panels below it read those metrics.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    # Deliberately do NOT write the structural-metrics parquet.

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert (
        "Structural metrics file is missing, so the beta panels below cannot draw their "
        "anchor metrics." in body
    )


def test_workspace_detail_warns_when_structural_metrics_source_run_id_mismatches(tmp_path):
    """Provenance gate: a structural metrics file from a DIFFERENT tool-a run than the
    published row must surface a notice ABOVE the beta panels it warns about.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)  # default tool_a_row carries source_run_id == "tool-a-run"
    # Structural file written with a DIFFERENT source_run_id.
    _write_structural_history_file(paths, "NEM", source_run_id="some-other-run-id")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    warning = (
        "The structural metrics file was produced by a different tool-a run than the "
        "published row, so the beta panels below may not match it."
    )
    assert warning in body
    # The notice must appear ABOVE the panel it warns about, so a user can never read the
    # up/down beta panel as endorsed by a mismatched structural file.
    assert body.find(warning) < body.find("Up vs Down Beta")





def test_workspace_detail_distinguishes_corrupt_structural_metrics_from_missing(tmp_path):
    """A corrupted structural-metrics parquet must produce a distinct page-level
    "Could not read the structural metrics file" notice, not be mis-classified as
    "missing" (which would send the user to the wrong fix).
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    # Write a deliberately-corrupt parquet (just garbage bytes).
    out_path = paths.latest_tool_a_structural_metrics_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"this is not a parquet file")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert "Could not read the structural metrics file" in body
    # The user should NOT see the "missing" wording for a corrupt file.
    assert "Structural metrics file is missing" not in body


def _make_tool_a_row(
    ticker: str,
    *,
    delta: float,
    up: float,
    down: float,
    score: float,
    rank: int,
) -> dict:
    """Helper for lens UX tests — builds a minimal score-eligible Tool A row."""
    return {
        "ticker": ticker,
        "as_of_date": date(2026, 4, 17),
        "anchor_window_id": "12M",
        "volatility_anchor_window_id": "12M",
        "structural_delta_core": delta,
        "structural_gamma_core": down - up,
        "asymmetry_ratio_core": (up / down) if down else None,
        "up_beta_core": up,
        "down_beta_core": down,
        "confidence_score": 0.85,
        "confidence_label": "HIGH",
        "total_volatility_52w": 0.4,
        "residual_volatility_52w": 0.2,
        "downside_volatility_52w": 0.25,
        "volatility_context": "LOW_NOISE",
        "profile_label": "CONVEX" if up > down else "FRAGILE",
        "tool_a_score": score,
        "tool_a_rank": rank,
        "score_eligible": True,
        "score_eligibility_reason": "OK",
        "eligible_structural_window_count": 3,
        "positive_delta_window_count": 3,
        "normalization_issue_summary": None,
        "snapshot_refresh_run_id": "refresh-run",
        "fx_policy_max_staleness_days": 5,
        "fx_policy_block_on_stale_fx": False,
        "r_squared_6m": 0.5,
        "r_squared_12m": 0.6,
        "r_squared_3y": 0.4,
        "window_status_6m": "ELIGIBLE",
        "window_status_12m": "ELIGIBLE",
        "window_status_3y": "ELIGIBLE",
        "delta_explanation": "Test delta.",
        "gamma_explanation": "Test gamma.",
        "asymmetry_explanation": "Test asymmetry.",
        "volatility_explanation": "Test volatility.",
        "confidence_explanation": "Test confidence.",
        "interaction_explanation": "Test interaction.",
        "tool_a_summary_explanation": "Test summary.",
        "source_run_id": "tool-a-run",
    }


def test_workspace_notes_section_sorts_open_first_with_status_badges(tmp_path):
    """Phase 1B.3: notes display should bucket OPEN above WATCH above DONE and tag each
    with a status badge so the workflow is scannable.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    add_stock_note(paths, ticker="NEM", note_text="DONE_NOTE_BODY", note_status="DONE")
    add_stock_note(paths, ticker="NEM", note_text="WATCH_NOTE_BODY", note_status="WATCH")
    add_stock_note(paths, ticker="NEM", note_text="OPEN_NOTE_BODY", note_status="OPEN")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]

    assert response["status"].startswith("200")
    # Summary line.
    assert "3 note(s) total" in body
    assert "1 open" in body
    assert "1 watch" in body
    assert "1 done" in body
    # Status badges render.
    assert "note-open" in body
    assert "note-watch" in body
    assert "note-done" in body
    # Sort order: OPEN body appears before WATCH body, which appears before DONE body.
    open_pos = body.index("OPEN_NOTE_BODY")
    watch_pos = body.index("WATCH_NOTE_BODY")
    done_pos = body.index("DONE_NOTE_BODY")
    assert open_pos < watch_pos < done_pos


def test_workspace_company_form_shows_readiness_summary_and_per_field_badges(tmp_path):
    """Phase 1B.2: the company form must surface (a) overall Tool B readiness — populated /
    verified / estimated / incomplete / missing counts — and (b) a per-field badge that
    distinguishes MISSING, NEEDS VERIFICATION, ESTIMATED, INCOMPLETE, VERIFIED.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    # Populate two of the eleven required fields and verify production_oz only.
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="production_oz=5900000&aisc_usd_per_oz=1566",
    )
    _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body="field_name=production_oz&verification_status=VERIFIED&source_date=2026-02-18",
    )

    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    assert response["status"].startswith("200")
    body = response["body"]
    # Readiness summary line.
    assert "Corporate Finance readiness:" in body
    assert "2/11 fields populated" in body
    assert "1 verified" in body
    assert "9 missing" in body
    # Per-field badges: verified (production_oz), needs verification (aisc), missing (others).
    assert "VERIFIED" in body
    assert "NEEDS VERIFICATION" in body
    assert "MISSING" in body


def test_workspace_verification_post_rejects_unknown_field_name(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/verification",
        body="field_name=not_a_real_field&verification_status=VERIFIED",
    )
    assert response["status"].startswith("400")
    assert "Unsupported verification field_name" in response["body"]


def test_workspace_tool_a_view_renders_only_tool_a_columns(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM", "GOLD"])
    response = _call_wsgi_app(app, method="GET", path="/tool-a")

    assert response["status"].startswith("200")
    assert "Gold Sensitivity" in response["body"]
    # Tool A columns must be present
    assert "Δ Core" in response["body"]
    assert "Gamma" in response["body"]
    assert "Asymmetry" in response["body"]
    # Tool B-specific columns must NOT bleed in
    assert "Corporate Finance Score" not in response["body"]
    assert "Verdict" not in response["body"]
    # Nav must mark this tab active
    assert 'aria-current="page" href="/tool-a"' in response["body"]


def test_workspace_tool_b_view_renders_only_tool_b_columns(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM", "GOLD"])
    response = _call_wsgi_app(app, method="GET", path="/tool-b")

    assert response["status"].startswith("200")
    assert "Corporate Finance" in response["body"]
    # Tool B columns must be present
    assert "Verdict" in response["body"]
    assert "Checks Passed %" in response["body"]
    assert "Forward P/E est." in response["body"]
    assert "EV/EBITDA est." in response["body"]
    assert "Net Debt/EBITDA" in response["body"]
    # Target-price scenarios are intentionally gone.
    assert "Peer P/E Target" not in response["body"]
    assert "Peak P/E Target" not in response["body"]
    assert "Peer FCF Target" not in response["body"]
    assert "Peak FCF Target" not in response["body"]
    assert "Best Target" not in response["body"]
    # Tool A-specific structural columns must NOT bleed in
    assert "Δ Core" not in response["body"]
    assert "Asymmetry" not in response["body"]
    # Nav must mark this tab active
    assert 'aria-current="page" href="/tool-b"' in response["body"]


def test_workspace_tool_c_view_renders_gold_downside_page(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_c_output(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-c")

    assert response["status"].startswith("200")
    assert "Gold Downside" in response["body"]
    assert "tool-c-table" in response["body"]
    assert "Downside Score" in response["body"]
    assert "Downside Rank" not in response["body"]
    assert 'aria-current="page" href="/tool-c"' in response["body"]
    # Phase 3: shared beta-window selector + a Gold-link trust column on Gold Downside.
    assert "window-switcher" in response["body"]
    assert "window=2Y" in response["body"] and "window=5Y" in response["body"]
    assert ">1Y</a>" in response["body"] and ">2Y</a>" in response["body"]
    assert "Gold-link" in response["body"]
    assert "1.60" in response["body"]  # default 12M windowed down beta (not the 1.5 core)
    # switching the window switches the displayed beta to that lookback
    response_5y = _call_wsgi_app(app, method="GET", path="/tool-c?window=5Y")
    assert 'name="window" value="5Y"' in response_5y["body"]
    assert "1.90" in response_5y["body"]  # 5Y windowed down beta
    # an intermediate display-only window (2Y) also switches the displayed beta
    response_2y = _call_wsgi_app(app, method="GET", path="/tool-c?window=2Y")
    assert 'name="window" value="2Y"' in response_2y["body"]
    assert "1.75" in response_2y["body"]  # 2Y windowed down beta


def test_workspace_tool_c_view_degrades_gracefully_for_old_artifact(tmp_path):
    """Backward compatibility: a pre-Phase-3 Tool C artifact has NO per-window beta columns.
    The Gold Downside page must still render (selector + core-based ranks) and show muted
    em-dash cells for the windowed betas at every window, never crash (optional display
    data degrades per item; mirrors the benchmark-betas old-artifact handling)."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    # Old artifact: core betas + ranks only, NO per-window display columns.
    context = RunContext.start(paths=paths, command="tool-c", parameters={}, config_hash="hash")
    persist_tool_c_outputs(
        paths=paths,
        run_context=context,
        tool_c_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "tool_c_downside_rank": 82.0,
                    "tool_c_downside_score": 71.0,
                    "tool_c_upside_rank": 64.0,
                    "tool_c_upside_score": 58.0,
                    "down_beta_core": 1.5,
                    "up_beta_core": 2.1,
                    "downside_hit_rate_10pct": 0.42,
                    "upside_hit_rate_10pct": 0.37,
                    "tool_c_downside_tags": "downside_sensitive",
                    "tool_c_upside_tags": "upside_participation",
                    "snapshot_refresh_run_id": "refresh-run",
                    "source_run_id": "tool-c-run",
                }
            ]
        ),
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    for window in ("12M", "2Y", "5Y"):
        response = _call_wsgi_app(app, method="GET", path=f"/tool-c?window={window}")
        assert response["status"].startswith("200"), window
        assert "Gold Downside" in response["body"]
        assert "window-switcher" in response["body"]  # selector still renders
        assert "82.0" in response["body"]  # core-based downside rank still shown
        # the windowed beta cells degrade to the muted None cell, not a crash or
        # stale value — missing values sort with the shared product-wide
        # sentinel (deep-review M3), never the old -999 missing-first order.
        assert 'data-order="9000000000000000"' in response["body"], window
        assert 'data-order="-999"' not in response["body"], window


def test_workspace_tool_d_view_renders_corporate_resilience_page(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-d")

    assert response["status"].startswith("200")
    assert "Corporate Resilience" in response["body"]
    assert "tool-d-table" in response["body"]
    assert "Resilience Score" in response["body"]
    assert "Interest-Cover Line" in response["body"]
    assert "Breakeven Gold" in response["body"]
    assert "Financials source" in response["body"]
    assert "/tool-d?gold_price=3400.00" in response["body"]
    assert 'aria-current="page" href="/tool-d"' in response["body"]


_TOOL_D_LEGACY_FCF_WARNING = (
    "This table was built before the FCF-yield fix (Tool D schema v1). "
    "FCF Yield @ G shows 'pending rebuild' until the next data refresh."
)


def _render_tool_d_page(tmp_path, *, current_schema: bool) -> str:
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths, current_schema=current_schema)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-d")
    assert response["status"].startswith("200")
    return str(response["body"])


def test_workspace_tool_d_legacy_artifact_declares_pending_fcf_rebuild(tmp_path):
    """A pre-v2 artifact must say so, never silently render the missing-value dash."""
    body = _render_tool_d_page(tmp_path, current_schema=False)

    assert _TOOL_D_LEGACY_FCF_WARNING in body
    assert "notice-warning" in body or "warning" in body
    assert "<td class=\"hint\">pending rebuild</td>" in body


def test_workspace_tool_d_current_artifact_renders_fcf_without_warning(tmp_path):
    """Control: a current-schema artifact renders the number and no warning."""
    body = _render_tool_d_page(tmp_path, current_schema=True)

    assert _TOOL_D_LEGACY_FCF_WARNING not in body
    assert "pending rebuild" not in body
    assert "12.0%" in body


def test_tool_d_source_selector_reports_legacy_v3_yahoo_rebuild() -> None:
    selection = select_tool_d_source_rows(
        pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "finance_source": "our",
                    "tool_d_schema_version": 3,
                }
            ]
        ),
        finance_source="yahoo",
        ticker="NEM",
        label="ticker NEM",
    )

    assert selection.frame.empty
    assert selection.reason == YAHOO_TOOL_D_REBUILD_REQUIRED_REASON


@pytest.mark.parametrize("version", [3.9, 4.9])
def test_tool_d_source_selector_rejects_fractional_schema_versions(version: float) -> None:
    selection = select_tool_d_source_rows(
        pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "finance_source": "our",
                    "tool_d_schema_version": version,
                }
            ]
        ),
        finance_source="yahoo",
        label="Corporate Resilience overview",
    )

    assert selection.frame.empty
    assert "malformed Tool D schema-version metadata" in str(selection.reason)
    assert selection.reason != YAHOO_TOOL_D_REBUILD_REQUIRED_REASON


def test_tool_d_source_selector_never_serves_selected_rows_with_malformed_version() -> None:
    selection = select_tool_d_source_rows(
        pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "finance_source": "our",
                    "tool_d_schema_version": 4.9,
                }
            ]
        ),
        finance_source="our",
        ticker="NEM",
        label="ticker NEM",
    )

    assert selection.frame.empty
    assert "malformed Tool D schema-version metadata" in str(selection.reason)


def test_tool_d_source_selector_rejects_yahoo_row_labelled_as_legacy_v3() -> None:
    selection = select_tool_d_source_rows(
        pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "finance_source": "yahoo",
                    "tool_d_schema_version": 3,
                }
            ]
        ),
        finance_source="yahoo",
        ticker="NEM",
        label="ticker NEM",
    )

    assert selection.frame.empty
    assert "legacy Tool D artifact contains a non-Our-View source" in str(selection.reason)
    assert selection.reason != YAHOO_TOOL_D_REBUILD_REQUIRED_REASON


def test_tool_d_source_selector_rejects_mixed_legacy_schema_generations() -> None:
    selection = select_tool_d_source_rows(
        pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "finance_source": "our",
                    "tool_d_schema_version": 1,
                },
                {
                    "ticker": "AEM",
                    "finance_source": "our",
                    "tool_d_schema_version": 3,
                },
            ]
        ),
        finance_source="our",
        label="Corporate Resilience overview",
    )

    assert selection.frame.empty
    assert "malformed Tool D schema-version metadata" in str(selection.reason)


def test_tool_d_source_selector_resolves_the_legacy_official_request_token() -> None:
    """W4: `official` is the Yahoo token older links still emit. It must take the
    YAHOO branch of this selector, not fall through to Our View."""

    frame = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "finance_source": "our",
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                "interest_cover_gold_usd": 2345.0,
            },
            {
                "ticker": "NEM",
                "finance_source": "yahoo",
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                "interest_cover_gold_usd": 1234.0,
            },
        ]
    )

    selection = select_tool_d_source_rows(
        frame,
        finance_source="official",
        ticker="NEM",
        label="ticker NEM",
    )

    assert selection.reason is None
    assert selection.frame["interest_cover_gold_usd"].tolist() == [1234.0]

    # ...and the same token on a legacy v3 (Our-View-only) artifact reports the
    # rebuild reason rather than silently serving Our View numbers as Yahoo.
    legacy = select_tool_d_source_rows(
        pd.DataFrame(
            [{"ticker": "NEM", "finance_source": "our", "tool_d_schema_version": 3}]
        ),
        finance_source="official",
        ticker="NEM",
        label="ticker NEM",
    )
    assert legacy.frame.empty
    assert legacy.reason == YAHOO_TOOL_D_REBUILD_REQUIRED_REASON


def test_tool_d_source_selector_rejects_duplicate_source_ticker_rows() -> None:
    duplicate = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "finance_source": "yahoo",
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
            },
            {
                "ticker": "nem",
                "finance_source": "yahoo",
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
            },
        ]
    )

    with pytest.raises(ValueError, match=r"duplicate persisted \(ticker, finance_source\)"):
        select_tool_d_source_rows(
            duplicate,
            finance_source="yahoo",
            label="Corporate Resilience overview",
        )


def test_workspace_tool_d_yahoo_source_reads_persisted_rows_and_preserves_links(
    tmp_path,
    monkeypatch,
):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)
    def unexpected_recompute(**_kwargs):
        raise AssertionError("plain at-spot Yahoo must read the persisted v4 row")

    monkeypatch.setattr(
        "golden_vector.serve.overview_tool_d._compute_scenario_frame",
        unexpected_recompute,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path="/tool-d?fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    assert "Scenario recomputed" not in response["body"]
    assert '<td data-order="1234.0">1,234</td>' in response["body"]  # Yahoo sentinel
    assert '<td data-order="2345.0">2,345</td>' not in response["body"]
    assert 'value="yahoo" selected>Yahoo Fundamentals</option>' in response["body"]
    assert 'name="gold_price" type="number" min="1" step="1" value=""' in response["body"]
    assert "/tool-d?gold_price=3400.00&amp;fundamentals_source=yahoo" in response["body"]
    assert "/ticker/NEM?fundamentals_source=yahoo" in response["body"]


def test_workspace_tool_d_yahoo_scenario_failure_keeps_source_and_spot_row(
    tmp_path,
    monkeypatch,
):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)

    def fail_compute_scenario_frame(**_kwargs):
        raise RuntimeError("official fundamentals unreadable")

    monkeypatch.setattr(
        "golden_vector.serve.overview_tool_d._compute_scenario_frame",
        fail_compute_scenario_frame,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path="/tool-d?fundamentals_source=yahoo&gold_price=3000",
    )

    assert response["status"].startswith("200")
    assert "Could not compute Yahoo Fundamentals stress scenario" in response["body"]
    assert "was NOT applied" in response["body"]
    assert 'value="yahoo" selected>Yahoo Fundamentals</option>' in response["body"]
    assert '<td data-order="1234.0">1,234</td>' in response["body"]
    assert '<td data-order="2345.0">2,345</td>' not in response["body"]


def test_workspace_tool_d_override_does_not_touch_spot_parquet(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)
    spot_path = paths.latest_tool_d_spot_snapshot_parquet_path
    before = spot_path.read_bytes()
    scenario_frame = pd.read_parquet(spot_path).copy()
    scenario_frame["gold_price_used"] = 3000.0

    def fake_compute_scenario_frame(**_kwargs):
        return scenario_frame

    monkeypatch.setattr(
        "golden_vector.serve.overview_tool_d._compute_scenario_frame",
        fake_compute_scenario_frame,
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-d?gold_price=3000")

    assert response["status"].startswith("200")
    assert "Scenario recomputed in" in response["body"]
    assert spot_path.read_bytes() == before


def test_workspace_tool_d_override_rejects_nonfinite_gold_price(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-d?gold_price=nan")

    assert response["status"].startswith("200")
    assert "Gold price must be a finite positive number" in response["body"]


def test_workspace_tool_d_flip_section_renders_all_backend_rows(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)
    base = pd.read_parquet(paths.latest_tool_d_spot_snapshot_parquet_path).iloc[0].to_dict()
    scenario_rows = []
    for index in range(15):
        row = dict(base)
        row["ticker"] = f"FLIP{index:02d}"
        row["gold_price_used"] = 3000.0
        row["resilience_flip_flags"] = "flips_margin_negative"
        scenario_rows.append(row)

    def fake_compute_scenario_frame(**_kwargs):
        return pd.DataFrame(scenario_rows)

    monkeypatch.setattr(
        "golden_vector.serve.overview_tool_d._compute_scenario_frame",
        fake_compute_scenario_frame,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-d?gold_price=3000")

    assert response["status"].startswith("200")
    assert "FLIP00" in response["body"]
    assert "FLIP14" in response["body"]


def test_threshold_backed_help_calls_always_receive_app_config():
    # A help_th/help_icon/help_term call whose key carries a config-driven threshold
    # silently drops the threshold sentence when app_config is not passed (the panel
    # only resolves thresholds when app_config is present). This guard fails loud if
    # any serve render path calls such a key without app_config, so the "live
    # site-wide thresholds" claim stays true (Codex options-UI review LOW).
    import re

    from golden_vector.serve.column_help import COLUMN_HELP

    threshold_keys = {
        key for key, spec in COLUMN_HELP.items() if spec.thresholds is not None
    }
    assert threshold_keys  # the registry has threshold-backed entries

    call_re = re.compile(r"help_(?:th|icon|term)\s*\(")
    offenders: list[str] = []
    for module in sorted(Path("golden_vector/serve").glob("*.py")):
        if module.name == "column_help.py":
            continue
        source = module.read_text(encoding="utf-8")
        for match in call_re.finditer(source):
            depth = 0
            end = match.end() - 1
            for index in range(match.end() - 1, len(source)):
                char = source[index]
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            call = source[match.start() : end + 1]
            key_match = re.search(r'key\s*=\s*"([a-z0-9_]+)"', call)
            # A real config must be passed: missing app_config OR app_config=None both
            # drop the threshold sentence, so reject both (Codex re-review: the earlier
            # guard accepted app_config=None and let Tool D's flip table slip through).
            has_real_app_config = re.search(r"app_config\s*=\s*(?!None\b)\S", call)
            if (
                key_match
                and key_match.group(1) in threshold_keys
                and not has_real_app_config
            ):
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{module.name}:{line} key={key_match.group(1)}")
    assert not offenders, (
        "threshold-backed help calls without a real app_config (their threshold "
        "sentence will silently drop): " + "; ".join(offenders)
    )


def test_workspace_tool_d_serve_layer_has_no_resilience_arithmetic():
    source = Path("golden_vector/serve/overview_tool_d.py").read_text(encoding="utf-8")

    assert "compute_tool_d_outputs" in source
    for forbidden in (
        "aisc_usd_per_oz",
        "production_oz",
        "sustaining_capex_musd",
        "interest_expense_musd",
        "net_debt_musd /",
        "forward_ebitda_musd_at_g /",
        "spot_gold *",
        "* 0.85",
        "* 0.75",
        "* 0.65",
        "_linear_ebitda_model",
        "_fcf_breakeven_gold",
        "_debt_stress_gold",
    ):
        assert forbidden not in source


def test_workspace_tool_b_serve_layer_has_no_financial_arithmetic():
    """The Tool B page renders backend-resolved columns only. No ratio
    math, no pandas-frame coalesce (.fillna/.combine_first), and no config-gold
    fallback may creep into serve — the gold dial's correctness depends on the
    page showing exactly what the one Tool B model computed (gold-dial plan,
    Codex MEDIUM 4). Dual-source ratio display fields are materialized upstream;
    serve must not inspect our-view/Yahoo ratio suffixes to decide active or
    alternate values."""
    source = Path("golden_vector/serve/overview_tool_b.py").read_text(encoding="utf-8")

    # The page must call the ONE Tool B model and the shared spot resolver.
    assert "compute_tool_b_in_memory" in source
    assert "latest_gold_price_from_history" in source
    for forbidden in (
        # Config-gold fallback: the dial prices at spot or an explicit
        # request, never the config constant.
        "resolve_gold_price",
        # Formula tokens: any of these in serve means forked Tool B math.
        "production_oz *",
        "* production_oz",
        "- aisc_usd_per_oz",
        "aisc_usd_per_oz -",
        "net_debt_musd /",
        "+ net_debt_musd",
        "market_cap_musd +",
        "/ forward_ebitda_musd",
        "/ ebitda",
        # Coalesce/fallback resolution belongs in the backend bundle.
        ".fillna(",
        ".combine_first(",
        # Ratio source resolution belongs in materialize_tool_b_finance_source.
        "resolve_dual_source",
        "prefer_official",
        "ev_ebitda_our_view",
        "ev_ebitda_official",
        "leverage_our_view",
        "leverage_official",
    ):
        assert forbidden not in source, forbidden


def test_ticker_page_options_serve_layer_has_no_option_arithmetic():
    """The M3d Options section renders backend-resolved columns only.

    Canon: every new serve surface gets a static-scan guardrail (clone of the
    Tool-D/Tool-B serve-arithmetic tests). The exhaustive token list lives with
    the section's own tests; this is the repo-wide sweep's entry for it, so a
    new serve surface can never be added without one.
    """
    source = Path("golden_vector/serve/ticker_page/options.py").read_text(encoding="utf-8")

    # It reads the persisted ratio columns by name (display only).
    assert "put_call_oi_ratio_total" in source
    for forbidden in (
        "put_oi_total /",
        "/ call_oi_total",
        "* OPTION_CONTRACT_MULTIPLIER",
        "black_scholes",
        "compute_scenario_bundle",
        ".fillna(",
        ".combine_first(",
    ):
        assert forbidden not in source, forbidden


def test_metric_formula_serve_layer_has_no_ratio_recompute():
    """metric_formula.py renders pre-computed ratio results + component VALUES for the info
    buttons; it must never recompute a ratio in serve (a recompute could make the popover
    disagree with the backend-computed cell). Canon: every new serve surface gets a static-scan
    guardrail (clone of the Tool-D/Tool-B serve-arithmetic tests)."""
    source = Path("golden_vector/serve/metric_formula.py").read_text(encoding="utf-8")
    # It reads the pre-computed result field by name (display only).
    assert "result_field" in source
    for forbidden in (
        "- aisc_usd_per_oz",
        "aisc_usd_per_oz -",
        "net_debt_musd /",
        "+ net_debt_musd",
        "market_cap_musd +",
        "/ forward_ebitda_musd",
        "/ ebitda",
        "/ market_cap_musd",
        "share_price_usd /",
        ".fillna(",
        ".combine_first(",
    ):
        assert forbidden not in source, forbidden


def test_dual_source_ratio_resolution_is_materialized_before_serve():
    """Serve helpers may format alternate-source fields, but source/coalesce decisions stay in
    the Tool B materializer."""

    for path in (
        Path("golden_vector/serve/detail_panels.py"),
        Path("golden_vector/serve/format_helpers.py"),
    ):
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "resolve_dual_source",
            "prefer_official",
            "ev_ebitda_our_view",
            "ev_ebitda_official",
            "leverage_our_view",
            "leverage_official",
        ):
            assert forbidden not in source, f"{path}: {forbidden}"


def test_charts_serve_layer_is_display_only():
    """charts.py maps already-computed values to pixels (x_at/y_at) and formats display-axis
    percents (_pct_label = value − base). Canon: every new serve surface gets a static-scan
    guardrail. No ratio recompute, no pandas-frame coalesce, and no rank/source resolution may
    creep into the chart layer — a chart must never become a second place business math lives."""
    source = Path("golden_vector/serve/charts.py").read_text(encoding="utf-8")
    for forbidden in (
        "- aisc_usd_per_oz",
        "net_debt_musd /",
        "/ ebitda",
        "/ forward_ebitda_musd",
        "/ market_cap_musd",
        "production_oz *",
        ".fillna(",
        ".combine_first(",
        "_official",  # no our-view/Yahoo source-resolution in the chart layer
        "resolve_gold_price",
    ):
        assert forbidden not in source, forbidden


def test_one_info_affordance_no_legacy_hover_remains():
    """The whole app shows info ONE way — the click-to-open panel. No serve module may emit the
    old dotted-hover tooltip (class="help-term" / a bare data-help= attribute), and the popover
    script must no longer carry the hover handler. (Structured data-help-* attrs are the panel.)"""
    import pathlib

    serve = pathlib.Path("golden_vector/serve")
    for py in serve.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert 'class="help-term"' not in src, py
        assert 'data-help="' not in src, py  # bare data-help= is the dead hover; data-help-* is fine
    js = (serve / "static" / "help-popover.js").read_text(encoding="utf-8")
    assert "help-term" not in js  # hover handler removed; only the click panel remains
    css_files = [serve / "static" / "workspace.css"]
    css_files.extend(sorted((serve / "static" / "css").glob("*.css")))
    for css_path in css_files:
        css = css_path.read_text(encoding="utf-8")
        assert ".help-term" not in css, css_path
        assert "th[title]" not in css, css_path


def test_dual_source_ratio_cell_is_compact_and_shows_yahoo_divergence():
    """The dual-source ratio treatment (compact value, no unit suffix, plus a
    "(Yahoo X)" divergence accent) survives the M3b ticker-page redesign.

    Its detail-page wrapper (`_snapshot_metric_value`) was DELETED with the old
    "Latest Corporate Finance Snapshot" table — that table carried
    `fundamental_check_summary`, `fundamental_check_rank` and
    `screening_verdict`, which the locked requirements ban from the ticker page.
    The behaviour itself has one surviving implementation, on the Tool B
    overview, and this test now pins that one."""
    import pandas as pd

    from golden_vector.screening.pipeline import materialize_tool_b_finance_source
    from golden_vector.screening.schema import TOOL_B_OUTPUT_COLUMNS
    from golden_vector.serve.overview_tool_b import _comparison_numeric_td

    def materialized(row: dict[str, object], finance_source: str) -> dict[str, object]:
        full_row = {column: None for column in TOOL_B_OUTPUT_COLUMNS}
        full_row.update(row)
        return materialize_tool_b_finance_source(
            pd.DataFrame([full_row]),
            finance_source=finance_source,
        ).iloc[0].to_dict()

    def cell_text(row: dict[str, object]) -> str:
        """The displayed value only — the trailing help button is not the cell."""
        html = _comparison_numeric_td(row, "ev_ebitda", decimals=1, rank_by="ev_ebitda")
        inner = html[html.index(">") + 1 : html.rindex("</td>")]
        return inner.split("<button")[0].strip()

    # Our View active, our-view 2.0 vs Yahoo 3.5, flagged as differing.
    cell = cell_text(
        materialized(
            {
                "ev_ebitda": 2.0,
                "ev_ebitda_our_view": 2.0,
                "ev_ebitda_official": 3.5,
                "ev_ebitda_differs": True,
            },
            "our",
        )
    )
    assert cell.startswith("2.0 ")  # compact active value, no unit suffix
    assert "x" not in cell  # cell carries no 'x' (header/popover do)
    assert "source-alternate" in cell and "(Yahoo 3.5)" in cell

    # No divergence -> plain compact value, no accent.
    plain = cell_text(materialized({"ev_ebitda": 2.0, "ev_ebitda_differs": False}, "our"))
    assert "source-alternate" not in plain and plain.startswith("2.0")

    # Yahoo source active (base materialized to the official value) -> alternate is Our View.
    ycell = cell_text(
        materialized(
            {
                "ev_ebitda": 2.0,
                "ev_ebitda_our_view": 2.0,
                "ev_ebitda_official": 3.5,
                "ev_ebitda_differs": True,
            },
            "yahoo",
        )
    )
    assert ycell.startswith("3.5 ") and "(Our View 2.0)" in ycell


def test_workspace_candidate_finder_serve_layer_has_no_forked_tool_b_d_math():
    """Canon-required per-surface guardrail (previously missing): the Candidate Finder
    serve layer DELEGATES to the one Tool B / Tool D models and never reimplements
    their ratio/score formulas. The spot-vs-scenario tolerance + gold_price_basis
    decision are sanctioned here exactly as on the Tool B page (it sets the rank basis
    from the resolved spot, it does not compute Tool B/D math)."""
    source = Path("golden_vector/serve/candidate_finder_data.py").read_text(encoding="utf-8")

    # Must call the ONE backend compute path for each tool.
    assert "compute_tool_b_in_memory" in source
    assert "compute_tool_d_outputs" in source
    # No forked Tool B / Tool D formula fragments may appear in serve. (.fillna( is
    # NOT forbidden here — it is used only on boolean has_usable_* display masks.)
    for forbidden in (
        "production_oz *",
        "* production_oz",
        "- aisc_usd_per_oz",
        "aisc_usd_per_oz -",
        "net_debt_musd /",
        "+ net_debt_musd",
        "/ forward_ebitda_musd",
        "/ ebitda",
        "_linear_ebitda_model",
        "_fcf_breakeven_gold",
        "_debt_stress_gold",
        ".combine_first(",
    ):
        assert forbidden not in source, forbidden


def test_workspace_tool_b_dial_recompute_shows_timing_and_scenario_basis(tmp_path):
    """Moving the dial recomputes live: the page must show the instrumented
    timing message and state the scenario basis with spot alongside."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-b?gold_price=3000")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Scenario active" in body
    assert "Scenario recomputed in" in body
    assert "inputs loaded in" in body
    assert "are at scenario gold $3,000/oz" in body
    # Spot preset stays visible (dated) so the user can always get back.
    assert "Reset to spot" in body
    # The dial input reflects the active scenario price.
    assert 'name="gold_price" type="number" min="1" step="1" value="3000"' in body


def test_workspace_tool_b_market_ours_controls_render_from_backend_columns(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000.0},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths,
        run_context=context,
        tool_b_outputs=pd.DataFrame(
            [
                tool_b_output_row(
                    "GOLD",
                    fundamental_check_score=90.0,
                    fundamental_check_rank=1,
                    divergent_field_count=0,
                ),
                tool_b_output_row(
                    "NEM",
                    fundamental_check_score=80.0,
                    fundamental_check_rank=2,
                    ev_ebitda=2.4,
                    ev_ebitda_official=3.2,
                    ev_ebitda_differs=True,
                    leverage=0.4,
                    leverage_official=0.25,
                    leverage_differs=True,
                    financial_data_status="OK",
                    divergent_field_count=2,
                    max_divergence_pct=1.0,
                ),
            ]
        ),
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["GOLD", "NEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path="/tool-b?rank_by=official&differences_only=1",
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Differences only" in body
    assert 'value="yahoo" selected>Yahoo Fundamentals</option>' in body
    # Compact one-line divergence: active (Yahoo) value reads inline, the differing Our View
    # value is a short accent parenthetical — not the old 3-line stacked cell.
    assert "(Our View 2.4)" in body
    assert "market-ours-pair" not in body
    assert "Yahoo Fundamentals 3.2" not in body  # active source isn't relabelled in-cell
    # The EV/EBITDA cell carries the unified info panel: title + the generic formula (in the
    # structured data-help-formula slot, from COLUMN_HELP) + this ticker's numbers in the
    # "This stock" values slot.
    assert 'data-help-title="EV/EBITDA"' in body
    assert "(Market cap + net debt) / forward EBITDA" in body  # formula in data-help-formula
    # Source consistency: in Yahoo (official) mode the "This stock" result equals the DISPLAYED
    # active value (3.2), not the Our View value (2.4) — the cell and its info button must agree.
    assert "→ 3.2x" in body
    assert "→ 2.4x" not in body
    assert "/ticker/NEM?fundamentals_source=yahoo" in body
    assert "/ticker/GOLD" not in body


def test_workspace_tool_b_view_renders_screening_parameters_form(tmp_path):
    """The /tool-b view now carries a Screening Parameters panel with 10
    yellow-cell-equivalent inputs so the user can tune scenarios without
    touching YAML or CLI."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-b")

    assert response["status"].startswith("200")
    body = response["body"]
    # The gold dial is the primary control; thresholds live in a collapsed
    # advanced panel (gold dial M1).
    assert "Gold price" in body
    assert "Advanced screening assumptions" in body
    assert '<details class="panel screening-params advanced-assumptions">' in body
    assert '<details class="panel screening-params advanced-assumptions" open>' not in body
    # All ten inputs must be present on the page (gold in the dial panel).
    for param in [
        "gold_price", "pe_target", "aisc_margin_yield_target", "aisc_target",
        "margin_target", "reserve_life_target", "leverage_target",
        "tier1_discount", "tier2_discount", "tier3_discount",
    ]:
        assert f'name="{param}"' in body


def test_workspace_tool_b_view_rejects_invalid_override_with_400(tmp_path):
    """Passing an invalid override (negative / non-numeric) must 400
    cleanly with a user-readable error banner rather than crashing."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app, method="GET", path="/tool-b?gold_price=-5",
    )

    assert response["status"].startswith("400")
    assert "Invalid override" in response["body"]
    assert "gold_price" in response["body"]


def test_workspace_tool_b_view_rejects_nonfinite_gold_price_with_400(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app, method="GET", path="/tool-b?gold_price=nan",
    )

    assert response["status"].startswith("400")
    assert "Invalid override" in response["body"]
    assert "finite" in response["body"]
    assert "Scenario active" not in response["body"]


def test_workspace_tool_b_view_no_overrides_uses_persisted_parquet(tmp_path):
    """Bare /tool-b (no URL params) must not trigger an in-memory recompute;
    it should render the persisted parquet verbatim, so verdicts/ranks
    come from the last tool-b CLI run."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-b")

    assert response["status"].startswith("200")
    # Baseline page must NOT show the "Scenario active" banner.
    assert "Scenario active" not in response["body"]


def test_workspace_tool_b_view_filter_form_carries_active_overrides_as_hidden_inputs(tmp_path):
    """When an override is active and the user submits the plain search
    form, the resulting URL must preserve the override. The HTML contract
    is: the filter form contains hidden inputs mirroring every active
    override. This test locks that contract.

    Regression guard for the self-review bug where typing in the search
    box used to silently clear the active scenario.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app, method="GET", path="/tool-b?gold_price=4500&aisc_target=1600",
    )

    assert response["status"].startswith("200")
    body = response["body"]

    import re
    # Isolate the filter (overview-filters-form) form from the page.
    filter_form_match = re.search(
        r'<form[^>]*overview-filters-form[^>]*>(.+?)</form>',
        body,
        flags=re.DOTALL,
    )
    assert filter_form_match, "filter form should be present on the Tool B view"
    filter_form = filter_form_match.group(1)

    # Active overrides must appear as hidden inputs inside the filter form.
    assert '<input type="hidden" name="gold_price" value="4500"' in filter_form
    assert '<input type="hidden" name="aisc_target" value="1600"' in filter_form


def test_workspace_tool_b_view_with_override_shows_scenario_banner(tmp_path):
    """When any override is active, the page must show the banner
    explaining that the table was recomputed and YAML/parquet are
    untouched."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    # Gold price override will trigger a live recompute path. The test
    # fixture's foundation snapshot may or may not have enough data for
    # the recompute; either way the banner must be present and the page
    # must not 500.
    response = _call_wsgi_app(
        app, method="GET", path="/tool-b?gold_price=4500",
    )

    assert response["status"].startswith("200")
    assert "Scenario active" in response["body"]


def test_workspace_tool_b_override_refuses_latest_foundation_when_model_state_corrupt(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    paths.latest_model_state_manifest_path.write_text("{not-json", encoding="utf-8")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path="/tool-b?gold_price=4500",
    )

    assert response["status"].startswith("200")
    body = response["body"]
    # Fail closed and say so honestly: the page must NOT claim a live
    # scenario it could not compute. With the model state corrupt there is
    # no trusted persisted basis either, so the dial input stays empty
    # rather than echoing the requested (uncomputed) 4500.
    assert "Scenario active" not in body
    assert "Could not recompute with overrides" in body
    assert "does not expose a usable immutable foundation artifact" in body
    assert 'name="gold_price" type="number" min="1" step="1" value=""' in body


def test_workspace_tool_b_failed_recompute_snaps_dial_back_to_persisted_spot(tmp_path):
    """When the recompute fails but the persisted spot frame is intact, the
    dial must snap back to the gold price of the frame actually shown
    (4000 in fixtures) — never display the requested-but-uncomputed price
    over spot rows. This is the fail-closed contract from the gold-dial
    plan (Codex MEDIUM 3)."""
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    # Break ONLY the foundation snapshot the recompute needs; the
    # persisted Tool B parquet and model state stay healthy.
    market_snapshot_path = (
        paths.runs_dir / "refresh-run" / "snapshots" / "market_snapshots_usd.parquet"
    )
    market_snapshot_path.write_text("not parquet", encoding="utf-8")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/tool-b?gold_price=4500")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Scenario active" not in body
    assert "Could not recompute with overrides" in body
    # The dial reflects the persisted frame (spot 4000), not the request.
    assert 'name="gold_price" type="number" min="1" step="1" value="4000"' in body
    # And the page states the basis it is actually showing.
    assert "All gold-dependent estimates are at spot gold $4,000/oz (close 2026-04-22)." in body


def test_workspace_root_renders_candidate_finder_home(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    root_response = _call_wsgi_app(app, method="GET", path="/")

    assert root_response["status"].startswith("200")
    assert "Candidate Finder" in root_response["body"]
    assert ">Bull</a>" in root_response["body"]
    assert ">Bear</a>" in root_response["body"]
    assert "Full model refresh" in root_response["body"]
    assert 'aria-current="page" href="/"' in root_response["body"]


def test_workspace_stale_tool_b_schema_renders_actionable_refresh_page(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 22),
                "target_price_peer_pe": 120.0,
            }
        ]
    ).to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/")

    assert response["status"].startswith("503")
    assert "Your local Corporate Finance data is from the previous version" in response["body"]
    assert "Run python main.py refresh" in response["body"]
    assert "The workspace hit an unexpected error" not in response["body"]


def test_workspace_generic_500_does_not_expose_raw_exception(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()

    def fail_loader(*args, **kwargs):
        raise RuntimeError("SECRET INTERNAL TRACE DETAIL")

    monkeypatch.setattr("golden_vector.serve.workspace.load_candidate_finder_data", fail_loader)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/")

    assert response["status"].startswith("500")
    assert "The workspace hit an unexpected error" in response["body"]
    assert "SECRET INTERNAL TRACE DETAIL" not in response["body"]
    assert "Run the command again from a terminal" in response["body"]


def test_workspace_combined_route_is_removed(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/combined")

    assert response["status"].startswith("404")


def test_all_serve_modules_avoid_unsanctioned_analytics_tokens():
    """Sweep EVERY serve module for high-signal analytics tokens (the
    per-file guardrails above only cover four modules, and token lists were
    proven bypassable via pandas method-call arithmetic). Sanctioned
    exceptions are explicit and documented here, so a NEW violation fails
    while today's audited state stays green."""

    sanctioned: dict[str, set[str]] = {
        # M3c deleted detail_panels.py's non-canonical-window volatility
        # recompute (plan §9.3 / P2): the research series is a persisted
        # artifact now, so the exception is GONE and the sweep enforces it.
        # Gold-dial scenario recompute is a sanctioned product tradeoff.
        "candidate_finder_data.py": {".fillna("},
    }
    forbidden_tokens = (
        "np.polyfit(",
        "np.linalg",
        ".eval(",
        ".query(",
        ".rolling(",
        ".ewm(",
        ".cov(",
        ".corr(",
        ".quantile(",
        ".std(",
        ".combine_first(",
        ".fillna(",
        # method-call arithmetic on frames (proven token-scan bypass)
        "].add(",
        "].sub(",
        "].mul(",
        "].div(",
    )
    violations: list[str] = []
    # rglob, not glob: new serve subpackages (e.g. serve/ui/) must never
    # escape this sweep (redesign audit finding H1, 2026-08-10).
    for module in sorted(Path("golden_vector/serve").rglob("*.py")):
        source = module.read_text(encoding="utf-8")
        # strip comments so documentation can mention banned tokens
        code_lines = [line.split("#", 1)[0] for line in source.splitlines()]
        code = "\n".join(code_lines)
        allowed = sanctioned.get(module.name, set())
        for token in forbidden_tokens:
            if token in code and token not in allowed:
                violations.append(f"{module.name}: {token}")
    assert not violations, (
        "Unsanctioned analytics in serve (backend computes, serve renders): "
        + ", ".join(violations)
    )


def test_model_state_banner_tone_is_warning_when_manifest_is_absent():
    """Plan 10.5: danger is reserved for corrupt-class states. A missing manifest
    (fresh clone, build never run) is a missing-with-action warning."""
    from golden_vector.serve.model_state_banner import render_model_state_banner

    html = render_model_state_banner(None)

    assert "notice-warning" in html
    assert "notice-danger" not in html
    assert "Model build state needs attention" in html


def test_model_state_banner_tone_is_danger_only_for_unreadable_manifest():
    from golden_vector.serve.model_state_banner import render_model_state_banner

    corrupt = render_model_state_banner(
        {"state": "incomplete", "manifest_readable": False, "warnings": ["bad json"]}
    )
    readable = render_model_state_banner(
        {"state": "incomplete", "manifest_readable": True, "warnings": ["missing tool_c"]}
    )

    assert "notice-danger" in corrupt
    assert "notice-warning" in readable
    assert "notice-danger" not in readable


def test_overview_empty_states_drop_js_datatable_class(tmp_path):
    """A colspan-only empty row does not match the explicit column model that
    workspace-tables.js hands DataTables; keeping js-datatable raises a blocking
    alert and kills every later table on the page. Same rule as Candidate Finder."""
    from tests.helpers import call_wsgi_app
    from tests.test_redesign_routes import _full_app

    _paths, app = _full_app(tmp_path)
    for path, table_id in (
        ("/tool-a?search=ZZZNOMATCH", "tool-a-table"),
        ("/tool-b?search=ZZZNOMATCH", "tool-b-table"),
        ("/tool-c?search=ZZZNOMATCH", "tool-c-table"),
        ("/tool-d?search=ZZZNOMATCH", "tool-d-table"),
    ):
        response = call_wsgi_app(app, method="GET", path=path)
        assert response["status"].startswith("200"), path
        body = response["body"]
        assert f'id="{table_id}" class="empty-table"' in body, path
        assert f'id="{table_id}" class="js-datatable"' not in body, path


# --------------------------- M3b: page order + POST re-render ---------------


def _m3b_app(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    return paths, create_workspace_app(
        paths, app_config=app_config, tool_b_tickers=["NEM"]
    )


_RESILIENCE_TITLE = "Resilience — at what gold price does this break?"


def _resilience_section(body: str) -> str:
    """Just the Resilience disclosure of a rendered ticker page."""
    start = body.index(_RESILIENCE_TITLE)
    return body[start : body.index("</details>", start)]


@pytest.mark.parametrize(
    ("requested_source", "expected", "other"),
    [
        ("our", "$2,345/oz", "$1,234/oz"),
        ("yahoo", "$1,234/oz", "$2,345/oz"),
    ],
)
def test_ticker_page_resilience_renders_only_the_requested_sources_row(
    tmp_path,
    requested_source,
    expected,
    other,
):
    """W5: end-to-end producer -> consumer lock.

    A REAL v4 dual-source Tool D artifact (written through
    ``persist_tool_d_outputs``, so it cannot drift from
    ``TOOL_D_OUTPUT_COLUMNS`` + the validators) carries a distinct
    interest-cover sentinel per source for the same ticker. The route must
    render the requested source's sentinel in the Resilience group and the
    other source's sentinel must appear NOWHERE in that section — the two
    keys are one row apart in the same file, so row order alone would pass a
    weaker test.
    """

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_latest_tool_d_output(paths)  # our=2345.0, yahoo=1234.0
    app = create_workspace_app(
        paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"]
    )

    response = _call_wsgi_app(
        app,
        method="GET",
        path=f"/ticker/NEM?fundamentals_source={requested_source}",
    )

    assert response["status"].startswith("200")
    section = _resilience_section(response["body"])
    assert "Interest-cover gold" in section
    assert expected in section
    assert other not in section
    expected_basis = (
        "Yahoo financials · Our View mining assumptions"
        if requested_source == "yahoo"
        else "Our View financials · Our View mining assumptions"
    )
    assert expected_basis in section


def test_ticker_page_degrades_one_section_on_a_duplicated_tool_d_key(tmp_path):
    """W2: a duplicate (ticker, finance_source) Tool D artifact used to raise a
    ValueError that the WSGI handler turned into a generic error page — losing
    the whole ticker page AND the reason. Tool D is an optional disclosure, so
    it degrades per item: the page still renders and the disclosure states the
    actual validation message."""

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    duplicated = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "finance_source": "our",
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                "interest_cover_gold_usd": 2345.0,
            },
            {
                "ticker": "nem",
                "finance_source": "our",
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                "interest_cover_gold_usd": 999.0,
            },
        ]
    )
    write_parquet_atomic(duplicated, paths.latest_tool_d_snapshot_parquet_path)
    write_parquet_atomic(duplicated, paths.latest_tool_d_spot_snapshot_parquet_path)
    app = create_workspace_app(
        paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"]
    )

    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Workspace Error" not in body
    # every other section still renders
    for anchor in ('id="performance"', 'id="corporate-finance"', 'id="market-behaviour"'):
        assert anchor in body, anchor
    section = _resilience_section(body)
    assert "duplicate persisted (ticker, finance_source) rows" in section
    # ...and neither ambiguous row's number is shown
    assert "$2,345/oz" not in section
    assert "$999/oz" not in section


def test_ticker_page_sections_render_in_the_required_order(tmp_path):
    """Requirements §2: performance -> corporate finance -> market behaviour ->
    options -> compare -> inputs. Asserted by POSITION, so a re-ordered page
    fails."""
    _paths, app = _m3b_app(tmp_path)
    body = _call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]

    positions = []
    for anchor in (
        'id="performance"',
        'id="corporate-finance"',
        'id="market-behaviour"',
        'id="options"',
        'id="compare"',
        'id="inputs"',
    ):
        assert anchor in body, anchor
        positions.append(body.index(anchor))
    assert positions == sorted(positions), positions


def test_ticker_page_nav_lists_exactly_the_six_redesigned_entries(tmp_path):
    _paths, app = _m3b_app(tmp_path)
    body = _call_wsgi_app(app, method="GET", path="/ticker/NEM")["body"]
    nav = body[body.index('<nav class="section-nav section-nav--compact"') :]
    nav = nav[: nav.index("</nav>")]

    assert nav.count("section-nav-link") == 6
    for fragment, label in (
        ("performance", "Performance"),
        ("corporate-finance", "Corporate finance"),
        ("market-behaviour", "Market behaviour"),
        ("options", "Options"),
        ("compare", "Compare"),
        ("inputs", "Inputs &amp; notes"),
    ):
        assert f'href="#{fragment}">{label}</a>' in nav, fragment
    # the pre-redesign entries are gone
    for stale in ("Gold Sensitivity</a>", "Charts</a>", "Reporting</a>", "Notes</a>"):
        assert stale not in nav, stale


#: Display strings the redesigned ticker page must NEVER contain (requirements
#: §3 "Verdicts and scores"). The page shows statuses and measured values; every
#: compiled score, verdict and cross-sectional rank belongs to the other pages.
#: Swept at RENDER level over the WHOLE response, so a value hidden inside a
#: closed disclosure ("Full research detail", the Lab) fails just as loudly.
REMOVED_TICKER_PAGE_STRINGS: tuple[str, ...] = (
    "fundamental_check_summary",
    "fundamental_check_rank",
    "screening_verdict",
    "Fundamental Check Summary",
    "Screening Verdict",
    "STRONG_CANDIDATE",
    "SCREEN_OUT",
    "WATCHLIST",
    # M3c: the market-behaviour composites went the same way.
    "Gold Sensitivity Score",
    # Stricter than the required "Confidence:" — the bare word is already
    # absent everywhere, so nothing is gained by weakening it.
    "Confidence",
    "confidence score",
    "tool_a_rank",
    "screening verdict",
    "fundamental check",
    # M3f: the cross-sectional ranks are Finder/Tool-page language.
    "quality rank",
    "downside rank",
    "upside rank",
)


@pytest.mark.parametrize("source", ["our", "yahoo"])
def test_ticker_page_never_shows_a_compiled_verdict_or_score(tmp_path, source):
    """Both finance sources, options section degraded (no option artifacts)."""
    _paths, app = _m3b_app(tmp_path)
    body = _call_wsgi_app(
        app, method="GET", path=f"/ticker/NEM?fundamentals_source={source}"
    )["body"]
    # the sweep is only meaningful over a page that actually rendered
    assert 'id="corporate-finance"' in body
    assert 'id="market-behaviour"' in body
    assert 'id="options"' in body
    for banned in REMOVED_TICKER_PAGE_STRINGS:
        assert banned not in body, f"{banned} ({source})"


@pytest.mark.parametrize("source", ["our", "yahoo"])
def test_ticker_page_sweep_holds_with_option_artifacts_published(tmp_path, source):
    """The same sweep with a POPULATED options section — the degraded options
    fixture above cannot prove anything about the contract tables."""
    from tests.test_option_trading_data import _write_option_inputs

    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    body = _call_wsgi_app(
        app, method="GET", path=f"/ticker/AEM?fundamentals_source={source}"
    )["body"]
    # the options section really is populated, not degraded to a notice
    assert 'id="options"' in body
    assert "Most liquid contracts" in body
    for banned in REMOVED_TICKER_PAGE_STRINGS:
        assert banned not in body, f"{banned} ({source}, options published)"


def test_ticker_page_options_nav_entry_tracks_the_options_region():
    """The Options entry is listed only when an options region is rendered."""
    from golden_vector.serve.detail_page import _detail_section_nav

    with_options = _detail_section_nav(
        has_page_sections=True,
        has_behaviour=True,
        has_options=True,
        has_compare=False,
        has_manual=True,
    )
    without = _detail_section_nav(
        has_page_sections=True,
        has_behaviour=True,
        has_options=False,
        has_compare=False,
        has_manual=True,
    )
    assert 'href="#options">Options</a>' in with_options
    assert "Options" not in without
    assert without.count("section-nav-link") == 4


def test_ticker_page_compare_nav_entry_tracks_the_compare_region():
    """M3e: the Compare entry is listed only when the section is rendered."""
    from golden_vector.serve.detail_page import _detail_section_nav

    with_compare = _detail_section_nav(
        has_page_sections=True,
        has_behaviour=True,
        has_options=True,
        has_compare=True,
        has_manual=True,
    )
    without = _detail_section_nav(
        has_page_sections=True,
        has_behaviour=True,
        has_options=True,
        has_compare=False,
        has_manual=True,
    )
    assert 'href="#compare">Compare</a>' in with_compare
    assert "Compare" not in without
    # page order: Compare sits after Options and before Inputs & notes
    assert with_compare.index("#compare") > with_compare.index("#options")
    assert with_compare.index("#compare") < with_compare.index("#inputs")


def test_ticker_page_compare_serve_layer_has_no_score_arithmetic():
    """The M3e Compare section renders backend-resolved percentiles only.

    Canon: every new serve surface gets a static-scan guardrail (clone of the
    Tool-D/Tool-B serve-arithmetic tests). The exhaustive scan (an AST sweep for
    ANY arithmetic operator) lives with the section's own tests; this is the
    repo-wide sweep's entry for it, so the surface can never exist without one.
    """
    source = Path("golden_vector/serve/ticker_page/compare.py").read_text(encoding="utf-8")

    # It obeys the persisted eligibility verdicts by name (display only).
    assert "rank_eligible" in source
    for forbidden in (
        "oriented_percentile",
        "sort_values",
        "rank(",
        ".fillna(",
        ".combine_first(",
        "weight *",
        "* pct",
        "/ budget",
    ):
        assert forbidden not in source, forbidden


#: A realistic comparison definition as score-builder.js writes it: the client
#: uses encodeURIComponent, so ":" and "," arrive percent-encoded.
_SB_STATE = "ev_ebitda%3A40%2Cmargin_pct%3A60"
_SB_DECODED = "ev_ebitda:40,margin_pct:60"


def test_score_builder_state_param_is_carried_by_the_page_not_stripped(tmp_path):
    """M3e: ``sb=`` is CLIENT-owned state. The server has no query whitelist, so
    the only requirement is that it never drops it — the forms' ``return_to``
    must round-trip it, or saving an input would silently reset the comparison
    the user just built."""
    _paths, app = _m3b_app(tmp_path)

    body = _call_wsgi_app(app, method="GET", path=f"/ticker/NEM?sb={_SB_STATE}")["body"]

    assert f'value="/ticker/NEM?sb={_SB_STATE}"' in body


def test_score_builder_state_param_survives_a_rejected_post(tmp_path):
    """The 400 re-render rebuilds the view from ``return_to``; unknown params
    pass through untouched."""
    _paths, app = _m3b_app(tmp_path)

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body=f"production_oz=not-a-number&return_to=%2Fticker%2FNEM%3Fsb%3D{_SB_STATE}",
    )

    assert response["status"].startswith("400")
    assert f'value="/ticker/NEM?sb={_SB_STATE}"' in response["body"]
    assert 'id="compare"' in response["body"]


def test_score_builder_state_param_survives_a_successful_save(tmp_path):
    """The post-save redirect adds ``saved=`` and keeps every other param."""
    _paths, app = _m3b_app(tmp_path)

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body=f"aisc_usd_per_oz=1200&return_to=%2Fticker%2FNEM%3Fsb%3D{_SB_STATE}",
    )

    assert response["status"].startswith("303")
    location = str(response["headers"]["Location"])
    assert "saved=company" in location
    assert f"sb={_SB_STATE}" in location or f"sb={_SB_DECODED}" in location


def test_rejected_post_re_renders_the_same_page_including_the_new_sections(tmp_path):
    """A validation error must not silently drop Performance / Corporate finance
    — the user would read the missing sections as data loss."""
    _paths, app = _m3b_app(tmp_path)
    response = _call_wsgi_app(
        app,
        method="POST",
        path="/ticker/NEM/company",
        body="production_oz=not-a-number&return_to=%2Fticker%2FNEM",
    )
    assert response["status"].startswith("400")
    body = response["body"]
    assert 'id="performance"' in body
    assert 'id="corporate-finance"' in body
    assert 'href="#corporate-finance">Corporate finance</a>' in body
    assert 'id="gold-dial"' in body
