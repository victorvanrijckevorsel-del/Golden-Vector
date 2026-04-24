from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import add_stock_note
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths


def test_workspace_overview_renders_structural_tool_a_and_tool_b_outputs(tmp_path):
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
    assert "/ticker/NEM" in response["body"]
    assert "Structural Delta" in response["body"]
    assert "CONVEX" in response["body"]
    assert "STRONG_CANDIDATE" in response["body"]


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
    assert "Structural Tool A" in response["body"]
    assert "Exploratory Horizon Ladder" in response["body"]
    assert "High structural delta means this stock has tended to move more than gold" in response["body"]
    assert "Single-Period Ratio" in response["body"]


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
    assert "Official Tool A score is withheld" in response["body"]
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


def test_workspace_overview_warns_when_tool_b_latest_alias_is_missing(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    # Only publish Tool A latest, not Tool B, to simulate the "stable alias missing" case.
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
                    "snapshot_refresh_run_id": "refresh-run",
                    "structural_delta_core": 1.9,
                    "score_eligible": True,
                    "score_eligibility_reason": "OK",
                }
            ]
        ),
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/")

    assert response["status"].startswith("200")
    assert "Tool B latest output is missing" in response["body"]


def test_workspace_overview_warns_when_tool_a_and_tool_b_reference_different_refreshes(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)

    tool_a_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=tool_a_context,
        tool_a_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "snapshot_refresh_run_id": "refresh-run",
                    "structural_delta_core": 1.9,
                    "score_eligible": True,
                    "score_eligibility_reason": "OK",
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
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "gold_price_assumption": 4000.0,
                    "tool_b_score": 72.5,
                    "tool_b_rank": 1,
                    "screening_verdict": "STRONG_CANDIDATE",
                    "snapshot_refresh_run_id": "an-older-refresh",
                }
            ]
        ),
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/")

    assert response["status"].startswith("200")
    assert "an-older-refresh" in response["body"]
    assert "mix data from different refreshes" in response["body"]


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
    assert "Official Tool A score is withheld" in response["body"]
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
                "delta_explanation": "Moderate structural delta means the stock has shown a meaningful weekly link to gold in the 12M anchor window.",
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
    expected_reason = "foundation snapshot on disk differs from the published Tool A row"
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
    expected_reason = "The published Tool A row does not carry a snapshot refresh identifier"
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


def test_workspace_overview_sort_dropdown_carries_disabled_attribute_when_lens_active(tmp_path):
    """Codex P3 follow-up: directly assert the `disabled` attribute on the sort
    `<select>` when a non-default lens is active. The hint text alone wasn't enough.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    # Default lens (composite) → sort is enabled.
    response = _call_wsgi_app(app, method="GET", path="/")
    body = response["body"]
    assert 'name="sort">' in body  # opening tag with no disabled attribute
    assert 'name="sort" disabled' not in body

    # Non-default lens → sort is disabled.
    response = _call_wsgi_app(app, method="GET", path="/?lens=upside_torque")
    body = response["body"]
    assert 'name="sort" disabled' in body


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
    assert body.find("12M Rolling Structural Delta") < body.find("Volatility Diagnostics")
    assert body.find("12M Rolling Structural Delta") < body.find("Exploratory Horizon Ladder")

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
    assert body.find("12M Rolling Structural Delta") < body.find("Volatility Diagnostics")


def test_workspace_detail_surfaces_corrupt_structural_metrics_at_page_level(tmp_path):
    """Codex follow-up to Fix #5: a corrupt structural-metrics file now surfaces a
    page-level notice in addition to the chart's own corrupt fallback, so scatter and
    up/down panels aren't silently degraded.
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
    # And the chart panel still gets its own message.
    assert "Could not read the structural history file" in body


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
                    "delta_explanation": "High structural delta means this stock has tended to move more than gold on a weekly basis in the 12M anchor window.",
                    "gamma_explanation": "Negative gamma means sensitivity has been stronger in up-gold weeks than in down-gold weeks in the 12M anchor window. That points to better upside regime participation.",
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
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "gold_price_assumption": 4000.0,
                    "tool_b_score": 72.5,
                    "tool_b_rank": 1,
                    "screening_verdict": "STRONG_CANDIDATE",
                    "confidence": "VERIFIED",
                    "best_upside_pct": 0.24,
                }
            ]
        ),
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


def test_workspace_detail_warns_when_structural_history_file_is_missing(tmp_path):
    """Plan v3 §6 T12 + codex P2 fix: missing structural-history file → "Not Available
    Yet" panel with the missing-file specific wording.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    # Deliberately do NOT write the structural-history parquet.

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    response = _call_wsgi_app(app, method="GET", path="/ticker/NEM")
    body = response["body"]
    assert "12M Rolling Structural Delta &mdash; Not Available Yet" in body
    assert "Structural history file has not been generated yet" in body


def test_workspace_detail_suppresses_chart_when_structural_source_run_id_mismatches(tmp_path):
    """Plan v3 §6 T13: structural file source_run_id different from Tool A row's
    source_run_id → chart suppressed with "Out of Sync" panel.
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
    assert "12M Rolling Structural Delta &mdash; Out of Sync" in body
    assert "Structural history file is out of sync with the published Tool A row" in body


def test_workspace_detail_renders_beta_history_chart_when_aligned(tmp_path):
    """Plan v3 §6 T15: aligned structural file + eligible 12M rows → SVG chart renders."""
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
    assert ">12M Rolling Structural Delta</h3>" in body
    assert "Out of Sync" not in body
    # Beta line as polyline + chart frame must be present.
    assert "<polyline points=" in body
    assert "12m rolling structural delta" in body.lower()


def test_workspace_detail_chart_shows_withheld_watermark_when_score_is_withheld(tmp_path):
    """Plan v3 §6 T16: when score is withheld, the chart still renders but carries a
    visible "context only" watermark.
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
    assert ">12M Rolling Structural Delta</h3>" in body
    assert "historical series shown for context only" in body


def test_workspace_detail_chart_shows_no_eligible_rows_message_when_history_is_only_low_observation(tmp_path):
    """Plan v3 §6 T21: ticker has rows in the structural file but none are ELIGIBLE.
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
    # No ELIGIBLE rows for this ticker → fallback to the "missing/empty" empty state.
    assert "Not Available Yet" in body


def test_workspace_detail_chart_renders_beta_line_when_foundation_misaligned_but_structural_aligned(tmp_path):
    """Replaces the previous gold-overlay-suppression test. The rebased gold overlay
    was removed in the post-deep-review fix pass (both reviewers agreed it was bad UX),
    so the assertion now is just: the chart still renders its beta line when the chart's
    own provenance (source_run_id) is OK, even if the foundation snapshot has moved past.
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
    assert ">12M Rolling Structural Delta</h3>" in body
    assert "<polyline points=" in body
    # No more gold-overlay-related copy in any direction.
    assert "Gold-price overlay" not in body
    # The aligned-Tool-A-but-misaligned-foundation message is the page-level alignment
    # notice, not a chart-panel note.
    assert "foundation snapshot has moved ahead" in body


def test_workspace_detail_chart_distinguishes_corrupt_parquet_from_missing(tmp_path):
    """Codex P2 fix: a corrupted structural-history parquet must produce a distinct
    "Could not read the structural history file" fallback, not be mis-classified as
    "Not Available Yet" (which would send the user to the wrong fix).
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
    assert "12M Rolling Structural Delta &mdash; Not Available Yet" in body
    assert "Could not read the structural history file" in body
    # The user should NOT see the "missing" wording for a corrupt file.
    assert "Structural history file has not been generated yet" not in body


def test_workspace_overview_lens_picker_reorders_table_by_lens_score(tmp_path):
    """Phase 2A: a non-default lens reorders the overview by lens_score in the lens's
    direction. Both the default Tool A Score column and the new Lens Score column must
    remain visible side by side.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD", "AEM"])
    _write_latest_foundation_snapshot(paths)
    # Three tickers with different upside-torque profiles. Recall:
    # upside_torque = delta_core × max(up_beta_core - down_beta_core, 0)
    # NEM:  2.0 × (2.5 - 1.0) = 3.0   (best)
    # AEM:  1.5 × (1.8 - 1.4) = 0.6   (middle)
    # GOLD: 1.2 × (1.0 - 1.5) = 0.0   (worst)
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            _make_tool_a_row("NEM", delta=2.0, up=2.5, down=1.0, score=92.0, rank=1),
            _make_tool_a_row("AEM", delta=1.5, up=1.8, down=1.4, score=70.0, rank=2),
            _make_tool_a_row("GOLD", delta=1.2, up=1.0, down=1.5, score=55.0, rank=3),
        ],
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM", "GOLD", "AEM"])

    # Default lens (composite) — sort dropdown drives order. Lens Score column
    # is hidden when lens=composite (it would just duplicate Tool A Score).
    response = _call_wsgi_app(app, method="GET", path="/?sort=tool_a_score")
    body = response["body"]
    assert "Tool A Score" in body  # original column header preserved
    assert ">Lens Score" not in body  # hidden in composite mode
    assert "View by lens" in body
    nem_pos = body.index("/ticker/NEM")
    aem_pos = body.index("/ticker/AEM")
    gold_pos = body.index("/ticker/GOLD")
    assert nem_pos < aem_pos < gold_pos

    # Switch to upside_torque lens — order is determined by the lens score.
    response = _call_wsgi_app(app, method="GET", path="/?lens=upside_torque")
    body = response["body"]
    assert "Lens Score (Upside torque)" in body
    assert "Sort dropdown is ignored while a non-default lens is active" in body
    nem_pos = body.index("/ticker/NEM")
    aem_pos = body.index("/ticker/AEM")
    gold_pos = body.index("/ticker/GOLD")
    assert nem_pos < aem_pos < gold_pos


def test_workspace_overview_lens_score_column_hidden_when_lens_is_composite(tmp_path):
    """Both reviewers agreed: when lens=composite, the Lens Score column duplicates the
    Tool A Score column and should be hidden. Switching to a non-default lens shows it.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response_default = _call_wsgi_app(app, method="GET", path="/")
    body_default = response_default["body"]
    assert ">Lens Score" not in body_default

    response_torque = _call_wsgi_app(app, method="GET", path="/?lens=upside_torque")
    body_torque = response_torque["body"]
    assert "Lens Score (Upside torque)" in body_torque


def test_workspace_overview_unknown_lens_falls_back_to_composite(tmp_path):
    """Phase 2A UX invariant: an unknown lens id renders without error and uses the
    composite lens, keeping the page stable for stale or hand-edited URLs.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi_app(app, method="GET", path="/?lens=not-a-real-lens")
    body = response["body"]
    assert response["status"].startswith("200")
    # Composite lens hint is present (we silently fell back).
    assert "Composite (Tool A score)" in body


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


def test_workspace_overview_filters_by_search_profile_verdict_confidence_and_sort(tmp_path):
    """Phase 1B.4: overview must support search by ticker, filter by profile, Tool B
    verdict and confidence, and a small sort allow-list. Filter form must be visible
    on the page.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD", "AEM"])
    _write_latest_foundation_snapshot(paths)
    # Three Tool A rows with different profiles + verdicts.
    _write_latest_outputs(
        paths,
        tool_a_rows=[
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 4, 17),
                "profile_label": "CONVEX",
                "confidence_label": "HIGH",
                "tool_a_score": 92.0,
                "tool_a_rank": 1,
                "score_eligible": True,
                "score_eligibility_reason": "OK",
                "snapshot_refresh_run_id": "refresh-run",
            },
            {
                "ticker": "GOLD",
                "as_of_date": date(2026, 4, 17),
                "profile_label": "FRAGILE",
                "confidence_label": "MEDIUM",
                "tool_a_score": 50.0,
                "tool_a_rank": 2,
                "score_eligible": True,
                "score_eligibility_reason": "OK",
                "snapshot_refresh_run_id": "refresh-run",
            },
            {
                "ticker": "AEM",
                "as_of_date": date(2026, 4, 17),
                "profile_label": "LINEAR",
                "confidence_label": "HIGH",
                "tool_a_score": 70.0,
                "tool_a_rank": 3,
                "score_eligible": True,
                "score_eligibility_reason": "OK",
                "snapshot_refresh_run_id": "refresh-run",
            },
        ],
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM", "GOLD", "AEM"])

    # Default: filter form is present, all three tickers visible.
    response = _call_wsgi_app(app, method="GET", path="/")
    body = response["body"]
    assert "overview-filters" in body
    assert "Showing 3 of 3 tickers" in body
    assert ">NEM<" in body and ">GOLD<" in body and ">AEM<" in body

    # Search by ticker substring.
    response = _call_wsgi_app(app, method="GET", path="/?search=NEM")
    body = response["body"]
    assert "Showing 1 of 3 tickers" in body
    assert ">NEM<" in body
    assert "/ticker/GOLD" not in body

    # Filter by profile.
    response = _call_wsgi_app(app, method="GET", path="/?profile=FRAGILE")
    body = response["body"]
    assert "Showing 1 of 3 tickers" in body
    assert "/ticker/GOLD" in body
    assert "/ticker/NEM" not in body

    # Filter by confidence.
    response = _call_wsgi_app(app, method="GET", path="/?confidence=HIGH")
    body = response["body"]
    assert "Showing 2 of 3 tickers" in body

    # Sort by tool_a_score descending — NEM (92) before AEM (70) before GOLD (50).
    response = _call_wsgi_app(app, method="GET", path="/?sort=tool_a_score")
    body = response["body"]
    nem_pos = body.index("/ticker/NEM")
    aem_pos = body.index("/ticker/AEM")
    gold_pos = body.index("/ticker/GOLD")
    assert nem_pos < aem_pos < gold_pos

    # Empty-state row for impossible filter.
    response = _call_wsgi_app(app, method="GET", path="/?profile=NOPE")
    body = response["body"]
    assert "No tickers match the current filters" in body


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
    assert "Tool B readiness:" in body
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
    assert "Tool A — Gold Sensitivity Ranking" in response["body"]
    # Tool A columns must be present
    assert "Δ Core" in response["body"]
    assert "Gamma" in response["body"]
    assert "Asymmetry" in response["body"]
    # Tool B-specific columns must NOT bleed in
    assert "Tool B Score" not in response["body"]
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
    assert "Tool B — Valuation Screening" in response["body"]
    # Tool B columns must be present
    assert "Verdict" in response["body"]
    # Four scenario target columns (matches Excel Top performers AA/AC/AI/AK).
    assert "Peer P/E Target" in response["body"]
    assert "Peak P/E Target" in response["body"]
    assert "Peer FCF Target" in response["body"]
    assert "Peak FCF Target" in response["body"]
    # The misleading single "Best Target" headline is gone.
    assert "Best Target" not in response["body"]
    # Tool A-specific structural columns must NOT bleed in
    assert "Δ Core" not in response["body"]
    assert "Asymmetry" not in response["body"]
    # Nav must mark this tab active
    assert 'class="nav-tab active" href="/tool-b"' in response["body"]


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
    assert "Screening Parameters" in body
    # All ten inputs must be present in the form.
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


def test_workspace_combined_alias_routes_match_root(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _repo_app_config()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    root_response = _call_wsgi_app(app, method="GET", path="/")
    combined_response = _call_wsgi_app(app, method="GET", path="/combined")

    assert root_response["status"].startswith("200")
    assert combined_response["status"].startswith("200")
    # Both should show the same overview heading and the combined nav active state.
    assert "Universe Overview" in root_response["body"]
    assert "Universe Overview" in combined_response["body"]
    assert 'class="nav-tab active" href="/"' in root_response["body"]
    assert 'class="nav-tab active" href="/"' in combined_response["body"]
