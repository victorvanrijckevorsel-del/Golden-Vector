# Codex Review: Overlay, Info Affordance, Metric Formula, Candidate Finder

Scope reviewed: `git diff 3492a04..5a71373 -- golden_vector/ tests/`.

Method: fanned out surface-specific agents for overlay SVG, overlay JS, info affordance, metric formula/dual source, Candidate Finder, beta rug ticks, then ran an independent skeptic pass against each candidate finding. Items below are confirmed against the actual tree and fixed in this worktree unless explicitly marked as test-only.

## Confirmed Findings

| Severity | Surface | Evidence | Fix |
|---|---|---|---|
| HIGH | `golden_vector/model/candidate_finder.py:129` | `score_eligible=False` rows were stored as `source_score_eligible=False` but could still rank on non-Tool-A criteria. Repro before fix: a degraded row with better `ev_ebitda` ranked first and appeared in the criterion top list. | Added a global `_source_rankable_mask()` and applies it before percentile/top-list scoring; `rank_eligible` now also requires `source_score_eligible`. Regression: `tests/test_candidate_finder_data.py:264`. |
| MEDIUM | `golden_vector/serve/charts.py:289` | Overlay grid step fell back to fixed `1000`, so a huge rebased span could emit unbounded gridlines or hang rendering. | Replaced fixed fallback with bounded 1/2/5 nice-step helper plus tick cap. Regression: `tests/test_rebased_overlay_panel.py:154`. |
| MEDIUM | `golden_vector/screening/pipeline.py:262` / `golden_vector/serve/overview_tool_b.py:106` / `golden_vector/serve/detail_panels.py:328` | Dual-source ratio active/alternate selection lived in `serve/format_helpers.py`, reading `_our_view`/`_official` and branching on source mode. That was source/coalesce resolution in serve. | Moved display-ready alternate fields into `materialize_tool_b_finance_source()` and the Tool B artifact schema. Serve now only formats `*_alternate_value`, `*_alternate_label`, and `*_show_alternate`. Guards: `tests/test_workspace_app.py:2373` and `tests/test_workspace_app.py:2438`. |
| MEDIUM | `golden_vector/serve/metric_formula.py:61` | Leverage help formula said Net debt / trailing EBITDA, but the live values line showed only net debt and the result, hiding the denominator. | Persisted `ebitda_ltm_musd` through Tool B output and added it as a leverage component. Regression: `tests/test_metric_formula.py:120`. |
| MEDIUM | `golden_vector/serve/detail_panels.py:328` | Detail snapshot hid the Our View alternate when Yahoo was selected and Yahoo's active ratio was missing; overview already showed `- (Our View 2.0)`. | The backend materializer now sets `*_show_alternate` for this case and detail consumes it. Regression: `tests/test_workspace_app.py:2497`. |
| LOW | `golden_vector/serve/charts.py:275` | Sub-1% overlay spans collapsed to integer labels, often showing only `0%` and no useful brackets. | `_pct_label()` now supports decimal percent labels while preserving integer labels for normal spans. Regression: `tests/test_rebased_overlay_panel.py:139`. |
| LOW | `golden_vector/serve/detail_panels.py:2323` | One-point overlay series passed the drawable filter and produced invisible one-point polylines instead of the unavailable panel. | Drawable overlay lines now require at least two distinct valid dated points. Regression: `tests/test_rebased_overlay_panel.py:331`. |
| LOW | `golden_vector/serve/candidate_finder_page.py:101` | Candidate Finder carried a second hardcoded percent-format list for `margin_pct`/`fcf_yield`, duplicating `metric_value_text()`. | `_fmt_criterion_value()` now uses `metric_value_text()` first, then falls back to generic number formatting. Regression: `tests/test_candidate_finder_page.py:525`. |
| LOW | `golden_vector/serve/column_help.py:1` / `golden_vector/serve/static/workspace.css` | Info-affordance unification left stale docs describing `.help-term` hover behavior and dead `th[title]` CSS. | Updated docs and removed legacy CSS. Guard extended at `tests/test_workspace_app.py:2480`. |
| LOW | `tests/test_column_help.py:138` | The new `data-help-values` slot was behaviorally escaped, but no test proved malicious values could not leak into HTML. | Added direct escaping test for `help_icon(values=...)`. |
| LOW | `tests/test_rebased_overlay_panel.py:178` | Overlay crosshair JS test only scanned source strings and would pass if `esc()` returned raw input. | Added a Node runtime test with a fake DOM that exercises escaping, viewport clamping, same-date short-circuit, and blur dismissal. |

## Refuted Concerns

- Overlay crosshair coordinate mapping: refuted for current CSS/viewBox behavior and the decoded payload mapping tests.
- Overlay `data-overlay` escaping: refuted; JSON is attribute-escaped server-side and dynamic JS fields are escaped before `innerHTML`.
- NaT overlay dates: refuted; existing tests cover all-NaT and mixed-NaT behavior.
- Base outside y-range: refuted; finite base is included in the y-domain.
- Info panel XSS: refuted; `help-popover.js` uses `textContent` for title, meaning, formula, values, and more.
- Info panel affordance split: refuted after cleanup; no live `.help-term`, bare `data-help=`, `.help-pop`, or `th[title]` path remains in serve.
- Metric compact units and 100x fraction scaling: refuted; shared metric formatter keeps compact cells and percent fields.
- Candidate Finder beta blend/per-window help basis: refuted; help key follows `source_field`.
- Beta rug tick title stripping/dismissal/escaping: refuted; no fixes needed.

## Verification

Focused affected suite:

```text
python -m pytest tests/test_tool_b_pipeline.py tests/test_tool_b_schema_contract.py tests/test_candidate_finder_page.py tests/test_candidate_finder_data.py tests/test_rebased_overlay_panel.py tests/test_metric_formula.py tests/test_column_help.py -q
137 passed in 145.61s
```

Workspace guard/detail subset:

```text
python -m pytest tests/test_workspace_app.py::test_snapshot_ratio_cell_is_compact_and_shows_yahoo_divergence tests/test_workspace_app.py::test_workspace_tool_b_serve_layer_has_no_financial_arithmetic tests/test_workspace_app.py::test_dual_source_ratio_resolution_is_materialized_before_serve tests/test_workspace_app.py::test_one_info_affordance_no_legacy_hover_remains tests/test_workspace_app.py::test_metric_formula_serve_layer_has_no_ratio_recompute tests/test_workspace_app.py::test_charts_serve_layer_is_display_only tests/test_workspace_app.py::test_workspace_candidate_finder_serve_layer_has_no_forked_tool_b_d_math -q
7 passed in 1.19s
```

Full gate:

```text
python -m pytest -q
1555 passed in 835.65s (0:13:55)
```
