# Codex Holistic Review: Replay Manifest Checkpoint B

**Date:** 2026-05-29  
**Reviewed range:** `febc14a` through `f1d760d`  
**Scope:** Replay manifest steps 1-4: phase-1 snapshots, `RunContext.start()` wiring, foundation phase-2 capture, and `verify-replay`.  
**Grade:** **NEEDS CHANGES before final ship**, but the architecture direction is sound.

## Executive Summary

The current design is the right practical shape for Golden Vector: one replay/provenance module, a phase-1 capture at run start, a phase-2 patch when the consumed foundation snapshot becomes known, and a human CLI verifier. This is simpler and more useful than a larger provenance framework. It also leaves a clean path for future predictive models: new model inputs can be recorded as additional manifest sections or later phase updates without changing the run folder concept.

The main issue is not architecture size. The main issue is confidence: the verifier can currently report success for a malformed manifest, and phase-2 failures can disappear silently in the exact cases where provenance is already damaged. Before this becomes the audit base for predictive models, the verifier should be stricter and the phase-2 hook should report incomplete capture more explicitly.

## Findings

### F1 - Verifier can return `OK` for malformed manifests

`verify_manifest()` reads whatever JSON is present, loops over `manifest.get("configs", [])`, optional `manual_data`, and optional `foundation_run_consumed`, then returns `OK` when no asset status failed (`golden_vector/app/replay_manifest.py:143-184`). If `replay_manifest.json` is `{}` or has no `configs`, `asset_statuses` is empty and the CLI prints a successful verdict via `run_verify_replay()` (`golden_vector/cli.py:1138-1145`). This is the highest-risk gap because `verify-replay` is supposed to be the trust check. A corrupt-but-parseable manifest should fail schema validation, not pass with "no snapshot assets recorded." Minimum fix before final: require `manifest_version`, `run_id`, `command`, `started_at_utc`, `git`, and exactly the expected config snapshot entries; return a non-OK verdict for missing or invalid required fields.

### F2 - Phase-2 failure handling is too quiet in damaged-manifest cases

`update_manifest_with_foundation()` correctly records an error string when copying the foundation manifest fails after the phase-1 manifest has been read (`golden_vector/app/replay_manifest.py:107-120`). But if the phase-1 manifest cannot be read, or if the final manifest rewrite fails, the function silently returns (`golden_vector/app/replay_manifest.py:101-105`, `golden_vector/app/replay_manifest.py:122-125`). The CLI wrapper also does not receive a status to log or add to metadata (`golden_vector/cli.py:1415-1423`). That means the foundation snapshot can be consumed successfully while the replay provenance remains `not-applicable` or stale. This does not need a big abstraction, but phase 2 should return a result object or accept the `RunContext` so the run log/metadata can say "foundation replay capture failed."

### F3 - Current-checkout drift is coupled to `ProjectPaths.discover()`

Snapshot integrity works for moved folders because it resolves snapshot paths relative to `run_dir` (`golden_vector/app/replay_manifest.py:269-307`). Drift checks, however, always compare original paths against `ProjectPaths.discover().repo_root` (`golden_vector/app/replay_manifest.py:322-340`), and foundation original-path normalization also uses `ProjectPaths.discover()` (`golden_vector/app/replay_manifest.py:432-436`). This is acceptable for local CLI use from the repo, but it blurs the design line between "is this run folder internally intact?" and "does this checkout match the run?" For future predictive-model audit, keep snapshot integrity pure and make checkout drift explicitly optional, probably by passing a `checkout_root` into `verify_manifest()` or leaving drift to the CLI layer.

### F4 - Phase-2 hook behavior is not tested at the CLI callsite level

The tests cover the phase-2 updater directly (`tests/test_replay_manifest.py:131-170`), but they do not prove that `run_tool_a`, `run_tool_b`, or `run_compare_horizons` actually call the hook after loading a foundation snapshot (`golden_vector/cli.py:497-505`, `golden_vector/cli.py:637-645`, `golden_vector/cli.py:1270-1277`). This is a meaningful gap because the hook placement is the core two-phase design. One fixture-level CLI test for Tool A would probably be enough: stub the foundation loader and pipeline, run the command, then assert `foundation_run_consumed` is populated.

### F5 - `RunContext.start()` now has hidden config/snapshot side effects

Wiring the writer into `RunContext.start()` is simple and matches the plan (`golden_vector/app/run_context.py:81-83`). The tradeoff is that `RunContext.start()` is no longer just "create a run folder and metadata"; it now requires valid config files and may copy a manual SQLite database. That is acceptable for the production lifecycle, but it explains why the shared test helper now silently copies repo configs for every temp path (`tests/helpers.py:7-27`). Longer term, this helper behavior can hide tests that expected an empty config directory. A small future cleanup would be an explicit helper name like `build_configured_test_paths()` or an optional flag, so tests opt into the config fixture instead of getting it implicitly.

### F6 - Hard-fail startup can leave partial run folders

If config snapshots succeed but SQLite backup fails, the writer raises after creating `replay_snapshots/configs/` but before writing `replay_manifest.json` (`golden_vector/app/replay_manifest.py:65-90`, `golden_vector/app/replay_manifest.py:203-234`). `RunContext.start()` has already written `metadata.json` with `RUNNING` before the manifest call (`golden_vector/app/run_context.py:81-83`). This is not a data-corruption problem, but it is operationally confusing: `verify-replay` on that folder will say the run predates replay manifests. Cleaning partial replay files or marking metadata failed would make failure states clearer.

## Architecture Assessment

The one-module approach is better than introducing a provenance framework now. Golden Vector is still local-first, file-based, and run-folder oriented; the replay manifest fits that model. The phase split is also the right abstraction: not everything is known at `RunContext.start()`, and future predictive models will have the same shape. For example, a predictive run may know config/manual/git at phase 1, then later know model artifact hash, feature table hash, training-window id, inference dataset hash, and random seed. The current pattern can support that without redesign.

The important architectural boundary to protect is this: `RunContext` should own run lifecycle, while replay manifest code should own provenance files. That is mostly true now. The part that needs care is reporting: when provenance capture fails after a run has started, the caller needs a visible result so the run can be marked "analytics succeeded, audit capture incomplete." Silent best-effort is fine for git dirty/unavailable, not for missing provenance that the system claims to capture.

## Simpler / More Practical Alternatives Considered

A smaller implementation could have stored only hashes in `metadata.json`. That would be easier, but it would not solve the audit gap because config/manual/foundation files can change later. Copying small snapshots into the run folder is the practical choice.

A bigger implementation could add a generic manifest event registry now. That would be premature. The current functions are plain and understandable. The next improvement should be stricter validation and clearer phase-2 reporting, not a new framework.

## Predictive Model Readiness

This is a reasonable base for later predictive tools because it records run inputs rather than tool-specific outputs. Before predictive models depend on it, I would want three things:

1. A manifest schema validator so "verified" means structurally valid, not merely parseable JSON.
2. A generic way to add later-known artifacts, probably a small `update_manifest_section()` helper rather than one function per future model concept.
3. Explicit model provenance fields when the model arrives: model code/version, model file hash, feature set hash, training data snapshot id, inference data snapshot id, hyperparameters, and random seed.

None of those require changing the current folder layout.

## Test Coverage Review

Coverage is strong for the writer and CLI happy/error cases: phase-1 capture, git unavailable, dirty tree, missing manual DB, missing config, locked SQLite, phase-2 success/failure, pristine verify, corrupted snapshot, moved folder, old run folder, and missing run folder (`tests/test_replay_manifest.py:22-250`). The missing tests are schema-invalid manifests and at least one CLI-level phase-2 hook test. Those two tests would catch the most important failure modes above.

## Recommended Next Fixes

1. Add manifest schema validation and a non-OK verdict for malformed manifests.
2. Make phase-2 update return/report failure instead of silently returning when the manifest cannot be read or rewritten.
3. Add one CLI-level phase-2 hook test.
4. Consider making checkout drift an explicit optional verify mode after the core verifier is stricter.
5. Leave predictive-model abstraction alone for now; extend the schema only when the first predictive run has concrete inputs to capture.
