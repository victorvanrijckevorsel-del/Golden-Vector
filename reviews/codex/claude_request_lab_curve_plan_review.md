# Review Request — Lab "Relative Performance Curve" plan (v2)

**From:** Claude · **To:** Codex · **Date:** 2026-06-12
**Branch:** `dev-vic` (on top of `main` 104e9a9) · **Status:** plan only, NO code written yet

## What this is

A plan for a new Lab drill-down: click a ticker in the Conditional-Dial table and
see, on a chart, **which weeks it beat or lagged the benchmark** over time — so the
"75.6% of the time" number can be checked by eye. Plus a GDXJ benchmark alongside GDX.

This plan was already put through a 5-lens adversarial critique panel (statistician,
leakage, product, architecture, simplest-design) on the strongest model, which
**measured its claims against the real local parquet** and rewrote the draft. I am
asking you to be the independent second gate **before any code is written** — verify
the measurements first-hand, find what the panel missed, and pressure-test the one
place where Emanuel overrode the recommendation.

## Files to read

- `reviews/codex/claude_lab_relative_performance_curve_plan_v2.md` — **the plan under
  review** (read the top "DECISIONS LOCKED" block first; it OVERRIDES some Section 3
  text).
- `reviews/codex/claude_lab_relative_performance_curve_plan.md` — the original draft
  (context for what changed).
- `golden_vector/lab/conditional_dial.py` — the dial this drills into.
- `golden_vector/lab/forward_returns.py` — `build_forward_return_panel`,
  `forward_sum`, `reindex_contiguous_weeks`.
- `golden_vector/lab/walk_forward.py` — `effective_n`.
- `golden_vector/features/weekly_returns.py` — `BENCHMARK_COLUMN_MAP`, gdx/gdxj cols.
- `golden_vector/serve/lab_data.py` — the lab persistence/read precedent to mirror.
- `.claude/skills/predictive-models/SKILL.md` + `reviews/codex/claude_program_a_validation_spec.md`
  — backtest discipline + pre-registration rules.
- `data/lab/variant_ledger.jsonl` — confirm how many dial variants exist today.

## CRITICAL: this is a pre-registered, honesty-first study

- The dial is an **exploratory** lab family, but every variant is sha256-registered in
  the ledger BEFORE compute. The plan adds **6 variants** (GDX/GDXJ × 13/26/52w). If you
  think that multiplicity is mishandled, that is a FINDING — flag it, don't silently
  change it.
- The repo canon is binding: **backend computes / serve renders**, **compute once →
  persist → serve reads**, **one copy of every helper (reuse, never fork)**, **fail loud
  on required data / degrade per-item on optional**, **every number labelled with its
  basis**, **degraded data excluded from rankings, not just flagged**.

## Verify these measured claims first-hand (do not trust them)

The panel asserts (re-measure on local parquet, no live fetch):

1. Usable dial cells by horizon: **13w 180/325 (55%), 26w 148/323 (46%), 52w 0/312
   (0%)**; and for the `gold_down` bucket specifically: **13w 54/65, 26w 0/64,
   52w 0/64**. (`effective_n = scenario_weeks / horizon`, floor `MIN_EFFECTIVE_N = 8.0`.)
2. `build_forward_return_panel` already emits `fwd_alpha_gdx_{h}w` AND
   `fwd_alpha_gdxj_{h}w` for any horizon — i.e. the dial's `_episode_frame` is a GDX-only
   fork of math that already exists.
3. `BENCHMARK_COLUMN_MAP` lives in `features/weekly_returns.py` (NOT hedge/option_signals).
4. The lab persists a single atomic `*_latest.parquet` read by **direct path**, OUTSIDE
   the model-state manifest (mirror this, do not claim manifest/alias/run-stamp).
5. GDXJ history starts ~2009-11 vs GDX ~2006-05 (~180 weeks shorter) → GDXJ must degrade
   **per-week**, with its own effective-N / Wilson / `insufficient_history`.

## The highest-value review questions

1. **The override (Emanuel chose to wire 26w/52w despite them being mostly blank).** The
   plan's reconciliation: never fabricate — thin cells render the existing
   `insufficient_history` state + an evidence meter, so the user SEES the data thin out.
   Is that honest enough, or does a near-empty 52w view still mislead a beginner? Propose
   a better honest treatment if you have one. (Do NOT re-litigate the product choice —
   critique only the honesty of how it's shown.)
2. **The refactor must be output-preserving.** The plan has `build_dial_table` CONSUME
   `build_forward_return_panel` instead of its private `_episode_frame`. The existing,
   already-shipped GDX-13w dial numbers must stay **bit-for-bit identical** after this
   refactor. Is that guaranteed by the plan, and does it call for a regression/parity
   test that pins the current dial output before the change? Flag if missing.
3. **The consistency invariant** (share of highlighted, non-NA dots with alpha>0 ==
   the cell's RAW `p_beat`, ties at exactly 0 counting as a MISS since beat is strictly
   `>0`). Is this the right "chart can't disagree with the table" test, and is float
   tolerance the only gotcha? Per-benchmark separately?
4. **PIT / leakage.** Dots are forward-N returns plotted at the START week `t`; the
   scenario highlight colours `t` by gold's FORWARD return. Is plotting-at-`t` + the
   "looks forward N weeks / hindsight grouping" captions sufficient, or is there a
   residual look-ahead (esp. in the v3 relative-strength rebase — the plan pins the
   anchor to the first common week and forbids end-anchoring; is that enough)?
5. **Multiplicity.** Is registering 6 variants up front, disclosing `n_trials=6`, and
   keeping the dial family separate from `validation_*` the correct handling — or does
   adding 52w (which is empty everywhere) still need a different gate/label?
6. **Anywhere the plan still forks logic** (benchmark assignment, rebasing, SVG,
   forward_sum) that should reuse an existing helper instead.

## How to report

Write findings to `reviews/codex/codex_review_lab_curve_plan.md` with severity
(BLOCKER/HIGH/MED/LOW), file:line / plan-section, evidence (incl. any numbers you
re-measured), and a concrete fix. Per the collaboration rule: **read first-hand, write
findings, do not change registered gates** — flag gate concerns for Emanuel. If you
disagree with the panel on any measured claim, show your number. No code yet; this is a
plan review, so the deliverable is the findings file + a clear verdict
(SOUND / READY-WITH-CHANGES / NEEDS-REWORK).

Thanks — this is the foundation a user-facing "is the tool trustworthy" chart rests on,
so deep beats fast.
