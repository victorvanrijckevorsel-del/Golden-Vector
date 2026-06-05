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

### Step 2 - Parent refresh id and all-or-nothing manifest publish

Built:

- `python main.py refresh` now mints a parent refresh id at the start of the run and publishes it into `latest_model_state.json` only after Tool D succeeds.
- Added a hidden test-only fault hook to stop the refresh after a named successful stage without publishing the model-state manifest.
- Added the fault-injection regression Claude requested:
  - publish an old complete manifest
  - overwrite mutable latest aliases during a new refresh
  - inject failure after Tool B
  - assert `latest_model_state.json` is unchanged
  - assert current-model readers still return the old Tool B artifact, not the overwritten alias

Self-review:

- Kept the fault hook private to `run_refresh` callers; it is not exposed as a CLI flag, so users cannot accidentally trigger it.
- Confirmed the manifest write still happens only in the success path after Tool D.

Checks:

- `python -m pytest tests/test_cli_refresh_and_status.py tests/test_model_state.py -q` -> 18 passed.
- `python -m compileall golden_vector/cli.py tests/test_cli_refresh_and_status.py` -> passed.

### Step 3 - Product refresh button, stage progress, and Tool D spot contract

Built:

- The workspace refresh control now starts `python main.py refresh` instead of `python main.py update-data --options`.
- The button copy now says "Refresh all model data" to match the actual product operation.
- Running refresh status reads the latest logged `Step N/5` line from the background log and surfaces it as stage progress.
- Refresh completion records the latest model-state `parent_refresh_id` instead of the options refresh id.
- Updated stale fallback copy that still instructed users to run `update-data --options`.
- Added a Tool D regression proving a scenario run can overwrite generic Tool D latest while leaving the Finder-facing spot alias unchanged.

Self-review:

- Searched for remaining options-only refresh copy and updated the one stale detail-panel fallback.
- Confirmed the full refresh button is still a single background job and still blocks duplicate starts.
- Confirmed Tool D's existing spot publish condition was already correct; the new test locks it down.

Checks:

- `python -m pytest tests/test_option_refresh.py tests/test_cli_tool_d.py tests/test_cli_refresh_and_status.py tests/test_candidate_finder_data.py tests/test_option_trading_data.py tests/test_workspace_app.py -q` -> 115 passed.
- `python -m compileall golden_vector/serve/detail_panels.py golden_vector/serve/option_refresh.py tests/test_option_refresh.py tests/test_cli_tool_d.py` -> passed.

### I2 self-review hardening

Finding fixed:

- Foundation/options immutable JSON copies were initially stamped with their source refresh ids only. That was safe from mutable aliases, but less clear than stamping them with the parent refresh id when a full model refresh publishes. Updated the manifest builder so a refresh-published model state snapshots foundation/options JSON under the same parent-refresh stamp as the atomic model build.
- Standalone Tool C and Tool D still read mutable Tool A/B latest aliases as upstream inputs. Full `refresh` must use the just-produced aliases before the new manifest is published, but standalone runs after a failed refresh should resolve through the current manifest. Added an internal input switch: standalone uses model-state artifacts; full refresh uses the just-produced aliases.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_cli_refresh_and_status.py tests/test_option_refresh.py tests/test_cli_tool_d.py tests/test_candidate_finder_data.py tests/test_option_trading_data.py tests/test_workspace_app.py -q` -> 123 passed.
- `python -m compileall golden_vector/app/model_state.py` -> passed.
- `python -m pytest tests/test_cli_refresh_and_status.py tests/test_cli_tool_c.py tests/test_cli_tool_d.py tests/test_tool_c.py tests/test_tool_d.py -q` -> 27 passed.
- `python -m compileall golden_vector/cli.py tests/test_cli_refresh_and_status.py` -> passed.
- `rg` check for direct `pd.read_parquet(paths.latest_tool_*_snapshot_parquet_path)` in CLI/serve -> no matches.

### I2 gate checks

Deliverables:

- Sample manifest saved at `reviews/codex/latest_model_state_i2_sample.json`.
- Manifest sample shows:
  - `parent_refresh_id: 20260605T120000Z-refresh-sample`
  - foundation/options paths stamped with the parent refresh id
  - Tool A/B/C/D paths pointing at retained `tool_x_latest_<run_id>.parquet` files
  - mutable alias paths recorded only as `source_alias_path`
  - planned I3 option/Finder artifact keys still present and optional
- Fault-injection test proves a failed refresh after Tool B leaves the previous model-state pointer intact and current-model readers still return the old coherent Tool B artifact.
- Full workspace refresh button now starts the full model refresh and surfaces the latest logged stage.
- Tool D scenario runs leave the spot alias intact; Candidate Finder resolves Tool D through the manifest's `tool_d_spot` artifact when present.

Checks:

- `python -m pytest -q` -> 699 passed.
- `python -m compileall golden_vector` -> passed.
- `python -m py_compile golden_vector/app/model_state.py golden_vector/cli.py golden_vector/serve/option_refresh.py` -> passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in the active Python environment.

### I2 deep-review hardening

Findings fixed:

- Current-model readers could fall back to mutable latest aliases when `latest_model_state.json` existed but was corrupt. That would make a damaged atomic pointer behave like no pointer at all. The loader now marks corrupt manifests as unreadable, and artifact resolution refuses alias fallback in that state.
- Current-model readers accepted an artifact marked `usable` even when it was not immutable. That could let an incomplete manifest point readers at `*_latest` aliases. Resolution now requires manifest artifact entries to be immutable.
- Standalone Tool C and Tool D read Tool A/B through the model-state manifest, but still loaded foundation from the mutable latest foundation alias. After a failed refresh, that could mix old Tool A/B with newer foundation data. Standalone Tool C/D now resolve foundation through the same model-state pointer; full `refresh` still uses the just-produced latest alias before atomic publish.
- Tool A detail pages still loaded foundation directly from the mutable latest foundation alias for rebuilt chart inputs. Detail-state loading now resolves foundation through the model-state manifest and refuses alias fallback when a manifest exists but is unusable.
- The Option Trading in-process cache did not include the current model-state manifest pointer in its key. Long-running workspace processes now invalidate option data when `latest_model_state.json` changes.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_cli_tool_c.py tests/test_cli_tool_d.py tests/test_option_trading_data.py -q` -> 35 passed.
- `python -m pytest tests/test_model_state.py tests/test_latest_data.py tests/test_cli_refresh_and_status.py tests/test_cli_tool_c.py tests/test_cli_tool_d.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py tests/test_workspace_app.py tests/test_option_refresh.py -q` -> 137 passed.
- `python -m pytest tests/test_workspace_app.py tests/test_model_state.py tests/test_latest_data.py tests/test_cli_tool_c.py tests/test_cli_tool_d.py tests/test_option_trading_data.py -q` -> 101 passed.
- `python -m compileall golden_vector` -> passed.
- `python -m pytest -q` -> 705 passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in the active Python environment.

### I1/I2 joint-link review

Findings fixed:

- A syntactically valid but wrong-shaped `latest_model_state.json` such as `[]` was not handled like a corrupt manifest. The loader now requires the root JSON value to be an object and returns the same unreadable-manifest payload used for parse failures, so readers fail closed instead of crashing or falling back to mutable aliases.
- The Tool B override/scenario view still recomputed from the mutable latest foundation alias. That could mix a manifest-selected Tool B baseline with a newer foundation snapshot after a failed refresh. The recompute path now resolves foundation through the current model-state manifest and falls back to the persisted table with a visible error if the manifest cannot provide a usable immutable foundation.
- The “current foundation” resolution rule had started to duplicate across CLI and UI paths. It is now centralized in `golden_vector.app.model_state.resolve_current_foundation_manifest_path`, with one shared fail-closed behavior for present-but-unusable manifests.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_workspace_app.py tests/test_cli_tool_c.py tests/test_cli_tool_d.py tests/test_cli_refresh_and_status.py -q` -> 89 passed.
- `python -m pytest tests/test_model_state.py tests/test_latest_data.py tests/test_workspace_app.py tests/test_cli_refresh_and_status.py tests/test_option_refresh.py tests/test_candidate_finder_data.py tests/test_option_trading_data.py tests/test_cli_tool_c.py tests/test_cli_tool_d.py -q` -> 140 passed.
- `python -m compileall golden_vector` -> passed.
- `python -m pytest -q` -> 707 passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in the active Python environment.

### Duplication review cleanup

Findings fixed:

- Score-eligible coercion had drifted between model code and UI lenses. Added `golden_vector.common.eligibility` and routed Tool C, Candidate Finder, Tool A ranking, overview lenses, and detail panels through one policy: missing values default to eligible for older Tool A snapshots; explicit false-like values block scoring.
- PASS/WARN/FAIL precedence was implemented in multiple places. Added `golden_vector.common.status.combine_statuses` and routed CLI/foundation status combining through it, with `SKIPPED` treated as neutral and unknown statuses rejected.
- SHA256 file hashing and repo-relative path formatting were copied across model-state, replay manifests, options manifests, Candidate Finder, and Option Trading. Added `golden_vector.common.files` and moved those call sites onto shared helpers.

Checks:

- `python -m pytest tests/test_common_helpers.py tests/test_lenses.py tests/test_tool_c.py tests/test_candidate_finder_scoring.py tests/test_tool_a_scoring.py tests/test_cli_tool_a.py tests/test_cli_refresh_and_status.py tests/test_latest_data.py tests/test_model_state.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py tests/test_replay_manifest.py tests/test_persist_options.py tests/test_options_phase.py -q` -> 134 passed.
- `python -m compileall golden_vector` -> passed.
- `python -m pytest -q` -> 712 passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in the active Python environment.
