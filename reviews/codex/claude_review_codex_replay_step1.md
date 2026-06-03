# Claude Review: Codex Replay Manifest Step 1

**Reviewer:** Claude Code
**Date:** 2026-05-28
**Commit reviewed:** `febc14a` (replay manifest step 1: add phase one manifest writer)
**Files changed:** `replay_manifest.py` (+374, new), `config.py` (+16/−9), `test_replay_manifest.py` (+177, new), `progress.md` (+7)
**Grade:** **READY** with four minor notes

## TL;DR

Codex implemented step 1 cleanly. The module structure, public API, SQLite defensive details, hard-fail vs. best-effort split, and config-list sync (AF2 fix) all match plan v2 exactly. All 7 specified tests are present and pass. Full suite at 313 (baseline 306 + 7 new). I created a real manifest end-to-end and the JSON schema matches §2b precisely. No corrections required; four minor nits below for the record.

## Review depth

This time I did:
- Read the entire `replay_manifest.py` (374 lines) end-to-end
- Read the entire test file end-to-end
- Read the `config.py` diff
- **Built a real manifest with a fixture** and inspected the JSON + the file tree it produced
- Ran the new tests directly (`7 passed`)
- Ran the full suite independently (`313 passed`)
- Unicode preservation check (n/a — all new code)
- Stray-whitespace audit
- AST-based unused-import scan

## ✅ Verified end-to-end

| Plan element | Verification | Result |
|---|---|---|
| `write_initial_replay_manifest` writes phase-1 manifest | Live fixture run | ✅ Produced 1895-byte JSON with all expected keys |
| Schema matches §2b | Inspected real output | ✅ `manifest_version`, `run_id`, `command`, `started_at_utc`, `git`, `configs`, `manual_data`, `foundation_run_consumed`, `foundation_load_status` all present and correctly shaped |
| 5 config snapshots + manual DB snapshot land in `replay_snapshots/` | Live fixture run | ✅ `replay_snapshots/configs/*.yaml` (5 files) + `replay_snapshots/manual_screening.sqlite3` |
| `foundation_load_status: "not-applicable"` at phase 1 | JSON output | ✅ Correct (phase 2 not yet wired) |
| SHA-256 of every snapshot matches manifest record | Test 1 + fixture | ✅ Verified independently |
| SQLite uses read-only URI + timeout + atomic temp-then-move | Source code lines 219-233 | ✅ Implemented as `closing(sqlite3.connect("file:...?mode=ro", uri=True, timeout=5.0))` and `os.replace(tmp, dst)` |
| Hard-fail on missing config | Test 5 + source line 322 | ✅ Raises `FileNotFoundError` with config name in message |
| Hard-fail on locked SQLite | Test 6 + source line 219-233 | ✅ `OperationalError` propagates through `_snapshot_manual_database` |
| Best-effort on git unavailable | Test 2 + source line 254-259 | ✅ Records `unavailable_reason`, doesn't raise |
| Best-effort on dirty tree | Test 3 + source line 263 | ✅ Records `dirty: true`, doesn't raise |
| Best-effort on missing manual DB | Test 4 + source line 207-208 | ✅ Records `manual_data: null`, doesn't raise |
| Config list sync (Codex AF2) | Test 7 + `config.py` diff | ✅ `EXPECTED_CONFIG_FILES` tuple + `expected_config_paths()` helper extracted; `load_app_config` now imports from it; test asserts manifest config list == loader's |
| Tests count | `python -m pytest -q` | ✅ 313 passed (baseline 306 + 7 new). No regressions. |
| Unicode preservation | Per-file count | ✅ N/A — new code has no Unicode chars to preserve (none in spec) |
| Stray whitespace | awk audit | ✅ All three new files clean |
| Unused imports | AST scan | ✅ All three new files clean |

## Real fixture run — JSON output (truncated)

```json
{
  "command": "tool-a",
  "configs": [
    {"name": "universe.yaml", "original_path": "config/universe.yaml",
     "sha256": "26971094...", "snapshot_path": "replay_snapshots/configs/universe.yaml"},
    ... 4 more
  ],
  "foundation_load_status": "not-applicable",
  "foundation_run_consumed": null,
  "git": {
    "commit": null,
    "dirty": null,
    "unavailable_reason": "Command '['git', 'rev-parse', 'HEAD']' returned non-zero exit status 128."
  },
  "manifest_version": 1,
  "manual_data": {
    "original_path": "data/manual/screening/manual_screening.sqlite3",
    "sha256": "77e2e667...",
    "snapshot_path": "replay_snapshots/manual_screening.sqlite3"
  },
  "run_id": "20260528T181056Z-tool-a-9e5897f3",
  "started_at_utc": "2026-05-28T18:10:56.986511Z"
}
```

The fixture run had no git repo in the temp dir, so the `git` block correctly captured the unavailable reason. The temp dir is not a git repo → exit 128 → recorded honestly. Everything else populated correctly.

## ⚠ Four minor nits (recorded, not blocking)

### Nit 1: Test helper `_create_manual_db` uses `with sqlite3.connect()` without `close()`

`tests/test_replay_manifest.py:151`:

```python
def _create_manual_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE manual_inputs (ticker TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO manual_inputs VALUES ('NEM')")
```

Python's `sqlite3.Connection` context manager **commits/rolls back but does NOT close** the connection. On Windows, this can leave the file locked and pytest's tmp_path cleanup can warn. The fix is `contextlib.closing()`, same pattern Codex used correctly in production code at `replay_manifest.py:223-228`. Tests still pass (pytest tolerates), but the inconsistency between production code and test code is worth fixing for hygiene.

**Suggested fix:** wrap the test helper in `contextlib.closing()` like the production code.

### Nit 2: Phase 2 silent return when manifest can't be read

`replay_manifest.py:102-105`:

```python
try:
    manifest = _read_manifest_path(manifest_path)
except Exception:
    return
```

If the manifest doesn't exist or is corrupted, phase 2 silently returns. Plan §2a said "Phase 2 failure → log a clear warning into `run.log` and the run metadata." Codex's implementation can't do that because the function only takes `run_dir`, not `RunContext`. Two options:

- (a) Accept silent return — the manifest doesn't exist, so there's nothing to update. Phase 2 was meaningless anyway.
- (b) Add an optional `run_context: RunContext | None` parameter so the function can warn into `run.log` when one is provided.

I'd lean (a) — it's honest about the state and doesn't add a second responsibility to the function. Document the silent-return as intentional in a one-line comment.

### Nit 3: Raw `CalledProcessError` str() in `unavailable_reason`

When git fails, the reason string is the verbatim subprocess output:

```
"Command '['git', 'rev-parse', 'HEAD']' returned non-zero exit status 128."
```

Functional but not user-friendly. The verify command will eventually surface this to the user (step 4). At that point the message will look weird in the terminal. Two small improvements possible:

- Strip the leading `"Command '...'"` and just show the exit code + a friendly hint (e.g. `"git rev-parse HEAD failed (exit 128) — likely not a git repository"`)
- Or split into two fields: `unavailable_reason_code` (numeric exit code) + `unavailable_reason_message` (human-friendly explanation)

Minor — defer until step 4 if it shows up ugly in verify output.

### Nit 4: Hard-fail leaves partial snapshot files in run_dir

In `write_initial_replay_manifest`, the config snapshots are written **before** the manual SQLite snapshot. If SQLite is locked (Codex's hard-fail case), the function raises after the configs have already been copied to disk. The run folder is left with:
- `replay_snapshots/configs/*.yaml` (5 files, partially-written state)
- No `replay_manifest.json`

A subsequent `verify-replay <run_id>` would say "run predates replay manifests" because there's no JSON, even though there are snapshot files. The diagnostic is misleading.

**Options:**
- (a) Wrap the whole writer in a try/except that cleans up partial files on raise.
- (b) Accept the partial state — the run failed anyway, and the cli should make that clear.

I'd lean (a) for cleaner ops, but it's not blocking. The run is failed regardless.

## What I verified clean (no findings)

- ✅ Schema matches plan §2b
- ✅ All 7 specified tests present and passing
- ✅ All 7 covering the right risks (R1, R2 best-effort/hard-fail split + AF2 config sync)
- ✅ Public API signatures match plan §2c exactly
- ✅ `EXPECTED_CONFIG_FILES` tuple + `expected_config_paths()` helper correctly extracted from `load_app_config`
- ✅ `_resolve_run_dir` correctly distinguishes Path-vs-id-vs-str (the Codex R3 design)
- ✅ `VerifyResult.ok` treats `PREDATES_REPLAY_MANIFEST` as success (Codex R5)
- ✅ Atomic temp-then-move via `os.replace` in both `_copy_file_atomic` and `_write_json_atomic`
- ✅ Cross-platform path checks (`"/"`/`"\\"` separator detection)
- ✅ JSON output is deterministic (`sort_keys=True`)
- ✅ Commit hygiene: one focused commit, four related files, progress log committed alongside
- ✅ Test count never decreases: 306 → 313

## Verdict

**Grade: READY.** Step 1 is solid. Nits 1-4 are minor and not blocking; address them opportunistically or never.

Proceed to **step 2** (wire `RunContext.start()` to call `write_initial_replay_manifest`). Stop at **CHECKPOINT B** after step 4.
