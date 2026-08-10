# Visual redesign — milestone handoff (2026-08-10)

Branch `dev-vic`, base `6c5015d`, head at Phase 8. 18 presentation/test/docs
commits; two interim Codex reviews fully resolved (GV-RD-CX-001…7,
GV-RD-P34-1…6 — resolutions in `defect_register.md`).

## What shipped (Phases 0–8)

- **Foundations**: dark §9.2 token palette (sole raw-colour file), CSS module
  manifest, semantic SVG series classes, z-index scale, system fonts.
- **Shell**: grouped sidebar (Discover/Analyse/Manage/Research), skip link,
  landmarks, modal drawer (inert background, close control, focus trap,
  breakpoint reset), `html.js` progressive enhancement — full no-JS navigation.
- **Component system** (`serve/ui/`, ownership in `ui/README.md`): page header,
  §10.5 notices (tone tests at call sites), status strip, section heading/nav
  (sticky anchors on ticker detail + Portfolio), toolbar, empty state,
  disclosure, buttons, and the labelled keyboard-focusable `table_region` —
  the ONLY horizontal-scroll owner (guardrail-enforced), with JS-conditional
  tab stops.
- **Every route migrated**: CF, Tools A–D, Option Trading, Portfolio, Lab
  (overview + drilldown), Scorecard, ticker detail (+forms). Header `scope`
  contract everywhere incl. the correlation matrix.
- **A11y/responsive**: consolidated release matrix (browser_evidence_final_matrix.json):
  0px overflow on 11 routes × 7 named widths 1440/1280/1024/768/640/390/320
  (640 == 200% zoom, 320 == 400% zoom by WCAG reflow equivalence), 0 alerts,
  error states + anchor visibility + 24px tap targets + skip-link first focus
  + back/forward all recorded;
  clamped popover/rug/crosshair; chart hover data ALSO rendered as collapsed
  keyboard-accessible data tables (GV-RD-FINAL-002 remedy — pointer events alone
  are not an operable touch/keyboard path); dashed benchmark strokes (no
  colour-only charts); forced-colors + reduced-motion + long-content handling;
  contrast: token pairs + curated control states + a self-maintaining scan that
  fails on ANY new self-colored selector below AA (inherited/composited
  combinations stay browser-gate territory, not statically claimed).
- **Legacy removed**: bare `.flash`, dead selectors (incl. `segmented-control`),
  `table-scroll`; dead-selector scan with documented dynamic allowlist.

## Verification evidence (this directory)

`browser_evidence_codex_fixes.json`, `browser_evidence_pilots.json` (+
`pilot_contract_diff.md`, `pilot_self_review.md`), `browser_evidence_p34_fixes.json`,
`browser_evidence_phase6.json`, `browser_evidence_phase8_matrix.json`,
`contracts_after_phase3/7.json`, before/after screenshots (no Portfolio content).
Key facts: contract diffs fully explained (classes/tone vocabulary only, flash
text byte-identical, active-nav booleans preserved); GET rendering wrote 0 of
18,253 artifact files in three separate proofs; zero external hosts; zero
console errors; ticker detail warm load 2.68s vs 3.3–3.8s baseline.

## Test scope and why it is sufficient

1,632 tests collect repo-wide (0 errors; +77 redesign additions). The pinned
release selection (`tests/tools/run_focused_selection.py`, 49 files) covers
every suite importing `golden_vector.serve` plus route-adjacent model-state/
URL/Portfolio/CLI suites plus the redesign guardrails — the full blast radius
of a presentation-only change. No §18.6 full-suite trigger applies: the diff
contains no analytics, pipeline, loader, schema, contract, manifest, artifact,
or shared-data change (boundary proof in the matrix evidence).

## Known limitations / open items

- **Defect register D1–D11: ALL RESOLVED** in labelled follow-up commits (see
  the register's resolution log). D11's zero-alert proof:
  browser_evidence_d11_fix.json + 0 alerts across the final matrix's 77 loads;
  D1's context-preservation half completed under GV-RD-FINAL-001 (ed756a9).
- Keyboard access to chart hover detail: CLOSED by GV-RD-FINAL-002 — every
  pointer-revealed chart value (overlay crosshair, rug ticks) is also rendered
  as a collapsed "Chart data (table)" disclosure in a labelled region,
  equivalence pinned by tests/test_chart_data_tables.py (table rows ==
  embedded payload entries).
- Benchmark-ETF vehicle detail variant is exercised by flag logic + live
  matrix, not a dedicated fixture route test.
- `--flash-*` token NAMES survive (values used by notice-danger); cosmetic
  rename left to avoid churn.

## Merge protocol

Not merged. Sequence: defect follow-up commits → independent final review
(fix highs/mediums) → Victor's approval → `dev-vic` → `main` via the standard
workflow. Branch audit: only `dev-vic` exists, one worktree, no overlapping
unmerged work to reconcile.
