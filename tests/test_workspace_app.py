from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import add_stock_note
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


def test_workspace_detail_page_renders_explanations_and_exploratory_ladder(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")

    assert response["status"].startswith("200")
    assert "Gold Sensitivity" in response["body"]
    assert "Exploratory Horizon Ladder" in response["body"]
    # Regression guard: the workspace now regenerates narrative cards live from
    # numeric inputs + band thresholds (single source of truth = model/explanations.py).
    # With structural_delta_12m=1.9 and high_min=2.0, the builder picks the "moderately
    # high" band. The pre-baked `delta_explanation` field on the row is NOT read.
    assert (
        "Moderately high structural delta means this stock has shown strong gold sensitivity"
        in response["body"]
    )
    assert "Single-Period Ratio" in response["body"]


def test_workspace_detail_page_honors_yahoo_fundamentals_source(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
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
    assert "Latest Corporate Finance Snapshot" in response["body"]
    assert "Financials source" in response["body"]
    assert "Yahoo Fundamentals" in response["body"]
    assert "SCREEN_OUT" in response["body"]
    assert "8.88" in response["body"]
    assert 'href="/?fundamentals_source=yahoo"' in response["body"]
    assert "/ticker/NEM?window=6m&amp;fundamentals_source=yahoo" in response["body"]
    assert "/ticker/NEM?lens=option-trading&amp;fundamentals_source=yahoo#option-trading" in response["body"]
    assert "/ticker/NEM?fundamentals_source=yahoo" in response["body"]
    assert 'name="return_to" value="/ticker/NEM?fundamentals_source=yahoo"' in response["body"]


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


def test_workspace_detail_page_surfaces_withheld_tool_a_notice(tmp_path):
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
    assert "Gold Sensitivity score is withheld" in response["body"]
    assert "STALE_FX" in response["body"]


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


def test_workspace_detail_surfaces_score_withheld_notice(tmp_path):
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
    assert "Gold Sensitivity score is withheld" in response["body"]
    assert "STALE_FX" in response["body"]


def test_workspace_detail_suppresses_foundation_backed_panels_when_refresh_is_out_of_sync(tmp_path):
    """Phase 1A / v3 §1: when the foundation manifest has moved past the displayed Tool A row,
    the scatter / up-down-beta / exploratory-ladder panels must be replaced with visible
    fallback cards that carry a title, a reason, and a CLI suggestion. No blank space.
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
    assert "foundation snapshot has moved ahead" in body
    # Every foundation-backed panel must appear as a suppressed card with a CLI suggestion.
    assert "Weekly Return Scatter &mdash; Out of Sync" in body
    assert "Up vs Down Beta &mdash; Out of Sync" in body
    assert "Exploratory Horizon Ladder &mdash; Out of Sync" in body
    assert body.count("Run <code>python main.py tool-a</code>") >= 3
    # Per codex P2: each suppressed card must carry its own reason sentence
    # in addition to the title and CLI suggestion (the v3 fallback bar).
    expected_reason = "foundation snapshot on disk differs from the published Gold Sensitivity row"
    assert body.count(expected_reason) >= 3
    # Volatility panel is not foundation-backed and should still render.
    assert "Volatility Diagnostics" in body


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
    assert "Weekly Return Scatter" in body
    assert "Up vs Down Beta" in body


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
    # All three foundation-backed panels must appear as out-of-sync cards.
    assert "Weekly Return Scatter &mdash; Out of Sync" in body
    assert "Up vs Down Beta &mdash; Out of Sync" in body
    assert "Exploratory Horizon Ladder &mdash; Out of Sync" in body
    # Per-card reason sentence specific to the missing-manifest state.
    expected_reason = "No validated foundation snapshot is available, so this panel cannot be rebuilt safely"
    assert body.count(expected_reason) >= 3
    # CLI suggestion for this state is update-data, not tool-a.
    assert body.count("Run <code>python main.py update-data</code>") >= 3
    # Volatility panel still renders because it reads from the published Tool A row.
    assert "Volatility Diagnostics" in body


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
    assert "does not carry a snapshot refresh identifier" in body
    assert "Weekly Return Scatter &mdash; Out of Sync" in body
    assert "Up vs Down Beta &mdash; Out of Sync" in body
    assert "Exploratory Horizon Ladder &mdash; Out of Sync" in body
    expected_reason = "The published Gold Sensitivity row does not carry a snapshot refresh identifier"
    assert body.count(expected_reason) >= 3
    assert body.count("Run <code>python main.py tool-a</code>") >= 3
    assert "Volatility Diagnostics" in body


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


def test_workspace_detail_chart_sits_above_volatility_in_both_alignment_branches(tmp_path):
    """Codex follow-up to Fix #10: the non-aligned branch was previously rendering the
    chart at the bottom, after volatility + suppressed exploratory. Both branches must
    now place the chart between the scatter row and the volatility row.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_structural_history_file(paths, "NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    # Aligned case.
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert body.find("Gold vs Stock vs Gold-Miner ETFs") < body.find("Volatility Diagnostics")
    assert body.find("Gold vs Stock vs Gold-Miner ETFs") < body.find("Exploratory Horizon Ladder")

    # Non-aligned case (foundation manifest's refresh != Tool A row's refresh).
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            _make_tool_a_row("NEM", delta=1.5, up=1.6, down=1.4, score=80.0, rank=1)
            | {"snapshot_refresh_run_id": "earlier-refresh", "source_run_id": "tool-a-run"}
        ],
    )
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    # Chart must come before the volatility panel even when foundation is misaligned.
    assert body.find("Gold vs Stock vs Gold-Miner ETFs") < body.find("Volatility Diagnostics")


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


def _write_latest_tool_d_output(paths) -> None:
    context = RunContext.start(
        paths=paths,
        command="tool-d",
        parameters={},
        config_hash="hash",
    )
    persist_tool_d_outputs(
        paths=paths,
        run_context=context,
        tool_d_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "finance_source": "our",
                    "tool_d_quality_rank": 88.0,
                    "tool_d_quality_score": 76.0,
                    "gold_price_used": 4000.0,
                    "spot_gold_usd": 4000.0,
                    "spot_gold_date": "2026-06-01",
                    "headroom_to_breakeven_pct_at_g": 0.62,
                    "leverage_stressed_at_g": 0.7,
                    "ev_ebitda_at_g": 4.5,
                    "margin_per_oz_at_g": 2200.0,
                    "fcf_yield": 0.12,
                    "screening_verdict": "STRONG_CANDIDATE",
                    "tool_d_tags": "strong_headroom",
                    "snapshot_refresh_run_id": "refresh-run",
                    "source_run_id": "tool-d-run",
                }
            ]
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
    """A missing structural-metrics file surfaces a page-level notice (the scatter /
    up-down / window panels read those metrics). The price-overlay chart does NOT
    depend on that file, so it still renders from foundation price history.
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
    assert "Structural metrics file is missing" in body
    # The overlay chart is independent of the structural-metrics file: it still draws.
    assert ">Gold vs Stock vs Gold-Miner ETFs</h3>" in body
    # Prove it actually drew the gold + stock lines (not the empty state) by name.
    assert body.count("<polyline points=") == 2
    assert "&#9632; NEM" in body
    assert "&#9632; Gold" in body


def test_workspace_detail_warns_when_structural_metrics_source_run_id_mismatches(tmp_path):
    """Provenance gate (moved from the old beta chart to the page level): a structural
    metrics file from a DIFFERENT tool-a run than the published row must surface an
    out-of-sync notice, because the scatter / up-down / window panels read those metrics.
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
    assert "Structural metrics file is out of sync with the published Gold Sensitivity row" in body
    # The provenance notice must appear ABOVE the overlay chart, so a user can never read the
    # chart as endorsed by a mismatched structural file (gate moved from chart to page level).
    assert body.find("out of sync with the published Gold Sensitivity row") < body.find(
        ">Gold vs Stock vs Gold-Miner ETFs</h3>"
    )
    # The price overlay is independent of structural-metrics provenance, so it still draws
    # its two foundation-price lines even while the out-of-sync notice is shown above it.
    assert body.count("<polyline points=") == 2


def test_workspace_detail_renders_rebased_overlay_chart_when_aligned(tmp_path):
    """Aligned foundation + price history → the rebased gold/stock/ETF overlay renders.

    Foundation history (gold + NEM) gives two drawable lines even without a cached
    GDX/GDXJ benchmark, so the chart draws and carries its indexed-to-100 caption.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    # Match the source_run_id from _write_latest_outputs default ("tool-a-run").
    _write_structural_history_file(paths, "NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert ">Gold vs Stock vs Gold-Miner ETFs</h3>" in body
    assert "out of sync" not in body.lower()
    # Two lines draw (gold + stock); the legend must name both so we know WHICH lines drew,
    # and there must be exactly two legend chips (legend count tracks the drawn-line count).
    assert body.count("<polyline points=") == 2
    assert body.count('<span class="chart-legend-item"') == 2
    assert "&#9632; NEM" in body
    assert "&#9632; Gold" in body
    # The caption is indexed-to-100 and names the active window's human label (12M -> "1Y").
    assert "indexed to 100" in body
    assert "1Y window" in body
    # The y-axis must be anchored on the rebasing baseline (100) — the dashed baseline proves the
    # indexed axis spans 100, i.e. the rebasing actually drove the chart scale.
    assert "stroke-dasharray=\"3 3\"" in body
    # No GDX/GDXJ cache here, so the caption must admit the benchmarks are absent (not imply them).
    assert "benchmark history was unavailable" in body


def test_workspace_detail_overlay_draws_all_four_lines_when_benchmarks_present(tmp_path):
    """End-to-end benchmark-present path: foundation prices + cached GDX/GDXJ histories →
    the overlay draws all four lines and the caption names the gold-miner ETFs honestly.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_structural_history_file(paths, "NEM", source_run_id="tool-a-run")
    _write_overlay_benchmark_history(paths, "GDX", scale=30.0)
    _write_overlay_benchmark_history(paths, "GDXJ", scale=45.0)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert ">Gold vs Stock vs Gold-Miner ETFs</h3>" in body
    # Four lines: NEM + Gold + GDX + GDXJ, each labelled in the legend.
    assert body.count("<polyline points=") == 4
    for label in ("NEM", "Gold", "GDX", "GDXJ"):
        assert f"&#9632; {label}" in body
    # Caption names the ETFs honestly and does NOT claim they were unavailable.
    assert "gold-miner ETFs (GDX / GDXJ)" in body
    assert "benchmark history was unavailable" not in body


def test_workspace_detail_chart_renders_without_suppression_when_score_withheld(tmp_path):
    """When the Gold Sensitivity score is withheld, the page surfaces a withheld notice
    at the page level, and the price overlay still renders honest prices WITHOUT any
    watermark or suppression (prices are factual; only the scored beta is withheld).
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
                "structural_delta_core": 1.5,
                "score_eligible": False,
                "score_eligibility_reason": "UNACCEPTABLE_NORMALIZATION_STATUS",
                "snapshot_refresh_run_id": "refresh-run",
                "source_run_id": "tool-a-run",
                "confidence_label": "WITHHELD",
                "profile_label": "SCORE_WITHHELD",
                "tool_a_summary_explanation": "Score withheld.",
                "delta_explanation": "Withheld.",
                "gamma_explanation": "Withheld.",
                "asymmetry_explanation": "Withheld.",
                "volatility_explanation": "—",
                "confidence_explanation": "Withheld.",
                "interaction_explanation": "Withheld.",
                "normalization_issue_summary": "STALE_FX",
                "fx_policy_max_staleness_days": 5,
                "fx_policy_block_on_stale_fx": False,
            }
        ],
    )
    _write_structural_history_file(paths, "NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    # Withheld score is surfaced page-level; the overlay still renders honest prices.
    assert "Gold Sensitivity score is withheld" in body
    assert ">Gold vs Stock vs Gold-Miner ETFs</h3>" in body
    # Prove the overlay actually drew (not the empty state) — the withheld score must not
    # suppress the factual price chart.
    assert body.count("<polyline points=") == 2


def test_workspace_detail_overlay_renders_even_when_structural_rows_are_low_observation(tmp_path):
    """The price overlay draws prices, not the scored betas, so it is NOT gated by
    structural-window eligibility: a ticker whose only structural rows are LOW_OBSERVATION
    still gets the overlay (from foundation price history), while the structural betas
    remain governed separately by the window panels.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    _write_structural_history_file(
        paths, "NEM", source_run_id="tool-a-run", extra_window_status="LOW_OBSERVATION"
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    # The overlay is not gated by structural eligibility: it draws exactly the two price
    # lines (gold + stock) from foundation history, with no benchmarks accidentally appearing.
    assert ">Gold vs Stock vs Gold-Miner ETFs</h3>" in body
    assert body.count("<polyline points=") == 2


def test_workspace_detail_overlay_renders_when_foundation_misaligned_but_metrics_aligned(tmp_path):
    """When the foundation snapshot has moved ahead of the published row, the scatter /
    up-down panels are suppressed, but the price overlay still renders (it draws prices
    from the foundation history). The misalignment is surfaced by the page-level notice.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            _make_tool_a_row("NEM", delta=1.5, up=1.6, down=1.4, score=80.0, rank=1)
            | {"snapshot_refresh_run_id": "earlier-refresh", "source_run_id": "tool-a-run"}
        ],
    )
    _write_structural_history_file(paths, "NEM", source_run_id="tool-a-run")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert ">Gold vs Stock vs Gold-Miner ETFs</h3>" in body
    assert "<polyline points=" in body
    # The aligned-Tool-A-but-misaligned-foundation message is the page-level alignment
    # notice, not a chart-panel note.
    assert "foundation snapshot has moved ahead" in body


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
    assert 'class="nav-tab active" href="/tool-a"' in response["body"]


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
    assert 'class="nav-tab active" href="/tool-b"' in response["body"]


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
    assert 'class="nav-tab active" href="/tool-c"' in response["body"]
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
        # the windowed beta cells degrade to the muted None cell, not a crash or stale value
        assert 'data-order="-999"' in response["body"], window


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
    assert 'class="nav-tab active" href="/tool-d"' in response["body"]


def test_workspace_tool_d_yahoo_source_recomputes_and_preserves_links(
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
    scenario_frame = pd.read_parquet(paths.latest_tool_d_spot_snapshot_parquet_path).copy()
    scenario_frame["finance_source"] = "yahoo"
    captured: dict[str, object] = {}

    def fake_compute_scenario_frame(**kwargs):
        captured["finance_source"] = kwargs["finance_source"]
        return scenario_frame

    monkeypatch.setattr(
        "golden_vector.serve.overview_tool_d._compute_scenario_frame",
        fake_compute_scenario_frame,
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(
        app,
        method="GET",
        path="/tool-d?fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    assert captured["finance_source"] == "yahoo"
    assert "Yahoo Fundamentals view recomputed" in response["body"]
    assert "Scenario recomputed" not in response["body"]
    assert 'value="yahoo" selected>Yahoo Fundamentals</option>' in response["body"]
    assert 'name="gold_price" type="number" min="1" step="1" value=""' in response["body"]
    assert "/tool-d?gold_price=3400.00&amp;fundamentals_source=yahoo" in response["body"]
    assert "/ticker/NEM?fundamentals_source=yahoo" in response["body"]


def test_workspace_tool_d_yahoo_failure_resets_rendered_source(tmp_path, monkeypatch):
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
        path="/tool-d?fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    assert "Could not compute Yahoo Fundamentals view" in response["body"]
    assert 'value="our" selected>Our View</option>' in response["body"]
    assert 'value="yahoo" selected>Yahoo Fundamentals</option>' not in response["body"]


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
    css = (serve / "static" / "workspace.css").read_text(encoding="utf-8")
    assert ".help-term" not in css
    assert "th[title]" not in css


def test_snapshot_ratio_cell_is_compact_and_shows_yahoo_divergence():
    """The ticker-detail snapshot renders dual-source ratios (ev_ebitda) with a compact value (no
    'x' suffix) plus the SAME '(Yahoo X)' divergence accent the Tool B overview shows."""
    import pandas as pd

    from golden_vector.screening.pipeline import materialize_tool_b_finance_source
    from golden_vector.screening.schema import TOOL_B_OUTPUT_COLUMNS
    from golden_vector.serve.detail_panels import _snapshot_metric_value

    def materialized(row: dict[str, object], finance_source: str) -> dict[str, object]:
        full_row = {column: None for column in TOOL_B_OUTPUT_COLUMNS}
        full_row.update(row)
        return materialize_tool_b_finance_source(
            pd.DataFrame([full_row]),
            finance_source=finance_source,
        ).iloc[0].to_dict()

    # Our View active, our-view 2.0 vs Yahoo 3.5, flagged as differing.
    row = materialized(
        {
            "ev_ebitda": 2.0,
            "ev_ebitda_our_view": 2.0,
            "ev_ebitda_official": 3.5,
            "ev_ebitda_differs": True,
        },
        "our",
    )
    cell = _snapshot_metric_value("ev_ebitda", row, financials_source="our")
    assert cell.startswith("2.0 ")  # compact active value, no unit suffix
    assert "x" not in cell  # cell carries no 'x' (header/popover do)
    assert "source-alternate" in cell and "(Yahoo 3.5)" in cell

    # No divergence -> plain compact value, no accent.
    assert _snapshot_metric_value(
        "ev_ebitda",
        materialized({"ev_ebitda": 2.0, "ev_ebitda_differs": False}, "our"),
        financials_source="our",
    ) == "2.0"

    # Yahoo source active (base materialized to the official value) -> alternate is Our View.
    yahoo_row = materialized(
        {
            "ev_ebitda": 2.0,
            "ev_ebitda_our_view": 2.0,
            "ev_ebitda_official": 3.5,
            "ev_ebitda_differs": True,
        },
        "yahoo",
    )
    ycell = _snapshot_metric_value("ev_ebitda", yahoo_row, financials_source="yahoo")
    assert ycell.startswith("3.5 ") and "(Our View 2.0)" in ycell

    yahoo_missing_row = materialized(
        {
            "ev_ebitda": 2.0,
            "ev_ebitda_our_view": 2.0,
            "ev_ebitda_official": None,
            "ev_ebitda_differs": True,
        },
        "yahoo",
    )
    assert (
        _snapshot_metric_value("ev_ebitda", yahoo_missing_row, financials_source="yahoo")
        == '- <span class="source-alternate">(Our View 2.0)</span>'
    )


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
        "gold_price", "pe_target", "fcf_yield_target", "aisc_target",
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
    assert 'class="nav-tab active" href="/"' in root_response["body"]


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
        # Bounded, measured non-canonical-window recompute (documented).
        "detail_panels.py": {"np.polyfit(", ".std("},
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
    for module in sorted(Path("golden_vector/serve").glob("*.py")):
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
