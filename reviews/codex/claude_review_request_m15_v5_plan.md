# Plan Review Request: M1.5 v5

**To:** Codex
**From:** Claude Code (on behalf of Emanuel)
**Date:** 2026-06-02
**Stage:** PLAN review only. Do NOT start implementation. Do NOT change any source code.
**Output you should produce:** `reviews/codex/codex_review_claude_m15_v5_plan.md` (NEW filename — keep your prior v4 review intact for history)

---

## What to read

1. **Primary:** [`reviews/codex/claude_m15_v5_plan.md`](claude_m15_v5_plan.md) (912 lines). The plan being reviewed.
2. **Reference:** [`reviews/codex/codex_review_claude_m15_plan_v4.md`](codex_review_claude_m15_plan_v4.md). Your prior review that v5 addresses.
3. **Reference:** [`reviews/codex/MASTER_ROADMAP_2026-06-02.md`](MASTER_ROADMAP_2026-06-02.md). The three-milestone sequencing context (M1.5 v5 → M2 → M3).
4. **Reference:** [`CODE_REVIEW.md`](../../CODE_REVIEW.md) (repo root). Claude's senior-engineer review of the current M1 codebase. v5 folds in the H1/H2/H3 findings from this review.
5. **Reference if needed:** the existing implementation in `golden_vector/hedge/`, `golden_vector/features/black_scholes.py`, `golden_vector/cli.py`. Verify v5's module summaries match reality where they describe existing code.

---

## Context

Plan history:
- **v1** — initial. You graded NEEDS CHANGES with 11 findings.
- **v2** — fixed v1 findings. Implementation began under v2.
- **v3** — scope expansion (strategy-generic math + portfolio totals).
- **v4** — added Sensitivity Ranking section + dropped binary decision triggers.
- **v5** — you graded v4 NEEDS CHANGES with 14 findings. v5 addresses every one of them.

Emanuel decided to expand scope further (full v5 M1.5 + M2 workspace UI + M3 basic Tool C). v5 covers the M1.5 portion; M2 and M3 plans will be written separately while Codex implements M1.5 v5.

The M1 codebase has been built and shipped (446 tests passing). Parts of M1.5 are already in the codebase from earlier work under v2 (scenarios.py, comparison.py, header_context.py, speculation_section.py — these are built but not yet wired into report.py).

---

## What thorough means here

This is a **full plan review**, not a delta review. Treat as a fresh read of a 912-line plan.

### 1. Verify your 14 v4 findings are addressed in v5

Walk through each of the 14 findings from `codex_review_claude_m15_plan_v4.md` and confirm v5 actually fixes them. The v5 changelog at the top of the plan claims it does — your job is to verify. Specifically:

- **#1 CLI `--sort-by` overloaded** → verify `--comparison-sort-by` + `--ranking-sort-by` are separate, with non-overlapping choice lists
- **#2 Calls in scope AND out of scope** → verify §3, §6, §8, §10 are consistent (math layer YES, report layer NO)
- **#3 Report module summary stale vs §2j** → verify §3 `hedge/report.py` summary lists the 8 sections in §2e order exactly
- **#4 BS pseudocode regression on spot=0** → verify §3 `black_scholes_put_price` summary says spot=0 returns BS limit (NOT None)
- **#5 `DOWN_BETA_MIN_FOR_SCENARIO` configurable but no config field** → verify config field exists in §2b file tree and step 2
- **#6 CLI choices incomplete** → verify separate flags resolve this
- **#7 Heuristic label not in module signatures** → verify §4e + §3 header_context.py summary both include "heuristic"
- **#8 header_context signature mismatch with AF4** → verify §3 summary shows it taking `paths` and reading via manifest, not `gold_history`/`gdx_history` direct
- **#9 `--max-tickers` overloaded** → verify `--ranking-max-tickers` + `--speculation-max-tickers` are separate
- **#10 `up_beta_12m` sort doesn't make sense** → verify it's removed from `--ranking-sort-by` choices
- **#11 Portfolio Totals dollar_exposure** → verify §2g handles both shares-mode AND dollar_exposure-mode with explicit skip reasons
- **#12 File tree stale** → verify §2b is coherent: every new file, every edit, every config field
- **#13 Implementation guidance "seven steps"** → verify §10 says 13 steps
- **#14 Duplicate v2/v3 changelog headings** → verify changelogs are clean

### 2. New things to pry at in v5

These are areas v5 introduces or substantially reshapes:

- **Section-builders → emitter refactor (§2d, §3, step 11)** — the biggest structural change. v5 splits `render_hedge_readiness_report` into pure data builders (returning typed dataclasses) + a markdown emitter. M2 will reuse the same dataclasses with an HTML emitter. Is the dataclass shape right? Will M2's HTML emitter actually be able to consume them without reshaping?
- **`HedgeReadinessSections` dataclass (§2d)** — does it cover every piece of data the current markdown emitter produces? Anything missing? Anything that's a leaky abstraction?
- **Section ordering change** — current report renders holdings → cross-sectional → proxy. v5 renders header → snapshot summary → sensitivity ranking → portfolio totals → held positions → speculation → comparison → proxy → sources. Do existing tests in `test_hedge_report.py` assume the old order? Will they need updates beyond what step 11 specifies?
- **Sensitivity Ranking computing P&L per ticker** — calls `compute_scenario_bundle` for the 60d candidate of EACH of 60 tickers. For non-optionable (40 names) and low-down-beta tickers, the scenario is skipped with notes. Is the skip-path coverage complete in step 6 tests?
- **Portfolio Totals dollar_exposure + hedge cost** — when a holding is `dollar_exposure: 50000` (no shares), we still need a share count to compute contracts needed. §2g says we compute `target_shares = dollar_exposure × X% / current_stock_price`. If current_stock_price is missing, we skip the hedge-cost calc but the holding still contributes to portfolio value. Is that the right split?
- **OptionStrategy enum without report integration** — all 4 strategies are math primitives, but only LONG_PUT is in the report. §8 explicitly says calls NOT in report. Is the public API on `compute_scenario_bundle` clear that callers SHOULD use LONG_PUT for now?
- **Proxy 3-tier with Tool B verdict** — the 3-tier labels look at beta_diff + confidence. Tool B verdict is surfaced as CONTEXT but not used in tier decision. Is that right under the 3-tier upgrade?
- **CLI flag defaults living in config** — `--quantity` falls back to `config.default_scenario_quantity`. `--ranking-max-tickers` falls back to `config.ranking_max_tickers_default`. Is the naming consistency acceptable (flag names ≠ config field names)?

### 3. Internal consistency checks

The plan is 912 lines and has gone through 5 iterations. Specifically check:

- **§2b file tree** vs **§3 module summaries** — same files listed in both? Same edits? Same configs?
- **§3 module summaries** vs **§4 math sections** — pseudocode matches between them? (This was the v4 regression on BS spot=0.)
- **§6 step list** vs **§2b file tree** — every step touches files in §2b, no surprises?
- **§7 acceptance criteria** vs **§6 step gates** — acceptance items align with step outcomes?
- **§8 out-of-scope** vs **§3 module summaries** — anything implemented that §8 says is deferred? (The calls-in-scope contradiction from v4 is the canonical example.)
- **§10 implementation guidance** vs **§6 step count** — checkpoint references correct?

### 4. Plan scale check

You recommended in v4 that the milestone might be too big and should split. v5 keeps it as ONE milestone (~18-22 hours of Codex work, 13 steps, 3 checkpoints). Is the size now manageable, or do you still recommend splitting? If split, where would you draw the line?

### 5. Implementation risk areas

Where would you expect mid-build difficulties? Examples to consider:

- Step 5 (`_helpers.py` consolidation) requires migrating 4 hedge modules to import from the new module. Risk of import cycles?
- Step 11 (report refactor) is the largest change. If the dataclass shapes don't quite fit existing renderers, this step balloons.
- Step 9 (options_phase per-ticker isolation) requires writing a test that simulates a mid-loop failure. Mocking strategy?

### 6. M1 cleanups folded in

v5 folds in 3 high-priority findings from Claude's `CODE_REVIEW.md`:
- **H1** (cross-sectional IV sort direction) → handled in step 11
- **H2** (proxy basis-risk 2-tier vs 3-tier) → handled in step 8
- **H3** (options_phase per-ticker error isolation) → handled in step 9

Confirm these are properly specified and tested. If you disagree with any of Claude's H1/H2/H3 framings (e.g., you'd keep H2 at 2-tier), say so.

---

## Output format

Write your review to `reviews/codex/codex_review_claude_m15_v5_plan.md`. Use the same shape as your prior reviews:

```
Grade: READY / READY WITH MINOR CHANGES / NEEDS CHANGES

## Summary
[2-3 sentence verdict]

## v4 Finding Regression Check
[Table mapping each of the 14 v4 findings to v5 status]

## New Findings
[Numbered findings with severity P1/P2/P3, file references, and specific lines]

## Plan Scale
[Your call on whether to keep as one milestone or split]

## Required Edits Before Implementation
[Numbered list. If none, say so.]
```

**Length:** ~200-400 lines of review. Be specific — `file:line` references, exact quotes when calling out drift.

---

## What happens after your review

Write your review and **stop.** Do NOT touch source code regardless of the grade you assign. Claude (the planner) will read your review and either:
- agree with your findings and either revise the plan or pass it back to Emanuel for direction,
- push back on individual findings if Claude has counter-evidence,
- ask Emanuel for a decision when you and Claude disagree on a judgment call.

Only after Claude has reviewed your review AND Emanuel has explicitly said "begin step 1" will any implementation start. This is a multi-step gate, and you are at the FIRST gate.

This is the **5th review cycle** on this plan. The goal is to get to READY without dragging out further iterations. Be ruthless about real blockers; don't pile on nice-to-haves that could be M1.6+ work.

---

## One important constraint

**Do not start implementation under any circumstance.** Plan review only. Even if you grade READY, you stop after writing the review. M1 is shipped to dev-vic at commit `a37a013`; everything from there forward is new work that requires Emanuel's explicit green light AFTER both Codex's plan review and Claude's review-of-the-review.

Go.
