# Codex Brief — Option Trading Tab (final review, then build)

**For:** Codex (implementation agent)
**From:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**The spec you implement:** `reviews/codex/claude_option_trading_ui_plan_v2.md` — read it in full. This brief is *how to work* (final review → batched build → self-review between batches). The plan is *what to build*.
**Context:** v1 of this plan was graded NEEDS CHANGES by you (`codex_review_claude_option_trading_ui_plan.md`); **v2 addresses all 8 of your findings** (see the v2 changelog table) plus 4 Claude self-review refinements.

---

## Step 0 — Final review of the plan (do this first)
Before writing any code, do **one more review pass** of `claude_option_trading_ui_plan_v2.md`:
1. Confirm each of your 8 v1 findings is genuinely resolved (the changelog maps them; verify the body matches).
2. Sanity-check the data contract against the real repo (`option_trading.py` builders, the composite cache key, the `OptionCandidate` migration vs `report.py`/tests, `up_beta_core` availability in Tool A).
3. If you find a **blocking** issue, **stop and write it up** (`codex_review_claude_option_trading_ui_plan_v2.md`) and wait — do not invent a fix mid-build. If it's non-blocking, note it and proceed.
4. If the plan is sound, write one line confirming "v2 review: ready to implement" in your progress log and begin Batch 1.

---

## How to work (same as the M1.5 milestone)
> Code a batch → **STOP** → review your own diff, run the full suite, fix everything you find → commit the fixes → only then start the next batch.

**4 batches**, each ending in a self-review gate. **Halt and wait for Emanuel** at the four checkpoints.

No `git push` (Emanuel pushes). No amend/rebase/force-push. One commit per plan step + one "self-review fixes" commit per batch.

---

## Pre-flight
1. `git branch --show-current` → `dev-vic`.
2. `python -m pytest -q` → record the baseline pass count.
3. Create `reviews/codex/codex_option_trading_progress.md` (baseline + one line per step/self-review).
4. Re-read v2 §2b (backend-vs-frontend rule) and §2d (data/cache layer) — these two govern the whole build.

---

## The 4 batches (steps map to v2 §4)

### BATCH 1 — Data layer + native tab (v1a steps 1–2)
- **Step 1:** `hedge/option_trading.py` overview builder + `serve/option_trading_data.py` (load frames + **composite-key cache**: options manifest + Tool A + Tool B run_ids). Compute each optionable ticker's candidate grids **once**, shared by overview + detail (v2 §2d). Tests.
- **Step 2:** `GET /option-trading` route + nav entry + `overview_option_trading.py` DataTable (put columns), default sort `down_beta_core` desc, filters, per-side status, honest empty/thin notes.
- → **SELF-REVIEW GATE 1**, then **CHECKPOINT A: STOP & report.** Tab live, optionable-only, sortable/filterable, rendered from structured data (no markdown). Wait for "continue."

### BATCH 2 — Put detail + retire markdown (v1a steps 3–4)
- **Step 3:** `_render_option_trading_panel` (puts) on `/ticker/<T>?lens=option-trading`; `active_nav="option_trading"`, anchor to panel, invalid-lens fallback.
- **Step 4:** delete the regex renderer in `serve/hedge_readiness_page.py`; **redirect** `/hedge-readiness → /option-trading`; remove the "Hedge Report" nav entry; add a raw-report **download** link; tests (incl. the redirect).
- → **SELF-REVIEW GATE 2**, then **CHECKPOINT B: STOP & report.** Paste the rendered tab + a put detail page. Markdown path gone; one canonical tab. Wait.

### BATCH 3 — Generic candidate model + calls (v1b steps 5–6)
- **Step 5:** generalize `CandidatePut → OptionCandidate` (`option_type` field), `build_candidate_grid(option_type=…)`, rename `down_beta_used → gold_beta_used` and the scenario scaling param `down_beta_core → gold_beta`. **Back-compat:** alias `CandidatePut = OptionCandidate` + keep `build_candidate_put_grid` wrapper so `report.py` (shipped CLI) stays working; update its renamed-field refs + tests. **Puts behaviour must be byte-for-byte unchanged.**
- **Step 6:** `build_candidate_grid(option_type="C")` (calls near +0.25Δ); call scenarios scaled by **`up_beta_core`**, positive-gold {0,+5,+10,+15,+20}%; add call context column to the overview + the segmented **Upside calls** subpanel (labelled *leveraged bullish speculation — not a hedge; time-decay risk*).
- → **SELF-REVIEW GATE 3**, then **CHECKPOINT C: STOP & report.** Show a detail page with both Downside puts and Upside calls. Wait.

### BATCH 4 — Sizing calculator + polish (v1b steps 7–8)
- **Step 7:** the **GET** sizing calculator: `?…&size_mode=contracts&quantity=N` XOR `&size_mode=budget&budget=$`; validation (positive, numeric, valid side/horizon → else fall back + note); **rescale** net P&L server-side (no BS recompute, no cache invalidation — v2 §2h); tests proving **it persists nothing**.
- **Step 8:** styling (`workspace.css`), empty-states, docs (dual gold-direction framing + calculator help).
- → **SELF-REVIEW GATE 4**, then **CHECKPOINT D: STOP.** Demo the calculator (contracts + budget); confirm no mutation. Write the completion report and wait for review.

---

## The self-review gate (run at the end of EVERY batch)
**A. Read your own diff** (`git diff <batch-start>..HEAD`), hunk by hunk: matches the step? any out-of-scope file? stray whitespace/imports/"improvements"? leftover debug?
**B. Run the full suite** (`pytest -q`): green, no new warnings, count ≥ baseline + this batch's new tests.
**C. Check acceptance** for these steps against v2 §5.
**D. Known failure modes:** Unicode→ASCII, defensive duplicate calls, unused imports, stray blank lines, a config/field defined-but-never-read.
**E. Verify the Option-Trading-specific traps (do NOT regress these):**
- **No financial math in the frontend** — JS is DataTables only; every P&L/candidate/breakeven/sizing number is computed in Python (v2 §2b).
- **No markdown regex** on the option-trading path.
- The calculator is a **GET that mutates nothing** (assert via test).
- **Per-side `put_status`/`call_status`** come from actual candidate availability, not the put-driven `optionability_tier`.
- The overview's "Put @ −10%" equals the detail's number (**shared candidate grids**, v2 §2d / R1).
- Calls scaled by **`up_beta_core`** (not down-beta) and labelled speculation.
- `OptionCandidate` rename kept the **CLI report working** (puts unchanged).
**F. Fix everything found, commit as** `option-trading batch <N> self-review fixes` (or "no findings" in the log).
**G. Log it** in `codex_option_trading_progress.md`.

**Stop conditions** (halt + report, don't push through): test count dropped / test errored or skipped; a diff hunk you can't explain in one sentence; a plan instruction that's wrong or impossible (surface it, don't improvise a different design); >~15 min on one fix.

---

## Git rules (strict)
- `dev-vic` only. One commit per step: `option-trading step <N>: <desc>`. One self-review commit per batch.
- Commit the progress-log update alongside. **No `git push`** (Emanuel pushes). No amend/rebase/force-push/`--no-verify`.

## Hard repo rules (unchanged)
No mixed-currency analytics; no live Yahoo in tests (fixtures only); testable/auditable transformations; out-of-scope (do NOT build): spreads, Greeks beyond delta, vol-skew, trade journal/persistence, client-side JS math, ADR mapping. Full out-of-scope list: v2 §6.

## Done = 
All of v2 §5 holds; full suite green with the new tests; completion report written; stopped at Checkpoint D for review. Every Codex v1 finding + every Claude self-review refinement ticked in the completion report.

---

## Quick map
| Batch | Steps | Gate | Then |
|---|---|---|---|
| 1 Data layer + tab | 1,2 | Gate 1 | **Checkpoint A — wait** |
| 2 Put detail + retire markdown | 3,4 | Gate 2 | **Checkpoint B — wait** |
| 3 Generic model + calls | 5,6 | Gate 3 | **Checkpoint C — wait** |
| 4 Calculator + polish | 7,8 | Gate 4 | **Checkpoint D — wait** |

Start at Step 0 (final plan review), then Batch 1.
```
