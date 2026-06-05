# Review — Merged Infrastructure Remediation Plan

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** `reviews/codex/codex_merged_infrastructure_remediation_plan.md`
**Date:** 2026-06-05
**Grade: APPROVE WITH REFINEMENTS.** The plan correctly merges both reviews, sequences risk well (observability → atomicity → data center → resilience → cleanup), and its judgment about what NOT to do is exactly right. Five refinements below make it stronger — the first reframes I1+I2 into one robust mechanism and is the most important.

## PRODUCT DECISION (locked by Emanuel — build to this)
**There is ONE refresh button that rebuilds ALL data in a single coherent pass. No separate "options-only" vs "full model" buttons in the UI.** Rationale: this tool is for daily (not intraday) use, so a slower once-a-day full refresh is perfectly acceptable, and a single action removes all user confusion about "did I refresh the right thing."

This is not just a UX choice — it is the cleanest version of the whole remediation:
- **It eliminates the mixed/partial-refresh problem by construction.** If the only action is "rebuild everything," there is no way to produce a fresh-options-vs-stale-betas state. The entire alignment/mixed-refresh reconciliation layer stops being needed as a runtime mechanism — it becomes, at most, a guard against a *failed* build.
- **It makes I2 (one parent refresh id + atomic publish) the natural design, not a retrofit.** One button = one refresh = one parent id = one atomic swap at the end. Your product instinct and the engineering best practice are the same thing.

Requirements for the one button:
1. **Runs the full pipeline** in order: update-data (equities, FX, gold, market snapshots) → options → Tool A → Tool B → Tool C → Tool D → option/candidate artifacts.
2. **Background + visible progress** (it is minutes, not seconds — show the current stage, e.g. "fetching option chains… computing Tool C…", so a long refresh is never a mystery).
3. **All-or-nothing publish:** if any stage fails, leave the previous complete build fully intact (yesterday's good data), and surface a clear "last build failed — showing previous build" state. (Per-ticker/per-chain failures within a stage stay isolated and recorded as today — all-or-nothing applies at the stage/build level, not to individual tickers.)
4. **Keep the granular commands** (`update-data --options`, `tool-a/b/c/d`, `refresh --skip-tool-b`) **as developer CLI only** — useful for building/debugging, but NOT exposed as separate UI buttons. One button for the product, full toolkit underneath.

**What this changes in the plan:** Phase 4's "split market-refresh vs full-model-refresh" UX work is **removed** — replace it with the single button + progress + the honest "complete / failed / building" state. Phase 1's manifest simplifies to "last successful full-build id/time + complete-or-failed." Phase 2 becomes the primary mechanism behind the one button. Everything else (I3 options data center, I4 resilience, I5 cleanup) is unchanged — note that the one button does NOT by itself fix page-load speed; the I3 compute-at-refresh artifacts are still required so pages read fast after the build.

## What's excellent (endorse as-is)
- **Right diagnosis, right order.** "Don't rewrite the math; build the data center" matches both reviews. Doing observability (I1) before the higher-risk publish path (I2) before the big refactor (I3) is the correct risk gradient.
- **The "What Not To Do Yet" section is the best part of the plan** — no scheduler, no second vendor, no more request caches as the speed fix, no rule-tuning while moving layers, no math rewrite. That restraint is exactly what keeps this from sprawling.
- **Strong risk-controls inside phases:** preserve standalone `tool-a/b/c/d` commands, dry-run retention by default, "move computation first, tune rules separately." Mature.
- **The first brief (I1) is correctly narrow** with good test coverage (complete / missing C/D / stale A/B vs fresh options / legacy fallback). Ship that scope as written.

## Refinements

### R1 (most important) — Make the current-state manifest the single atomic *pointer*, so I1 and I2 become one mechanism (not two with rework)
The plan does I1 (manifest) then I2 (atomic publish) as separate phases, and I2 plans to "swap all latest aliases together using `os.replace()`." Two problems:
- **Swapping N separate `*_latest.parquet` aliases is NOT actually atomic.** `os.replace` is atomic per-file, but N of them in sequence leaves a window where Tool A is new and Tool B is still old — the exact torn state I2 is trying to prevent. True all-or-nothing requires switching **one** thing.
- **I1's manifest, if built on the current 4-separate-id reconstruction, gets reworked by I2** when the parent id arrives.

**Both dissolve if the manifest IS the atomic switch.** Design it so:
- Each stage writes its output as an **immutable, run-id-named file** (already the retained-output convention).
- The current-state manifest names the coherent set: `{parent_refresh_id, foundation: <path+hash>, tool_a: <path+hash>, ...}`.
- **Readers resolve their inputs *through* the manifest**, not via the mutable `*_latest.parquet` aliases.
- Publishing = write all per-run files, then **`os.replace()` the single manifest**. That is genuinely atomic: a reader sees either the old complete manifest or the new one, never a mix.

So: build I1's manifest **already shaped as the pointer**, with `parent_refresh_id` present (nullable until I2 fills it) and an extensible artifact map (so I3's option/finder artifacts slot in without reshaping). This makes I2 "populate the parent id + flip reads to go through the manifest" instead of "invent a separate atomic-swap scheme," and it removes the rework risk. The `*_latest.parquet` aliases can stay as convenience copies but stop being the authoritative read path.

### R2 (gap) — Carry the Tool D spot-vs-scenario alias split as an explicit *correctness* fix, not just status reporting
The plan only mentions Tool D spot/scenario in Phase 7 *status reporting*. But there's a real correctness fix missing: today a scenario `tool-d --gold-price X` run overwrites the same `tool_d_latest.parquet` the Candidate Finder consumes, so an exploratory run silently disables the Finder's Tool D criterion (this is finding C1 from the Tool C/D audit). Note `paths.py:256-262` **already defines `latest_tool_d_spot_snapshot_parquet_path`** — the alias exists but isn't wired. Make it explicit, in **I2 (publish discipline)**:
- Tool D writes the **spot** run to the spot alias; the Finder reads the **spot** alias; a `--gold-price` scenario run publishes only to scenario/retained outputs and **never touches the spot alias.**
- Add an acceptance test: a scenario run leaves the Finder-consumed spot artifact unchanged.

### R3 (cross-track dependency) — The Tool C/D *correctness* fixes must land before Phase 0's "rely on the Finder"
This infra plan is correctly scoped to infrastructure, but Phase 0 says "run a full refresh so Tool A/B/C/D align, then rely on UI output." If you rebuild the estate while the Tool C/D audit's must-fixes are still open, you get a **freshly-built but still-wrong Finder**:
- the preset eligibility regression (Tool C/D added to the two presets → tickers silently dropped / scoring shifted — audit K1/H1), and
- the Tool C `KeyError` crash when Tool A is absent (audit H2).

These live in `claude_review_tool_c_d_full_audit.md` / `claude_vs_codex_tool_c_d_review_merge.md`, not in this plan. **Reconcile the two tracks:** either fold "apply the Tool C/D must-fixes" into Phase 0 as a prerequisite, or state explicitly that Phase 0 means "data is built" not "Finder output is trustworthy yet." Don't let the infra rebuild imply the Finder is correct when the audit fixes are still pending.

### R4 (preserve a contract through the refactor) — the persisted option-candidate artifact must retain `liquidity_tier`
When I3 moves candidate selection to a persisted artifact, the **strict "usable = tradable" contract** (option-redesign F1 / Tool C/D L1) must survive: the Finder's `_has_usable_slots` filters on `tier == "tradable"`, so the persisted artifact has to carry each slot's `liquidity_tier` (and tradable/watch status), and the Finder must keep filtering on it. Add an acceptance line: "moving candidates to artifacts does not change which tickers count as having a usable put/call (regression test vs current behavior)." Otherwise centralization could silently widen "usable."

### R5 (test rigor for the risky phase) — I2 needs explicit fault-injection tests
Phase 2's acceptance ("a forced failure after Tool B does not publish a half-new state") should be a **deliberate fault-injection test**: simulate a Tool C failure mid-refresh and assert the previous manifest/state is fully intact and readers still see the old coherent world. This is the one phase where a subtle bug corrupts user-visible state, so the test must inject the failure, not just assert the happy path. (Windows note: single-file `os.replace` is atomic on the same volume — which is another reason R1's single-manifest switch is the safe design versus multi-file swaps.)

## Smaller notes
- **Sequencing of I4 (resilience) is fine after I3**, but pull **timing diagnostics** (Phase 4/5) *earlier* — even a crude per-stage timer in I1 would immediately answer "is the slowness Yahoo, options, or model?" while you build the rest. Low cost, high diagnostic value now.
- **Schema contracts (Phase 6):** when you add them, version them (`schema_version` stamped in the artifact) so the loud-failure check can also handle deliberate migrations gracefully.
- **Endorse the milestone split (I1–I5)** — it's the right granularity for review-per-milestone.

## Bottom line
This is a well-judged plan — accurate, sequenced, and admirably disciplined about scope. Approve it. The one change worth making before building is **R1: design the current-state manifest as the single atomic pointer readers resolve through**, which merges I1+I2 into one robust, genuinely-atomic mechanism and avoids rework. Then carry the **Tool D spot-alias split (R2)** and **preserve the tradable-tier contract (R4)** as explicit acceptance items, reconcile the **Tool C/D correctness fixes as a Phase-0 prerequisite (R3)**, and make **I2 fault-injection-tested (R5)**. With those, the I1 first brief is ready to build exactly as scoped.
