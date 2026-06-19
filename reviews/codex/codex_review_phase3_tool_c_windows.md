# Codex Review - Phase 3 Tool C Window Selector

Verdict: PASS after one P2 display-degradation fix.

## Findings

### P2 - Fixed - Missing/null window status could make partial artifacts look reliable

- File: `golden_vector/serve/windows.py:96`
- Evidence: before this review pass, `window_is_reliable()` used `metrics.get("status") or ""`, so a partial Tool C/Tool A row with `r_squared_2y=0.50`, beta values, and missing/null `window_status_2y` returned `True`. A direct `pd.NA` status could also raise `TypeError: boolean value of NA is ambiguous`.
- Impact: ranks/scores were not affected, but a partial old/intermediate artifact could render the selected window's beta cells as normal instead of muted even though the status metadata proving sample adequacy was absent.
- Fix applied: `window_is_reliable()` now distinguishes explicit legacy blank status from missing/null status, uses the shared `is_missing()` helper, and keeps missing/null status muted. Regression coverage added in `tests/test_windows.py:53`.

## Invariant Audit

- `TOOL_C_WINDOW_DISPLAY_COLUMNS` contains exactly 25 columns.
- `set(TOOL_C_WINDOW_DISPLAY_COLUMNS) & (DOWNSIDE_COMPONENTS | UPSIDE_COMPONENTS)` is empty.
- Tool C scoring still flows through `DOWNSIDE_COMPONENTS` / `UPSIDE_COMPONENTS`, then `oriented_percentile()` on `tool_c_downside_score` and `tool_c_upside_score`.
- Tool C tags and explanations still read core betas, hit rates, confidence, and relative-behavior fields; no per-window display column reaches those paths.
- The `/tool-c` page reads selected-window values through `window_metrics(row, active_window)` only for rendered Down Beta, Up Beta, and Gold-link cells. The rank cells still render `tool_c_downside_rank` and `tool_c_upside_rank`.

## Helper Move Audit

- `overview_tool_a.py` now imports `win_num_td()` and `gold_link_td()` from `serve/windows.py`; `rg` found no leftover `_win_num_td` / `_gold_link_td` references.
- A helper-output comparison against the old definitions matched for missing values, NaN, reliable/unreliable numeric cells, and all R2 bands.
- The normal Tool A render path remains covered by the workspace/DataTables tests.

## Test Coverage Notes

- Strengthened `test_tool_c_display_windows_never_change_rank()` to include tags and explanations, not just score/rank/eligibility/core betas.
- Old Tool C artifact degradation is covered by the serve-layer test and still renders the selector, core ranks, and muted missing window cells.
- Persist coverage verifies all 25 display columns round-trip and `weeks_*` columns remain integer.

## Verification

- `python -m pytest tests/test_tool_c.py tests/test_windows.py tests/test_persist_tool_c.py tests/test_workspace_app.py::test_workspace_tool_c_view_renders_gold_downside_page tests/test_workspace_app.py::test_workspace_tool_c_view_degrades_gracefully_for_old_artifact` - 15 passed.
- `python -m pytest tests/test_workspace_app.py tests/test_workspace_datatables.py` - 97 passed.
- `python -m pytest tests/test_cli_tool_c.py tests/test_candidate_finder_data.py tests/test_candidate_finder_page.py` - 45 passed.
- `git diff --check` - no whitespace errors; Git reported only existing CRLF conversion warnings for edited files.
