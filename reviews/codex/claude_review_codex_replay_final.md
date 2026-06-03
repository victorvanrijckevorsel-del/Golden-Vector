# Claude Review: Codex Replay Manifest — Final (Checkpoint C)

**Reviewer:** Claude Code
**Date:** 2026-05-29
**Commits since last review:** `fa81bcb` (review fixes), `3449290` (step 5), `5e57ccd` (step 6)
**Total commits in milestone:** 7 (steps 1–6 + review fixes)
**Grade:** **READY**

## TL;DR

All three review findings from the steps 2-4 pass were addressed exactly as recommended. Step 5 added a meaningful end-to-end fixture test. Step 6 produced an honest, well-written audit doc update. Full suite at 323 (baseline 306 + 17 new). Verify command works live on a real historical run. **The milestone is ready to merge to main.**

## Review depth

- Read all three new commits' full diffs end-to-end
- Read the completion report's 8 sections and cross-checked claims
- Re-ran the full suite independently (323 passed)
- Re-ran `verify-replay` on a real historical run folder
- AST-based unused-import + Unicode + whitespace audit across all 7 touched files

## ✅ All three previous-review findings — verified fixed

### Finding 1 (must-fix): duplicate `_write_metadata` calls

Codex's fix matches **Option B** from my recommendation exactly. `run_context.py:80-83`:

```python
try:
    write_initial_replay_manifest(context)
finally:
    context._write_metadata(status="RUNNING", summary={}, notes=["Run created."])
```

The try/finally makes the defensive intent explicit: metadata is written **regardless** of whether the manifest write raises. No more accidental-looking duplicate. ✅

### Finding 2 (should-fix): no-checkout fallback for `_current_checkout_drift_findings`

`replay_manifest.py:320-323`:

```python
def _current_checkout_drift_findings(manifest: dict[str, Any]) -> list[str]:
    try:
        repo_root = ProjectPaths.discover().repo_root
    except Exception:
        return ["unavailable - no current checkout context"]
```

Plus a new test (`test_verify_replay_cli_handles_missing_checkout_context`) that monkeypatches `ProjectPaths.discover` to raise and asserts the expected message + exit 0. ✅

### Finding 3 (cosmetic): ASCII markers documented as intentional

`cli.py:1183`:

```python
# ASCII markers stay readable in older Windows terminals.
marker = "[OK]" if asset.status == "ok" else "[FAIL]"
```

Plus the completion report §2 explicitly names this as deviation 2. The choice is now annotated rather than silent. ✅

## ✅ Step 5 — fixture integration smoke test

`test_fixture_tool_a_run_with_foundation_replay_manifest_verifies` does exactly what step 5 called for:

1. Builds fixture paths (no external APIs)
2. Calls `RunContext.start()` — triggers phase 1 via the wiring
3. Calls `update_manifest_with_foundation` — phase 2
4. Calls `run_verify_replay(paths, run_id_or_path=context.run_id)` — the actual CLI function
5. Asserts exit 0, "[OK] foundation_manifest.json - sha256 matches recorded", and "Verdict: OK."

End-to-end phase-1 + phase-2 + verify round-trip in one test. No external network. Matches plan §4 step 5's intent. ✅

## ✅ Step 6 — `docs/snapshot_retention_audit.md` update

The doc now correctly:
- Headers itself as updated 2026-05-29 after the milestone
- States the gap is closed for runs from this milestone forward
- Explicitly says historical pre-manifest runs are not backfilled and explains why ("using today's code/config/manual data would create false provenance")
- Points users at `verify-replay` as the integrity command
- Distinguishes "what's retained for historical runs" (parquet snapshots) from "what's retained for new runs" (replay manifests with full provenance)
- Forward-looks: future model-specific provenance (artifact hash, feature snapshot hash, training window, random seed) would be a separate addition, not another retention layer

Well-written. No exaggeration about what was solved. ✅

## ✅ Live smoke test on a real historical run

```
$ python main.py verify-replay 20260424T191957Z-tool-a-f6e2bbf9

Replay manifest: ...\data\runs\20260424T191957Z-tool-a-f6e2bbf9\replay_manifest.json

Snapshot integrity:
  [INFO] run predates replay manifests

Code state at run time:
  unavailable - no replay manifest exists for this run

Drift since run:
  unavailable - no replay manifest exists for this run

Verdict: PREDATES REPLAY MANIFEST. This older run has no replay manifest to verify.

Exit code: 0
```

Exit 0 for the predates case (so monitoring/scripts don't false-alarm on old runs), with a clear human message. ✅

## ✅ Test deltas + commit hygiene

| Metric | Result |
|---|---|
| Baseline (pre-milestone) | 306 passed |
| Step 1 | 313 (+7) |
| Step 2 | 314 (+1) |
| Step 3 | 316 (+2) |
| Step 4 | 321 (+5) |
| Review fixes | 322 (+1) |
| Step 5 | 323 (+1) |
| Step 6 | 323 (no new tests, doc-only) |
| **Final total** | **323 passed** |
| Net new tests | **+17** |
| Test count regressions | 0 |
| Commits | 7 total, each cleanly scoped |
| Progress log committed alongside | Yes, every step |
| Unicode preservation | Clean (cli.py's 5 unicode chars are pre-existing) |
| Stray whitespace | Clean across all 7 touched files |
| Unused imports | Clean (1 pre-existing `execute_horizon_pipeline` in cli.py — not introduced here) |

## Completion report quality

Codex's `codex_replay_manifest_completion_report.md` covers all 8 sections I asked for in plan §10, with the right level of honest detail:

| Section | Quality |
|---|---|
| 1. File changes | Complete, with line counts |
| 2. Deviations | All five deviations called out with `file:line` references and reasoning |
| 3. Hard-fail vs. best-effort | Two clean lists, matches what's actually in code |
| 4. Schema example | Real manifest JSON pasted (not a sketch) — useful for any future verifier |
| 5. Verify output example | Real terminal output pasted |
| 6. Test deltas | Baseline + final pass count + new test file name + modified files |
| 7. Edge cases verified | Table of 16 edge cases with test names — easy to audit |
| 8. Open questions | Three forward-looking notes, none blocking |

The three "open questions" are reasonable forward-look observations, not unfinished work:
- Stricter manifest schema validation (deferred — outside v2 plan)
- Silent return when phase-1 manifest can't be read (I accepted this earlier; consistent with previous decision)
- Predictive-model provenance fields (forward-looking; correctly out of scope until the first predictive model lands — matches the [[inflight-planning-tool-c-d]] sequencing)

## Acceptance criteria from plan v2 §5 — all met

| Criterion | Status |
|---|---|
| Every new run produces `replay_manifest.json` and `replay_snapshots/` | ✅ Wired in `RunContext.start()` |
| Manifest contains all required fields | ✅ Verified via real fixture JSON |
| `verify-replay` returns 0 on pristine + non-zero on tampered | ✅ Tests + live check |
| Run doesn't fail if git is unavailable | ✅ Test 2 covers it |
| Run doesn't fail if manual SQLite is missing | ✅ Test 4 covers it |
| Full suite passes including 6 new tests in `tests/test_replay_manifest.py` | ✅ +17 new tests, all green |
| `docs/snapshot_retention_audit.md` updated | ✅ Step 6 |

All seven met. No outstanding items.

## Verdict

**Grade: READY.** The milestone is done. No fixes required.

This is the cleanest milestone we've shipped — no scope creep, no surprise behaviors, all review findings addressed exactly as recommended, completion report is precise.

## Next step for Emanuel

Per the CLAUDE.md milestone workflow:
1. Push `dev-vic` to GitHub
2. Switch to `main`, pull latest, merge `dev-vic` into `main`
3. Push `main`
4. Delete remote `dev-vic` (`git push origin --delete dev-vic`)
5. Recreate local `dev-vic` from `main` to continue working

Once `main` is updated, I'll write the **Tool C / Tool D plan** per the direction locked in 2026-05-29 ([[inflight-planning-tool-c-d]]). Tool C is the bigger piece (three downside metrics + composite + new pipeline + new overview page + new detail-page lens); Tool D is smaller (mostly arithmetic over existing Tool B inputs).
