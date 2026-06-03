# Claude Review: Codex Replay Manifest Steps 2–4 (Checkpoint B)

**Reviewer:** Claude Code
**Date:** 2026-05-29
**Commits reviewed:** `87e8d0f` (step 2), `b97a081` (step 3), `f1d760d` (step 4)
**Grade:** **READY WITH MINOR FIXES**

## TL;DR

The plumbing works end-to-end. Every new run produces a replay manifest, foundation-consuming runs patch in the foundation snapshot, and `verify-replay` correctly handles four cases (OK, corrupted, missing dir, predates). I ran the verify command against a real historical run on disk — it returned the right "PREDATES REPLAY MANIFEST" message with exit 0. Full suite at 321 (baseline 306 + 15 new), all green.

Three minor issues to address before this gets merged, only one of which is actually visible to users.

## Review depth

This time I:
- Read all three commits' diffs end-to-end
- Read the current `run_context.py`, the new test files, the cli.py phase-2 hooks, the new verify-replay code
- **Ran the verify command live** on an existing pre-manifest run folder
- **Ran a fixture wiring check via Python** to confirm `RunContext.start()` actually produces the manifest and records it in artifacts
- Ran the full suite independently — 321 passed
- AST-based unused-import / unicode / whitespace audit across all touched files

## ✅ Verified end-to-end

| Plan element | Verification | Result |
|---|---|---|
| Step 2 — `RunContext.start()` wires the manifest writer | Live fixture run: created RunContext, checked `replay_manifest.json` exists, checked it's in artifacts list | ✅ Manifest created, recorded as artifact |
| Step 3 — phase 2 hook called at the 3 cli.py callsites | Read git diff for all 3 sites (tool-a:488, tool-b:628, compare-horizons:1177) | ✅ All three present, calling `_capture_foundation_for_replay_manifest` immediately after `_load_latest_foundation_snapshot()` |
| Step 3 — uses correct foundation snapshot fields | Read `foundation_snapshot.refresh_run_id` + `.manifest_path` | ✅ Better than plan suggested — uses actual loaded snapshot's manifest path rather than the global moving pointer |
| Step 4 — `verify-replay` CLI command exists | `python main.py verify-replay <real-run-id>` | ✅ Returns correct PREDATES message with exit 0 |
| Step 4 — Output format: 3 sections | Inspected live output | ✅ "Snapshot integrity", "Code state at run time", "Drift since run" all present |
| Step 4 — Exit codes | Tested live | ✅ 0 for OK/PREDATES, 1 for FAIL/missing dir |
| Test count | `python -m pytest -q` | ✅ 321 passed in 225s (baseline 306 + 15) |
| All 15 new tests present | `pytest -v tests/test_replay_manifest.py tests/test_run_context.py` | ✅ All present and passing |
| Commit hygiene | Each commit touches only its scoped files; progress log committed alongside | ✅ Clean |
| Unicode preservation | Per-file count | ✅ N/A — new code |
| Stray whitespace | awk audit | ✅ All clean |
| Unused imports | AST scan | ✅ All clean (one pre-existing `execute_horizon_pipeline` in cli.py — not introduced here, ignore) |

## Live verify-replay output (real historical run)

```
$ python main.py verify-replay 20260424T191957Z-tool-a-f6e2bbf9

Replay manifest: C:\Users\Emanuel\code\Golden-Vector\data\runs\20260424T191957Z-tool-a-f6e2bbf9\replay_manifest.json

Snapshot integrity:
  [INFO] run predates replay manifests

Code state at run time:
  unavailable - no replay manifest exists for this run

Drift since run:
  unavailable - no replay manifest exists for this run

Verdict: PREDATES REPLAY MANIFEST. This older run has no replay manifest to verify.

Exit code: 0
```

Exactly the right behavior for a pre-manifest run: clear message, exit 0, no scary error.

## ⚠ Minor findings

### Finding 1 (real code smell): Duplicate `_write_metadata` calls in `RunContext.start()`

`golden_vector/app/run_context.py:81-84` now reads:

```python
context._write_metadata(status="RUNNING", summary={}, notes=["Run created."])
write_initial_replay_manifest(context)
context._write_metadata(status="RUNNING", summary={}, notes=["Run created."])
return context
```

The two `_write_metadata` calls have **identical arguments**. Each one overwrites `metadata.json`. The functional outcome is correct (the second call captures the manifest artifact added by `write_initial_replay_manifest`), but anyone reading this file will think it's a bug — there's no comment explaining the pattern, and "call this twice with the same args" is a hard-to-justify code shape.

**Likely intent:** defensive — line 81 ensures `metadata.json` exists with RUNNING status before the manifest write, so if `write_initial_replay_manifest` raises, we still have a metadata record. Line 83 captures the artifact afterward.

**Recommended fix:** pick one of these three patterns, all cleaner:

```python
# Option A — single call after, accept that crashed manifest writes mean no metadata.json
write_initial_replay_manifest(context)
context._write_metadata(status="RUNNING", summary={}, notes=["Run created."])

# Option B — try/finally makes the defensive intent explicit
try:
    write_initial_replay_manifest(context)
finally:
    context._write_metadata(status="RUNNING", summary={}, notes=["Run created."])

# Option C — keep both calls but differentiate the notes so the intent is readable
context._write_metadata(status="RUNNING", summary={}, notes=["Run created."])
write_initial_replay_manifest(context)
context._write_metadata(status="RUNNING", summary={}, notes=["Run created.", "Replay manifest written."])
```

I'd lean **Option B** — it makes the defensive contract explicit.

### Finding 2 (deviation from plan): `_current_checkout_drift_findings` does not gracefully handle "no checkout"

Plan v2 §2a said:

> When the current checkout is unavailable (verifying on a different machine), the "Drift" section says "Drift checks unavailable — no current checkout context" rather than failing.

Codex's implementation in `replay_manifest.py:322`:

```python
def _current_checkout_drift_findings(manifest: dict[str, Any]) -> list[str]:
    repo_root = ProjectPaths.discover().repo_root
    findings: list[str] = []
    ...
```

`ProjectPaths.discover()` raises if you're not inside a checkout. There is no try/except wrapping this. So `verify-replay` would crash if run from outside the repo on a moved run folder.

In practice, this is a rare path — `verify-replay` is mostly used locally. But the plan explicitly called for the graceful case, and it's a 5-line fix:

```python
def _current_checkout_drift_findings(manifest: dict[str, Any]) -> list[str]:
    try:
        repo_root = ProjectPaths.discover().repo_root
    except Exception:
        return ["unavailable - no current checkout context"]
    findings: list[str] = []
    ...
```

### Finding 3 (cosmetic): `[OK]` / `[FAIL]` / `[WARN]` ASCII markers instead of ✓/✗ Unicode

Plan §2a said "Human-readable text with ✓/✗ markers (not JSON)." Codex used `[OK]`, `[FAIL]`, `[WARN]`, `[INFO]`. The ASCII choice is actually more cross-platform safe (older Windows terminals struggle with Unicode), but it's a small unannounced deviation from the plan's explicit symbols.

**Recommend:** keep ASCII markers (the cross-platform consideration is real), but note this as a knowing deviation if Codex hasn't already.

## What I verified clean (no findings)

- ✅ All 3 commits cleanly scoped (one purpose per commit, progress log alongside)
- ✅ No scope creep on any commit (unlike the workspace-split step-7 fix)
- ✅ Function body integrity not relevant — this is all new code
- ✅ Test helper `build_test_paths` was sensibly refactored to centralize config copy (saved duplication across tests)
- ✅ Step 3 chose `foundation_snapshot.manifest_path` over `paths.latest_foundation_manifest_path` — that's BETTER than what I suggested in the plan, since it captures the run-local immutable path, not the global moving pointer
- ✅ Phase 2 helper `_capture_foundation_for_replay_manifest` is small, focused, single-responsibility
- ✅ Two-phase tests cover both happy path and failure case (foundation manifest source missing → `error:` status recorded, no raise)
- ✅ Verify exit codes are correct: 0 for OK/PREDATES, 1 for failures
- ✅ `_resolve_verify_replay_run_dir` in cli.py is technically duplicated from `_resolve_run_dir` in replay_manifest.py, but the duplication is small and the cli version correctly uses the injected `paths.runs_dir` instead of `ProjectPaths.discover()`. Defensible.
- ✅ `_format_recorded_git_state` reads the manifest a second time (wasteful — git state isn't in `VerifyResult`), but the result is correct
- ✅ Test count never decreases: 306 → 313 → 314 → 316 → 321
- ✅ Live verify on a real historical run returns the expected PREDATES message

## Verdict

**Grade: READY WITH MINOR FIXES.** Three small fixes:

1. **Finding 1 (must-fix):** clean up the duplicate `_write_metadata` calls — pick a pattern with clearer intent. ~3 line edit.
2. **Finding 2 (should-fix):** add try/except around `ProjectPaths.discover()` in `_current_checkout_drift_findings`. ~5 line edit.
3. **Finding 3 (cosmetic):** confirm the `[OK]`/`[FAIL]`/`[WARN]` deviation from plan's ✓/✗ is intentional (probably yes, for Windows console compatibility).

After these land, the milestone is ready. The acceptance criteria from plan §5 are all met:
- Every new run produces `replay_manifest.json` and `replay_snapshots/` ✅
- Manifest contains all required fields ✅
- `verify-replay` returns 0 on pristine + non-zero on tampered ✅
- Runs don't fail if git is unavailable ✅
- Runs don't fail if manual SQLite is missing ✅
- Full test suite passes ✅
- `docs/snapshot_retention_audit.md` update is step 6 — still to come.

Continue to steps 5 and 6 after addressing findings 1–3. Stop at **CHECKPOINT C** with the completion report.
