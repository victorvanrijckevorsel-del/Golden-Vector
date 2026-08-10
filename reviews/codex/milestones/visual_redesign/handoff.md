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
- **A11y/responsive**: 0px body overflow on 11 routes × 4 widths + 200% zoom;
  clamped popover/rug/crosshair (pointer events add touch); dashed benchmark
  strokes (no colour-only charts); forced-colors + reduced-motion + long-content
  handling; WCAG contrast enforced by token AND selector-level tests.
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

- **Defect register D1–D11** (pre-existing, characterized, NOT yet fixed):
  next step is separate labelled behavioural commits — D1 (ticker POST
  validation 500s with real data) and D11 (Portfolio DataTables alert) are the
  HIGHs. D11 still fires in the matrix, as expected.
- Keyboard access to chart hover detail: documented accepted gap (Phase 6
  evidence) — tables carry the numbers; pointer events cover touch.
- Benchmark-ETF vehicle detail variant is exercised by flag logic + live
  matrix, not a dedicated fixture route test.
- `--flash-*` token NAMES survive (values used by notice-danger); cosmetic
  rename left to avoid churn.

## Merge protocol

Not merged. Sequence: defect follow-up commits → independent final review
(fix highs/mediums) → Victor's approval → `dev-vic` → `main` via the standard
workflow. Branch audit: only `dev-vic` exists, one worktree, no overlapping
unmerged work to reconcile.
