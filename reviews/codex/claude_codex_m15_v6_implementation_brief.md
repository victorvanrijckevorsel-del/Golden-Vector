# Codex Implementation Brief — M1.5 v6 (Hedge Readiness Completion)

**For:** Codex (implementation agent)
**From:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**The spec you implement:** `reviews/codex/claude_m15_v6_plan.md` — **this brief does not replace it.** Read v6 in full first. This brief tells you *how to work* (cadence, self-review, git), and the plan tells you *what to build* (steps, schemas, math, acceptance).

---

## 0. How to read this brief

Emanuel wants you to **build in batches, and self-review your own code between batches** — not race to the end and review once. Concretely:

> Code a batch of steps → **STOP** → review your own diff, run the full suite, fix everything you find → commit the fixes → only then start the next batch.

There are **4 batches**. You do a full self-review at the end of each. You **halt and wait for Emanuel** at the three checkpoints marked below.

Do **not** `git push` — Emanuel pushes. Do **not** amend/rebase/force-push. One commit per plan step, plus one "self-review fixes" commit per batch (see §4).

---

## 1. Before you touch anything

1. `git branch --show-current` → must be `dev-vic`.
2. `git status` → you will see **uncommitted changes** in 10 files. **This is expected.** Those are the M1 punch-list fixes (H1/H2/H3/M4) and their tests. Do not discard them — Step 0 commits them. (Full explanation: v6 §0.5.)
3. `python -m pytest -q` → record the baseline pass count. (At review time the 5 touched test files were 65/65 green; the full suite was 446 before these changes — confirm the current full number and write it down.)
4. Create `reviews/codex/codex_m15_v6_progress.md`. First line = baseline count + timestamp. Append one line per step and per self-review.
5. Re-read `reviews/codex/claude_m15_v6_plan.md` end to end. Re-read `reviews/codex/codex_review_claude_m15_v5_plan.md` and `reviews/codex/claude_self_review_m15_v5_plan_opus48.md` so you understand *why* each decision was made.

---

## 2. The 4 batches (with self-review gates)

Steps refer to the **§6 table in v6** (steps 0–9). The §6 table is the single source of truth for step numbering; if anything elsewhere disagrees, the table wins.

### BATCH 1 — Foundation (steps 0, 1, 2, 3)
- **Step 0:** Commit the existing working-tree work as the M1 punch-list baseline. **Verify the diff contains exactly H1/H2/H3/M4 + their tests and nothing stray** before committing. Commit message: `m15 v6 step 0: commit M1 punch-list (H1/H2/H3/M4)`.
- **Step 1:** `black_scholes_call_price()` + put-call parity tests (incl. spot=0).
- **Step 2:** Add the **7 non-proxy** config fields to `config_models.py` + `hedge_readiness.yaml` (the 3 proxy fields already exist — do not re-add). Schema-validation tests.
- **Step 3:** `OptionStrategy` enum + `compute_strategy_pnl` (v6 §2h — intrinsic computed *inside* the function). Thread `down_beta_min_for_scenario` into `compute_scenario_bundle` **and** `_skip_reason` (v6 §3, §4d). 
- → **SELF-REVIEW GATE 1** (see §3). Fix, commit fixes, append to progress log.

### BATCH 2 — New modules (steps 4, 5, 6)
- **Step 4:** NEW `_helpers.py`; migrate the 4 hedge modules to import from it. **No behavioural change.** Keep `_helpers.py` dependency-light — no imports of `AppConfig`, `ProjectPaths`, or other hedge modules (avoids import cycles).
- **Step 5:** NEW `sensitivity_ranking.py` (v6 §2f, §3). Sort by `down_beta_core`; P&L column uses the *same* beta; `risk_free_rate: float | None`.
- **Step 6:** NEW `portfolio_totals.py` (v6 §2g). Both holdings modes; share-based hedge cost; dollar-exposure-without-price → skip hedge cost with reason but still count notional.
- → **SELF-REVIEW GATE 2** (see §3). Fix, commit fixes.
- → **CHECKPOINT A: STOP. Report to Emanuel and wait for "continue."** Report: tests added per step, full count, anything surprising.

### BATCH 3 — Integration (steps 7, 8)
- **Step 7:** Add the **5 CLI flags** (v6 §2c); plumb through `run_hedge_readiness`. argparse `default=None` → config fallback.
- **Step 8:** **REWRITE** `report.py` into section-data builders + a markdown emitter; wire all **9 sections** in the v6 §2e order; surface the **r=0 risk-free fallback** (M5). Start by defining the complete `HedgeReadinessSections` object (including `header` and `sources`) before moving any renderer code.
- → **SELF-REVIEW GATE 3** (see §3). Fix, commit fixes.
- → **CHECKPOINT B: STOP. Report to Emanuel and wait.** Paste **two real reports** — one with empty `holdings.yaml`, one with a 2-position mixed-mode fixture (one shares, one dollar_exposure) — and demonstrate all 5 flags.

### BATCH 4 — Finalize (step 9)
- **Step 9:** Manual smoke (both holdings states + all 5 flags incl. `--quantity 10`, `--ranking-max-tickers 5`), then write the `docs/` updates listed in v6 §6 step 9.
- → **SELF-REVIEW GATE 4** (see §3).
- → **CHECKPOINT C: STOP.** Write the completion report (v6 §11) and wait for review.

---

## 3. The self-review gate (run this at the end of EVERY batch)

This is the heart of what Emanuel asked for. Do not skip it. Do not rush it. Treat it as if a senior engineer is going to read your diff next (one will).

**Step A — Read your own diff.**
`git diff <batch-start-commit>..HEAD`. Read every hunk. For each one ask:
- Does this match the plan step it belongs to?
- Did I touch any file *not* in v6 §2b's scope?
- Any whitespace/comment/import edit that isn't part of the work?
- Any "improvement" I slipped in that the plan didn't ask for?
- Any leftover debug code, commented-out code, or TODO?

**Step B — Run the full suite.** `python -m pytest -q`. Must be green, no new warnings, count ≥ baseline + the tests this batch should have added. If anything is red or skipped, **stop and fix before continuing.**

**Step C — Check against acceptance.** Re-read the relevant bullets in v6 §7 (Acceptance) and §9 (Risks) for the steps in this batch. Verify each one is actually true in your code — don't assume.

**Step D — Hunt the known failure modes** (these have bitten prior milestones):
- Unicode → ASCII normalization slipping in
- Defensive duplicate calls added without a comment explaining why
- Unused imports left behind
- Stray blank lines accumulating
- A config field that's defined but never actually read (the v6 plan calls this out specifically for `down_beta_min_for_scenario` — verify `_skip_reason` reads the *parameter*, not the old module constant)
- Two dataclasses with the same role under different names (v6 §2d defines each section type **once** — don't reintroduce a `…Block` vs `…Data` split)

**Step E — Verify the v6-specific traps** (things v5 got wrong — do NOT reintroduce them):
- `comparison.py` must be **unchanged**. If your diff touches it, revert that. The default sort is already correct (v6 §2k).
- `options_phase.py` status counting must stay **after** the successful try (v6 §3, self-review C2). Don't move it earlier.
- Sensitivity Ranking sort key and its P&L column must both use `down_beta_core` (v6 §2f, self-review H-A).

**Step F — Fix everything you found, then commit the fixes** as a single commit: `m15 v6 batch <N> self-review fixes`. If you found nothing, write that explicitly in the progress log ("Batch N self-review: no findings"). 

**Step G — Log it.** Append to `codex_m15_v6_progress.md`: what you reviewed, what you found, what you fixed, the test count.

**Stop conditions** (any one → halt and report to Emanuel, don't push through):
- Test count dropped, or a test errored/skipped.
- A diff hunk you can't explain in one sentence.
- A plan instruction that turned out to be wrong or impossible (don't silently improvise a different design — surface it).
- You've spent more than ~15 minutes fixing one thing.

---

## 4. Git rules (strict)

- Branch `dev-vic` only. Confirm before starting.
- **One commit per plan step**, message `m15 v6 step <N>: <one-line description>`.
- **One "self-review fixes" commit per batch**, message `m15 v6 batch <N> self-review fixes`.
- Commit the progress-log update alongside (or within) each commit.
- No `git push` (Emanuel pushes). No amend, no rebase, no force-push, no `--no-verify`.
- One commit = one stated purpose. If a fix and a feature are unrelated, that's two commits.

---

## 5. Hard rules from the repo (do not violate)

- No analytics on mixed currencies without explicit normalization.
- No new horizons added ad hoc — only via centralized config.
- No composite scores before raw-data QA gates pass.
- No hidden/manual label overrides.
- Every transformation testable, versioned, auditable.
- No live Yahoo calls in tests — fixtures only.
- Out of scope (do NOT build): Workspace UI, Tool C pipeline, trade journal, calls/short strategies **in the report** (math primitives only), spreads, Greeks beyond delta, vol-skew, ADR mapping, paid feeds. (Full list: v6 §8.)

---

## 6. What "done" looks like

All of v6 §7 (Acceptance) holds, the full suite is green with ~55–60 net new tests above the Step-0 baseline, the completion report (v6 §11) is written, and you've stopped at Checkpoint C for review. Every Codex v5 finding, every Opus-4.8 self-review finding, and every CODE_REVIEW.md M1 item is ticked in the completion report.

---

## 7. Quick reference — batch → checkpoint map

| Batch | Steps | Self-review gate | Then |
|---|---|---|---|
| 1 Foundation | 0,1,2,3 | Gate 1 | continue |
| 2 New modules | 4,5,6 | Gate 2 | **Checkpoint A — wait** |
| 3 Integration | 7,8 | Gate 3 | **Checkpoint B — wait** |
| 4 Finalize | 9 | Gate 4 | **Checkpoint C — wait** |

Start with §1 (pre-flight), then Batch 1. Good luck.
