# Ticker-page redesign — M3 complete: handoff for Codex review

**Date:** 2026-08-12 · **Author:** Claude (orchestrator: Fable; lane workers: Opus/Sonnet)
**Branch:** `dev-vic`, 9 commits ahead of `origin/dev-vic` at write time (pushed together with this file)
**Range:** `082385c..a793bf0` — 51 files, +24,499 / −3,487
**Plan:** `reviews/codex/claude_ticker_page_plan.md` (v3 + §15/§16) · **Requirements:** `claude_ticker_page_requirements.md` (locked, incl. addendum)

## 1. What shipped (all M3 lanes complete)

| Commit | Lane | Content |
|---|---|---|
| `082385c` | M3b | `serve/ticker_page/corporate.py` (headline cards + closed disclosures from gold_response/percentiles), global gold dial + `static/gold-dial.js`, `serve/embed.py` safe JSON embedding, page reordered to the locked six-section order, composites (`fundamental_check_*`, `screening_verdict`) off the page, POST error re-render carries the new sections |
| `e6da4e4` | JS | `static/score-builder.js` + `static/option-sizing.js`, 3-layer parity lock (Python mirror ↔ machine-verified fixtures ↔ real JS through node), 29/30 seeded mutations caught |
| `3752479` | M3c | `serve/ticker_page/behaviour.py` (beta bars + rugs moved as-is, Tool C record with evidence wording, windows table on the window_fit schema, explanation cards betas-only, volatility from persisted fields), Lab disclosure reusing the `/lab` renderers (8w ticker default, `/lab` keeps 13w — D-5), `detail_panels.py` 2379→1050 lines, `np.polyfit` request-path recompute deleted + its token-sweep exception removed |
| `9d8bc99` | M3d | `serve/ticker_page/options.py`: five-state availability matrix (only a CURRENT artifact's NONE_LISTED hides the section; misaligned resolved first), both P/C ratios with the disagreement sentence, OI trend with PARTIAL-capture gaps, target-window contract tables (real expiry + DTE per row), new sizing tool wired to the frozen JS contract (quote_ok/reason from persisted fields; carried-forward degrades every quote), greeks disclosure, gold-scenario sizing table REMOVED from this page (rejected Q40 device), legacy URL params still prefill. Recovered after a Windows restart orphaned the worker; every batch re-verified |
| `015d4ce` | producer | `fundamental_check_fail_codes` (+`_official`) persisted from `compute_fundamental_checks` — machine-readable, deliberately optional (pre-existing artifacts keep validating) |
| `770dfb9` | M3e | `serve/ticker_page/compare.py`: frozen score-builder payload + DOM contract from persisted percentiles only, opt-in result region, H2 "at spot" label, `#compare` mounted + nav |
| `3c66a19` | perf | Bounded generation cache on `load_ticker_page_data` keyed on the model-state pointer stat (plan §5.4 identity; closes Codex 2026-08-12 P2 "four independent full-universe reads") |
| `639dde0` | M3f | Forward-P/E failing sentence (screening basis named), scatter window sample + fit line from published `structural_window_metrics` coefficients, percentile rounding to 0.1 at the producer persist boundary (§12), explainer audit (31 new + 26 unwired help entries fixed + unknown-key guardrail), page-wide removed-string sweep (caught a live "Gold Sensitivity Score" reference in help text) |
| `a793bf0` | review fixes | All 26 adversarially-verified findings from the bundled review round (see §3) + the performance chart's accessible data-table twin |

## 2. Verification

- **Per-lane targeted suites** (each lane's exit gate, all green at its commit): M3b 126 · M3c 209+144 lab+157 blast · M3d 217+123 · M3e 197 · M3f 359 · review fixes 404. ruff clean at every commit.
- **JS behaviour:** `tests/test_ticker_page_js_parity.py` (23) executes the REAL modules through node against machine-verified fixtures; mutation checks on both the modules (29/30) and the review fixes (10/10 reverts caught).
- **Full suite (serial, once, after the final commit):** RESULT RECORDED IN §7 below.
- **Real-tree render smoke:** performed per lane; every section shows its honest degraded/PENDING state (see §5).
- **Browser gate:** batched Playwright pass over (a) a fixture harness driving the three real JS modules (selector coverage 37/37) and (b) the real page structure smoke — evidence recorded in §7.

## 3. Bundled review round (structure Codex may want to replicate)

43 agents: diverse-lens reviewers (integration seams, serve purity, basis truthfulness, moved-code seams, test honesty) + one adversarial verifier per finding, default-refute. **26 of 38 raw findings survived; zero HIGH.** Representative confirmed findings, all fixed in `a793bf0`:

- Serve had re-implemented the backend's forward-P/E `<= 0` rule and could fabricate a claim from a missing value (unreachable on real artifacts, but a canon breach + a vacuous test) → the producer now persists `FORWARD_PE_NON_POSITIVE_EARNINGS` vs `FORWARD_PE_FAIL` and serve routes codes with zero comparisons.
- `app_config=None` hardwired at help icons suppressed the config-resolved threshold text while a hardcoded "−10%" twin rendered — two contradictory definitions of one statistic possible on one page → threaded through; both twins deleted; config is the single statement.
- The restored scatter fit line ignored the persisted `window_status` → suppressed for non-eligible windows with the status named.
- Several new tests could not fail (single-row newest-wins fixture, non-repeating tie pool, aria-label matched instead of the help icon) → all replaced with tests proven to fail on revert.

## 4. Architecture notes for the re-review

- **Serve purity:** all analytics live in persisted artifacts; the ONLY client-side computation is the three sanctioned modules (D-1/D-2), each parity-locked. Token sweeps cover every `serve/ticker_page/` module; the AST guardrail bans arithmetic; note it does NOT yet ban `ast.Compare` judgments — the one Compare that slipped in was caught by review, and extending the guardrail is a cheap follow-up.
- **Basis discipline:** spot vs scenario labelled everywhere the dial moves; failing sentences name the screening basis (`$/oz as of date`) distinctly from the spot cards; our/yahoo resolution happens in the model layer (`OPTIONAL_YAHOO_FINANCE_SOURCE_COLUMN_MAP` — tolerant, clears rather than leaks Our-View values under a Yahoo heading).
- **Availability truthfulness:** "no options" is claimable only by a current artifact's NONE_LISTED; every other unhappy path renders a reasoned degraded state (incl. `awaiting first v4 refresh` pre-v4).
- **Generation cache:** identity = model-state pointer stat only, correct because loaders are manifest-first and standalone alias refreshes deliberately do not serve.

## 5. Known state / not done here

1. **The real refresh at this pin has NOT run** — the manifest still names the pre-redesign generation, so all five ticker artifacts load as PENDING_FIRST_PUBLISH and sections render honest pending/degraded states. Victor's 19:30 scheduled task (inside US market hours for option v4) is the intended run. Until then the browser gate exercises structure + JS behaviour, not real numbers.
2. **Payload budget re-measure on real data** waits for that refresh. Fixture-shape measurement: compare payload 97 KB at 60 tickers × 19 metrics (the largest embed), within the ≤300 KB budget; producer-side percentile rounding (`639dde0`) roughly halves it at the next publish. §12 rules hold (no raw Lab episodes embedded — verified by test).
3. **Deferred, recorded in plan §16 (Victor-approved):** C10 atomic ticker-generation pointer, C12/C13 option-domain guards, C8 validator framework, layer1 MISSING_SUSTAINING_CAPEX gate decision.
4. **New follow-ups from this run:** `gold_response` v2 could add `spot_{line_metric}` columns so the earnings-table spot column server-renders (today the sanctioned JS evaluates it at g=spot; recorded in M3b notes); extend the serve AST guardrail to Compare nodes; ~35 low-severity `<th>` help gaps (lane notes); consolidate the three JS modules' formatters into one shared file (all three are parity-locked individually, so this is cosmetic); Codex stable-app review Gates A–C (`claude_stable_app_performance_responsiveness_review_2026-08-12.md`) — explicitly scheduled after this project reaches its stable boundary.
5. **`.scratch/` in the repo root** is an agent-created leftover (permission-locked, untracked) — delete when unlocked. `naukri.md` is Victor's file, untouched.

## 6. Acceptance path from here

1. Victor's real refresh publishes the five-artifact generation (his scheduled task).
2. Victor looks at `/ticker/<T>` with real data.
3. Codex re-review (this file + the range `082385c..a793bf0`).
4. Merge workflow to `main` per CLAUDE.md (only after 1–3).

## 7. Final gate results

**Full suite (serial, one run at `a793bf0`):** `2,158 passed, 6 failed in 664s`. All six
failures were gate catches OUTSIDE the lane blast-radius lists, fixed in the follow-up
commit: `--ink-soft` used with raw-colour fallbacks but never defined in tokens.css (now a
token alias, fallbacks stripped); eight dead option-panel CSS selectors left by the M3d
markup deletion (removed); three route-level tests pinning the REMOVED crosshair overlay
chart (deleted with a note — the new performance chart's table twin is asserted
cell-by-cell at render level; a route-level twin check needs a published generation and
belongs to the post-refresh gate). Both files + the CSS-reading shell/UI suites re-run
green; ruff clean.

**Browser gate — JS harness (real modules, real events, file-served):** full pass, zero
console errors:
`dial: initialClean, spotCellsFilled, scenarioRevealed, spotUnmoved, scenarioValuePresent,
resetClean, ariaLiveSpoke — all true · score: optInPromptFirst, scoreShown, rankShown,
rankedListPopulated, urlCarriesSb, directionFlips, weightsSumTo100 — all true · sizing:
"11 contracts · $935.00 premium · break-even $11.15" (matches floor(1000/(ask×100)) and
strike−ask exactly), ladder rendered, crossed-quote contract disabled with its persisted
reason.` Harness + driver at `.playwright-mcp/m4_harness/` (selector coverage 37/37).

**Browser gate — real page:** `/ticker/NEM` returns a **calm 503** ("Golden Vector
Workspace Error", no traceback, global nav intact) — the designed fail-loud posture while
the manifest names the pre-C1-rename Tool B generation. Real-page structure/interaction
verification on live data is the explicit post-refresh step (§6.1) and repeats the harness
checklist plus payload budgets there.
