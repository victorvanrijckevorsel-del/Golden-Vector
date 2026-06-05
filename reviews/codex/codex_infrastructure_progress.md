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

### I2 gate review merge fixes

Merged:

- Claude's I2 gate review at `reviews/codex/claude_review_i2_gate.md`.
- Codex's I1/I2 self-review at `reviews/codex/codex_self_review_i1_i2_manifest_integration.md`.

Findings fixed:

- Current-model artifact resolution now fails closed for syntactically valid but wrong-shaped model-state manifests such as `{}` or manifests without an `artifacts` object. Once `latest_model_state.json` exists, readers no longer fall back to mutable aliases just because an artifact key is absent.
- `python main.py refresh --skip-tool-b` now publishes a model-state manifest after the partial refresh. The manifest is expected to be `incomplete` when Tool B/C/D are carried from older runs, but readers no longer stay silently pinned to the previous full build after fresh foundation/Tool A aliases were written.
- Model-state immutable Parquet resolution now uses the published `source_run_id` to select the run-id-stamped retained artifact instead of sha256-matching the mutable alias against retained twins. This removes the fragile byte-identity dependency and avoids retained-run glob scans on the normal path.
- Hedge Readiness report generation and header context now resolve options, Tool A, and Tool B through the model-state manifest instead of reading mutable latest aliases directly.
- Tool A structural metrics are now represented as an optional model-state artifact and the detail page resolves that artifact through the manifest before reading structural side data.
- Atomic JSON/status writes touched in I2 now use shared unique-temp-file helpers instead of fixed `.tmp` names.
- `_unique_strings` behavior is centralized through `golden_vector.common.strings`, so freshness-id handling now filters blank and NaN-like strings consistently across model state, Option Trading, Candidate Finder, and Hedge Readiness.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_cli_refresh_and_status.py tests/test_hedge_report.py tests/test_header_context.py tests/test_workspace_app.py tests/test_candidate_finder_data.py tests/test_option_trading_data.py tests/test_common_helpers.py tests/test_option_refresh.py -q` -> 157 passed.
- `python -m pytest tests/test_cli_tool_c.py tests/test_cli_tool_d.py tests/test_tool_c.py tests/test_tool_d.py tests/test_latest_data.py tests/test_candidate_finder_scoring.py tests/test_lenses.py -q` -> 53 passed.
- `python -m pytest -q` -> 718 passed.
- `python -m compileall golden_vector` -> passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in the active Python environment.

### I3 artifact-contract commit

Built:

- Updated the merged remediation plan with Claude's I3 clarifications: I3 option artifacts reuse the M1 `source_run_id` immutable artifact mechanism, build inside `run_refresh` before manifest publish, share a non-serve builder, keep sizing request-time on persisted candidates, and test parity with identical chains/risk-free-rate inputs including GDX/GDXJ proxy coverage.
- Added one shared option artifact contract in `golden_vector.contracts.option_artifacts` for artifact names, latest alias paths, and run-stamped paths.
- Added `ProjectPaths.output_options_dir`.
- Registered I3 option/Finder artifacts in the model-state manifest as optional Parquet artifacts, including the previously missing `option_selected_candidates` artifact needed by request-time sizing.
- Added a resolver test proving an I3 option artifact resolves by writer-recorded `source_run_id` to the immutable run-stamped file even when the mutable latest alias bytes differ.

Self-review finding fixed:

- The first version of the option run-stamped path helper would have used a raw source run id directly. I moved model-state's safe filename fragment helper into `golden_vector.common.files.safe_file_fragment` and reused it from both model-state and the option artifact contract instead of duplicating filename normalization.

Checks:

- `python -m pytest tests/test_model_state.py` -> 15 passed.

### I3 shared non-serve option builder

Built:

- Extracted the current option-selection orchestration out of `golden_vector.serve.option_trading_data` into `golden_vector.hedge.option_artifact_builder`.
- Added one high-level `build_option_artifact_inputs(...)` entry point that builds put/call candidate slots, accepted candidate grids, liquidity measurements, source context, and Option Trading overview rows from already-loaded chains/features/Tool A/Tool B.
- Updated the serve loader to call the shared builder, preserving current request-time behavior while giving refresh-time persistence the same engine to call next.
- Removed the old serve-local candidate-slot, accepted-grid, liquidity-measurement, source-context, and stock-price helper block.

Self-review findings:

- Confirmed normal `serve/option_trading_data.py` no longer contains option candidate-slot or liquidity-scan functions.
- Confirmed `scan_option_chain(...)` is now referenced only by the non-serve builder among the touched Option Trading path.
- Reused `common.strings.unique_strings` and existing `hedge._helpers.as_float` instead of carrying over local `_unique_strings` or `_safe_float` copies.

Checks:

- `python -m pytest tests/test_option_trading_data.py` -> 17 passed.
- `python -m pytest tests/test_candidate_finder_data.py tests/test_option_trading_data.py` -> 33 passed.
- `python -m compileall golden_vector/hedge/option_artifact_builder.py golden_vector/serve/option_trading_data.py` -> passed.

### I3 option artifact serialization and writer

Built:

- Added `golden_vector.hedge.option_artifact_frames` to serialize shared-builder outputs into the six I3 Parquet artifact frames: contract metrics, liquidity measurements, candidate slots, selected candidates, Option Trading overview rows, and Candidate Finder inputs.
- Added `golden_vector.ingestion.persist_option_artifacts.persist_option_artifact_frames`, which writes one output file, one immutable run-stamped latest file, and one convenience latest alias for each artifact.
- Added `golden_vector.hedge.option_availability.has_usable_option_slots` and routed Candidate Finder's private compatibility wrapper through it, so persisted Finder inputs and request-time Finder use the same "usable = tradable selected candidate" policy.
- Added tests for Finder usable serialization, run-stamped/latest artifact writes, and fail-fast missing artifact frames.

Self-review finding fixed:

- The first writer version would have silently written empty fallback frames for missing artifacts. It now rejects incomplete artifact sets and rejects frames missing `source_run_id`, because those artifacts cannot become immutable through the model-state resolver.

Checks:

- `python -m pytest tests/test_option_artifact_persistence.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py` -> 36 passed.
- `python -m compileall golden_vector/ingestion/persist_option_artifacts.py tests/test_option_artifact_persistence.py` -> passed.

### I3 non-serve option source loader

Built:

- Added `golden_vector.hedge.option_artifact_sources` to load the options manifest, option feature snapshots, raw cached chains, Tool A, Tool B, and risk-free-rate context without importing `golden_vector.serve`.
- Added a `use_model_state` switch: UI/current readers use the manifest-selected artifacts, while refresh-time artifact publishing can read the just-built latest aliases before the new manifest is published.
- Added `golden_vector.common.parquet.read_optional_parquet` and moved Option Trading's optional Parquet reads to that shared helper instead of adding another local reader.
- Updated `serve.option_trading_data` to use the non-serve source loader and removed its duplicated manifest/features/chains loader functions.

Self-review findings:

- Removed a stale `as_float` import from `serve.option_trading_data`.
- Confirmed the serve file no longer defines `_read_optional_parquet`, `_load_chains`, or `_load_features`.

Checks:

- `python -m pytest tests/test_option_artifact_persistence.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py` -> 36 passed.
- `python -m compileall golden_vector/common/parquet.py golden_vector/hedge/option_artifact_sources.py golden_vector/serve/option_trading_data.py` -> passed.

### I3 refresh-time option artifact build

Built:

- Added `run_option_artifacts(...)` as an internal CLI runner that loads latest options/Tool A/Tool B outputs with `use_model_state=False`, builds artifacts through the shared non-serve builder, persists all six option artifacts, and writes an artifact summary.
- Inserted option artifact building into full `run_refresh` after Tool D and before `write_current_model_state_manifest`.
- Updated the full refresh step count from 5 to 6 and recorded `stage_timings["option_artifacts"]`.
- Added a refresh failure test proving an option-artifact failure leaves the previous model-state manifest intact and returns before publish.
- Added a direct `run_option_artifacts` smoke test proving its outputs become manifest-addressable optional artifacts.

Self-review finding fixed:

- Empty option artifacts initially could not become immutable because no row carried `source_run_id`. The artifact stamper now records `source_run_id`, `snapshot_refresh_run_id`, schema version, parent refresh id, and config hash in DataFrame attrs; the model-state Parquet artifact reader uses those attrs when row columns are empty. This preserves the writer-recorded run-id mechanism without sha256 reconstruction.

Checks:

- `python -m pytest tests/test_cli_refresh_and_status.py` -> 12 passed.
- `python -m pytest tests/test_option_artifact_persistence.py tests/test_cli_refresh_and_status.py` -> 16 passed.
- `python -m pytest tests/test_option_artifact_persistence.py tests/test_model_state.py tests/test_cli_refresh_and_status.py` -> 31 passed.
- `python -m pytest tests/test_model_state.py tests/test_option_artifact_persistence.py tests/test_cli_refresh_and_status.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py` -> 64 passed.
- `python -m compileall golden_vector/cli.py tests/test_cli_refresh_and_status.py golden_vector/app/model_state.py golden_vector/hedge/option_artifact_frames.py` -> passed.

### I3 persisted option-artifact readers

Built:

- Flipped `serve.option_trading_data.load_option_trading_data` from request-time raw-chain scanning to manifest-resolved persisted option artifacts.
- Rebuilt Option Trading rows, selected candidates, candidate slots, liquidity measurements, Candidate Finder option inputs, source context, and risk-free-rate context from the six persisted option artifacts.
- Kept ticker detail sizing request-time, but it now sizes against persisted selected candidates and persisted slots instead of scanning raw chains.
- Updated Candidate Finder fixtures to publish real Tool A/B/C/D and option artifacts through the same immutable model-state path used by production readers.
- Added a parity test that feeds identical cached chains plus identical risk-free-rate context to the shared builder and persisted reader, then compares overview rows, put/call slots, selected candidates, liquidity measurements, usable candidate sets, and GDX/GDXJ proxy fallback.

Self-review findings fixed:

- Candidate Finder tests still expected mutable latest Tool D aliases and corrupt latest Tool A aliases to control current-state reads. After I2/I3 the manifest is authoritative, so those tests now prove mutable alias changes are ignored when a current manifest selects immutable artifacts.
- Option Trading route tests still mutated raw chain or Tool A latest aliases after option artifacts were published. The tests now republish option artifacts after raw-chain fixture changes, and create Tool A fixture changes through the writer path before artifact publish, matching the M1/I2 immutability contract.
- The first persisted reader resolved each option artifact path and then called a helper that resolved it again. It now reads the already-resolved immutable path through `golden_vector.common.parquet.read_optional_parquet`.
- The first deserializer used broad `Any` typing and a `type: ignore` for reconstructed option slot status. It now validates and casts option type, slot status, and side status explicitly.

Checks:

- `python -m pytest tests/test_candidate_finder_data.py -q` -> 16 passed.
- `python -m pytest tests/test_option_trading_data.py -q` -> 18 passed.
- `python -m pytest tests/test_option_trading_data.py tests/test_candidate_finder_data.py -q` -> 34 passed.
- `python -m pytest tests/test_model_state.py tests/test_option_artifact_persistence.py tests/test_cli_refresh_and_status.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py -q` -> 65 passed.
- `python -m pytest tests/test_option_trading_routes.py -q` -> 17 passed.
- `python -m pytest tests/test_model_state.py tests/test_option_artifact_persistence.py tests/test_cli_refresh_and_status.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py tests/test_option_trading_routes.py -q` -> 82 passed.
- `python -m compileall golden_vector` -> passed.
- `python -m pytest -q` -> 725 passed.
- `python -m ruff check golden_vector/serve/option_trading_data.py golden_vector/hedge/option_artifact_frames.py tests/test_option_trading_data.py tests/test_candidate_finder_data.py` -> not run; `ruff` is not installed in the active Python environment.

### I3 deep self-review and Claude review merge

Reviewed:

- Claude's deep I3 review at `reviews/codex/claude_review_i3_deep.md`.
- The full I3 data path: cached options snapshots/features -> non-serve artifact builder -> persisted option artifacts -> current model-state manifest -> Option Trading and Candidate Finder readers.
- The shared infrastructure added around I3: immutable run-id artifact resolution, Parquet persistence, strict/optional Parquet readers, ticker normalization, and model-state completeness/alignment.

Findings fixed:

- Option and tool Parquet writes previously wrote directly to target files. Added `atomic_write_file(...)` and `write_parquet_atomic(...)`, then routed the shared persistence helper, options snapshots, options feature rows, and benchmark snapshot writes through atomic temp-file replacement.
- Core option artifacts were not required for `latest_model_state.json` to report `state: complete`. The manifest now requires `option_candidate_slots`, `option_trading_overview`, and `candidate_finder_inputs`; missing or zero-row required Parquet artifacts make the state incomplete.
- Model-state alignment did not compare required option artifacts with the options manifest refresh id. It now records `option_artifact_refresh_run_ids` and warns when core option artifacts reference a different options refresh.
- Build-time option artifact inputs swallowed corrupt chain snapshots. Manifest-listed chains now use strict Parquet reads and verify any recorded options-manifest sha256 before the builder runs.
- Read-time Option Trading artifact loading swallowed corrupt or tampered current artifacts. The reader now verifies the manifest-recorded sha256 and uses strict Parquet reads; failures surface as a visible option-artifact error instead of an empty table.
- Candidate Finder option artifact schema was open-ended. It is now pinned to the option fields Candidate Finder uses plus the persisted put/call usability booleans.
- Ticker normalization in the new option artifact path now uses shared `normalize_ticker(...)` / `normalize_ticker_series(...)` helpers.

Checks:

- `python -m compileall golden_vector` -> passed.
- `python -m pytest tests/test_common_helpers.py tests/test_model_state.py tests/test_option_artifact_persistence.py tests/test_option_trading_data.py -q` -> 49 passed.
- `python -m pytest tests/test_cli_refresh_and_status.py tests/test_option_trading_routes.py tests/test_candidate_finder_data.py tests/test_option_trading_data.py tests/test_option_artifact_persistence.py tests/test_model_state.py tests/test_common_helpers.py -q` -> 94 passed.
- `python -m pytest -q` -> 731 passed.
- `python -m ruff check ...` -> not run; `ruff` is not installed in the active Python environment.

### I3 gate approval carry-forward

Timing:

- Measured `/option-trading` WSGI cold app-cache route timing on the same controlled cached-options fixture because this checkout does not yet have a real local `data/status/latest_model_state.json` from a full refresh.
- Pre-reader-flip commit `1148425`: samples `457.34, 276.59, 283.39, 295.43, 344.57, 288.44, 294.32` ms; median `294.32` ms.
- Current HEAD after I3: samples `66.70, 41.36, 40.95, 46.12, 38.86, 40.64, 52.20` ms; median `41.36` ms.
- Fixture improvement: about `7.1x` faster by median. Production 60-name timing still needs to be measured after Emanuel runs the full local refresh and publishes a real current model-state manifest.

Carry-forward into I4/I5 per I3 gate approval:

- Consolidate the four alignment/freshness copies by consuming the model-state manifest's `_alignment` output instead of recomputing freshness separately in CLI status, Candidate Finder, Option Trading, and UI banners.
- Carry Tool D spot/scenario and empty-option/core-option-artifact fault tests into the I4/I5 test plan.

### I4 Phase 4 resilience

Built:

- Added one shared ingestion resilience helper for Yahoo retry/backoff and collection-stat summaries.
- Routed real `YahooClient` history, fast-info, expiration, and option-chain calls through the shared retry helper.
- Added optional targeted option-expiry fetching by configured DTE bands, defaulting to the existing full-chain behavior.
- Preserved per-ticker best-effort options ingestion while making one bad expiration non-fatal when other expirations load.
- Added option collection stats to the options manifest summary and exposed foundation/options collection stats through `latest_model_state.json` via existing `stage_timings.update_data.collection_stats`.
- Reused the shared atomic text writer for the latest options manifest instead of a deterministic `.tmp` path.

Self-review findings fixed:

- Partial option-expiry failures were visible in stats but did not downgrade the options phase to `WARN`. The phase status now treats expiration-level failures as a warning.
- Successful partial-expiry failures did not carry the explanatory message into the per-ticker event summary. The collection event now includes the fetch result message.
- The fetch-status summarizer assumed both start/end timestamp columns existed if it needed to derive durations. It now handles malformed/missing timing columns without raising.

Checks:

- `python -m pytest tests/test_collection_resilience.py tests/test_fetch_options.py tests/test_options_phase.py tests/test_cli_refresh_and_status.py` -> 23 passed.
- `python -m ruff check ...` -> not run; `ruff` is not installed in the active Python environment.

### I4 Phase 5 schema validation

Built:

- Extended `golden_vector.common.parquet.read_required_parquet(...)` so the existing checked-read path can also enforce required columns, schema version, and optional dtype expectations.
- Added a single `ParquetSchemaError` shape for Parquet contract drift.
- Routed option artifact UI reads through the shared checked-read with `OPTION_ARTIFACT_SCHEMA_VERSION`.
- Replaced local required/optional Parquet helper copies in current foundation/report readers with the shared common helpers.

Self-review findings fixed:

- The first schema validator path was separate from the checked reader; it is now part of `read_required_parquet(...)`.
- The current foundation and hedge report readers still carried local Parquet helper copies. They now reuse the shared helper.

Checks:

- `python -m pytest tests/test_parquet_contracts.py tests/test_latest_data.py tests/test_hedge_report.py tests/test_option_trading_data.py tests/test_option_trading_routes.py` -> 60 passed.
- `python -m compileall golden_vector/common/parquet.py golden_vector/app/latest_data.py golden_vector/hedge/report.py golden_vector/serve/option_trading_data.py` -> passed.

### I4 Phase 5 replay provenance and retained model states

Built:

- Added raw equity and raw FX snapshot paths to the latest foundation manifest.
- Extended replay-manifest foundation source assets so raw equity, raw FX, raw gold, normalized equities, and normalized market snapshots are all hashed and checked for drift.
- Added retained model-state JSON snapshots under `data/intermediate/status/model_states/`.
- Kept atomic publish ordering: write the retained model-state snapshot first, then swap `latest_model_state.json`.

Self-review findings fixed:

- `prune-runs` would not be able to preserve older coherent states if the project only retained one mutable latest pointer. The writer now emits a retained snapshot for each model-state publish.

Checks:

- `python -m pytest tests/test_model_state.py tests/test_replay_manifest.py tests/test_latest_data.py tests/test_cli_refresh_and_status.py` -> 59 passed.

### I4 Phase 5 prune-runs

Built:

- Added `golden_vector.app.run_pruning.prune_runs(...)` as a report-first retention helper.
- Added `python main.py prune-runs`, dry-run by default; deletion requires `--apply`.
- Protected `latest_model_state.json`, the retained model-state snapshots, every artifact path referenced by every retained model state, and every run id referenced by retained artifacts.
- Included option artifacts in the same artifact-map protection path; there is no option-specific deletion shortcut.
- Limited recursive deletion to directories under `data/runs`.

Self-review findings fixed:

- If no retained model-state manifest exists, pruning now no-ops with an informational warning instead of treating all historical run dirs as unprotected.
- Artifact candidates now require a run-id-like timestamp stamp, so mutable latest aliases such as `tool_d_latest_spot.parquet` are not pruned just because they match a broad glob.

Checks:

- `python -m pytest tests/test_run_pruning.py tests/test_model_state.py tests/test_cli_refresh_and_status.py` -> 33 passed.
- `python -m compileall golden_vector/app/run_pruning.py golden_vector/cli.py tests/test_run_pruning.py` -> passed.

### I4 gate self-review

Reviewed:

- Phase 4 Yahoo retry/backoff and collection-stat flow into `stage_timings`.
- Phase 5 schema validation through `read_required_parquet(...)`.
- Raw foundation provenance added to replay manifests.
- Retained model-state snapshot publish order.
- `prune-runs` destructive boundaries, dry-run default, no-manifest no-op, retained-manifest artifact protection, run-id protection, and option artifact coverage.

Gate checks:

- `python -m compileall golden_vector` -> passed.
- `python main.py prune-runs --keep-model-states 2` -> dry-run no-op with warning because this checkout has no retained model-state manifest yet.
- `python -m pytest -q` -> 741 passed in 628.95s.

Remaining carry-forward:

- I5 should still consolidate the four alignment/freshness consumers onto the model-state manifest alignment output.
- I5 should still carry the Tool D spot/scenario and empty-option/core-option-artifact fault tests noted at the I3 gate.

### I4 post-gate self-review fixes

Reviewed:

- The I4 collection-stat path from Yahoo/fetch status tables into `stage_timings`.
- The schema validator and option-artifact checked-read integration.
- Model-state retained snapshot publish order and replay raw-source provenance.
- The `prune-runs` safety boundary, especially old-data/corrupt-manifest cases.

Findings fixed:

- A malformed fetch-status Parquet table with rows but no `status` column could break collection-stat summarization. The summarizer now emits `UNKNOWN` status counts without raising.
- `prune-runs --apply` could produce delete candidates when the only retained model-state pointer was readable JSON but not a protectable model-state manifest. Pruning now no-ops unless at least one retained manifest is readable and carries an artifact map.
- Schema validation accepted the first non-null `schema_version`; mixed-version artifacts now fail loudly as schema drift.

Checks:

- `python -m pytest tests/test_collection_resilience.py tests/test_run_pruning.py tests/test_fetch_options.py tests/test_options_phase.py tests/test_model_state.py tests/test_replay_manifest.py tests/test_parquet_contracts.py` -> 59 passed.
- `python -m pytest tests/test_parquet_contracts.py tests/test_collection_resilience.py tests/test_run_pruning.py tests/test_option_trading_data.py` -> 30 passed.
- `python main.py status` -> passed.
- `python -m compileall golden_vector` -> passed.
- `python -m pytest tests/test_model_state.py tests/test_replay_manifest.py tests/test_cli_refresh_and_status.py tests/test_options_phase.py tests/test_fetch_options.py tests/test_latest_data.py tests/test_option_trading_routes.py` -> 85 passed.
- `python -m pytest -q` -> 744 passed in 742.61s.
