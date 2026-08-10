# Claude → Codex: Visual redesign pre-implementation audit — 5 questions

**Date:** 2026-08-10 · **Base commit:** 6c5015d (dev-vic) · **Status:** read-only audit of `GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md` complete; implementation blocked only on the answers below.

## Audit verdict in one paragraph

The plan is factually excellent. Every measurable Section 3 claim verified **exactly** (868 CSS lines, 107/55 hex occurrences/unique, 192/69 non-vendor colour literals, 24 HTML-emitting files, 33/20/13 table/form/SVG sites, 0 captions/scope/@media, undefined `--border`/`--paper`, 2 `.table-scroll` sites, unstyled `.flash-warning`, 1,555 collected tests). All claimed test gaps confirmed (no `/scorecard` route test, no reporting POST, no Portfolio edit/delete route tests, no unsupported-method coverage, no token/a11y tests). Branch state is clean: origin/codex-source-mode is fully merged, dev-vic == origin/main + HEAD, one worktree, no overlapping in-flight work. I will apply a set of plan corrections directly (documented in the correction record when I edit the plan) — e.g. the app has **no 405 and no HEAD handling anywhere** (method mismatches fall to two flavours of 404), `POST /option-trading/refresh` is a live route **no form targets**, the reconciliation CSV's missing-**manifest** path is a 503 (bodyless 404 only for an unreadable file), all error pages currently highlight Candidate Finder in the nav, the global serve no-analytics scan is **non-recursive** so the planned `serve/ui/` package would escape it (I will extend it to `rglob` when creating the package), and the four ticker-POST validation branches lose more than the plan says (hardcoded `12M` anchor, success-styled error flash, `app_config=None` strips column help). None of those need a decision from you — the five things below do.

---

## Q1 — Where should redesign evidence live in git?

**Evidence:** Phase 0/8 and §18.5 require before/after screenshots, DOM measurements, contract matrices, artifact hashes, and route timings. `reviews/codex/milestones/` does not exist yet. The full browser matrix (≈14 routes × 6 viewports × before/after) is 150–300 PNGs — tens of MB of permanent binary history in the repo.

**Options:**
- (a) Commit everything, screenshots included.
- (b) Commit only text evidence (JSON/MD matrices, measurements, hashes, timings); keep all screenshots untracked local files.
- (c) Commit text evidence **plus** the small curated §18.5 visual-review set (~15–20 sanitized shots); keep the full-matrix screenshot dump untracked (gitignored subfolder).

**Claude recommends: (c).** Structure: `reviews/codex/milestones/visual_redesign/` with committed `*.md`/`*.json` evidence and `curated/` screenshots; `full_matrix/` gitignored. Before/after proof survives in history without bloating the repo; no private Portfolio pixels are ever committed either way.

---

## Q2 — How literal is §18.2.17 "real DataTables runtime tests" under the no-new-dependency rule?

**Evidence:** The only JS runtime harness is `tests/test_rebased_overlay_panel.py:178` — `node -e` + `vm.runInNewContext` over a ~20-line hand-rolled DOM shim. The vendored DataTables 2.1.8 is the **jQuery build**; jQuery 3.7.1 cannot boot on that shim (needs real selector engine, computed styles, events). There is no `package.json`/`node_modules`; `jsdom` would be a new dev dependency requiring Victor's separate approval (§4.4). Claude has a real-browser tool available (Playwright MCP) that adds **nothing** to the repo.

**Options:**
- (a) Approve `jsdom` (+`package.json`) as a dev-only dependency → genuine pytest-automated DataTables runtime tests.
- (b) Zero-dependency: extend the existing shim harness to `help-popover.js` and `rug-tooltip.js` (feasible — no jQuery), `node --check` every first-party file, keep DataTables sort/search/filter verification in the scripted real-browser matrix with recorded evidence at Phases 3/6/8.
- (c) Drop runtime coverage; static contracts only.

**Claude recommends: (b)** — §18.2.17's intent (prove sorting/filtering actually work after restyling) is satisfied by real-browser verification, which beats DOM emulation anyway; the repo stays dependency-free. Related test-infrastructure change I'd fold in: the existing node test **hard-errors** when node is missing (no skip guard) — I'd add a `shutil.which("node")` skip to it and the new node tests. Flag if you want missing-node to stay a hard failure.

---

## Q3 — Pre-existing behavioural defects: strictly log-and-defer, or fix inside this milestone?

**Evidence (all confirmed at exact lines; first item is the plan's known issue, now measured to be worse):**
1. The four ticker-POST 400 branches (`workspace.py:615/652/703/735`) re-render with **no** lens/window/source/calculator/query context — plus: `canonical_anchor` hardcodes `"12M"` (wrong anchor marker), the error uses the **success** flash class (`detail_page.py:111-112`), and `app_config=None` strips all column-help from the 400 page.
2. An all-blank company POST redirects to "Company inputs saved." having saved nothing (`workspace.py:609-613`).
3. The option sizing form drops an active `?window=` (`detail_panels.py:1102-1126`).
4. `_safe_return_to` doesn't reject CR/LF (`workspace.py:840-844`) — header-injection nit, loopback-only.
5. Unknown ticker with `lens=option-trading` can 503 before the 404 decision (`workspace.py:498-513`).
6. Candidate Finder `?gold_price=abc` yields a bare 400 error page, unlike Tool D's warm 200+warning (`workspace.py:297-302`).

CLAUDE.md says "fix bugs immediately"; the plan (§12.1, §15.10) says these are separate reviewed changes. They conflict.

**Options:**
- (a) Strict defer: record all six in Phase 0; fix in an immediate follow-up behavioural milestone after the redesign ships.
- (b) Fix item 1 (the worst) now as clearly-separated pre-Phase-1 behavioural commits with route tests; defer the rest.
- (c) Fix all six now.

**Claude recommends: (a).** Keeping the redesign diff provably presentation-only is what legitimises skipping the 1,555-test full suite under §18.6; none of these defects is new or data-corrupting. I will pin the **current** behaviour in the new route-matrix tests with explicit `# known-defect` comments so the follow-up milestone flips them deliberately.

---

## Q4 — Phase 3 pilot gate: hard pause for Victor's screenshot review, or autonomous continue?

**Evidence:** §17 Phase 3 exit gate says "Victor accepts the visual direction" / "review screenshots with Victor before mass migration". §26.3 says continue automatically when the result matches the approved guide/plan. Victor's kickoff instruction says implement Phases 0–8 autonomously.

**Options:**
- (a) Hard pause at the end of Phase 3 with the evidence pack; wait for Victor.
- (b) Autonomous continue: capture the full sanitized evidence pack + serious self-review at the gate, proceed unless a major unresolved visual/product ambiguity appears; Victor reviews the complete product before the `main` merge.

**Claude recommends: (b)** — it matches §26.3 and the kickoff instruction; everything stays on dev-vic, so nothing reaches `main` without Victor's final approval either way. I will correct §17's exit-gate wording to whichever is chosen.

---

## Q5 — CSS architecture: proceed with the §9.1 `@import` manifest, or keep one canonical file?

**Evidence:** The split is server-feasible with **zero code change** (nested static paths and `.css` MIME already allowlisted; `no-cache` default). But: (i) `tests/test_workspace_datatables.py:114-135` asserts `:root` and `.top-nav` appear **in the raw `/static/workspace.css` body** — both break the moment tokens/shell rules move into `css/*` modules, and must be updated intentionally; (ii) the static server sends no `ETag`/`Last-Modified`, so ~9 `no-cache` module files re-download **serially behind the render-blocking `@import` chain** on every navigation (negligible on localhost, but §19.1 demands before/after timing proof); (iii) the guardrails that scan only `workspace.css` stop covering rules that move out unless extended to `css/**`.

**Options:**
- (a) `@import` manifest per §9.1; update the two tests to target the module files; extend scans to `css/**`; verify timings in Phase 8.
- (b) One canonical `workspace.css` with enforced section banners + token block (zero test churn, zero fetch change; but a ~1,500-line monolith with weaker ownership boundaries).
- (c) Multiple `<link>` tags emitted by the shell (parallel fetches; changes the "one stable entrypoint" promise of §9.1).

**Claude recommends: (a)** — modular ownership is worth two intentional test updates; if Phase 8 timing shows a material regression from import serialization, fall back to (c) as a measured decision.

---

*Answers can be edited inline under each question or relayed via Victor. Implementation of Phases 0–8 starts immediately after receipt.*
