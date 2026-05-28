# Codex Workspace Split Completion Report

Date: 2026-05-28

## Summary

Status: CHECKPOINT D complete.

- Commits in this split: 13 total (12 planned steps plus one step-7 review-fix commit).
- Final `golden_vector/serve/workspace.py` size: 397 lines after post-review whitespace cleanup.
- Final full test run: 306 passed after post-review regression tests.
- Final router shape: only `create_workspace_app` and `run_workspace_server` remain as top-level functions.

## 1. Final Layout Readback

The target sibling-file layout from the plan is met. Differences from the target are called out below the table.

| File | Lines | Description |
| --- | ---: | --- |
| `golden_vector/serve/__init__.py` | 1 | Package marker. |
| `golden_vector/serve/workspace.py` | 397 | WSGI router, request dispatch, form POST handling, server entry. |
| `golden_vector/serve/workspace_state.py` | 366 | Workspace dataclasses, route parsing, parquet/json loaders, structural history loading. |
| `golden_vector/serve/overview_combined.py` | 467 | Combined overview page, overview filters, provenance and refresh notices. |
| `golden_vector/serve/overview_tool_a.py` | 133 | Tool A overview page. |
| `golden_vector/serve/overview_tool_b.py` | 373 | Tool B overview page, screening params form, override hidden inputs. |
| `golden_vector/serve/detail_page.py` | 78 | Ticker detail page renderer, renamed `render_detail_page`, lens-aware signature. |
| `golden_vector/serve/detail_panels.py` | 1099 | Detail analytical panels, window resolver/switcher helpers, chart panels. |
| `golden_vector/serve/detail_forms.py` | 330 | Company, reporting, verification, and note forms. |
| `golden_vector/serve/charts.py` | 286 | SVG chart builders for scatter, dual bar, and beta history. |
| `golden_vector/serve/format_helpers.py` | 260 | Formatting, coercion, small table/card atoms, ticker row helpers. |
| `golden_vector/serve/http_helpers.py` | 146 | HTML/redirect responses, form-body parsing, static file serving, error page. |
| `golden_vector/serve/page_shell.py` | 41 | Top navigation and page shell. |
| `golden_vector/serve/lenses.py` | 233 | Existing overview lens definitions, unchanged by this split. |
| `golden_vector/serve/screening_overrides.py` | 192 | Existing screening override parsing/application, unchanged by this split. |
| `golden_vector/serve/static/workspace.css` | 382 | Extracted workspace CSS. |
| `golden_vector/serve/static/workspace-tables.js` | 94 | Existing DataTables glue, unchanged by this split. |
| `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.css` | 1 | Vendored DataTables CSS, unchanged. |
| `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.js` | 4 | Vendored DataTables JS, unchanged. |
| `golden_vector/serve/static/vendor/datatables/jquery-3.7.1.min.js` | 2 | Vendored jQuery JS, unchanged. |

Layout differences from the plan:

- `workspace.py` landed at 397 lines after post-review whitespace cleanup, below both the hard `<600` acceptance gate and the target "under ~500" guidance.
- `_render_provenance_warnings` and `_render_refresh_summary` landed in `overview_combined.py` instead of `detail_panels.py`; see deviations.
- Static vendor files are listed here for completeness even though the plan only called them out as unchanged existing assets.

## 2. Deviations From The Plan

1. `overview_combined.py` owns `_render_provenance_warnings` and `_render_refresh_summary` at `golden_vector/serve/overview_combined.py:324` and `golden_vector/serve/overview_combined.py:372`. The plan table had them under `detail_panels.py`, but after step 8 their only callers were overview pages. Keeping them in `overview_combined.py` avoided a detail-to-overview import relationship and kept detail modules focused on ticker pages.

2. `http_helpers.py` now distinguishes repo-owned static assets from vendored static assets at `golden_vector/serve/http_helpers.py:137`. Vendored DataTables assets keep immutable caching; `workspace.css` and repo-owned JS use `Cache-Control: no-cache` at `golden_vector/serve/http_helpers.py:141`. This was added while acting on Claude's review so local CSS changes do not get stuck behind a year-long immutable cache. Coverage landed in `tests/test_workspace_datatables.py:115`.

3. Step 7 got a small correction commit (`76ee786`) before step 8. It restored three Unicode arrow/dash characters in `charts.py` comments/docstring after Claude found an unauthorized character normalization. This made the step-7 move more mechanical; no behavior changed.

4. The final smoke command used the current CLI subcommand, `python main.py workspace --port ...`, not `python main.py serve`. `python main.py --help` shows `workspace` is the available local workspace command.

## 3. Symbols Moved Per File

| File | Constants/classes now owned | Functions now owned |
| --- | --- | --- |
| `workspace_state.py` | `WorkspaceState`, `ToolADetailState`, `OverviewFilters`, `StructuralHistoryLoad`, `DETAIL_ALIGNMENT_*`, `_STRUCTURAL_WINDOWS`, `_WINDOW_WEEKS`, `_WINDOW_COLORS` | `_load_workspace_state`, `_load_tool_a_detail`, `_load_published_structural_metrics`, `_safe_load_structural_history`, `_parse_ticker_route`, `_read_optional_parquet`, `_load_json_file`, `_load_structural_delta_history`, `_structural_history_matches_tool_a` |
| `overview_combined.py` | None | `_render_overview_page`, `_render_overview_filters_form`, `_overview_sort_key`, `_render_provenance_warnings`, `_render_refresh_summary`, `_collect_filter_options`, `_render_filter_bar` |
| `overview_tool_a.py` | None | `_render_tool_a_overview_page` |
| `overview_tool_b.py` | `_OVERRIDE_PARAM_NAMES` | `_render_tool_b_overview_page`, `_resolve_tool_b_frame`, `_render_screening_params_form`, `_render_overrides_as_hidden_inputs` |
| `detail_page.py` | `DETAIL_DEFAULT_LENS_ID` | `render_detail_page` |
| `detail_panels.py` | None | `_render_window_switcher`, `_detail_alignment`, `_render_detail_alignment_notice`, `_render_suppressed_panel`, `_render_latest_panels`, `_render_tool_a_panel`, `_render_structural_metrics_load_notice`, `_render_signal_notice`, `_render_explanation_cards`, `_build_active_window_explanations`, `_render_structural_window_table`, `_render_visual_panels`, `_active_window_metric`, `_active_window_sample`, `_anchor_window_metric`, `_anchor_window_sample`, `_render_scatter_panel`, `_render_up_down_beta_panel`, `_render_volatility_panel`, `_window_status`, `_compute_window_volatility`, `_classify_volatility_context`, `_render_exploratory_horizon_panel`, `_canonical_anchor_window`, `_resolve_active_window`, `_resolve_visible_windows`, `_render_beta_history_panel`, `_render_chart_fallback_panel`, `_render_chart_unavailable_panel` |
| `detail_forms.py` | `VERIFICATION_STATUS_OPTIONS`, `NOTE_STATUS_OPTIONS`, `COMPANY_FORM_FIELDS`, `REPORTING_FORM_FIELDS` | `_render_company_form`, `_render_reporting_form`, `_render_verification_section`, `_render_note_section` |
| `charts.py` | None | `_build_scatter_svg`, `_build_dual_bar_svg`, `_build_beta_history_svg` |
| `format_helpers.py` | `RATE_FIELDS`, `TOOL_A_PERCENT_FIELDS`, `TOOL_A_NUMERIC_FIELDS`, `_MISSING_SORT_SENTINEL` | `_fmt_form_number`, `_column_unique`, `_is_na`, `_fmt_note_tag`, `_render_small_table`, `_metric_card`, `_frame_index_by_ticker`, `_ticker_rows`, `_humanize_column_name`, `_fmt_text`, `_fmt_number`, `_fmt_percent`, `_fmt_numeric_td`, `_fmt_value`, `_format_form_value`, `_coerce_form_numeric`, `_coerce_form_text`, `_optional_float` |
| `http_helpers.py` | `_STATIC_ROOT`, `_STATIC_ALLOWED_EXTENSIONS`, `_IMMUTABLE_STATIC_PREFIXES` | `_flash_message`, `_render_error_page`, `_read_form_data`, `_html_response`, `_redirect_response`, `_serve_static_file`, `_static_cache_control`, `_static_not_found` |
| `page_shell.py` | `_NAV_LINKS` | `_render_top_nav`, `_page_shell` |

## 4. HTML Baseline Diff Results

- Step 2 CSS extraction: expected HTML change only. The inline `<style>...</style>` block was replaced by `<link rel="stylesheet" href="/static/workspace.css">`; `workspace.css` had zero `{{` or `}}` brace artifacts.
- Step 4 voluntary smoke: `/`, `/tool-a`, `/tool-b`, and `/ticker/AEM` matched the step-2 HTML output exactly.
- Step 8 overview move: zero HTML differences for `/`, `/tool-a`, `/tool-b`, and `/ticker/AEM`.
- Step 11 detail-page move/lens parameter: `/ticker/AEM`, `/ticker/AEM?lens=tool-a`, and `/ticker/AEM?lens=banana` all returned 200; both lens variants had zero HTML differences against `/ticker/AEM`.
- Final browser render pass: `/`, `/tool-a`, `/tool-b`, and `/ticker/AEM` loaded in the in-app browser with expected titles/H1s, tables, nav links, and `/static/workspace.css` present.

## 5. Acceptance Criteria Checklist

| Criterion | Status | Evidence |
| --- | --- | --- |
| `wc -l golden_vector/serve/workspace.py` < 600 | MET | 397 lines. |
| Existing tests pass | MET | Final run: 306 passed. Existing test expectations were preserved; imports were updated where private helpers moved. |
| Manual smoke for `/`, `/tool-a`, `/tool-b`, `/ticker/AEM` | MET | Step 8 HTML diff was zero; final browser render pass loaded all four routes with CSS present. |
| `/ticker/AEM?lens=tool-a` equals `/ticker/AEM` | MET | Step 11 smoke diff: zero lines. |
| `/ticker/AEM?lens=banana` falls back to tool-a with 200 | MET | Step 11 smoke diff against `/ticker/AEM`: zero lines; status 200. Fallback is in `workspace.py:181-183`. |
| `docs/snapshot_retention_audit.md` exists and answers both retention questions | MET | Audit exists and separately covers retained output snapshots plus the remaining replay-metadata gap. |
| `workspace.css` has no doubled f-string braces | MET | `rg -n "\\{\\{|\\}\\}" golden_vector/serve/static/workspace.css` returned no matches. |

## 6. Test Deltas

- Baseline pass count: 303.
- Final pass count: 306.
- New test files added: none.
- Tests modified:
  - `tests/test_workspace_datatables.py`: updated private-helper imports after moves; added `test_static_route_serves_workspace_css_with_revalidation` for repo-owned CSS cache behavior and `test_static_route_uses_resolved_path_for_cache_policy` for normalized static paths.
  - `tests/test_workspace_app.py`: added `test_workspace_detail_lens_param_defaults_to_tool_a` for detail lens fallback behavior.
  - `tests/test_workspace_horizon_switcher.py`: updated private-helper imports from `workspace.py` to `detail_panels.py`.

## 7. Open Questions For Reviewer

- Please sanity-check deviation 1: moving `_render_provenance_warnings` and `_render_refresh_summary` to `overview_combined.py` instead of `detail_panels.py`.
- Please sanity-check deviation 2: static cache split between vendored immutable assets and repo-owned `no-cache` assets.
- Please sanity-check the step-11 lens shape: `render_detail_page(..., lens=...)` is present and router-normalized, but there is intentionally no lens registry or UI yet because only `tool-a` exists.
