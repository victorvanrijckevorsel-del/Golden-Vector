# Plan: Replay Manifest

**Author:** Claude Code
**Branch:** `dev-vic`
**Date:** 2026-05-28 (v2 after Codex review)
**Reviewer:** Codex — graded `NEEDS CHANGES` on v1; v2 addresses every finding
**Related:** [docs/snapshot_retention_audit.md](../../docs/snapshot_retention_audit.md), [reviews/codex/codex_review_claude_replay_manifest_plan.md](codex_review_claude_replay_manifest_plan.md)

## v2 changelog (against Codex review)

| Codex finding | Where addressed |
|---|---|
| R1 — best-effort scope too broad | §2a narrows best-effort to git-unavailable / dirty / missing-manual-DB only. Config-not-found or manifest-write-failure now hard-fail with a clear error. |
| R2 — SQLite backup defensive details | §2c specifies read-only URI, 5-second timeout, atomic temp-then-move, fail-not-null on lock. |
| R3 — `verify-replay` for moved folders | §3 now accepts either a run id (resolved under `data/runs/`) or a direct path. Output explicitly separates "snapshot integrity" from "current-checkout drift unavailable" when those checks can't run. |
| **R4 — BLOCKER: foundation_run_consumed timing** | §2c is rewritten as a **two-phase write**: phase 1 at `RunContext.start()` (configs + manual + git), phase 2 at the three `_load_latest_foundation_snapshot()` callsites in `cli.py` (foundation manifest copy + run id). §2b schema updated with `foundation_run_consumed.manifest_path` for the immutable copy. |
| R5 — no backfill, no placeholders | §2a confirms forward-only. §3 specifies the `verify-replay` error wording for old folders: "run predates replay manifests." |
| AF1 — `RunContext.start()` covers more commands than I listed | §2a now explicitly lists all 7 commands: update-data, tool-a, tool-b, combined, manual-data, manual-note, compare-horizons. §2c handles the `manual-data init` edge case where the DB doesn't exist yet at start. |
| AF2 — config list should not duplicate `load_app_config` | §2c reuses `load_app_config`'s `expected_files` constant rather than hardcoding the 5 names in a second place. New test asserts the manifest config list equals `load_app_config`'s. |
| AF3 — step 4 calls external market data | §4 step 4 is now fixture-based only. External-API smoke check is documented as opt-in and not part of the implementation pass. |

---

## 0. The simplest thing that could work

> **A new `RunContext.write_replay_manifest()` method, called once at the start of every run, that (a) SHA-256-hashes the 5 config YAMLs and the manual SQLite DB, (b) copies them into `data/runs/<run_id>/replay_snapshots/`, (c) records the git commit + dirty flag, and (d) writes `data/runs/<run_id>/replay_manifest.json` listing everything. Plus a `verify-replay <run_id>` CLI command that confirms the manifest is self-consistent and reports drift vs. current working state. ~150 lines of code, ~6 tests, one new CLI subcommand. No new pipelines, no architecture change.**

Everything below is justification, edge-case handling, and explicit decisions on top of that baseline.

---

## 1. Current state (verified 2026-05-28)

### What already exists
- `golden_vector/app/run_context.py` (129 lines) — `RunContext` dataclass with `start()`, `write_json()`, `record_artifact()`, `finalize()`. Already creates `data/runs/<run_id>/metadata.json`.
- `data/runs/<run_id>/` already contains `metadata.json`, `config_summary.json`, `foundation_snapshot_summary.json`, `qa_summary.json`, `run.log`, output summaries.
- `data/runs/<run_id>/snapshots/` (for update-data runs only) already contains raw + normalized foundation parquet.
- `metadata.json` already records `config_hash` (a single hash), but no copy of the configs themselves and no per-config hashes.

### Concrete sizes (small — replay snapshot is essentially free)
| Asset | Size |
|---|---:|
| `config/horizons.yaml` | 221 B |
| `config/qa.yaml` | 339 B |
| `config/scoring.yaml` | 1.1 KB |
| `config/screening_params.yaml` | 1.0 KB |
| `config/universe.yaml` | 12.9 KB |
| `config/*.yaml` total | **15.5 KB** |
| `data/manual/screening/manual_screening.sqlite3` | **208 KB** |
| **Total replay payload per run** | **~225 KB** |

67 retained runs × 225 KB ≈ **15 MB total** if backfilled. Trivial vs. the parquet snapshots already retained.

### What the audit (step 1) explicitly said is missing per run
From [docs/snapshot_retention_audit.md](../../docs/snapshot_retention_audit.md) §"What Is Not Fully Retained":
1. Full loaded application config (only a summary is kept)
2. Exact code revision (Git commit)
3. Immutable copy of the foundation manifest used by the run
4. Manual-data store snapshot or version reference for Tool B

The replay manifest addresses all four.

---

## 2. Design

### 2a. Decisions locked

| Decision | Choice | Why |
|---|---|---|
| File location | `data/runs/<run_id>/replay_manifest.json` + sibling `data/runs/<run_id>/replay_snapshots/` directory for bulk content | Keeps JSON small + grep-able; bulk content sits next to it. |
| Hash + snapshot strategy | Both: store SHA-256 in manifest AND copy file into `replay_snapshots/` | Hash alone = future-you must trust the path; snapshot alone = future-you must re-hash to verify. Together they self-check. |
| When to write | **Two phases.** Phase 1 at `RunContext.start()` writes the configs + manual + git portion. Phase 2 fires from the three `cli.py` callsites of `_load_latest_foundation_snapshot()` (lines 479, 618, 1165) and updates the manifest with `foundation_run_consumed` + a copied `replay_snapshots/foundation_manifest.json`. | Per Codex R4: tool-a/tool-b/combined only know which foundation run they consumed AFTER they load it. Phase 1 captures inputs before the run modifies anything; phase 2 captures the foundation pointer the moment it's resolved. |
| Which run types | All 7 commands that go through `RunContext.start()`: **update-data**, **tool-a**, **tool-b**, **combined**, **manual-data** (incl. `init` subcommand), **manual-note**, **compare-horizons**. Phase 2 only runs on commands that consume a foundation snapshot (tool-a, tool-b, combined). | No flag. Simple rule = fewer bugs. |
| `manual-data init` edge case | If the manual SQLite doesn't exist at phase-1 time, record `manual_data: null` in the manifest. The init command will create it during the run; we don't retroactively snapshot. | Honest signal. The `init` run is bootstrap; there's no "before-state" to capture. |
| SQLite snapshot method | `sqlite3.connect("file:<path>?mode=ro", uri=True, timeout=5.0)` for the source connection. `Connection.backup()` into a temp file inside `replay_snapshots/`. `os.replace()` to atomically move into place. Both connections closed via context managers (`with`). | Defensive per Codex R2. Read-only URI prevents accidental writes during backup. Atomic temp-then-move prevents half-written snapshots on crash. |
| SQLite locked failure | If `sqlite3.OperationalError("database is locked")` (or backup times out), **fail the manifest with an explicit warning**. Do NOT silently record `manual_data: null`. | Per Codex R2. Silent null would create a false "successful" run with the audit gap unfixed. |
| Best-effort vs. hard-fail (Codex R1) | **Best-effort (never fail run):** git unavailable, working tree dirty, manual DB absent (manual-data init case). **Hard-fail (raise from `RunContext.start()`):** a required config file is missing, a snapshot copy fails, the manifest JSON write fails, or SQLite is locked. | Per Codex R1. A "successful" run with no manifest is worse than a failed run. The acceptance criterion is "every new run produces a manifest." |
| Phase 1 vs. Phase 2 failure isolation | Phase 1 failure → run fails (because the run is just starting). Phase 2 failure → log a clear warning into `run.log` and the run metadata, finalize the manifest with `foundation_run_consumed: null, foundation_load_status: "<reason>"`, and proceed. The foundation load itself is what truly matters; the manifest update is a satellite. | A failed phase 2 doesn't mean the pipeline failed; it means the manifest is incomplete. Better to record honestly than crash a working tool-a run. |
| Git unavailable case | Record `git: {commit: null, dirty: null, unavailable_reason: "<reason>"}`. Do not fail. | Replay manifest is a best-effort improvement. |
| Working tree dirty | Record `git.dirty: true` honestly. Do not fail. Verify command warns. | Honest signal, don't block work. |
| Backfill historical runs | **No.** Forward-only. No placeholder manifests for old runs either (per Codex R5). | Backfill with today's commit/config/manual state would create false provenance. Fake uniformity is worse than no manifest. `verify-replay` for old runs returns a clear "run predates replay manifests" message. |
| Schema versioning | `manifest_version: 1` field in the JSON | Forward-compatible. Future bumps are explicit. |
| Verify command output | Human-readable text with ✓/✗ markers (not JSON). Three clearly-separated sections: "Snapshot integrity", "Code state at run time", "Drift since run". When the current checkout is unavailable (verifying on a different machine), the "Drift" section says "Drift checks unavailable — no current checkout context" rather than failing. | Per Codex R3. CLI is for humans. The three sections answer three different questions; mixing them is confusing. |

### 2b. Manifest schema (concrete)

```json
{
  "manifest_version": 1,
  "run_id": "20260528T140753Z-tool-a-6175c3fb",
  "command": "tool-a",
  "started_at_utc": "2026-05-28T14:07:53Z",
  "git": {
    "commit": "1c195d3abc456def...",
    "dirty": false,
    "unavailable_reason": null
  },
  "configs": [
    {
      "name": "horizons.yaml",
      "original_path": "config/horizons.yaml",
      "snapshot_path": "replay_snapshots/configs/horizons.yaml",
      "sha256": "abc123..."
    },
    { "name": "qa.yaml", "...": "..." },
    { "name": "scoring.yaml", "...": "..." },
    { "name": "screening_params.yaml", "...": "..." },
    { "name": "universe.yaml", "...": "..." }
  ],
  "manual_data": {
    "original_path": "data/manual/screening/manual_screening.sqlite3",
    "snapshot_path": "replay_snapshots/manual_screening.sqlite3",
    "sha256": "def456..."
  },
  "foundation_run_consumed": {
    "run_id": "20260528T140000Z-update-data-cd2219fc",
    "manifest_original_path": "data/intermediate/status/latest_foundation_manifest.json",
    "snapshot_path": "replay_snapshots/foundation_manifest.json",
    "manifest_sha256": "ghi789..."
  },
  "foundation_load_status": "captured"
}
```

Notes on the schema:
- `foundation_run_consumed` is `null` for commands that don't consume a foundation snapshot: **update-data**, **manual-data**, **manual-note**, **compare-horizons**. It is populated for **tool-a**, **tool-b**, **combined**.
- `foundation_load_status` is one of: `"not-applicable"` (commands that don't consume foundation), `"captured"` (phase 2 succeeded), or a short error string if phase 2 failed (per Codex R4's two-phase design).
- `foundation_run_consumed.snapshot_path` points to the **immutable copy** of the foundation manifest inside this run folder. This is the key change from v1 — we now keep the manifest content, not just its hash. Closes the audit's "foundation manifest is a moving pointer" gap.
- All `*_path` values: `original_path` is relative to repo root; `snapshot_path` is relative to the run folder. This holds up even if the run folder is moved or copied to another machine.
- All hashes are lowercase hex `sha256`.

### 2c. Code changes (file-by-file)

#### New file: `golden_vector/app/replay_manifest.py` (~130 lines)

Responsibilities:
- Compute SHA-256 of a file (streaming).
- Detect git commit + dirty state via `subprocess` with a 5-second timeout. Capture failure modes cleanly.
- Snapshot the configs (using `load_app_config()`'s `expected_files` constant — per Codex AF2, no duplicated list) and the manual SQLite into `<run_dir>/replay_snapshots/`.
- Compose and write `<run_dir>/replay_manifest.json`.
- Provide a phase-2 update function that patches the manifest with `foundation_run_consumed` + the foundation manifest copy.
- Provide `read_manifest()` and `verify_manifest()` for the CLI command.

Public API:
```python
def write_initial_replay_manifest(run_context: RunContext) -> Path:
    """Phase 1: write configs + manual + git portion of the manifest at RunContext.start().
    Hard-fails (raises) if a required config is missing, snapshot copy fails, SQLite is locked,
    or the manifest JSON write fails. Best-effort (does NOT raise) for git unavailable, dirty
    working tree, or missing manual DB.
    """

def update_manifest_with_foundation(
    run_dir: Path,
    *,
    foundation_run_id: str,
    foundation_manifest_path: Path,
) -> None:
    """Phase 2: copy the foundation manifest into replay_snapshots/foundation_manifest.json,
    hash it, and patch the existing replay_manifest.json's `foundation_run_consumed` block.
    Best-effort: on failure, records foundation_load_status with the error string and proceeds.
    """

def read_manifest(run_dir_or_id: Path | str) -> dict: ...
def verify_manifest(run_dir_or_id: Path | str) -> "VerifyResult": ...
```

`VerifyResult` is a small dataclass holding per-asset status, drift findings (when current checkout is available), and a top-level verdict string. When called with a `str`, it's treated as a run id and resolved under `data/runs/`; when called with a `Path`, it's treated as a direct path (supports moved folders per Codex R3).

**SQLite snapshot implementation** (per Codex R2 defensive details):
```python
src_uri = f"file:{manual_db_path}?mode=ro"
tmp_dst = snapshot_dir / "manual_screening.sqlite3.tmp"
with sqlite3.connect(src_uri, uri=True, timeout=5.0) as src_conn, \
     sqlite3.connect(tmp_dst) as dst_conn:
    src_conn.backup(dst_conn)
os.replace(tmp_dst, snapshot_dir / "manual_screening.sqlite3")
```

#### Edit: `golden_vector/app/run_context.py` (~5 lines)

Add one call inside `RunContext.start()`, after `_write_metadata("RUNNING", ...)`:

```python
from golden_vector.app.replay_manifest import write_initial_replay_manifest
# at the end of start(), after _write_metadata:
write_initial_replay_manifest(context)  # raises on hard-fail conditions per §2a
```

No try/except wrap — the function itself decides what's best-effort and what's hard-fail (per Codex R1). That is the *only* edit to `run_context.py`.

#### Edit: `golden_vector/cli.py` — phase 2 hook + new subcommand

**Phase 2 hook** at the three `_load_latest_foundation_snapshot()` callsites (verified at lines 479, 618, 1165 in current `cli.py`):

```python
foundation_snapshot = _load_latest_foundation_snapshot(...)
# immediately after:
update_manifest_with_foundation(
    run_dir=context.run_dir,
    foundation_run_id=foundation_snapshot.run_id,
    foundation_manifest_path=paths.latest_foundation_manifest_path,
)
```

**New subcommand** `verify-replay`:
```
python main.py verify-replay <run-id-or-path>
```
Reads the manifest, calls `verify_manifest()`, prints a human-readable report. Returns non-zero exit code if any snapshot file is missing or any hash mismatches. For run folders that predate replay manifests, returns 0 with a clear "run predates replay manifests" message (per Codex R5).

#### Tests: `tests/test_replay_manifest.py` (~200 lines, ~10 test functions)

Test fixtures must NOT call external APIs (per Codex AF3). Use tmp_path + a synthesized minimal config + a synthesized empty manual SQLite.

| Test | What it covers |
|---|---|
| `test_phase1_creates_manifest_and_snapshots` | Happy path: manifest JSON exists, all expected fields present, all 5 config snapshots + manual DB snapshot exist, all sha256 fields match real file hashes. |
| `test_phase1_handles_missing_git_gracefully` | Mock `subprocess.run` to raise `FileNotFoundError`. Manifest still written with `git.unavailable_reason` set. No exception. |
| `test_phase1_records_dirty_working_tree` | Create a temp git repo with an unstaged change. Manifest records `git.dirty == true`. No exception. |
| `test_phase1_handles_missing_manual_db_for_init` | When manual SQLite is absent, manifest records `manual_data: null`. No exception. |
| `test_phase1_hard_fails_on_missing_config` | If `config/scoring.yaml` doesn't exist, `write_initial_replay_manifest` raises. (Per Codex R1.) |
| `test_phase1_hard_fails_on_locked_sqlite` | Simulate a locked SQLite source. `write_initial_replay_manifest` raises with a clear "database is locked" error. (Per Codex R2.) |
| `test_phase2_updates_foundation_block` | Write phase-1 manifest, call phase-2 update, confirm `foundation_run_consumed` populated and `replay_snapshots/foundation_manifest.json` exists with matching hash. |
| `test_phase2_failure_records_status_not_raise` | When phase 2 can't copy the foundation manifest, the run does not crash; manifest records `foundation_load_status` with the error string. |
| `test_verify_passes_for_pristine_manifest` | Round-trip: write phase 1 + phase 2, immediately verify, expect "OK" verdict. |
| `test_verify_detects_corrupted_snapshot` | Write a manifest, mutate one snapshot file, verify detects the hash mismatch and returns non-zero. |
| `test_verify_handles_moved_folder` | Verify accepts a direct Path arg (folder moved outside `data/runs/`) and works. |
| `test_verify_reports_predates_for_old_run` | Verify on a run folder with no manifest returns 0 with "run predates replay manifests" message (per Codex R5). |
| `test_manifest_config_list_matches_load_app_config` | Per Codex AF2: assert the configs the manifest snapshots equal the keys in `load_app_config`'s `expected_files`. Prevents drift if a future config YAML is added. |

---

## 3. The verify command — what the user sees

```
$ python main.py verify-replay 20260528T140753Z-tool-a-6175c3fb

Replay manifest: data/runs/20260528T140753Z-tool-a-6175c3fb/replay_manifest.json
Manifest version: 1
Command: tool-a
Started: 2026-05-28T14:07:53Z

Snapshot integrity:
  ✓ horizons.yaml             — sha256 matches recorded
  ✓ qa.yaml                   — sha256 matches recorded
  ✗ scoring.yaml              — SHA256 MISMATCH (snapshot has been edited)
  ✓ screening_params.yaml     — sha256 matches recorded
  ✓ universe.yaml             — sha256 matches recorded
  ✓ manual_screening.sqlite3  — sha256 matches recorded

Code state at run time:
  Git commit recorded: 1c195d3abc456def...
  Working tree at run: clean
  Current HEAD:        4f8e9d2... (DIFFERS — replay would need: git checkout 1c195d3abc)

Drift since run:
  ✗ config/scoring.yaml has changed since the run (current ≠ snapshot).
  ✓ All other configs match current files.
  ✗ Manual data has changed since the run (current ≠ snapshot).

Verdict: SNAPSHOT INTEGRITY FAILED. One snapshot file's hash does not match
the manifest record. The run folder has been modified after the run completed.
```

The output cleanly distinguishes three things:
1. **Snapshot integrity** — were the snapshot files in the run folder tampered with?
2. **Code state** — does today's HEAD match the run's commit?
3. **Drift** — does today's working tree match what the run saw?

---

## 4. Order of operations

| # | Step | Test gate |
|---|---|---|
| 1 | Add `golden_vector/app/replay_manifest.py` with `write_initial_replay_manifest`, `update_manifest_with_foundation`, `read_manifest`, `verify_manifest`, `VerifyResult`. **No callers yet.** Tests 1-6 from §2c (phase-1 happy path, git-unavailable, dirty tree, missing manual DB, missing config hard-fail, locked SQLite hard-fail) + test 13 (config list sync with `load_app_config`). | Suite green. New tests pass. |
| 2 | Wire `RunContext.start()` to call `write_initial_replay_manifest(context)`. Per §2a, the function decides what's best-effort vs. hard-fail; no try/except wrap at the call site. | Suite green. **Fixture smoke:** use a test fixture or short synthesized run (NOT a real `update-data` external call) to confirm a replay manifest appears in the run folder. |
| 3 | Add phase-2 hook at the three `_load_latest_foundation_snapshot()` callsites in `cli.py` (lines 479, 618, 1165 in current code — verify before editing). Tests 7-8 from §2c (phase-2 happy path + failure-records-status). | Suite green. |
| 4 | Add `verify-replay <run-id-or-path>` CLI subcommand. Tests 9-12 from §2c (pristine, corrupted, moved folder, predates-message). | Suite green. |
| 5 | Fixture-based integration smoke: write a synthesized tool-a run with phase 1 + phase 2, verify it, confirm zero exit code. **Do NOT call real `update-data` — that hits external APIs per Codex AF3.** External-API smoke is opt-in only and stays out of the implementation pass. | Suite green. Manual fixture smoke captured in the progress log. |
| 6 | Update `docs/snapshot_retention_audit.md` to note: (a) the gap is closed for runs from this commit forward, (b) historical runs predate replay manifests, (c) the `verify-replay` command exists. | Suite green. |

Each step is a single commit. Codex stops if any step breaks tests. Per workspace-split learnings: commit the progress log alongside each step.

### 4a. Optional opt-in step (NOT in this milestone)

After Emanuel explicitly approves the cost/risk of external market-data calls:
- Run real `python main.py update-data` → `tool-a` → `tool-b`.
- Call `verify-replay` on each. All should return zero.
- Confirm `foundation_run_consumed` is populated correctly across the chain.

This is a manual user-led validation, not part of the implementation commits.

---

## 5. Acceptance criteria

The work is done when all of the following hold:
- Every new run produces a `replay_manifest.json` and a `replay_snapshots/` directory.
- The manifest contains the seven concrete fields from §2b (manifest_version, run_id, command, started_at_utc, git, configs, manual_data, foundation_run_consumed).
- `python main.py verify-replay <run_id>` returns exit code 0 on a freshly-produced run, and non-zero (with a clear ✗ line) when any snapshot is tampered.
- A run does NOT fail if git is unavailable. It records `git.unavailable_reason` and proceeds.
- A run does NOT fail if the manual SQLite is missing. It records `manual_data: null` and proceeds.
- The full test suite passes, including 6 new tests in `tests/test_replay_manifest.py`.
- `docs/snapshot_retention_audit.md` is updated to reflect the new state.

---

## 6. Out of scope (deliberately)

These are NOT part of this work:
- Actual replay command (`python main.py replay-run <run_id>`) — re-running the pipeline against historical state. Bigger surface area; separate milestone.
- Backfilling historical runs.
- Encrypting or compressing snapshots.
- Cleanup / retention policy for old replay snapshots (we'll deal with disk pressure if it ever happens — 225 KB/run is essentially free).
- A web UI for browsing manifests.
- Cross-machine reproducibility (Python version pinning, OS pinning). The manifest captures what THIS machine had; cross-machine replay is a future concern.

---

## 7. Risks Codex should pry at

Specifically push back on these:

1. **Best-effort failure handling.** I'm proposing the replay manifest write never crashes a run. Is that the right call, or should `update-data` fail hard if it can't create the manifest? Tradeoff: hard-fail = stronger guarantee but creates a new failure mode for working pipelines.
2. **SQLite backup semantics.** Is `sqlite3.connect().backup()` actually safe when the source is a real on-disk DB the workspace might be writing to concurrently? Or do we need a lockfile? Runs in this project are sequential CLI invocations, but the workspace server is also a writer.
3. **Snapshot path interpretation.** I made `original_path` repo-root-relative and `snapshot_path` run-dir-relative. Does that hold up if the run folder is moved or the repo is renamed?
4. **Schema for `foundation_run_consumed`.** For `update-data` runs, this is `null`. For `tool-a` / `tool-b` / `combined`, it points at the foundation run id they consumed. **Self-review finding (2026-05-28):** the data is already accessible — every existing tool-a/tool-b run writes `foundation_snapshot_summary.json` with a `refresh_run_id` field that captures exactly this. So the question is just *when* the manifest writer reads it. Two options: (a) `RunContext` carries a `foundation_run_consumed` field set by the caller after foundation load, OR (b) the manifest writer reads `foundation_snapshot_summary.json` if present and ignores it otherwise. Option (b) is simpler and avoids touching `RunContext`'s constructor signature. Codex: please pick one.
5. **Forward-only choice.** I'm proposing no backfill. Is that the right call, or should we backfill with explicit "predates replay manifests" placeholder records so the verify command works uniformly across all run folders?

---

## 8. Why this plan is shaped this way

| Principle | How it shows up |
|---|---|
| Simplest thing first | §0 states the no-frills version. Each extra is called out. |
| Match rigor to risk | Data/infrastructure work → full plan + Codex review (right rigor). |
| No premature abstraction | One module, one CLI subcommand, ~200 lines. No registry, no plugin system, no framework. |
| Don't redo work | Reuses `RunContext`, `data/runs/<run_id>/` pattern, existing run lifecycle, `load_app_config`'s `expected_files`. |
| Honest about limitations | §0, §2a, §6 each call out what this does NOT solve. |
| Verifiable | The verify command is part of the milestone, not a future task. Without it, we wouldn't know the writer works. |
| Plain English | Section headers describe what's being decided, not just what's being done. |

---

## 9. Implementation guidance (this section is for Codex to follow during coding)

Treat this section as the operational brief. Same rules that worked for the workspace split, tightened for a smaller piece of work.

### Git workflow
- All work on branch `dev-vic`. Confirm with `git branch --show-current`.
- One commit per step. Six steps → six commits.
- Commit message format: `replay manifest step <N>: <one-line description>`
- Commit the progress log alongside each step (two files per commit).
- No amend, no rebase, no force-push, no skip-hooks, no `git push` — Emanuel pushes.
- **One commit = one stated purpose.** If you decide to do additional work mid-step (like a related improvement), commit the planned step first, then commit the new work separately with its own message. (Per the workspace-split step-7-fix lesson.)

### Test gate (between every step)
Command: `python -m pytest -q`. Pass condition: all tests green AND no new warnings AND test count ≥ baseline. Establish the baseline at the start of the session.

If a step breaks tests, STOP. Revert with `git reset --soft HEAD~1`, fix, re-commit. 15-minute fix cap before stopping and reporting.

### Self-review at every step (mandatory)
- **Read your own diff before committing** (`git diff --staged`). Look for unintended edits — whitespace shifts, comment characters changed, type hints drifted, imports left behind. (Per the step-7 Unicode-normalization lesson.)
- **Test count must never decrease.** If pass count drops, that's a STOP — usually a silently-broken import.
- **Confirm the commit's diff matches the step description.** No scope creep on a single commit.

### Progress log (write as you go)
Create `reviews/codex/codex_replay_manifest_progress.md` at start with the baseline. Append one line per step:
```
Step <N> (<step-name>): committed <sha>. Tests: <pass>/<total>. Fixture smoke: <yes/no/n-a>. Notes: <one line>.
```

### Checkpoints — STOP and report at each
- **CHECKPOINT A** — after step 1 (module + tests, no callers yet). Report: tests added, all passing, no behavior change yet. Wait for "continue."
- **CHECKPOINT B** — after step 4 (verify command in place). Report: current behavior, sample of `verify-replay` output. Wait for "continue."
- **CHECKPOINT C** — after step 6 (final). Write the completion report (see §10). Wait for review.

### Out of scope — do NOT do any of these
- Actual `replay-run` command (re-execute pipeline against historical state)
- Backfilling historical runs
- Calling external market-data APIs in any test or smoke check (per Codex AF3)
- Encrypting or compressing snapshots
- Web UI changes
- Anything outside the files named in §2c except `docs/snapshot_retention_audit.md` per step 6

### If anything is ambiguous
Stop and ask. The plan is specific by design. If it doesn't cover your case, that's a signal to pause, not invent.

### Start now
1. Confirm branch: `git branch --show-current` → `dev-vic`
2. Baseline: `python -m pytest -q` and record the pass count
3. Create `reviews/codex/codex_replay_manifest_progress.md` with baseline
4. Re-read this plan v2 (especially the changelog) and confirm all 8 Codex findings are addressed to your satisfaction
5. Begin step 1
6. Stop at **CHECKPOINT A** and report

---

## 10. Completion report (write at CHECKPOINT C)

Write `reviews/codex/codex_replay_manifest_completion_report.md` covering:

1. **Final file changes**: list every file added/modified with final line counts.
2. **Deviations from the plan**: every judgment call not specified, with `file:line` references. If none, say so explicitly.
3. **Hard-fail vs. best-effort behavior — what actually shipped**: list which exception types/conditions hard-fail vs. log-and-continue. Confirm this matches §2a.
4. **Schema example**: paste a real manifest JSON produced by a fixture run, so Claude can see what landed.
5. **Verify output example**: paste a real `verify-replay` text output for a fixture run.
6. **Test deltas**: baseline pass count, final pass count, new test files added, tests modified.
7. **Edge cases verified**: git unavailable, dirty tree, missing manual DB, locked SQLite, phase-2 failure, moved folder, predates-message. Tick each with the test name that proves it.
8. **Open questions for the reviewer**: anything you want Claude to look at specifically.

Keep it short and structured — Claude will use it as a guided tour of the diff.
