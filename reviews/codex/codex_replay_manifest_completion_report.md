# Replay Manifest Completion Report

## 1. Final File Changes

| File | Lines | Change |
| --- | ---: | --- |
| `golden_vector/app/replay_manifest.py` | 363 | New replay manifest writer, phase-2 updater, reader, verifier, and verify result dataclasses. |
| `golden_vector/app/config.py` | 44 | Extracted shared expected config-file list used by config loading and replay snapshots. |
| `golden_vector/app/run_context.py` | 117 | `RunContext.start()` now writes the initial replay manifest and then writes metadata. |
| `golden_vector/cli.py` | 1532 | Added foundation phase-2 capture hooks and `verify-replay` command/output. |
| `docs/snapshot_retention_audit.md` | 61 | Updated audit status after replay manifest milestone. |
| `reviews/codex/codex_replay_manifest_progress.md` | 10 | Recorded baseline, each step, review fixes, and test gates. |
| `tests/helpers.py` | 24 | Shared test path helper now creates a repo-like config fixture. |
| `tests/test_replay_manifest.py` | 280 | New replay manifest unit, CLI, and fixture smoke tests. |
| `tests/test_run_context.py` | 45 | Added `RunContext.start()` manifest smoke test. |

## 2. Deviations From The Plan

- `golden_vector/cli.py:1423`: phase 2 uses `foundation_snapshot.manifest_path` from the loaded snapshot, not `paths.latest_foundation_manifest_path`. This is stricter because it captures the actual manifest object that was loaded.
- `golden_vector/cli.py:1183`: verify output uses `[OK]`, `[FAIL]`, `[WARN]`, and `[INFO]` instead of Unicode check/cross marks. This is intentional for older Windows terminal compatibility.
- `golden_vector/app/run_context.py:80`: the final shape uses `try/finally` around `write_initial_replay_manifest()` so metadata is written even if the manifest hard-fails. This addresses Claude's review finding and makes the defensive behavior explicit.
- `tests/helpers.py:22`: temporary test workspaces copy repo config files by default because `RunContext.start()` now hard-requires config files. This keeps existing fixture tests focused while preserving the production hard-fail rule.
- `golden_vector/cli.py:1140`: `verify-replay` rejects a missing run directory with exit 1. The plan specified predates behavior for existing old run folders, not nonexistent folders.

## 3. Hard-Fail vs. Best-Effort Behavior

Hard-fail:

- Missing required config source during phase 1 raises `FileNotFoundError`.
- Config snapshot copy failure raises.
- Manual SQLite backup lock/error raises.
- Manifest JSON write failure raises.

Best-effort:

- Git unavailable records `git.commit: null`, `git.dirty: null`, and `git.unavailable_reason`.
- Dirty working tree records `git.dirty: true` and does not block the run.
- Missing manual DB records `manual_data: null`; this covers `manual-data init`.
- Phase-2 foundation capture failure records `foundation_load_status: "error: ..."` when the phase-1 manifest can be read and rewritten.
- Drift checks return `unavailable - no current checkout context` if checkout discovery is unavailable.

This matches plan section 2a, plus the explicit no-checkout behavior requested in Claude's steps 2-4 review.

## 4. Schema Example

Fixture manifest produced after phase 1 plus phase 2:

```json
{
  "command": "tool-a",
  "configs": [
    {
      "name": "universe.yaml",
      "original_path": "config/universe.yaml",
      "sha256": "26971094398336d935296058eaa8d00827945d836b9a39b57b9d0969cdd4d5fe",
      "snapshot_path": "replay_snapshots/configs/universe.yaml"
    },
    {
      "name": "horizons.yaml",
      "original_path": "config/horizons.yaml",
      "sha256": "5011e117353c5b0cbc059949ef766d6a7b418d816c64cd3951d76271fe534f8e",
      "snapshot_path": "replay_snapshots/configs/horizons.yaml"
    },
    {
      "name": "qa.yaml",
      "original_path": "config/qa.yaml",
      "sha256": "a4cd78004ef9030fd61c519c739c957d10469be5a61f9a63ab32635840bd14f1",
      "snapshot_path": "replay_snapshots/configs/qa.yaml"
    },
    {
      "name": "scoring.yaml",
      "original_path": "config/scoring.yaml",
      "sha256": "7929b78ea4ab71bdcf0a979513306c921ff754993f7505e2f3e5dc509c05bc57",
      "snapshot_path": "replay_snapshots/configs/scoring.yaml"
    },
    {
      "name": "screening_params.yaml",
      "original_path": "config/screening_params.yaml",
      "sha256": "bef669af11bf6457b1e29ff2d7d431b3e30c6854ecb192c88e067752aa064cd4",
      "snapshot_path": "replay_snapshots/configs/screening_params.yaml"
    }
  ],
  "foundation_load_status": "captured",
  "foundation_run_consumed": {
    "manifest_original_path": "C:\\Users\\Emanuel\\AppData\\Local\\Temp\\tmpnfbwvkzj\\data\\intermediate\\status\\latest_foundation_manifest.json",
    "manifest_sha256": "6a7ecfc477ca08405971890e9c142d75a502fbd8128e219402f9fa8595616223",
    "run_id": "foundation-run",
    "snapshot_path": "replay_snapshots/foundation_manifest.json"
  },
  "git": {
    "commit": null,
    "dirty": null,
    "unavailable_reason": "Command '['git', 'rev-parse', 'HEAD']' returned non-zero exit status 128."
  },
  "manifest_version": 1,
  "manual_data": {
    "original_path": "data/manual/screening/manual_screening.sqlite3",
    "sha256": "c3ce371f6cb4406f87fae45d3328cc779075076679453f6f44b80eacd1fe248e",
    "snapshot_path": "replay_snapshots/manual_screening.sqlite3"
  },
  "run_id": "20260529T110559Z-tool-a-0b7b41ea",
  "started_at_utc": "2026-05-29T11:05:59.790765Z"
}
```

## 5. Verify Output Example

```text
Replay manifest: C:\Users\Emanuel\AppData\Local\Temp\tmpnfbwvkzj\data\runs\20260529T110559Z-tool-a-0b7b41ea\replay_manifest.json
Run directory: C:\Users\Emanuel\AppData\Local\Temp\tmpnfbwvkzj\data\runs\20260529T110559Z-tool-a-0b7b41ea

Snapshot integrity:
  [OK] universe.yaml - sha256 matches recorded
  [OK] horizons.yaml - sha256 matches recorded
  [OK] qa.yaml - sha256 matches recorded
  [OK] scoring.yaml - sha256 matches recorded
  [OK] screening_params.yaml - sha256 matches recorded
  [OK] manual_screening.sqlite3 - sha256 matches recorded
  [OK] foundation_manifest.json - sha256 matches recorded

Code state at run time:
  Git unavailable at run time: Command '['git', 'rev-parse', 'HEAD']' returned non-zero exit status 128.

Drift since run:
  [OK] universe.yaml matches the run snapshot
  [OK] horizons.yaml matches the run snapshot
  [OK] qa.yaml matches the run snapshot
  [OK] scoring.yaml matches the run snapshot
  [OK] screening_params.yaml matches the run snapshot
  [WARN] manual_screening.sqlite3 differs from the run snapshot
  [OK] foundation_manifest.json matches the run snapshot

Verdict: OK.
```

The manual-data drift warning is expected in this temp fixture because the run snapshot came from a temp SQLite file while drift checks compare against the current repo checkout. Snapshot integrity is still OK.

## 6. Test Deltas

- Baseline before replay manifest work: `306 passed`.
- Final gate after step 6: `323 passed`.
- New tests: 17 total.
- New test file: `tests/test_replay_manifest.py`.
- Modified test files: `tests/test_run_context.py`, `tests/helpers.py`.
- Command used for final gate: `python -m pytest -q`.

## 7. Edge Cases Verified

| Edge case | Test |
| --- | --- |
| Git unavailable | `test_phase1_handles_missing_git_gracefully` |
| Dirty working tree | `test_phase1_records_dirty_working_tree` |
| Missing manual DB | `test_phase1_handles_missing_manual_db_for_init` |
| Missing required config | `test_phase1_hard_fails_on_missing_config` |
| Locked SQLite | `test_phase1_hard_fails_on_locked_sqlite` |
| Config list sync | `test_manifest_config_list_matches_load_app_config` |
| Phase-2 success | `test_phase2_updates_foundation_block` |
| Phase-2 failure records status | `test_phase2_failure_records_status_not_raise` |
| RunContext auto manifest | `test_run_context_start_writes_replay_manifest` |
| Pristine verify | `test_verify_replay_cli_passes_for_pristine_manifest` |
| Corrupted snapshot | `test_verify_replay_cli_detects_corrupted_snapshot` |
| Moved run folder | `test_verify_replay_cli_accepts_moved_folder` |
| Historical pre-manifest run | `test_verify_replay_cli_reports_predates_for_old_run` |
| Missing run directory | `test_verify_replay_cli_rejects_missing_run_dir` |
| No checkout drift context | `test_verify_replay_cli_handles_missing_checkout_context` |
| Fixture Tool A phase-1 plus phase-2 chain | `test_fixture_tool_a_run_with_foundation_replay_manifest_verifies` |

## 8. Open Questions For Reviewer

- The holistic review flagged stricter schema validation for malformed-but-parseable manifests as a useful hardening follow-up. I did not add it because it was outside the v2 plan and Claude's required fixes.
- Phase-2 failures are recorded when the phase-1 manifest can be read. If the manifest cannot be read at all, the phase-2 updater still returns silently. Claude accepted this as minor earlier; review whether the final milestone should keep it.
- Predictive-model provenance should not be abstracted yet. When the first predictive model lands, the manifest should add concrete fields for model artifact hash, feature snapshot hash, training/inference window, hyperparameters, and random seed.
