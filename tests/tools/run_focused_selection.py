"""Run the pinned focused release selection for presentation-layer work.

This is the file-path-based selection required by the visual redesign plan
(GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md section 18.6). No pytest markers exist
in this repository, so the selection is pinned here as an explicit file list:
every test file that imports ``golden_vector.serve`` plus the route-adjacent
model-state, URL, explanation, Portfolio, and CLI-workspace suites, plus the
redesign guardrail suites (design tokens, workspace shell — GV-RD-CX-006).

Run from the repository root (the guardrail scans resolve paths relative to
the working directory)::

    python tests/tools/run_focused_selection.py [extra pytest args]

Extra arguments are passed through to pytest (e.g. ``-x``, ``-q``, ``-k``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Every tests/*.py that imports golden_vector.serve (audit 2026-08-10), plus
# the plan-required suites that exercise serve contracts without importing it.
FOCUSED_TEST_FILES: tuple[str, ...] = (
    "tests/test_benchmark_comparison.py",
    "tests/test_candidate_finder_data.py",
    "tests/test_candidate_finder_page.py",
    "tests/test_chart_data_tables.py",
    "tests/test_cli_refresh_and_status.py",
    "tests/test_cli_workspace.py",
    "tests/test_column_help.py",
    "tests/test_common_helpers.py",
    "tests/test_config_models.py",
    "tests/test_data_status.py",
    "tests/test_design_tokens.py",
    "tests/test_detail_panel_review_fixes.py",
    "tests/test_detail_volatility_context.py",
    "tests/test_explanations.py",
    "tests/test_finite_input_validation.py",
    "tests/test_fundamentals_provenance.py",
    "tests/test_gold_dial_js_behavior.py",
    "tests/test_header_context.py",
    "tests/test_lab_behaviour_panel.py",
    "tests/test_lab_curve.py",
    "tests/test_lab_gold_profile.py",
    "tests/test_lab_page.py",
    "tests/test_lab_scorecard.py",
    "tests/test_lab_validation.py",
    "tests/test_market_hours_refresh.py",
    "tests/test_metric_formula.py",
    "tests/test_model_state.py",
    "tests/test_option_artifact_persistence.py",
    "tests/test_option_artifact_sources.py",
    "tests/test_option_availability.py",
    "tests/test_option_carry_forward.py",
    "tests/test_option_horizon_selection.py",
    "tests/test_option_refresh.py",
    "tests/test_option_signal_charts.py",
    "tests/test_option_signals.py",
    "tests/test_option_trading_data.py",
    "tests/test_option_trading_detail_panel.py",
    "tests/test_option_trading_overview.py",
    "tests/test_option_trading_routes.py",
    "tests/test_options_liquidity_cli.py",
    "tests/test_options_phase.py",
    "tests/test_persist_options.py",
    "tests/test_portfolio_artifacts_v6.py",
    "tests/test_portfolio_m1.py",
    "tests/test_portfolio_snowball_apply.py",
    "tests/test_portfolio_snowball_import.py",
    "tests/test_portfolio_store_v2.py",
    "tests/test_portfolio_totals.py",
    "tests/test_portfolio_valuation_v2.py",
    "tests/test_rebased_overlay_panel.py",
    "tests/test_redesign_routes.py",
    "tests/test_relative_behavior.py",
    "tests/test_replay_manifest.py",
    "tests/test_screening_overrides.py",
    "tests/test_scheduled_refresh.py",
    "tests/test_ticker_page_behaviour.py",
    "tests/test_ticker_page_command_workspace.py",
    "tests/test_ticker_page_compare.py",
    "tests/test_ticker_page_contracts.py",
    "tests/test_ticker_page_corporate.py",
    "tests/test_ticker_page_data_cache.py",
    "tests/test_ticker_page_fx_attribution.py",
    "tests/test_ticker_page_js_parity.py",
    "tests/test_ticker_page_options.py",
    "tests/test_ticker_page_producers.py",
    "tests/test_ticker_page_sections.py",
    "tests/test_ticker_page_stage.py",
    "tests/test_tradable_liquidity.py",
    "tests/test_tool_c.py",
    "tests/test_tool_d.py",
    "tests/test_tool_d_contract.py",
    "tests/test_ui_components.py",
    "tests/test_url_helpers.py",
    "tests/test_windows.py",
    "tests/test_windows_scheduled_refresh.py",
    "tests/test_windows_registry.py",
    "tests/test_workspace_app.py",
    "tests/test_workspace_datatables.py",
    "tests/test_workspace_horizon_switcher.py",
    "tests/test_workspace_shell.py",
    "tests/test_workspace_state_cache.py",
)


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[2]
    missing = [name for name in FOCUSED_TEST_FILES if not (root / name).exists()]
    if missing:
        sys.stderr.write(
            "Focused selection is stale; missing files:\n"
            + "\n".join(f"  {name}" for name in missing)
            + "\nUpdate tests/tools/run_focused_selection.py.\n"
        )
        return 2
    command = [sys.executable, "-m", "pytest", *FOCUSED_TEST_FILES, *argv]
    return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
