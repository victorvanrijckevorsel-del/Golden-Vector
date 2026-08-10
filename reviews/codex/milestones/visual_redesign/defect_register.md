# Visual redesign — defect register

Single source of truth for every pre-existing defect and code smell found before or during the presentation-only redesign (base `6c5015d`). Per the Codex decision of 2026-08-10: Phases 0-8 do **not** fix these; each actionable entry is resolved in a separate, clearly labelled follow-up commit after Phase 8 and before final release, with regression tests. Characterization tests may pin current behaviour with a `known-defect` label, but broken behaviour is never described as the desired contract. New findings from any phase, review agent, test, or browser check are appended here — they must not disappear into commentary.

Severity: HIGH = misleads the user or corrupts workflow state; MEDIUM = wrong/inconsistent surface behaviour; LOW = nit/hardening. Impact flags: S=security, D=data, A=analytics, P=product behaviour.

---

## D1 — Ticker POST validation errors crash to 500 on real data; degraded 400 otherwise
- **Severity:** HIGH · **Impact:** P
- **Route/files:** `POST /ticker/{t}/company|reporting|verification|note` error branches — `golden_vector/serve/workspace.py:615-628, 652-665, 703-716, 735-748`; `golden_vector/serve/detail_page.py:42-59, 111-112`; crash site `golden_vector/model/explanations.py:40` via `detail_panels.py:1521`.
- **Observable behaviour (Phase 0 characterization, 2026-08-10):** when the ticker has Tool A data — i.e. **every ticker on the live workspace** — a validation failure does not even reach the degraded 400 page: the error-branch re-render passes `app_config=None`, so `scoring_config` is `None` and `build_delta_explanation` raises `AttributeError`, which the outer handler converts to the generic **500** "The workspace hit an unexpected error." page. The user's typo in a date/number field reads as a server crash and the entered context is gone. Only when Tool A artifacts are absent (the pre-existing tests' fixture shape) does the intended 400 page render — and that page has its own defects: `active_window="12M"`, `canonical_anchor="12M"` (hardcoded — window switcher marks the wrong anchor), `lens="tool-a"`, `financials_source="our"`, `query_params=None` (so `return_to` collapses to bare `/ticker/{t}`), no column help, and the error styled with the success `flash` class.
- **Likely cause:** the four branches call `render_detail_page(state, ticker=…, tool_a_detail=…, flash=None, error=…)` without threading the request's resolved view state (`app_config`, window, lens, source, query params).
- **Test-quality note:** the existing 400-assertion tests pass only because their fixtures omit `_write_latest_outputs`, skipping the explanation path — a pass-for-the-wrong-reason case (soul.md #7). `tests/test_redesign_routes.py::test_reporting_post_invalid_date_crashes_to_500_with_tool_a_data` pins the real-data behaviour as `known-defect`.
- **Discovered:** 2026-08-10 Phase 0 audit; 500-crash discovered by the Phase 0 characterization suite the same day (extends the issue already named in plan §15.10).
- **Why deferred:** behavioural change; plan §12.1/§15.10 + Codex Q3 decision keep the redesign presentation-only.
- **Proposed fix:** extract the GET-path view-state resolution (window/lens/source/query/app_config/anchor) into a helper and reuse it in all four error branches; render the error with the error notice component.
- **Regression tests:** route tests POSTing invalid payloads with `?lens=option-trading&window=6M&fundamentals_source=yahoo` + calculator params, asserting the 400 page preserves each, shows an error-styled notice, and keeps help icons; `return_to` retains the full query.
- **Affects analytics/data:** no — serve-layer only.

## D2 — All-blank company POST claims "Company inputs saved."
- **Severity:** MEDIUM · **Impact:** P
- **Route/files:** `POST /ticker/{t}/company` — `golden_vector/serve/workspace.py:596-613`.
- **Observable behaviour:** submitting the company form with nothing typed and no clear-checkbox ticked performs no store write yet 303-redirects with `saved=company`, flashing "Company inputs saved."
- **Likely cause:** the empty `company_values` dict short-circuits to the success redirect instead of a no-op path.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** behavioural change (message/redirect semantics).
- **Proposed fix:** either redirect without `saved=company`, or flash a neutral "No changes to save." Decision at fix time.
- **Regression tests:** empty-POST case asserting no manual-store mtime/content change and the chosen message.
- **Affects analytics/data:** no.

## D3 — Option sizing form drops an active `?window=` selection
- **Severity:** MEDIUM · **Impact:** P
- **Route/files:** ticker option lens sizing form — `golden_vector/serve/detail_panels.py:1102-1126`.
- **Observable behaviour:** recomputing sizing (GET to `/ticker/{t}#option-sizing`) carries `lens`/`fundamentals_source`/side/horizon/bucket/size_mode/quantity/budget but not `window`; an active non-default window resets.
- **Likely cause:** the form's hidden inputs never included `window`.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** behavioural (query-contract) change.
- **Proposed fix:** add hidden `window` input when a non-default window is active (reuse the existing hidden-query helper).
- **Regression tests:** sizing submit with `?window=6M` retains `window=6M`.
- **Affects analytics/data:** no.

## D4 — `_safe_return_to` does not reject CR/LF
- **Severity:** LOW · **Impact:** S (loopback-only, requires crafted local POST)
- **Route/files:** `golden_vector/serve/workspace.py:840-844`; header write `golden_vector/serve/http_helpers.py:73-78`.
- **Observable behaviour:** a `return_to` containing encoded CR/LF passes the current checks and reaches the `Location` header unvalidated by wsgiref.
- **Likely cause:** allowlist checks cover empty/leading-slash/`//`/`\` but not control characters.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** security-adjacent behavioural change; plan §19.2 records-don't-change posture during visual work.
- **Proposed fix:** reject any control character (`<0x20`) in `return_to`.
- **Regression tests:** extend the two existing external-target rejection tests with `%0d%0a` variants (and protocol-relative/backslash cases while there).
- **Affects analytics/data:** no.

## D5 — Unknown ticker with `lens=option-trading` can 503 before the 404 decision
- **Severity:** MEDIUM · **Impact:** P
- **Route/files:** `golden_vector/serve/workspace.py:498-513`.
- **Observable behaviour:** `/ticker/BOGUS?lens=option-trading` loads the full option dataset first; a stale option schema surfaces as 503 for a ticker that should simply 404.
- **Likely cause:** option-data load precedes the active-ticker check.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** behavioural (status-code ordering) change.
- **Proposed fix:** check ticker membership before loading option data.
- **Regression tests:** unknown ticker + option lens under a stale-option-schema fixture asserts 404.
- **Affects analytics/data:** no.

## D6 — Candidate Finder parse failure renders a bare 400 page (inconsistent error UX)
- **Severity:** MEDIUM · **Impact:** P
- **Route/files:** `golden_vector/serve/workspace.py:297-302, 471-476`.
- **Observable behaviour:** `?gold_price=abc|0|-1|inf` on `/` or `/candidate-finder` returns a minimal error page with no screen content, while a *runtime* scenario failure warmly falls back to the persisted screen with a warning (`candidate_finder_page.py:280-281`), Tool B returns a full-page 400 with the form intact, and Tool D returns 200 + warning.
- **Likely cause:** `CandidateFinderScenarioError` raised during parse is handled by the bare `_render_error_page` path.
- **Discovered:** 2026-08-10 Phase 0 audit (plan §15.1 previously described only the warm path).
- **Why deferred:** harmonizing is a product decision about validation UX across four surfaces (Victor may have a preference; recommendation at fix time: render the persisted screen + error notice, keeping 400).
- **Proposed fix:** route parse failures through the persisted-screen renderer with an error notice, preserving the 400 status.
- **Regression tests:** parse-failure cases asserting status + persisted screen + notice.
- **Affects analytics/data:** no.

## D7 — Tool D silently swaps to `our` source while the URL says `fundamentals_source=yahoo`
- **Severity:** LOW · **Impact:** P
- **Route/files:** `golden_vector/serve/overview_tool_d.py:90-95`.
- **Observable behaviour:** when the Yahoo-source scenario computation fails, the page renders the `our`-source view with a warning, but the URL and source select still claim Yahoo — the displayed basis and the stated basis disagree.
- **Likely cause:** fallback reassigns `finance_source` internally without reflecting it in the rendered controls/URL.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** behavioural; interacts with "label every number with its basis" policy — fix should make the fallback explicit in the UI.
- **Proposed fix:** on fallback, render the source control in its true effective state (or add an explicit "showing our-source data" line to the existing warning naming the requested source).
- **Regression tests:** failing-Yahoo fixture asserts the warning names both requested and effective source.
- **Affects analytics/data:** no (display labelling only).

## D8 — `/lab/dial/{ticker}` double-decodes PATH_INFO
- **Severity:** LOW · **Impact:** P
- **Route/files:** `golden_vector/serve/workspace.py:407`.
- **Observable behaviour:** the dial route applies `unquote()` to an already-WSGI-decoded path segment (the `/ticker/` route does not), so a ticker containing `%` sequences decodes twice; harmless for the current universe but asymmetric.
- **Likely cause:** leftover manual decode.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** behavioural nit, zero current-universe impact.
- **Proposed fix:** drop the extra `unquote()`.
- **Regression tests:** dial route test with a `%`-bearing path segment.
- **Affects analytics/data:** no.

## D9 — `POST /refresh` discards the start result; concurrent refresh is silent
- **Severity:** LOW · **Impact:** P
- **Route/files:** `golden_vector/serve/workspace.py:281-291`; `golden_vector/serve/option_refresh.py:446-462`.
- **Observable behaviour:** the refresh POST ignores `OptionRefreshStartResult`; POSTing while a refresh is already running returns the same 303 with no user-visible signal (the button is only HTML-disabled while the page shows a running status).
- **Likely cause:** result intentionally unused when the route was built.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** behavioural; needs a small UX decision on the "already running" message.
- **Proposed fix:** thread an `already_running` flag into the redirect (e.g. `?refresh=already-running`) and show the existing status wording.
- **Regression tests:** double-POST route test asserting the signal.
- **Affects analytics/data:** no.

## D10 — Ticker-save redirects returning to Candidate Finder show no confirmation
- **Severity:** LOW · **Impact:** P
- **Route/files:** `golden_vector/serve/workspace.py` ticker POST redirects; Candidate Finder renderers (no `_flash_message` call).
- **Observable behaviour:** a manual-input save whose `return_to` points at `/` or `/candidate-finder` lands with `?saved=…` in the URL but no flash — the save looks unacknowledged.
- **Likely cause:** Candidate Finder never reads `saved`.
- **Discovered:** 2026-08-10 Phase 0 audit.
- **Why deferred:** behavioural; low impact (the normal flow returns to the ticker page).
- **Proposed fix:** read `saved` on Candidate Finder and render the shared success notice.
- **Regression tests:** GET `/` with `?saved=company` asserts the notice.
- **Affects analytics/data:** no.

## D11 — Portfolio positions DataTable throws a blocking alert on every real-browser load
- **Severity:** HIGH · **Impact:** P
- **Route/files:** `/portfolio` — `golden_vector/serve/portfolio_page.py:416` (positions table `<table class="js-datatable">` with **no `id` attribute**), nested per-position lots tables rendered inside its rows.
- **Observable behaviour:** on the live workspace, loading `/portfolio` in a real browser pops a modal `alert()`: `DataTables warning: table id=DataTables_Table_0 - Requested unknown parameter '16' for row 0, column 16`. The user must dismiss it on every visit; the positions table's sort/filter behaviour is unreliable after the error. Captured 2026-08-10 during the Phase 0 baseline browser matrix (`browser_measurements_before.json`, results[8].meta.alerts).
- **Likely cause:** DataTables initializes over a table whose rows embed nested `<table>` disclosures (per-lot detail), so the column model it derives disagrees with the outer rows' cell count; the table also lacks an explicit `id` (auto `DataTables_Table_0`), which additionally breaks the `data-filter-target="#<id>"` named-filter contract used everywhere else.
- **Why never caught:** zero JavaScript runtime coverage existed (the §18.2 gap) — every DataTables test asserts static markup only, and fixture pages were never loaded in a real browser.
- **Discovered:** 2026-08-10 Phase 0 browser matrix.
- **Why deferred:** behavioural (JS/table-structure) change. Exception note: the Phase 3/5 Portfolio migration restructures this exact markup into the shared table region; if the alert blocks migration QA, Codex's "blocks safe implementation" exception applies and the structural fix (lots disclosures out of the datatable-managed table + explicit id) may land with the migration, clearly labelled.
- **Proposed fix:** give the positions table an explicit id; move nested lots tables out of the DataTables-managed table (or stop marking that table `js-datatable`); add a static guard test that every `js-datatable` table has an id and contains no nested `<table>`.
- **Regression tests:** static guard above + browser-matrix zero-alert assertion on `/portfolio`.
- **Affects analytics/data:** no.

---

**Resolution log** (filled during post-Phase-8 follow-up): none yet.

---

## Codex interim review 2026-08-10 — GV-RD-CX-001…007 (ALL RESOLVED same day on dev-vic)

Review record: `reviews/codex/2026-08-10_claude_visual_redesign_review_findings.md` (scope: Phase 1 commits + uncommitted Phase 2 shell). Fixes landed immediately after the Phase 2 commit, per the review's instruction to resolve before later phases.

- **GV-RD-CX-001 (High) — mobile nav unavailable without JavaScript: RESOLVED.** All off-canvas drawer CSS in `responsive.css` is now scoped under `html.js`, set by an inline bootstrap in the page shell; without JavaScript the sidebar stays in normal document flow above the content and every route link remains reachable. Regression: `test_shell_dark_activation_and_no_js_fallback` (scoped-rule presence + unscoped-hiding scan) + JS-disabled check in the consolidated browser evidence.
- **GV-RD-CX-002 (High) — inactive segmented/preset controls ~1.08:1: RESOLVED.** The shared control pattern (`.segmented-control a`, `.candidate-preset`) now uses `--paper` surface + `--ink` text (≈15:1). The misleading `--white` alias was deleted from tokens.css so the pairing cannot recur. Regression: `test_control_selectors_meet_contrast_with_their_actual_tokens` (actual selector declarations, active + inactive).
- **GV-RD-CX-003 (Medium) — white on teal 2.44:1: RESOLVED.** New `--verified-fill` (#1F6E66) solid teal surface carries `--ink` text at ≥5.5:1 for `.benchmark-toggle.active` and `.winrate-fill`; the win-rate label also clears 4.5:1 on the empty track, which a dark-ink-on-teal fix would have broken. `--color-verified` stays the bright text/badge teal. Regression: selector-level contrast assertions incl. both win-rate backgrounds.
- **GV-RD-CX-004 (Medium) — DataTables dark theme not activated: RESOLVED.** Shell renders `<html lang="en" class="dark">`, activating the vendored DataTables dark selectors. Regression: shell contract assertion + sorted-table check in the consolidated browser evidence.
- **GV-RD-CX-005 (Medium) — drawer behaviour/semantics disagreement: RESOLVED (modal pattern).** The open drawer is now announced as `role="dialog"` `aria-modal="true"` with a visible "Close menu" button; the app content and skip link are made `inert`; focus moves to the close control on open, is trapped across all drawer focusables, and is restored on close (never on link-navigation close). Regression: `test_drawer_runtime_modal_semantics_focus_and_trap` (Node shim).
- **GV-RD-CX-006 (Medium) — focused runner excluded redesign suites: RESOLVED.** `tests/test_design_tokens.py` and `tests/test_workspace_shell.py` added to `FOCUSED_TEST_FILES`; `test_focused_selection_includes_redesign_suites` pins the redesign-critical set so the gap cannot silently reopen.
- **GV-RD-CX-007 (Low) — drawer-open state survives breakpoint changes: RESOLVED.** A `matchMedia("(min-width: 64rem)")` change listener normalises state (close without focus steal) when the layout crosses into desktop. Regression: Node-shim matchMedia assertion.
