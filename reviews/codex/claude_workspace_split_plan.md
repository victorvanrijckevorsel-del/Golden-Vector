# Plan: surgically split `workspace.py` (+ confirm snapshot retention)

**Author:** Claude Code
**Branch:** `dev-vic`
**Date:** 2026-05-28 (v2 after Codex review)
**Reviewer:** Codex — graded `READY WITH MINOR CHANGES` on v1; v2 addresses all six findings
**Related memory:** [[inflight-planning-workspace-split]], [[feedback-prefer-simpler-designs]]

## v2 changelog (against Codex review)

| Codex finding              | Where addressed in v2                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------- |
| R1 — hidden coupling (constants) | §3d gained a **Module constants** subtable mapping every flagged constant to its new home, plus an implementer grep-check |
| R2 — CSS extraction        | Confirmed safe; no change needed (was already addressed in §3e)                       |
| R3 — step 11 size          | Confirmed reviewable as one step; no change                                           |
| R4 — `lens` default        | §3c now defines a separate `DETAIL_DEFAULT_LENS_ID = "tool-a"` (NOT reusing overview's `composite` default). Smoke check for unknown lens added to §5 |
| R5 — snapshot retention    | §2 now explicitly separates "outputs retained" from "replay metadata retained"; audit doc must answer both |
| AF1 — step ordering bug    | §4 reordered: `page_shell.py` is now step 4 (was step 7), before `http_helpers.py`, since `_render_error_page` depends on `_page_shell` |
| AF2 — dataclass inconsistency | §3b and §3d now both say dataclasses move to `workspace_state.py`                  |
| AF3 — docs/ exception      | §6 now states the `docs/snapshot_retention_audit.md` exception explicitly             |

---

## 0. The simplest thing that could work

Before any clever design, the simplest version is stated first so Codex and Emanuel can react to it:

> **Move large blocks of `workspace.py` into a few sibling files in `golden_vector/serve/` with no behavior change, no new abstractions, no signature changes. Move only what cleanly comes out. Run the full test suite after every move. Stop when the file is small enough to navigate.**

That is the baseline. Everything below is an addition I'm proposing on top of it, and each addition is called out and justified individually so Codex can strike any of them.

---

## 1. Current state (verified 2026-05-28, not from memory)

| File                                              | Lines | Purpose                                                     |
| ------------------------------------------------- | ----- | ----------------------------------------------------------- |
| `golden_vector/serve/workspace.py`                | 4130  | Everything: routing, overviews, detail page, CSS, SVG, etc. |
| `golden_vector/serve/lenses.py`                   | 233   | Already-extracted scoring lenses (good — leave alone)       |
| `golden_vector/serve/screening_overrides.py`      | 192   | Already-extracted overrides parsing (good — leave alone)    |
| `golden_vector/serve/static/workspace-tables.js`  | 3.6KB | Already-extracted DataTables glue (good — leave alone)      |

Inside `workspace.py`, the rough functional bands are (verified by `grep` of top-level defs):

| Line range  | Content                                                                                                 |
| ----------- | ------------------------------------------------------------------------------------------------------- |
| 1–177       | Imports, constants, dataclasses (`WorkspaceState`, `ToolADetailState`, `OverviewFilters`)               |
| 178–516     | `create_workspace_app` (WSGI app — the **router**) + `run_workspace_server`                             |
| 517–678     | Data loading: `_load_workspace_state`, `_load_tool_a_detail`, `_load_published_structural_metrics`, etc.|
| 679–974     | Combined overview rendering + filters + sort                                                            |
| 975–1086    | Tool A overview page                                                                                    |
| 1087–1436   | Tool B overview page + screening params form + helpers                                                  |
| 1437–2459   | **Ticker detail page** — all Tool-A-flavored: panels, structural metrics, scatter, beta, vol, etc.      |
| 2460–2749   | Detail page forms (company, reporting, verification, notes)                                             |
| 2750–2856   | Small render helpers (metric cards, anchors, top nav)                                                   |
| 2858–3261   | `_page_shell` — **~400 lines of CSS embedded in a Python f-string**                                     |
| 3262–3522   | Format helpers, error page, response helpers, form helpers                                              |
| 3523–3610   | Static file serving (`_serve_static_file`, etc.)                                                        |
| 3612–4129   | SVG building (scatter, dual_bar, beta_history) + chart fallback panels                                  |

**Existing test coverage we must keep green** (`tests/`):
- `test_workspace_app.py` (overall WSGI behavior)
- `test_workspace_datatables.py`
- `test_workspace_horizon_switcher.py`
- `test_cli_workspace.py`
- `test_lenses.py`

---

## 2. Snapshot retention — STATUS UPDATE

The previous plan memory said "start keeping `update-data` snapshots instead of overwriting." Looking at the actual filesystem on 2026-05-28:

- `data/runs/` already contains timestamped foundation, tool-a, tool-b, and combined run folders going back to 2026-04-22.
- `data/output/tool_a/` keeps every historical `tool_a_latest_<runid>.parquet` and `tool_a_output_<runid>.parquet`, plus a `tool_a_latest.parquet` pointer.
- `data/output/tool_b/` does the same for Tool B.

**This means snapshot retention is largely already done.** What we don't know yet:
1. Is the **raw foundation** (market data per ticker) similarly retained per run, or does each `update-data` overwrite the prior raw pull?
2. Are the snapshots **complete enough to backtest a predictive signal** later — i.e., does each Tool A snapshot capture the inputs that produced its outputs, not just the outputs?

**Plan for this work item:** instead of building new retention code, the first step is a **5-minute audit** of what's already retained (read `golden_vector/app/latest_data.py`, the foundation persistence path, and the run manifests). Then write a tiny doc note in `docs/snapshot_retention_audit.md` describing what *is* kept, what is *not* kept, and what would be needed for backtesting. If a gap exists, propose a 1-paragraph fix in the same doc. If no gap exists, this item is closed with zero code changes.

> Why not just "keep more snapshots to be safe": disk is cheap but ambiguity isn't. If I add a second retention layer on top of one that already exists, every future reader of the codebase will have to figure out which one is canonical.

> **Refined after Codex R5:** the audit must separate two distinct questions, not one:
>
> 1. **Are snapshots of the *outputs* retained?** (Tool A/B per-run parquet, foundation snapshots under `data/runs/.../snapshots/`.) — evidence already on disk says yes.
> 2. **Is enough *replay metadata* retained to reconstruct exactly what produced a given snapshot?** Specifically: per-run config signature, code version, input universe, ticker list, scoring config used. `latest_foundation_manifest.json` is a moving pointer, not a per-run snapshot; `RunContext.record_artifact` (`golden_vector/app/run_context.py:92-98`) records artifact paths but does not copy their contents. The audit must explicitly answer whether each run folder contains enough to replay it deterministically, or whether something needs to be added.
>
> The doc must answer both questions separately. A single-line "snapshots are kept" answer is not sufficient.

---

## 3. The split plan

### 3a. Decisions locked in

1. **Tool-shaped split for the detail page only, mechanical for everything else.** (Decision from Emanuel, 2026-05-28.)
2. **Best-long-run on snapshot retention** — handled via §2 audit, not blind retention code.

### 3b. New file layout (target)

All new files live in `golden_vector/serve/`, next to `lenses.py` and `screening_overrides.py`. Sibling-only — no new sub-packages. (Reason: simpler imports, less re-shuffle if we change our minds.)

```
golden_vector/serve/
  __init__.py
  workspace.py              # SHRUNK: only the WSGI router (create_workspace_app, run_workspace_server)
  workspace_state.py        # NEW: WorkspaceState / loaders / route parsing
  overview_combined.py      # NEW: combined overview page rendering
  overview_tool_a.py        # NEW: Tool A overview page
  overview_tool_b.py        # NEW: Tool B overview page + screening params form
  detail_page.py            # NEW: ticker-centric detail page (lens-aware, see §3c)
  detail_panels.py          # NEW: panel render helpers used by detail_page
  detail_forms.py           # NEW: company / reporting / verification / notes forms
  charts.py                 # NEW: SVG builders (scatter, dual_bar, beta_history)
  format_helpers.py         # NEW: _fmt_*, _humanize_*, _coerce_form_*, small atoms
  http_helpers.py           # NEW: _html_response, _redirect_response, _read_form_data, _serve_static_file
  page_shell.py             # NEW: _page_shell + _render_top_nav  (Python side only)
  static/
    workspace.css           # NEW: ~400 lines of CSS extracted from _page_shell
    workspace-tables.js     # UNCHANGED
    vendor/                 # UNCHANGED
  lenses.py                 # UNCHANGED
  screening_overrides.py    # UNCHANGED
```

After the split, `workspace.py` should be **under ~500 lines**: imports + `create_workspace_app` + `run_workspace_server`. The dataclasses (`WorkspaceState`, `ToolADetailState`, `OverviewFilters`) move to `workspace_state.py` alongside their loaders, so dataclass + loader live in the same file. `workspace.py` becomes purely the router — read it, you know every URL the app exposes.

### 3c. The one tool-shaped change: detail page becomes ticker-centric

This is the only place we don't do a pure mechanical move. Rationale: Emanuel has two new tools in mind (predictive scores, short/put finder) that will need a ticker detail page too. Making the detail page "Tool A-centric" hardcodes a rewrite cost into the next two tools.

Concretely:

- `detail_page.py` exports one function: `render_detail_page(state, ticker, lens_id, query, app_config)`.
- `detail_page.py` defines its **own** `DETAIL_DEFAULT_LENS_ID = "tool-a"` constant. It does **not** reuse `golden_vector.serve.lenses.DEFAULT_LENS_ID` — that one is `"composite"` and serves the overview, which is a different surface. Reusing it would silently change the detail page default. The two defaults are deliberately independent.
- The current detail page is mounted in the router as the **"tool-a" lens** of that page — so today's URL `/ticker/AEM` becomes equivalent to `/ticker/AEM?lens=tool-a`, and `tool-a` is the default when no lens is given (so all existing links still work, no behavior change visible to the user).
- Unknown lens IDs (e.g. `/ticker/AEM?lens=banana`) fall back to `DETAIL_DEFAULT_LENS_ID` silently — same behavior the overview already uses for unknown lenses (see `golden_vector/serve/lenses.py:197`).
- A `lens` parameter is plumbed through but **only `tool-a` is implemented right now**. We do NOT design a `LensSpec` for the detail page in this work — that would be over-engineering. We just make sure the function signature is ticker-first and lens-aware, so future lenses can be added without changing the router or the function signature.
- The detail panel functions (scatter, beta history, structural windows, etc.) stay as named functions in `detail_panels.py`. They're not yet abstracted behind a registry. When the second lens lands, *that's* when we decide whether they should be.

> Why this is the right amount: I'm shaping the *interface*, not building the *abstraction*. The interface is one extra parameter and one renamed function. The abstraction (registry, lens classes for detail panels) costs nothing extra to add later because the interface is already lens-shaped.

### 3d. Mechanical moves — explicit destination per function and per constant

For Codex's review: every top-level def AND every module-level constant currently in `workspace.py` listed by new home. (Source line numbers from §1 plus Codex's R1 finding.)

#### Module constants (added after Codex R1)

Each constant moves with the first module that reads it. Constants read across two or more new modules go to the file Codex flagged as their canonical home. The implementer must grep for each constant's name before deleting it from `workspace.py` to confirm no stragglers remain.

| Constant                                                                                          | Current line  | New file              | Reason                          |
| ------------------------------------------------------------------------------------------------- | ------------: | --------------------- | ------------------------------- |
| `_STATIC_ROOT`, `_STATIC_ALLOWED_EXTENSIONS`                                                      | 16–17         | `http_helpers.py`     | only `_serve_static_file` reads them |
| `COMPANY_FORM_FIELDS`, `REPORTING_FORM_FIELDS`, `VERIFICATION_STATUS_OPTIONS`, `NOTE_STATUS_OPTIONS` | ~57–80      | `detail_forms.py`     | only the form renderers read them |
| `REQUIRED_MANUAL_FIELDS` (re-import from `golden_vector.screening.manual_data`)                   | imports block | `detail_forms.py`     | only forms reference it          |
| `_STRUCTURAL_WINDOWS`, `_WINDOW_WEEKS`, `_WINDOW_COLORS`                                          | ~655 area     | `workspace_state.py`  | shared by loaders + panels + charts; state is the most upstream consumer |
| `DETAIL_ALIGNMENT_*` constants                                                                    | ~1587 area    | `workspace_state.py`  | set by loader, read by panel — colocate with loader |
| `RATE_FIELDS`, `TOOL_A_PERCENT_FIELDS`, `TOOL_A_NUMERIC_FIELDS`, `_MISSING_SORT_SENTINEL`         | ~3343–3473    | `format_helpers.py`   | only formatting helpers read them |
| `DETAIL_DEFAULT_LENS_ID = "tool-a"` (NEW constant introduced by §3c)                              | n/a (new)     | `detail_page.py`      | detail-page-specific default     |

> **Implementer checklist (R1):** before committing each step in §4, run `rg <constant-name> golden_vector/serve/` to confirm the constant is unused in `workspace.py` and used at its new home. If any constant Codex listed slipped through, this catches it.

#### Functions and classes

<details>
<summary>Click for full move table</summary>

| Current line | Symbol                                           | New file              |
| -----------: | ------------------------------------------------ | --------------------- |
|          115 | `WorkspaceState`                                 | `workspace_state.py`  |
|          129 | `ToolADetailState`                               | `workspace_state.py`  |
|          139 | `OverviewFilters`                                | `workspace_state.py`  |
|          178 | `create_workspace_app`                           | `workspace.py` (stay) |
|          494 | `run_workspace_server`                           | `workspace.py` (stay) |
|          517 | `_load_workspace_state`                          | `workspace_state.py`  |
|          542 | `_load_tool_a_detail`                            | `workspace_state.py`  |
|          615 | `_load_published_structural_metrics`             | `workspace_state.py`  |
|          642 | `_safe_load_structural_history`                  | `workspace_state.py`  |
|          670 | `_parse_ticker_route`                            | `workspace_state.py`  |
|          679 | `_render_overview_page`                          | `overview_combined.py`|
|          889 | `_render_overview_filters_form`                  | `overview_combined.py`|
|          949 | `_overview_sort_key`                             | `overview_combined.py`|
|          975 | `_render_tool_a_overview_page`                   | `overview_tool_a.py`  |
|         1087 | `_render_tool_b_overview_page`                   | `overview_tool_b.py`  |
|         1256 | `_resolve_tool_b_frame`                          | `overview_tool_b.py`  |
|         1303 | `_render_screening_params_form`                  | `overview_tool_b.py`  |
|         1387 | `_fmt_form_number`                               | `format_helpers.py`   |
|         1411 | `_render_overrides_as_hidden_inputs`             | `overview_tool_b.py`  |
|         1437 | `_render_ticker_page`                            | `detail_page.py` (renamed `render_detail_page`, lens-aware) |
|         1490 | `_render_window_switcher`                        | `detail_panels.py`    |
|         1528 | `_render_provenance_warnings`                    | `detail_panels.py`    |
|         1576 | `_column_unique`                                 | `format_helpers.py`   |
|         1593 | `_detail_alignment`                              | `detail_panels.py`    |
|         1616 | `_render_detail_alignment_notice`                | `detail_panels.py`    |
|         1637 | `_render_suppressed_panel`                       | `detail_panels.py`    |
|         1647 | `_render_refresh_summary`                        | `detail_panels.py`    |
|         1667 | `_render_latest_panels`                          | `detail_panels.py`    |
|         1694 | `_render_tool_a_panel`                           | `detail_panels.py`    |
|         1773 | `_render_structural_metrics_load_notice`         | `detail_panels.py`    |
|         1811 | `_render_signal_notice`                          | `detail_panels.py`    |
|         1836 | `_render_explanation_cards`                      | `detail_panels.py`    |
|         1869 | `_build_active_window_explanations`              | `detail_panels.py`    |
|         1979 | `_render_structural_window_table`                | `detail_panels.py`    |
|         2020 | `_render_visual_panels`                          | `detail_panels.py`    |
|         2123 | `_active_window_metric` / `_active_window_sample`| `detail_panels.py`    |
|         2162 | `_anchor_window_metric` / `_anchor_window_sample`| `detail_panels.py`    |
|         2195 | `_render_scatter_panel`                          | `detail_panels.py`    |
|         2226 | `_render_up_down_beta_panel`                     | `detail_panels.py`    |
|         2255 | `_render_volatility_panel`                       | `detail_panels.py`    |
|         2304 | `_window_status`                                 | `detail_panels.py`    |
|         2318 | `_compute_window_volatility`                     | `detail_panels.py`    |
|         2390 | `_classify_volatility_context`                   | `detail_panels.py`    |
|         2420 | `_is_na`                                         | `format_helpers.py`   |
|         2429 | `_render_exploratory_horizon_panel`              | `detail_panels.py`    |
|         2460 | `_render_company_form`                           | `detail_forms.py`     |
|         2553 | `_render_reporting_form`                         | `detail_forms.py`     |
|         2580 | `_render_verification_section`                   | `detail_forms.py`     |
|         2681 | `_render_note_section`                           | `detail_forms.py`     |
|         2747 | `_fmt_note_tag`                                  | `format_helpers.py`   |
|         2754 | `_render_small_table`                            | `format_helpers.py`   |
|         2778 | `_metric_card`                                   | `format_helpers.py`   |
|         2800 | `_canonical_anchor_window`                       | `detail_panels.py`    |
|         2818 | `_resolve_active_window`                         | `detail_panels.py`    |
|         2830 | `_resolve_visible_windows`                       | `detail_panels.py`    |
|         2850 | `_render_top_nav`                                | `page_shell.py`       |
|         2858 | `_page_shell` (drop the CSS into `static/workspace.css`) | `page_shell.py` |
|         3262 | `_frame_index_by_ticker`                         | `format_helpers.py`   |
|         3273 | `_ticker_rows`                                   | `format_helpers.py`   |
|         3279 | `_flash_message`                                 | `http_helpers.py`     |
|         3289 | `_render_error_page`                             | `http_helpers.py`     |
|         3298 | `_humanize_column_name`                          | `format_helpers.py`   |
|         3302 | `_fmt_text` / `_fmt_number` / `_fmt_percent` / `_fmt_numeric_td` / `_fmt_value` | `format_helpers.py` |
|         3375 | `_collect_filter_options` / `_render_filter_bar` | `overview_combined.py`|
|         3465 | `_format_form_value` / `_coerce_form_numeric` / `_coerce_form_text` | `format_helpers.py` |
|         3503 | `_read_optional_parquet` / `_load_json_file`     | `workspace_state.py`  |
|         3515 | `_read_form_data`                                | `http_helpers.py`     |
|         3524 | `_html_response` / `_redirect_response`          | `http_helpers.py`     |
|         3549 | `_serve_static_file` / `_static_not_found`       | `http_helpers.py`     |
|         3612 | `_build_scatter_svg` / `_build_dual_bar_svg`     | `charts.py`           |
|         3703 | `_optional_float`                                | `format_helpers.py`   |
|         3718 | `_load_structural_delta_history`                 | `workspace_state.py`  |
|         3762 | `_structural_history_matches_tool_a`             | `workspace_state.py`  |
|         3793 | `_build_beta_history_svg`                        | `charts.py`           |
|         3980 | `_render_beta_history_panel`                     | `detail_panels.py`    |
|         4092 | `_render_chart_fallback_panel`                   | `detail_panels.py`    |
|         4105 | `_render_chart_unavailable_panel`                | `detail_panels.py`    |
|         4118 | `StructuralHistoryLoad`                          | `workspace_state.py`  |

</details>

### 3e. CSS extraction

`_page_shell` currently embeds ~400 lines of CSS in a Python f-string (lines ~2870–3261). Three reasons to move it to `static/workspace.css`:

1. CSS in Python is read-only in any editor that does CSS validation; broken styles get noticed late.
2. The `static/` directory is already served (see `_serve_static_file` at line 3549) — no new routing needed.
3. `_page_shell` shrinks from ~410 lines to ~10. It becomes legible.

The page shell will reference the new CSS file via a `<link rel="stylesheet">` exactly like the existing DataTables CSS link already does on line 2866. **Zero visual change** is the acceptance criterion.

> **Subtlety, caught on self-review:** the CSS currently lives inside a Python f-string, so every literal `{` and `}` is **doubled** (`:root {{ ... }}`). When the CSS moves to `static/workspace.css`, every doubled brace must be un-doubled (`{{` → `{`, `}}` → `}`). This is a mechanical find-and-replace, but missing it means broken styles. The acceptance check: open the new `.css` file and grep for `{{` or `}}` — there should be none.

---

## 4. Order of operations (safety first)

Each step is a single commit. Tests run between every step. **No step changes behavior** — that is the entire point.

Order is chosen so each step only imports from steps already done. This avoids two-step rewrites of import lines.

| # | Step                                                                                 | Test gate                                                                |
|---|--------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| 1 | Audit snapshot retention (§2). Write `docs/snapshot_retention_audit.md`. Code-free.  | (none)                                                                   |
| 2 | Extract CSS to `static/workspace.css`. Link from `_page_shell` (un-double `{{`/`}}`).| Full test suite + manual visual check of overview, Tool A, Tool B, detail|
| 3 | Move pure leaf helpers → `format_helpers.py` (formatting + numeric coercion + their constants from §3d). | Full test suite                                       |
| 4 | Move page shell + nav → `page_shell.py`. **Moved up (was step 7) per Codex AF1: `_render_error_page` depends on `_page_shell`, so page_shell must precede http_helpers.** | Full test suite + manual visual check |
| 5 | Move HTTP plumbing → `http_helpers.py` (incl. `_render_error_page`, `_STATIC_ROOT`, `_STATIC_ALLOWED_EXTENSIONS`). | Full test suite                                       |
| 6 | Move state + loaders + dataclasses → `workspace_state.py` (incl. `_STRUCTURAL_WINDOWS`, `_WINDOW_WEEKS`, `_WINDOW_COLORS`, `DETAIL_ALIGNMENT_*`). | Full test suite |
| 7 | Move SVG builders → `charts.py`.                                                     | Full test suite                                                          |
| 8 | Move overview pages → `overview_combined.py`, `overview_tool_a.py`, `overview_tool_b.py`. | Full test suite + manual check of three overview URLs                |
| 9 | Move detail panels → `detail_panels.py`.                                             | Full test suite                                                          |
| 10| Move detail forms → `detail_forms.py` (incl. `COMPANY_FORM_FIELDS`, `REPORTING_FORM_FIELDS`, `VERIFICATION_STATUS_OPTIONS`, `NOTE_STATUS_OPTIONS`). | Full test suite |
| 11| Move detail page render → `detail_page.py`, rename to `render_detail_page`, **add `lens` param + `DETAIL_DEFAULT_LENS_ID = "tool-a"` constant**, plumb through router. URLs unchanged. | Full test suite + manual check of `/ticker/AEM`, `/ticker/AEM?lens=tool-a` (identical), and `/ticker/AEM?lens=banana` (falls back to tool-a, no 404) |
| 12| Verify `workspace.py` is now small (~500 lines) and contains only router + entry.    | `wc -l golden_vector/serve/workspace.py` < 600                           |

If any step breaks tests, **stop and fix before the next step.** Do not bundle steps.

---

## 5. Acceptance criteria

The split is done when **all** of the following hold:
- `wc -l golden_vector/serve/workspace.py` < 600
- All existing tests pass with no modifications to test logic (imports may need updating where tests import private helpers — that's allowed and expected)
- Manual smoke test: `python main.py serve` opens, and the four routes (`/`, `/tool-a`, `/tool-b`, `/ticker/AEM`) render visually identical to before
- The detail page accepts a `lens` query parameter (today only `"tool-a"` is implemented):
  - `/ticker/AEM?lens=tool-a` renders identically to `/ticker/AEM`
  - `/ticker/AEM?lens=banana` (unknown lens) falls back to `tool-a` silently and returns 200, not 404 (added per Codex R4)
- `docs/snapshot_retention_audit.md` exists and answers BOTH questions from §2: (a) are output snapshots retained, (b) is enough replay metadata retained (per Codex R5)
- A grep for `{{` or `}}` in `static/workspace.css` returns zero matches (per the brace-escape catch in §3e)

## 6. Out of scope (deliberately)

These are NOT part of this work, and should be left alone:
- Designing a `DetailLensSpec` or panel registry — wait for the second lens to exist before abstracting
- Building any predictive tool or short/put-finder
- Adding new retention beyond what §2 audit shows is missing
- Refactoring `lenses.py`, `screening_overrides.py`, or the `static/workspace-tables.js`
- Touching anything outside `golden_vector/serve/` (no changes to `app/`, `screening/`, `model/`, `features/`, `contracts/`) — **single exception:** writing `docs/snapshot_retention_audit.md` per §2 / step 1 (per Codex AF3)
- Performance work, dependency upgrades, type hint improvements

## 7. Risks Codex should pry at

I want the review to push specifically on these:

1. **Hidden coupling.** A function I marked as "leaf" in §3d may actually reach back into module-level state. If any of these functions read a module global other than imports, the move will break silently.
2. **CSS extraction.** If `_page_shell` interpolates Python values *into* the CSS (e.g. dynamic colors), the move-as-static-file is wrong. I scanned for it and saw none, but Codex should double-check the f-string for any `{` outside literal CSS braces.
3. **Step 11 ordering.** I'm renaming the detail page render function and adding a parameter in the *same* commit. If the diff is too large to review, split it: first rename, then add the lens param.
4. **The `lens` param default.** Today, `/ticker/AEM` works. After step 11, `/ticker/AEM?lens=banana` should fall back to `tool-a` rather than error. Confirm this is the right default.
5. **Snapshot audit (§2).** Am I right that retention is largely done? Or is there something the audit will miss that you'd want kept now?

---

## 8. Why this plan is shaped this way

| Principle (from Emanuel)                  | How it shows up in the plan                                                              |
|-------------------------------------------|------------------------------------------------------------------------------------------|
| Simplest thing that could work, first     | §0 states the no-frills version. Every extra is called out separately.                   |
| Match rigor to risk                       | Structural change → full plan + Codex review (correctly applied).                        |
| Test gates between steps                  | §4 has 12 steps, each with its own test gate.                                            |
| No premature abstraction                  | §3c builds a **lens interface**, not a lens abstraction. Registry waits for second lens. |
| Don't redo work that's already done       | §2 audits retention before writing retention code.                                       |
| Plain English                             | This file is readable end-to-end without jargon.                                         |
