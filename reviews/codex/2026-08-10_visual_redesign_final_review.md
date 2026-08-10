# Golden Vector visual redesign — independent final review

- **Date:** 2026-08-10
- **Branch/head:** `dev-vic` at `86351ff` (matches `origin/dev-vic`)
- **Reviewed range:** base `6c5015d`; visual-redesign commits `902369a..86351ff`
- **Mode:** read-only review; no product fixes; no full-suite rerun
**Verdict:** **NOT READY TO MERGE** — 0 HIGH, 4 MEDIUM, 8 LOW findings.

The presentation-only boundary held in the integrated code: the range changes no analytics, pipeline, schema, manifest, artifact, or shared-data module, and `golden_vector/serve/ui/` is currently data-unaware. The final `tables.css` containment rule is also safe: it uses `min-width: 0` only and neither clips content nor creates an anonymous scroll container. Notice call sites reviewed in the newer phases map already-resolved state to the Section 10.5 vocabulary; I found no new state threshold in the UI package.

The saved focused result (`845 passed`) was accepted rather than repeated. I used source review, commit-by-commit diffs, the saved evidence, `git diff --check`, an in-memory rerun of the fixture contract extractor, and two fixture-only WSGI reproductions for suspected defects. No source file or `naukri.md` was changed.

## Findings

### GV-RD-FINAL-001 — MEDIUM — D1 is only partially fixed; validation errors still discard the request/form context

**Files:**

- `golden_vector/serve/workspace.py:498-503, 638-650, 676-688, 728-740, 761-773`
- `golden_vector/serve/detail_page.py:51-60, 69-72`
- `tests/test_redesign_routes.py:114-148`
- `reviews/codex/milestones/visual_redesign/defect_register.md:9-19, 136`

Commit `45583e6` fixed the crash by passing `app_config`, but all four error branches still call `render_detail_page` without the resolved `active_window`, `canonical_anchor`, `lens`, `financials_source`, `query_params`, provenance, option detail, or submitted form values. The renderer therefore uses its `12M`/Tool-A/Our-View defaults, builds a bare `/ticker/{ticker}` `return_to`, and reloads the previously stored row instead of showing what the user submitted. This is exactly the second half of D1 and its proposed regression contract, yet the resolution log calls D1 fully resolved.

**Concrete fixture repro:**

```text
POST /ticker/NEM/reporting?window=6M&fundamentals_source=yahoo
next_financial_report_date=not-a-date
notes=typed marker
return_to=/ticker/NEM?window=6M&fundamentals_source=yahoo

=> 400 Bad Request
=> active window tab: 1Y (the fixture's canonical/default), not 6M
=> every rendered hidden return_to: /ticker/NEM
=> "typed marker" absent from the response
```

The two new tests use no non-default view/query state and only assert status, notice, and section copy, so they pass while the documented context-preservation contract remains broken. The correction should reuse the GET-path view-state resolution in all four branches and add the full query/submitted-value regression described in the register.

### GV-RD-FINAL-002 — MEDIUM — chart detail remains pointer-only despite the Phase 6 touch/keyboard gate

**Files:**

- `golden_vector/serve/charts.py:154-163, 427-456`
- `golden_vector/serve/static/rug-tooltip.js:13-18, 35-58`
- `golden_vector/serve/static/overlay-crosshair.js:71-122`
- `reviews/codex/milestones/visual_redesign/browser_evidence_phase6.json` (`rug_tooltip`, `documented_gap`, `verdict`)
- `reviews/codex/milestones/visual_redesign/handoff.md:23-25, 57-58`
- `GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md:673-687, 1082-1099, 1233, 1273, 1450-1452, 1489`

The rug ticks are SVG `<line>` elements with no keyboard focus or activation. With JavaScript active, their `<title>` fallbacks are removed, and the replacement listens only for `pointerover`, `pointermove`, and `pointerout`. The overlay chart likewise listens only for `pointermove`; it has no `focus`, keyboard, `click`, or `pointerdown` path. Merely using Pointer Events does not make a drag/move-only interaction an operable touch-tap interaction.

**Concrete repro:** keyboard-tab through `/ticker/NEM`; no rug tick or overlay date can receive focus, so none of the per-tick/per-date tooltip values can be opened. On touch, the overlay has no tap handler at all. The overlay's per-date series values are not exposed by the generic `aria-label="Rebased price comparison"`, and there is no same-page table containing that complete per-date payload.

The Phase 6 evidence openly records the missing keyboard equivalent but still returns `PASS`, while the handoff overclaims that “pointer events add touch.” The blueprint allowed this gap only if it remained blocking; it cannot be accepted as a completed accessibility gate.

### GV-RD-FINAL-003 — MEDIUM — the new sticky section navigation obscures itself and its anchor targets

**Files:**

- `golden_vector/serve/static/css/components.css:161-188`
- `golden_vector/serve/static/css/shell.css:85-107`
- `golden_vector/serve/static/css/responsive.css:43-55`
- `tests/test_redesign_routes.py:314-331`

`.section-nav` is sticky at `top: 2.5rem` (40px). On narrow layouts the sticky app header contains a `min-height: 44px` menu button plus 20px vertical padding (16px below 480px), making the header about 60–64px high. The section nav therefore sticks 20–24px underneath the higher-z-index app header. There is also no `scroll-margin-top` or `scroll-padding-top` anywhere in the CSS, so clicking any `#section` link aligns its target behind both sticky layers.

**Concrete repro:** at a 390px viewport, open `/ticker/NEM`, scroll until “On this page” sticks, then activate `#corporate-finance` (the same occurs on Portfolio). The upper portion of the section nav is under the app header, and the target heading is aligned behind the sticky header/nav rather than visibly below them.

The route test proves only that each `href` has a matching `id`; it never checks the resulting scroll position or visibility. The offset needs to follow the actual header height, and anchor targets need a corresponding scroll margin (or the sticky behavior should change at narrow widths).

### GV-RD-FINAL-004 — MEDIUM — the recorded browser release gate is materially smaller than the blueprint matrix

**Files/evidence:**

- `GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md:1244-1278`
- `reviews/codex/milestones/visual_redesign/browser_evidence_phase6.json`
- `reviews/codex/milestones/visual_redesign/browser_evidence_phase8_matrix.json`
- `reviews/codex/milestones/visual_redesign/handoff.md:23-26, 35-49`

Section 18.3 requires 1,440, 1,280, 1,024, 768, and 390px for the full matrix; a 320px stress pass; representative 400/403/404/503 states; 200% on every route plus a representative 400% pass; and recorded focus, touch-target, chart keyboard/touch, back/forward, malformed-HTML, and action-reachability checks. The committed Phase 6 evidence records only 11 routes × four **unnamed** widths plus a few spot checks. The only redesign evidence that enumerates its widths uses 400/768/1024/1440, not the required five, and there is no final 320px or 400% result. Phase 8 reduces the result further to aggregate fields such as `"overflow_px_all_routes": 0` without route/width measurements and does not record the required error-state or interaction matrix.

This is not asking for a full Python suite. It is the presentation milestone's own browser gate, and the missing checks include the two real interaction defects above. After fixes, one consolidated scripted browser pass should record the actual route × viewport results and the required accessibility interactions.

### GV-RD-FINAL-005 — LOW — D9 still gives no already-running message through the main `/refresh` workflow

**Files:**

- `golden_vector/serve/workspace.py:281-297, 332-334, 472-489`
- `golden_vector/serve/candidate_finder_page.py:125-154`
- `tests/test_redesign_routes.py:397-423`
- `reviews/codex/milestones/visual_redesign/defect_register.md:98-107, 144`

The POST handler covers both `/refresh` and `/option-trading/refresh` and appends `refresh=already-running` to either redirect. Only the Option Trading GET route consumes that flag. Candidate Finder consumes `saved` and `error_message`, but never `refresh`, so the primary “Refresh all model data” control still silently returns to the screen.

**Concrete fixture repro:**

```text
POST /refresh with start_options_refresh(...already_running=True)
=> 303 /?refresh=already-running
GET /?refresh=already-running
=> 200, message absent, notice-info absent
```

The regression test exercises only `/option-trading/refresh`, despite the register naming `POST /refresh`. Either both landing surfaces must render the signal, or the defect/resolution contract must be narrowed honestly.

### GV-RD-FINAL-006 — LOW — several defect tests are weaker than the contracts recorded in the register

**Files:**

- `tests/test_redesign_routes.py:337-376`
- `tests/test_tool_d.py:686-694`
- `reviews/codex/milestones/visual_redesign/defect_register.md:21-30, 54-63, 76-85`

Three examples are concrete pass-by-accident risks:

1. D2 says to prove an all-blank POST does not change manual-store content/mtime, but the test checks only redirect text and the next page's notice. A no-op-looking path that still touches the store would pass.
2. D5 requires an unknown ticker under a **stale option schema** to return 404 before loading options. The test uses an artifact-free fixture. If load ordering regressed but the empty loader remained tolerant, the intended stale-schema ordering contract would still not be tested.
3. D7 tests `_yahoo_fallback_error()` in isolation. It would pass if `_render_tool_d_overview_page` stopped calling that helper or rendered a different/ambiguous notice. The register explicitly requested a failing-Yahoo route/render fixture.

The current implementations look consistent with D2/D5/D7; this finding is about making the regression tests prove the stated behavior rather than a convenient sub-piece.

### GV-RD-FINAL-007 — LOW — the `serve/ui` “purity” guard proves dependency isolation, not presentation purity

**Files:**

- `tests/test_ui_components.py:148-166`
- `tests/test_workspace_app.py:2981-3028`
- `golden_vector/serve/ui/README.md:6-16, 45-55`

The UI-package test only restricts import roots to `__future__`, `html`, and `re`. A new function such as `return sum(rows) / len(rows)` or state/fallback selection using built-ins requires no import and passes. The global serve scan is a short string list (`.fillna`, `.corr`, `.std`, etc.); ordinary arithmetic, `sum`, sorting/ranking, and `or`-based fallback resolution also pass.

The current `serve/ui` package is pure on manual inspection, so this is not an active analytics leak. The test/README claim is nevertheless stronger than the enforcement. Strengthen the guard or narrow its documented guarantee to “stdlib dependency isolation,” with presentation purity retained as a review rule.

### GV-RD-FINAL-008 — LOW — Phase 7 left a legacy `table-scroll` consumer, and the dead-CSS guard cannot detect that direction of drift

**Files:**

- `golden_vector/serve/candidate_finder_page.py:531-550`
- `tests/test_design_tokens.py:152-201`
- `reviews/codex/milestones/visual_redesign/handoff.md:27-28`

Candidate Finder still emits `<div class="table-scroll">`, but no first-party CSS rule for `.table-scroll` exists. The handoff says `table-scroll` was removed. The dead-selector test scans CSS classes and asks whether each name appears anywhere in concatenated Python/JS; it never scans emitted markup classes in the opposite direction to find classes with no style/behavior owner. It also uses raw substring membership, so a class name in a comment, docstring, function name, or unrelated longer token counts as an emitter.

**Concrete repro:** `rg -n 'table-scroll' golden_vector/serve` finds the Candidate Finder markup and comments, but no selector. Remove/replace the stale wrapper or explicitly document it as an unstyled structural hook, and make the guard's claim match what it checks.

### GV-RD-FINAL-009 — LOW — the overflow ownership test has two simple bypasses

**File:** `tests/test_design_tokens.py:137-149`

The guard accepts an entire selector block whenever the selector text contains `.table-region`. Therefore this illegal rule passes:

```css
.table-region, .anonymous-panel { overflow-x: auto; }
```

It also checks only `overflow-x: auto|scroll`, so `.anonymous-panel { overflow: auto; }` creates horizontal scrolling without detection. Current first-party CSS has no such offender, and the final panel containment fallback is safe. To enforce the ownership claim, parse each comma-separated selector arm and cover overflow shorthand that enables horizontal scrolling.

### GV-RD-FINAL-010 — LOW — the DataTable structure guard does not cover every route/state it claims

**Files:**

- `tests/test_redesign_routes.py:465-533`
- `golden_vector/serve/overview_tool_c.py:119-134`

`_GUARD_FULL_ROUTES` omits `/tool-c`, even though Tool C renders `class="js-datatable"`, and also omits the scorecard, Lab drilldown, non-default ticker lens, and alternate/empty states. The parser is run only against one fixture state per listed route; there is no static inventory tying every `js-datatable` emitter to a covered render. For example, removing the Tool C table id or nesting a table there would leave `test_js_datatables_have_ids_and_no_nested_tables` green.

D11 itself is correctly fixed in the current Portfolio markup and has real-browser zero-alert evidence. The guard should either cover a complete emitter/route inventory or be described as a representative-route guard rather than “every js-datatable.”

### GV-RD-FINAL-011 — LOW — the contrast guard is a curated sample, not an app-wide contrast guarantee

**File:** `tests/test_workspace_shell.py:300-383`

The tests correctly calculate WCAG ratios, resolve token aliases, and check the listed token pairs plus seven concrete control states. They do not discover foreground/background pairs from the full CSS or rendered routes. A newly emitted control using a poor pair can pass all contrast tests as long as it is not added to the hard-coded `pairs`/`checks` lists; opacity, inherited backgrounds, and overlay/cascade combinations are also outside the test.

I found no failing current pair among the audited controls. The finding is that the handoff's “WCAG contrast enforced” wording is broader than the regression guard. Maintain an explicit complete inventory of text-bearing component states (including notices, badges, buttons, help, tooltips, and disabled states), or narrow the evidence claim and retain browser-level contrast review.

### GV-RD-FINAL-012 — LOW — Portfolio's section navigation does not implement the blueprint's subsection map

**Files:**

- `GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md:825-837`
- `golden_vector/serve/portfolio_page.py:62-84, 189-220, 537-570`

Section 15.7 asks for distinct navigation to Composition, Gold-beta exposure, Currency, Hedge sizing, Correlations, History, Reconciliation, Positions, and Lot management. The implementation adds Summary/Data issues, collapses Gold-beta exposure and Currency into one `#composition` target (their `<div><h3>` blocks have no ids), and labels `#lots` as “Add lots.” That target reaches only the Add Position Lot section; the following Edit Lots section has no id or shared Position/Lot-management wrapper.

All forms remain reachable by scrolling, so this is not a form-contract regression. It is an incomplete Phase 5 navigation deliverable. Either add the planned subsection anchors/management region or record and approve the reduced navigation as an intentional blueprint change.

## Checks that passed this review

- `dev-vic` and `origin/dev-vic` both point to `86351ff`; the only working-tree item is the pre-existing untracked `naukri.md`, which was not touched.
- There is one worktree and no other branch unmerged into `origin/main`; `dev-vic` is 28 commits ahead and 0 behind.
- Changed production code is confined to `golden_vector/serve/**`; other changes are tests/review evidence/planning/config docs. No data spine, analytics, schema, manifest, or artifact writer changed.
- Current `golden_vector/serve/ui/` implementations are presentation primitives and import only the allowed stdlib modules.
- Section 10.5 tone call sites reviewed in Phases 5–8 map existing statuses/messages; no new threshold or state inference was introduced by `serve/ui`.
- The final `tables.css` panel/two-column containment rule cannot clip or trap content; horizontal scrolling remains on `.table-region` in the current CSS.
- The in-memory final contract extractor had the same route counts and differed from `contracts_after_phase7.json` only on the two Portfolio pages, where D11 intentionally adds `portfolio-positions-table` (plus already-documented fixture UUID/timestamp nondeterminism). No unrelated final form/table/nav delta appeared in that extractor.
- D3, D4, D6, D8, D10, and D11 match their intended current behavior on code review; D2, D5, and D7 look correct but need the stronger regressions in FINAL-006.
- No full suite was run. The recorded `845 passed` focused selection is sufficient once the findings above are corrected and the affected focused/browser checks are rerun.

## Recommended fix/review order

1. Fix FINAL-001, FINAL-002, and FINAL-003 first; they are real user-visible contract/accessibility defects.
2. Rerun the consolidated browser matrix and replace the aggregate evidence (FINAL-004).
3. Resolve D9's main-route gap and the Phase 5/7 cleanup findings.
4. Harden the guardrails/tests without expanding into analytics work.
5. Have Codex perform a short affected-files re-review; do not rerun the unrelated full repository suite unless a fix crosses the plan's Section 18.6 trigger boundary.
