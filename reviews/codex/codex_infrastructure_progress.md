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

### Milestone I1 self-review

Reviewed:

- Manifest shape against Claude R1:
  - single atomic pointer path present
  - `parent_refresh_id` present and nullable
  - extensible artifact map already includes I3 option/Finder slots
  - legacy latest aliases explicitly marked non-authoritative
- CLI status behavior:
  - reads model-state first
  - falls back to legacy latest-file inspection when absent
  - reports all legacy mismatches, not only the first one
- UI behavior:
  - shared overview banner distinguishes complete vs incomplete/missing/corrupt model state
  - no data readers were moved off legacy aliases yet

Self-review findings:

- No code changes were needed after the full-suite run.
- Saved a compact sample manifest for review at `reviews/codex/latest_model_state_i1_sample.json`.

Checks:

- `python -m pytest -q` -> 692 passed.
- `python main.py status` -> showed no local model-state manifest yet, foundation/options at `20260601T135914Z-update-data-f555b2fe`, Tool A/B stale at `20260424T140753Z-update-data-6175c3fb`, Tool C/D missing, and both Tool A and Tool B mismatches listed.

### I1 deep-review fixes

Reviewed:

- Manifest artifact semantics.
- CLI status behavior when no foundation refresh id exists.
- UI coverage for the screens that depend on mixed model/option inputs.
- Candidate Finder cache invalidation after model-state changes.
- Duplicate model-state banner rendering.

Findings fixed:

- Required artifacts used `present` as the completion signal. A corrupt Parquet/JSON file could be present but unusable. Added explicit `readable` and `usable` fields and changed completion to depend on `usable`.
- Corrupt required files now remain `present: true` with `usable: false` and a `read_error`, instead of being flattened into "missing".
- Foundation/options manifests without required status fields can no longer produce a complete model state.
- Legacy CLI status now reports refresh alignment as `UNKNOWN` when the foundation refresh id is absent, not `OK`.
- Option Trading and Candidate Finder now render the model-state banner.
- Candidate Finder cache keys now include the model-state manifest hash, so the banner cannot go stale behind the cache.
- Consolidated duplicate banner HTML into `golden_vector.serve.model_state_banner`.
- Refreshed `reviews/codex/latest_model_state_i1_sample.json` to show the hardened `present`/`readable`/`usable` contract.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_cli_refresh_and_status.py tests/test_workspace_app.py tests/test_option_refresh.py tests/test_candidate_finder_data.py tests/test_candidate_finder_page.py -q` -> 105 passed.
- `python -m compileall golden_vector/app/model_state.py golden_vector/cli.py golden_vector/serve/model_state_banner.py golden_vector/serve/overview_combined.py golden_vector/serve/overview_tool_a.py golden_vector/serve/overview_tool_b.py golden_vector/serve/overview_option_trading.py golden_vector/serve/candidate_finder_data.py golden_vector/serve/candidate_finder_page.py golden_vector/serve/workspace.py` -> passed.
- `python -m pytest -q` -> 695 passed.

## I2 - Atomic Publish, Manifest Readers, And Product Refresh

### Step 1 - Immutable model-state artifacts and reader resolver

Built:

- Model-state manifests now record immutable run-id-stamped artifacts for the required build products:
  - foundation/options JSON manifests are copied to run-id-stamped files in `data/intermediate/status/`
  - Tool A/B/C/D Parquet artifacts resolve to retained `tool_x_latest_<run_id>.parquet` files instead of mutable `tool_x_latest.parquet` aliases
  - each artifact records `immutable`, `source_alias_path`, and the immutable file hash/size/mtime
- Added centralized resolver helpers:
  - `resolve_current_model_artifact_path`
  - `read_current_model_parquet`
  - `read_current_model_json`
- Workspace, Option Trading, Candidate Finder, and CLI status now resolve current model inputs through the manifest when it contains an artifact entry.
- Candidate Finder keeps the existing Tool D spot-run rule, but now prefers the manifest's `tool_d_spot` artifact before falling back to `tool_d`.

Self-review:

- Found a transition bug where a missing fallback alias was still returned as a path; this made Candidate Finder choose a nonexistent Tool D spot alias and mark Tool D missing. Fixed the resolver so fallbacks are returned only when the file exists.
- Found the I1 status text still said `parent_refresh_id: (pending I2)` for null parent ids. Updated it to `(none)` because I2 will populate the value on refresh publishes.
- Added a regression test proving that after a model-state manifest is published, overwriting mutable aliases does not change what current-model readers load.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_cli_refresh_and_status.py tests/test_candidate_finder_data.py tests/test_option_trading_data.py tests/test_workspace_app.py -q` -> 107 passed.
- `python -m compileall golden_vector/app/model_state.py golden_vector/cli.py golden_vector/serve/workspace_state.py golden_vector/serve/candidate_finder_data.py golden_vector/serve/option_trading_data.py tests/test_model_state.py` -> passed.
