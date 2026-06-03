# Claude Review: Codex Step 1 — Snapshot Retention Audit

**Reviewer:** Claude Code
**Date:** 2026-05-28
**Commit reviewed:** `4a99427` (workspace split step 1: audit snapshot retention)
**Files changed:** `docs/snapshot_retention_audit.md` (+76 lines)
**Grade:** **READY** — with one tiny housekeeping ask + one decision point for Emanuel

---

## TL;DR

Codex's audit is accurate, well-structured, and answers the right questions. Every factual claim in the doc has been spot-checked against the live filesystem and matches. The recommendation (a per-run `replay_manifest.json`) is minimal and well-targeted. Recommend proceeding to **step 2** after Emanuel decides whether to defer or in-scope the replay-manifest work.

---

## 1. Factual claims — spot-checked

Each claim in the audit was verified against the actual filesystem on 2026-05-28.

| Codex claim | Reality | Match |
|---|---|---|
| 67 timestamped run folders in `data/runs/` | 67 | ✅ |
| 8 update-data runs exist | 8 | ✅ |
| 7 of those 8 have a `snapshots/` directory | Verified: only `20260422T201446Z-update-data-7606a39f` lacks one (earliest run, as Codex predicted) | ✅ |
| `data/runs/20260424T140753Z-update-data-6175c3fb/snapshots/` contains `raw_equities.parquet`, `raw_fx.parquet`, `raw_gold.parquet`, `usd_equities.parquet`, `market_snapshots_usd.parquet` | All 5 files present | ✅ |
| 19 historical `tool_a_latest_*.parquet` + 19 `tool_a_output_*.parquet` | 19 each (verified by counting `.parquet` only — total file count of 38 includes the parallel `.csv` files) | ✅ |
| 19 each for Tool B parquet | 19 each | ✅ |
| 12 historical Tool A structural files | 11 historical + 1 latest pointer = 12 total | ✅ |
| Combined output retention exists | 2 historical combined runs retained with `combined_output_<runid>.parquet` and `combined_latest_<runid>.parquet` | ✅ |

**No factual errors.** Codex was honest about the one early update-data run that predates the snapshot retention implementation, rather than glossing over it.

## 2. Structure — answers the two questions from R5

The plan v2 (per Codex's own R5 finding) required the audit to separate two questions, not conflate them. Codex did this correctly:

| Question | Audit answer | Honest? |
|---|---|---|
| **Are output snapshots retained?** | Yes — Tool A, Tool B, combined, foundation snapshots, structural metrics all kept per run with run-local paths. | Yes — backed by concrete file paths and counts. |
| **Is enough replay metadata retained?** | Partially — runs have `metadata.json`, `config_summary.json`, status summaries, and artifact lists, but these are **summaries not full configs**. Specifically missing: full loaded config, exact code revision (Git commit), immutable foundation manifest copy per run, Tool B manual-data snapshot. | Yes — names specific files and code paths. |

This is the structural quality I was looking for. A single-line "snapshots are kept" answer would have hidden the real gap. Codex didn't take that shortcut.

## 3. The recommendation — evaluated

Codex's proposed fix: **add a per-run `replay_manifest.json`** that copies the full loaded config (or a content-addressed reference), records the Git commit, copies the foundation manifest used by the run, and records the manual-data store version.

| Property | Verdict |
|---|---|
| Targeted | ✅ Doesn't propose a new snapshot layer — extends existing per-run metadata. |
| Minimal | ✅ One new JSON file per run. No new storage system, no new pipelines. |
| Addresses both gaps cleanly | ✅ Config + commit covers code-side replay; foundation manifest copy + manual-data version covers data-side replay. |
| Avoids the "two retention layers" trap I worried about in plan §2 | ✅ Explicitly says "do not add another snapshot layer." |
| Implementation cost | Low. ~50 lines of code in `RunContext` or alongside it; no changes to existing data persistence. |

The recommendation is sound. **No correction needed.**

## 4. One tiny housekeeping ask (not blocking)

The progress log file `reviews/codex/codex_workspace_split_progress.md` is **untracked**, not committed. The implementation brief asked for the log to be appended-to but didn't explicitly require committing it.

`git show 4a99427` confirms the commit contains only the audit doc (76 insertions, 1 file).

This is a minor pattern choice. Two options:
- **(a)** Leave the progress log untracked — treat it as a session journal that doesn't belong in git history. Pro: keeps commit history clean of audit-trail noise.
- **(b)** Commit the progress log update alongside each step. Pro: progress log SHA matches the work SHA; easier to audit later.

**My weak preference:** (b). The progress log is a real deliverable of this work; if you re-clone, you lose it today. Either way, a tiny ask for Codex going forward — see §6 below.

## 5. Decision point for Emanuel — defer the replay manifest, or include it now?

Codex's audit identifies a real gap (deterministic replay metadata) but the gap is **not blocking** the workspace split. It is a backtesting prerequisite for the future predictive tool.

You have three options:

| Option | What happens | Pro | Con |
|---|---|---|---|
| **A.** Defer replay manifest entirely | Audit doc stands as a future-work record. Proceed to step 2. | Keeps current scope tight; matches plan §6 spirit. | When you eventually build the predictive tool, you'll discover historical runs from this period aren't replayable. |
| **B.** Add replay manifest as a new step between 1 and 2 | Codex writes ~50 lines into `RunContext` + tests. ~30–60 min. | Future-proofs *forward* runs immediately. | Expands scope mid-work; adds a step the original plan didn't have. |
| **C.** Add to backlog explicitly (out-of-band) | You file a TODO somewhere; the audit doc points at it. Proceed to step 2. | Tight scope now, but preserves intent. | Discipline-dependent — easy to forget. |

**My recommendation: (A) defer.** Reasoning:
- The retention gap only affects runs from *today onward* that would need replay. The current workspace split is structural-only; it doesn't produce historical data that becomes un-replayable.
- The predictive tool is not next on the roadmap. By the time it is, replay manifest can be designed alongside it with the predictive tool's needs in mind.
- Expanding scope mid-Codex-run violates the "tight scope" rule we've been holding to.

If you agree with (A), the audit doc is the durable record — no separate TODO needed. The doc itself is the artifact that says "this gap exists, here's the proposed fix when we need it."

## 6. Instruction for Codex going forward

Two tiny additions for steps 2–12 (no need to fix step 1 retroactively):

1. **Commit the progress log alongside each step.** Two files per commit: the actual step's work + the progress log entry for that step. Keeps the audit trail with the code.
2. **Continue exactly as the brief specifies.** No other changes — the work on step 1 was good.

## 7. Verdict

**Grade: READY.** Step 1 deliverable is accurate, well-structured, and answers the right questions. No corrections required.

Emanuel: please pick A / B / C on §5 (replay manifest), and tell Codex to "continue" with steps 2 onward + the progress log commit habit from §6.
