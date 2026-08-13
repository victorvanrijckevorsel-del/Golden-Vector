# INCIDENT — local data store deleted (2026-08-13 00:42)

Status: CLOSED — UNRECOVERABLE (2026-08-13 ~10:40). Recovery exhausted; rebuild executed;
prevention rules landed in AGENTS.md + CLAUDE.md.

## Recovery attempts (all executed 2026-08-13 morning, per Victor's instruction)

1. Recycle Bin: empty of matches (deletion bypassed the shell).
2. Volume Shadow Copies (elevated `vssadmin list shadows`, Victor-authorized UAC): exactly one
   shadow exists, created 08:41:58 — AFTER the 00:42 deletion; it snapshots the already-empty
   state. Older shadows had rotated out.
3. OneDrive / File History / sibling or backup copies: none exist for this tree.
4. NTFS undelete (Microsoft Windows File Recovery `winfr`, elevated, regular/MFT mode, filtered
   to `\Users\Emanuel\code\Golden-Vector\data\`): **0 files recovered.**
5. Root cause of unrecoverability confirmed: the volume is an NVMe SSD (WD SN810) with TRIM
   enabled (`DisableDeleteNotify = 0`). TRIM invalidated the deleted blocks at the hardware
   level shortly after 00:42. No software or laboratory technique recovers TRIMmed NAND;
   signature-mode scans would find the same nothing and were deliberately skipped.

Legacy 16:00/19:30 refresh tasks were disabled during the recovery window to stop writes; they
are superseded by the new hidden scheduled tasks at release.

## Final loss + rebuild

Permanently lost: daily option-chain history captures ~2026-06-12 → 2026-08-12 (perishable PIT
market data) and Lab LIVE vintage accruals over the same window; run archive + replay manifests
for retained generations. Rebuilt same day: full refresh (all current-state artifacts), Lab
deterministic backfill, ledger records reconstructed by hand (no committed copy existed — see
the reconstruction section below for what that costs). The Lab accrual clock
restarts 2026-08-13 with this document as the permanent gap record; collection of option-chain
history resumed with the first rebuilt refresh.

## The variant ledger is a RECONSTRUCTION, and what that costs

`data/lab/variant_ledger.jsonl` was destroyed with everything else and is
gitignored, so no copy exists in git, in a backup, or anywhere else. The five
`validation_*` records were rebuilt by hand on 2026-08-13.

**First attempt was wrong and the guardrail caught it.** The 09:41 UTC reseed
invented a flat config shape (`mean_ic_gate`, `share_gate`, …). The ledger's
guardrail test reads a nested `gates` mapping, and it had been *skipping* while
the records were missing entirely — so the reseed is what made it run, and it
failed with `KeyError: 'gates'` in the release focused selection. Corrected the
same day: records rewritten **in place** (appending would have doubled every
signal's `n_trials`, which is a real input elsewhere) with every threshold read
from `golden_vector.lab.validation`, the implementation's single source of
truth. Script archived beside this file.

**What is permanently degraded.** The ledger exists to pre-register an
experiment's exact configuration *before* compute, so a result cannot be
p-hacked after the fact, and so drift between the implementation's constants and
the registered ones is detectable. A ledger regenerated from today's constants
can do neither: it agrees with the code because it was derived from the code,
and it is not evidence that anything was registered in advance. The five records
therefore carry `reseeded_after_incident: "2026-08-13"` inside `config`, which
also changes their `variant_hash` — a reconstruction can never be mistaken for
the original registration, by hash or by eye. Genuine pre-registration resumes
with the next newly registered variant.

## Prevention (implemented)

- AGENTS.md + CLAUDE.md "Never do": absolute ban on `git clean` and on recursive deletes under
  `data/` (agent-wide, mirrors the 2026-08-11 worker git-ban).
- Nightly local `data/` backup task (dated zip, retention) installed alongside the release's
  scheduled tasks; off-machine backup target recommended to Victor as follow-up (same-disk
  backups protect against deletion, not disk failure).

## Facts (verified first-hand, read-only)

- Detected by `tests/test_lab_scorecard.py::test_backtest_signals_are_actually_registered_in_the_repo_ledger`
  failing in both the focused selection (1 failed / 1750 passed) and full suite (1 failed / 2491
  passed) on 2026-08-13. The test is a live-ledger invariant and is CORRECT — it is the canary,
  not the defect. All five `BACKTEST_SIGNAL_IDS` report `n_trials == 0`.
- `data/lab`, `data/output` (including every subdirectory), `data/raw`, `data/runs`: EMPTY.
  Directory mtimes all 2026-08-13 00:42 (also the repo-root mtime). `data/intermediate` was
  recreated 08:02 by some later process (`ensure_runtime_dirs` pattern).
- Survivors: `data/manual` (tracked in git, mtime Jun 3 unchanged), `venv/`, `.scratch/`
  (gitignored, mtime Aug 12 20:53), `naukri.md`.
- Recycle Bin: no matching entries — deletion bypassed the shell.
- No archive/moved copy found under `C:\Users\Emanuel\code` siblings; no `data*.bak`.
- Signature analysis: exactly the git-ignored contents *inside `data/`* were removed; tracked
  files inside `data/` survived; ignored trees outside `data/` (venv, .scratch) survived. This
  matches a `git clean -fdx`-style operation scoped to `data/` (or an equivalent scripted
  recursive delete), executed at 00:42 — within the overnight Codex session window whose own
  release-gate notes record activity before its execution quota was exhausted. Attribution is
  inferred from the evidence pattern, not from a transcript.
- Data was verifiably intact through ~22:00 on 2026-08-12 (the complementary review's journeys
  agent read real Tool D parquets; the 19:30 scheduled refresh published a dual-source
  generation at 19:32).

## Loss classification

| Class | Contents | Recoverable? |
|---|---|---|
| Current-state artifacts | Tools A–D outputs, ticker-page artifacts, option snapshots, portfolio pipeline outputs | YES — one real refresh (free APIs) rebuilds today's state |
| Deterministic history | Lab backfill (~36k vintage rows derived from historical prices) | YES — rerun backfill command |
| Ledger registrations | Lab pre-registration entries (configs live in committed code) | YES — re-register (n_trials discipline preserved by re-registering the same committed configs) |
| Perishable PIT history | Daily option-chain history since ~June (deliberate keep-the-chain decision), Lab LIVE vintage accruals since June (2031-verdict clock), run archive + replay manifests | NO — only via filesystem-level recovery (VSS/Previous Versions/backup) |

## Recovery options (Victor's decision)

1. RECOMMENDED FIRST: Volume Shadow Copy / "Previous Versions" check from an ELEVATED terminal
   (`vssadmin list shadows`; then mount/copy `data\` from the newest pre-00:42 shadow). Time
   matters: copy-on-write churn ages shadows. Disable the legacy 16:00/19:30 scheduled tasks
   before attempting, so nothing writes mid-recovery.
2. Any external backup of `Golden-Vector\data` (OneDrive/File History/manual copy) supersedes.
3. If unrecoverable: rebuild (refresh + lab backfill + re-registration) and record a permanent
   provenance note that option-chain history and live Lab vintages restart 2026-08-13; the Lab
   scorecard's accrual gap must be labelled in the UI provenance, not silently absorbed.

## Prevention (to implement regardless of recovery outcome)

- AGENTS.md + CLAUDE.md: absolute ban on `git clean` (any flags) and on any recursive delete
  under `data/` by agents; mirrors the existing worker git-ban learned 2026-08-11.
- Nightly automated backup of `data/` (even a dated zip to a second location makes this class
  of incident a non-event). Decision + mechanism pending Victor.
- The rebuilt pipeline already writes immutable run-stamped artifacts; consider periodic
  off-tree sync of `data/runs` + `data/lab` + options history specifically.

## Impact on the in-flight release

The Phase 5/6 overlay itself is unaffected (code + tests are file-based; 1 failed / 2491 passed
is exactly the canary). The bounded review's 16 fixes stand. The release gate resumes at step 7
(real refresh) only after the recovery decision; the browser pass and task installation follow.
