# Merged Review — Claude vs Codex on the Tool C/D build

**Author:** Claude Code (Opus 4.8)
**Date:** 2026-06-05
**Inputs:** `claude_review_tool_c_d_full_audit.md` (Claude) + `codex_full_review_tool_c_d_option_data_center.md` (Codex).
**Purpose:** per the parallel-review rule, merge both into one finding table, mark who caught what, reconcile severity, and define the fix list.

## Headline
- **Grades:** Claude = "Strong build, ship after 2 fixes." Codex = "NEEDS CHANGES."
- **Why they differ:** *scope*, not disagreement. Claude scoped tightly to **Tool C/D correctness + Finder integration**. Codex scoped **wider** — it folded in the **Option Trading performance / data-center architecture** (the 19.8s cold load), which Claude had reviewed *separately* in `claude_review_option_trading_handoff.md` and already endorsed. Fold that architecture finding back in and the two positions converge: **the Tool C/D math is fundamentally sound, but there's a real list of contract/centralization gaps to close before it's "done."**
- **Net:** neither review dominates. Codex was **stronger on lock-compliance details** (config-pinning, GDXJ, tail-tagging, replay) that Claude's pass graded too generously. Claude was **stronger on two concrete defects** (a Finder eligibility regression and a crash path) that Codex didn't surface. Together they're the complete picture.

## Where the two reviews OVERLAP / AGREE
| Topic | Claude | Codex | Reconciled |
|---|---|---|---|
| Option UI does heavy compute at request time → slow cold load | Raised separately (handoff review): endorse precompute artifact | **P1**, measured 19.8s cold; detailed data-center artifact design | **AGREE — top architecture priority.** Codex added the measurement + concrete artifact spec. |
| Tool D math (3 components, FCF context-only, EBITDA≤0→null) | Verified correct | Verified math "currently correct" | **AGREE — correct.** |
| Finder reader correctly refuses non-spot Tool D | Verified guard correct (L1) | Verified guard correct | **AGREE — reader side is correct.** |
| Backward-compat (status/refresh/old manifests don't crash) | Verified graceful | Not disputed | **AGREE.** |

## Findings CODEX caught that CLAUDE missed (the important part)
| # | Finding | Why it's real | Claude's miss |
|---|---|---|---|
| C1 | **Non-spot `tool-d --gold-price` overwrites `tool_d_latest.parquet`** (writer side: `cli.py:1267` publishes latest aliases regardless of spot). A legitimate stress run then makes the Finder *correctly* blank its Tool D criterion until a spot run is regenerated. | Claude verified the **reader** guard but never checked the **writer** — a normal exploratory run silently disables a Finder criterion. | **Genuine miss.** This is also the concrete *trigger* for Claude's H1 (below). |
| C2 | **Tool D rank directions are hard-coded, not pinned in `tool_d.yaml`** (`_add_quality_scores` hard-codes high/low-good; config has only `version` + `max_reasonable_ev_ebitda`). | The build-brief **L4 explicitly required directions in config**. Math is right, but the contract isn't auditable/centrally changeable. | **Genuine partial-L4 miss.** Claude's agent verified the *math* but not the *config-pinning* L4 also required. |
| C3 | **GDXJ is carried but unused; weekly frame omits `n_weeks_gold/gdx/gdxj`.** `weekly_returns` emits `gdxj_log_ret` but `relative_behavior` never computes any `rel_*_vs_gdxj`, and the per-benchmark week-counts the brief (L3) named aren't emitted at the frame level. | Junior-miner benchmark is dead weight; the locked L3 contract is only partly met. | **Genuine partial-L3 miss.** Claude's agent rated L3 "PASS" on the strength of gold+GDX per-metric counts and overlooked the unused GDXJ + the frame-level counts. |
| C4 | **Thin-tail metrics excluded from rank but NOT tagged.** `thin_history` only inspects relative/hit-rate counts, not tail counts — a ticker can have unusable tail context with no warning. | The plan said thin tails are *flagged AND excluded*. Excluded ✓, flagged ✗. | **Genuine miss.** Claude conflated "excluded from rank" (true) with "flagged" (false for tails). |
| C5 | **Replay verify conflates immutable snapshot with mutable current source.** `verify_manifest` checks both the copied snapshot *and* the live `latest` file against the captured hash, so once `latest` moves on (normal), an intact snapshot is marked FAILED. Tests only verify right after writing. | Drift against current files should report as drift, not snapshot-integrity failure. | **Genuine miss.** Claude's agent checked old-manifest back-compat but not the snapshot-vs-mutable-source conflation. |
| C6 | Option cache key too coarse (no manifest/feature/config hashes); option-selection thresholds only partly in config; ticker-detail still does some request-time analytics. | Real, but Option-Trading scope (overlaps Claude's separate handoff review). | Out of Claude's Tool C/D audit scope; consistent with Claude's prior precompute recommendation. |

## Findings CLAUDE caught that CODEX missed
| # | Finding | Why it's real | Codex's miss |
|---|---|---|---|
| K1 | **Preset eligibility regression** — `bearish_put`/`bullish_call` went 5→7 criteria; with `min_criteria_fraction 0.67`, when Tool C/D are absent the new always-NA criteria push previously-eligible tickers (4/5=0.80) under the gate (4/7=0.57) → they **silently drop off the screen**. | Highest-value page silently changes output; untested. | **Codex missed the eligibility mechanics.** Codex's C1 (overwrite) is the *trigger*; Claude's K1 is the *mechanism* (it's why blanking the rank for everyone is harmful). They complete each other. |
| K2 | **Tool C `KeyError: 'score_eligible'` crash** when Tool A input is empty/lacks the column (`tool_c.py:225/237`), despite the code advertising a Tool-A-less fallback (`:133`). | Real crash on a plausible misuse (`tool-c` before `tool-a`). | **Codex missed it** (its probe ran against full local data). |
| K3 | **The L2 "ignores bogus leverage" test is vacuous** — the decoy `999.0` sits in a frame column that's stripped before Tool D reads it, so the test can't fail. | Test-rot risk: the named L2 guard doesn't actually guard. | **Codex missed it.** |

## Reconciled fix list (merged, severity-ordered)
**Must-fix before relying on Tool C/D + Finder:**
1. **C1 + K1 together (Finder/Tool D latest):** persist **separate spot vs scenario Tool D aliases** (keep `tool_d_latest_spot` for the Finder), so an exploratory `--gold-price` run can't disable the Finder criterion (C1); **and** stop universally-absent criteria from dropping tickers in the preset eligibility gate (K1). Add a parity regression test. *(These are the same wound from two sides — fix together.)*
2. **K2 (crash):** one-line guard — seed `score_eligible` in `_ensure_columns` (or short-circuit when Tool A is absent).

**Lock-compliance / contract (close before "done"):**
3. **C2:** move Tool D's three component directions into `tool_d.yaml`; test fails if model ignores config.
4. **C3:** either compute & rank GDXJ-relative metrics + emit `n_weeks_gold/gdx/gdxj`, **or** explicitly document GDXJ as context-only and drop the dead column.
5. **C4:** include tail counts in the `thin_history` tagging.
6. **C5:** replay verify should report current-source drift as *drift*, not snapshot-integrity failure; add a test for the "latest moved on" state.

**Test hygiene:**
7. **K3:** make the L2 leverage test inject the decoy into the consumed frames.
8. Add the other missing tests both reviews list (L5 threshold-changes-output, L4 zero-component→null, net-cash sign).

**Architecture (separate, bigger track — already agreed):**
9. **C6 / Codex's data-center plan:** precompute option metrics + candidate slots + a Candidate-Finder input frame at refresh time; UI reads artifacts. This is the Option-Trading precompute work Claude already endorsed in the handoff review — **do it as its own milestone**, not mixed into the Tool C/D fixes.

## Bottom line
The two reviews **agree on substance** and the difference in grade is scope. **Take Codex's grade ("NEEDS CHANGES") as the operative one** — its lock-compliance findings (C2–C5) are legitimate gaps Claude's pass under-weighted, and the writer-side overwrite (C1) pairs with Claude's eligibility finding (K1) to expose a real Finder fragility. Conversely Codex should fold in Claude's crash (K2) and eligibility mechanics (K1). Fix items 1–2 before the Finder is trusted; 3–8 before Tool C/D is "done"; 9 is the larger data-center track already on the roadmap.
