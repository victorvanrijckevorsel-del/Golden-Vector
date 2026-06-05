# Infrastructure Remediation Progress

## I1 - Atomic Current-State Manifest And Honest Status

### Step 1 - Manifest contract

Built:

- Added `latest_model_state_manifest_path` to centralized paths.
- Added `golden_vector.app.model_state` with:
  - manifest builder
  - atomic writer using a single temp-file replace
  - loader
  - CLI/UI summary helper
  - artifact hashing, row counts, source refresh ids, manual-store hash, stage timing passthrough
  - nullable `parent_refresh_id`
  - extensible artifact map with planned I3 option/Finder artifacts
- Added focused tests for complete aligned builds, missing Tool C/D, full mismatch reporting, and missing-manifest fallback.

Self-review:

- Found that present-but-failed foundation/options manifests and empty required Tool outputs could still be marked complete.
- Fixed by adding artifact health warnings that force `state = incomplete`.
- Confirmed the manifest does not make legacy latest aliases authoritative.

Checks:

- `python -m pytest tests/test_model_state.py -q` -> 4 passed.
- `python -m ruff check ...` could not run because `ruff` is not installed in the active Python environment.

### Step 2 - Refresh, status, and UI wiring

Built:

- `python main.py refresh` now records crude per-stage timings for update-data, Tool A, Tool B, Tool C, and Tool D.
- A successful non-skipped full refresh writes `latest_model_state.json` after Tool D completes.
- `python main.py status` reads the model-state manifest first, then preserves legacy artifact inspection.
- Legacy refresh alignment now reports all mismatched tools, not only the first mismatch.
- Workspace overview, Tool A, and Tool B pages now show a model-build banner:
  - complete build
  - incomplete/corrupt/missing model-state manifest
  - pending I2 parent refresh id

Self-review:

- Found that a corrupt `latest_model_state.json` could crash CLI status and workspace loading.
- Fixed the loader to return an explicit incomplete state with a warning instead of raising.
- Confirmed I1 still leaves readers on legacy latest aliases; the manifest is shaped for I2 but not yet authoritative for data reads.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_cli_refresh_and_status.py tests/test_workspace_app.py -q` -> 72 passed.
