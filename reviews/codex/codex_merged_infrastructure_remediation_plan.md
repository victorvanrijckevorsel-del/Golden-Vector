# Merged Infrastructure Remediation Plan

**Author:** Codex
**Date:** 2026-06-05
**Inputs:** `reviews/codex/claude_infrastructure_holistic_review.md`, Codex's holistic infrastructure review, `reviews/codex/claude_vs_codex_infrastructure_merge.md`, and Claude's review of this plan in `reviews/codex/claude_review_infrastructure_remediation_plan.md`.

## v3 Changelog

This update incorporates the I2 gate lessons from `reviews/codex/claude_review_i2_gate.md` and Codex's I1/I2 self-review:

1. I1/I2 are now treated as already built and hardened through commit `eda8fb6`: manifest-authoritative readers, immutable run-id artifacts, partial-refresh manifest publish, Hedge Readiness manifest reads, Tool D spot wiring, shared atomic/file/string helpers.
2. Every remaining phase now has an explicit **duplication guard**. New work must reuse existing shared primitives instead of re-growing helpers.
3. I3 is reframed as "artifact contract first, computation move second, serve layer last." This prevents the Options Data Center from becoming a second option pipeline beside the current UI pipeline.
4. I3 must preserve current candidate-selection behavior exactly and prove before/after parity before any option rule tuning.
5. I4/I5 now explicitly reuse the shared IO/status/schema primitives introduced in I1/I2 and may extend them only when behavior has first been reconciled.

## v3.1 I3 Clarifications

This update incorporates Claude's I3 review in `reviews/codex/claude_review_infra_plan_v3_i3.md`:

1. M1's immutable artifact mechanism is confirmed done in commit `eda8fb6`: Parquet artifacts record `source_run_id`, the manifest resolves that writer-recorded run id to the run-stamped `*_latest_<run_id>.parquet` file, and the resolver does not reconstruct immutability by sha256 matching.
2. New I3 option artifacts must use that same writer-recorded `source_run_id` contract. They may keep mutable latest aliases as convenience files, but manifest readers must resolve the run-stamped files through `resolve_current_model_artifact_path`.
3. The option artifact build belongs inside `run_refresh` after Tool D and before `write_current_model_state_manifest`; if option artifact building fails, the model-state manifest is not published.
4. The shared option artifact builder must live outside `golden_vector/serve/` so both refresh-time publishing and any interim serve compatibility path import the same non-serve implementation.
5. The sizing calculator stays request-time because it depends on user quantity/budget/scenario input, but it must operate on the persisted selected candidate rather than scanning raw option chains.
6. The parity test must feed identical cached chains and identical risk-free-rate inputs to the old and new paths, and must cover GDX/GDXJ benchmark liquidity plus proxy-fallback behavior.

## v2 Changelog

Claude approved the plan with refinements. This version incorporates them:

1. The current-state manifest is now the **single atomic pointer** readers resolve through, not just a status report.
2. The product has **one refresh button**: it rebuilds the full pipeline. Granular commands remain developer CLI tools only.
3. Tool C/D audit must-fixes are an explicit Phase 0 prerequisite before trusting refreshed Finder output.
4. Tool D spot-vs-scenario publish behavior is promoted from a status cleanup to a correctness requirement.
5. Persisted option candidate artifacts must retain `liquidity_tier` and preserve the existing "usable means tradable" contract.
6. Atomic publish requires fault-injection tests.
7. Basic timing diagnostics move earlier so slow refreshes can be explained immediately.

## Executive Decision

Golden Vector does not need a math rewrite. The core model architecture is in good shape: QA gates are real, currency normalization is enforced, model functions are mostly pure, and retained outputs already exist. The infrastructure work should focus on the operating layer around the math:

1. Make one full refresh produce one coherent model state.
2. Move heavy option analytics out of the UI and into persisted refresh-time artifacts.
3. Publish the current model state through one atomic manifest pointer so users never see half-refreshed data.
4. Harden data collection, provenance, schema checks, and retention.

The highest-leverage next milestone is a **Golden Vector data center**: one build identity, one atomic current-state manifest, and precomputed option/candidate artifacts that the UI reads quickly.

## Product Decision

There is one product refresh button.

It runs the full pipeline:

`update-data` -> options -> Tool A -> Tool B -> Tool C -> Tool D -> option/candidate artifacts.

The UI should not expose separate "options-only" and "full model" refresh buttons. The product is daily-use, not intraday, so one slower but coherent refresh is better than multiple confusing partial-refresh states. Granular commands such as `update-data --options`, `tool-a`, `tool-b`, `tool-c`, and `tool-d` remain available for developer/debug CLI use.

The refresh button must run in the background with visible progress and clear states:

- building
- complete
- failed, still showing previous complete build

## Current Implementation State After I2 Gate

Already built:

- `latest_model_state.json` is the atomic current-state pointer.
- Main UI readers, Option Trading, Candidate Finder, CLI status, standalone Tool C/D, Hedge Readiness, and Tool A structural detail reads now resolve through the model-state manifest where they consume current model artifacts.
- Full refresh publishes a parent-refresh manifest only after successful completion.
- `refresh --skip-tool-b` publishes an explicitly incomplete partial manifest instead of silently leaving readers pinned to the previous build.
- Tool D scenario runs do not overwrite the Finder-facing spot artifact.
- Shared primitives now exist:
  - `golden_vector.app.model_state.resolve_current_model_artifact_path`
  - `golden_vector.app.model_state.read_current_model_parquet`
  - `golden_vector.app.model_state.read_current_model_json`
  - `golden_vector.app.model_state.resolve_current_foundation_manifest_path`
  - `golden_vector.common.files.atomic_write_text`
  - `golden_vector.common.files.atomic_write_bytes`
  - `golden_vector.common.files.repo_relative`
  - `golden_vector.common.files.sha256_file`
  - `golden_vector.common.files.optional_sha256_file`
  - `golden_vector.common.strings.clean_string`
  - `golden_vector.common.strings.unique_strings`
  - `golden_vector.common.status.combine_statuses`
  - `golden_vector.common.eligibility.is_score_eligible`
  - `golden_vector.common.eligibility.score_eligible_mask`

Planning rule for all remaining phases:

- Before adding any helper or logic block, grep for the existing equivalent and reuse it.
- If behavior differs between existing copies, reconcile the intended behavior first, then centralize.
- Do not add new local copies of `_unique_strings`, `_repo_relative`, `_file_sha256`, `_sha256_file`, `_read_optional_parquet`, `_combine_statuses`, score-eligible coercion, atomic temp-file writes, or run-id/freshness reconciliation.
- New artifacts must be manifest-addressable through the existing model-state resolver rather than adding a parallel "latest file" reader.

## Merged Problem Map

| Priority | Problem | Evidence | Fix Direction |
|---|---|---|---|
| P0 | Current local estate can be stale or incomplete | `main.py status` showed fresh foundation/options, stale Tool A/B, and missing Tool C/D | Add a single model-state manifest and make incomplete builds visible |
| P1 | No single full-refresh identity | `run_refresh` calls independent stages; each stage mints/publishes its own latest | Mint one parent refresh id and publish one current-state manifest pointer |
| P1 | Latest outputs are not published atomically as a group | Each tool writes latest aliases as it finishes | Stage outputs first; atomically replace one current-state manifest pointer after full success |
| P1 | Option candidate/liquidity analytics run in the serve layer | `load_option_trading_data` reads raw chains and rebuilds slots/liquidity at request time | Persist option contract metrics, candidate slots, overview rows, and Finder inputs during refresh |
| P1 | UI refresh button suggests more freshness than it provides | Option refresh runs `update-data --options`, not full Tool A/B/C/D recompute | Replace it with one product refresh button that runs the full pipeline |
| P1 | Tool D scenario runs can interfere with Finder's spot Tool D input | Spot and arbitrary scenario outputs can share/latest aliases unless carefully wired | Finder reads the spot alias; scenario runs never overwrite the spot artifact |
| P2 | Option cache keys are weaker than Candidate Finder keys | Option cache keys are mostly run-id based; Finder uses stronger content hashes | Use content/config hashes or remove heavy option cache once artifacts are persisted |
| P2 | Options feature/candidate provenance is incomplete | Latest options manifest tracks raw snapshots better than derived features/slots | Manifest every derived option artifact with path, row count, schema version, config hash, and sha256 |
| P2 | Yahoo collection is fragile and slow | Thin yfinance wrapper, no retry/backoff/timing, all-expiry option fetches | Add retry/backoff/throttle/timing; later add targeted expiry-band fetch mode |
| P2 | Raw equity and FX replay proof is incomplete | Claude found raw equities/FX not hashed into replay manifest | Add raw equity/FX file hashes to replay manifest |
| P2 | Analytical Parquet schema drift can degrade silently | Readers often patch missing columns or return empty frames | Add schema contracts and fail loudly on writer/reader mismatch |
| P3 | Retained runs grow without cleanup | No prune command yet | Add retention command that preserves current-state referenced artifacts |
| P3 | Tool C/D still have some config-centralization drift | Some thresholds/directions live in model code | Move analytic constants to config after infrastructure is stable |

## Sequenced Plan

### Phase 0 - Correctness and Operational Baseline

Goal: know the current state and close known correctness gaps before trusting a refreshed Finder.

Work:

1. Verify the Tool C/D audit must-fixes are closed before treating refreshed Finder output as trustworthy:
   - preset eligibility does not silently change because Tool C/D columns exist
   - Tool C does not crash when Tool A is absent
   - Finder reads the intended Tool D spot artifact
2. Run `python main.py status` and save the important state in a progress file.
3. Run the focused test groups for refresh/status/options/Finder.
4. Run one full `python main.py refresh` only after the correctness checks above are satisfied, so Tool A/B/C/D and options are aligned locally.

Acceptance:

- The current stale/missing state is documented.
- No code architecture is judged using stale local outputs.
- A full rebuild does not imply the Finder is trustworthy until the Tool C/D correctness prerequisites pass.

Why first:

This avoids confusing infrastructure bugs with old local data, and avoids creating a freshly-built but still-wrong Finder.

### Phase 1 - Atomic Current-State Manifest

Goal: give the CLI and UI one source of truth for "what complete Golden Vector build should I read?"

Work:

1. Add a `latest_model_state.json` style manifest shaped as an atomic pointer, not just a status report.
2. Include:
   - parent refresh id, nullable until Phase 2 threads it through every stage
   - foundation refresh id and status
   - options refresh id and status
   - an extensible artifact map for foundation, options, Tool A/B/C/D, option candidates, and Finder inputs
   - output paths, hashes, row counts, schema versions, and source refresh ids
   - manual data hash / timestamp
   - config hashes
   - complete/incomplete flag
   - human-facing warnings
3. Publish the manifest with single-file `os.replace()` so the pointer switch itself is atomic.
4. Keep existing `*_latest.parquet` aliases as convenience files, but do not design new readers around them as the authoritative coherence mechanism.
5. Update `main.py status` to read this manifest first, while keeping fallback behavior for older local data.
6. Update UI readiness banners to use this manifest instead of independently reconstructing alignment.
7. Add crude stage timing fields where available so slow refreshes can already be explained.

Acceptance:

- Status reports all missing/mismatched pieces, not only the first mismatch.
- Candidate Finder and Option Trading can show "model complete", "data fresh but tools stale", or "missing outputs" clearly.
- Readers can be migrated to resolve coherent artifacts through the manifest.
- No change to model math.

Risk control:

- Build the manifest in its final pointer shape now to avoid rework when Phase 2 adds the parent refresh id and reader migration.

### Phase 2 - One Parent Refresh ID, One Product Refresh Button

Goal: make a full refresh all-or-nothing from the user's perspective.

Work:

1. Mint one parent `refresh_run_id` at the start of `run_refresh`.
2. Thread it through foundation, options, Tool A, Tool B, Tool C, and Tool D outputs as the parent model build id.
3. Keep per-stage run ids if useful for replay/debugging, but make the parent id the coherence key.
4. Write immutable per-run outputs first.
5. Publish by replacing the single current-state manifest pointer after the full refresh succeeds.
6. If any stage fails, leave the previous latest model state intact.
7. Replace the current UI options-only refresh action with one product refresh button that runs the full build in the background.
8. Show visible progress by stage:
   - fetching foundation data
   - fetching option chains
   - computing Tool A
   - computing Tool B
   - computing Tool C
   - computing Tool D
   - building option/candidate artifacts
   - publishing current state
9. Wire Tool D spot/scenario publishing correctly:
   - spot Tool D writes the spot alias consumed by Finder
   - arbitrary `--gold-price` scenario runs never overwrite the spot alias
   - Finder consumes the spot artifact

Acceptance:

- A forced failure after Tool B does not publish a half-new state.
- A deliberate Tool C failure leaves the previous manifest/state fully intact.
- A UI read during refresh either sees the old complete state or the new complete state, never a torn state.
- Mixed-refresh warning becomes an exceptional fallback, not the normal coherence mechanism.
- One UI button rebuilds everything; granular commands remain developer CLI only.
- A Tool D scenario run leaves the Finder-consumed spot artifact unchanged.

Risk control:

- Preserve standalone `tool-a`, `tool-b`, `tool-c`, and `tool-d` commands. Atomic group publish should apply to full `refresh`, not necessarily every standalone analytical run.
- Test the failure path directly with fault injection, not only the happy path.

### Phase 3 - Options Data Center

Goal: stop computing option selection inside web requests.

Phase gate before coding:

- Search the option and Finder serve/model layers for existing helpers and call sites:
  - `load_option_trading_data`
  - `build_option_trading_overview`
  - `_candidate_slots`
  - `_liquidity_measurements`
  - `_accepted_candidate_grids`
  - `load_candidate_finder_data`
  - `_has_usable_slots`
- Write down the exact current request-time inputs and outputs before moving anything.
- Reuse the shared primitives listed in "Current Implementation State After I2 Gate".
- Do not add a second option-selection engine. Extract or call the existing one.

Work:

1. Define one Options Data Center artifact contract before moving computation:
   - artifact names
   - schema versions
   - required columns
   - source artifact dependencies
   - manifest keys
   - UI/CLI consumers
   - immutable publish rule: each Parquet artifact writes a run-stamped `*_latest_<source_run_id>.parquet` file and a convenience latest alias containing the same `source_run_id`; the model-state manifest resolves the run-stamped file through the existing `resolve_current_model_artifact_path` path, not through sha256 matching
2. Add a refresh-time builder that reuses the existing option-selection logic instead of reimplementing it.
   The shared builder must live outside `golden_vector/serve/` and both refresh publishing and any interim compatibility path must call it.
3. Persist these artifacts:
   - normalized option contract metrics
   - liquidity measurements
   - candidate slots by ticker, side, horizon band, and bucket
   - selected put/call candidates for the simplified UI
   - Option Trading overview table
   - Candidate Finder option inputs
   This step runs after Tool D and before the model-state manifest swap. A failure leaves the previous current manifest intact.
4. Add artifact manifests with:
   - source options refresh id
   - parent model refresh id
   - config hash
   - source chain hashes
   - row counts
   - schema version
   - sha256
   - `liquidity_tier` and tradable/watch/no-trade status for every candidate slot
5. Register the new artifacts in `latest_model_state.json` and resolve them with `resolve_current_model_artifact_path`.
6. Update `serve/option_trading_data.py` to read persisted artifacts through the manifest.
7. Update `serve/candidate_finder_data.py` so it reads persisted Finder option inputs and does not call the heavy option-chain scanner.
8. Keep raw-chain fallback only as an explicit diagnostic/developer path, not normal UI behavior.
9. Keep the sizing calculator request-time, but feed it persisted selected candidates and persisted scenario inputs rather than loading chains.

Shared primitives to reuse:

- Manifest/artifact reads: `resolve_current_model_artifact_path`, `read_current_model_parquet`, `read_current_model_json`.
- Atomic writes: `atomic_write_text`, `atomic_write_bytes`.
- Provenance and cache hashes: `sha256_file`, `optional_sha256_file`, `repo_relative`.
- String/run-id normalization: `clean_string`, `unique_strings`.
- Status aggregation: `combine_statuses`.
- Score eligibility: `is_score_eligible`, `score_eligible_mask`.

Do not create:

- another `_unique_strings`
- another `_repo_relative`
- another `_file_sha256` / `_sha256_file`
- another ad hoc Parquet optional-read helper unless it is first added as a shared common primitive
- another freshness/alignment reconciliation routine
- another option candidate-ranking implementation

Acceptance:

- Cold `/option-trading` and `/candidate-finder` loads do not scan all raw chains.
- Candidate selection is replayable from artifacts.
- The same candidate rows feed CLI, report, Option Trading UI, ticker detail, and Candidate Finder.
- Option cache keys either use artifact content hashes or become unnecessary.
- Moving candidates to artifacts does not change which tickers count as having a usable put/call.
- Finder keeps the strict "usable means tradable" contract by filtering persisted slots on `liquidity_tier == "tradable"`.
- Before/after parity test proves persisted artifacts produce:
  - the same tickers
  - the same put/call slots
  - the same `liquidity_tier`
  - the same "usable = tradable" set
  - the same Option Trading overview rows, except for intentional provenance fields
  - the same benchmark ETF liquidity support for GDX/GDXJ
  - the same proxy fallback candidates for non-benchmark tickers
- The parity fixture gives both paths the same cached chains and same risk-free rate so delta/IV differences cannot be hidden as provenance differences.
- A request-time code scan shows normal UI readers do not scan raw chains.
- A cold-load timing check is recorded before and after the move.

Risk control:

- Do not change the candidate-selection rules in this phase unless required. First move the computation to the right layer, then tune rules separately.
- If the existing request-time path has messy helpers, extract the smallest shared helper needed and update both old and new paths before deleting the old path. Do not fork logic.

### Phase 4 - Data Collection Resilience

Goal: make Yahoo/yfinance failures less mysterious and less disruptive.

Phase gate before coding:

- Inventory existing Yahoo/yfinance timing, retry, status, and manifest-write helpers.
- Reuse shared atomic/file/string helpers for every status/provenance write.
- Do not introduce a second data-vendor abstraction, scheduler, or request-time cache.

Work:

1. Add retry/backoff around Yahoo calls.
2. Add light throttling and per-symbol timing.
3. Keep per-ticker best-effort behavior.
4. Add structured collection stats to manifests.
5. Add an optional configured expiry-band fetch mode for options:
   - full-chain mode for audit/debug
   - targeted mode around configured DTE bands for faster refresh
6. Consider incremental equity/FX/gold pulls after the atomic model-state work is stable.

Acceptance:

- Transient Yahoo failures are retried and logged.
- Refresh reports which tickers/expiries failed or were slow.
- No paid API or second vendor is introduced yet.
- Collection stats use one shared status shape; UI/CLI/report readers should not parse separate local variants.
- Timing/provenance writes use `atomic_write_text` / `atomic_write_bytes` and `repo_relative`.

### Phase 5 - Provenance, Schema Contracts, and Retention

Goal: make historical runs replayable and durable without silent drift.

Phase gate before coding:

- Search for existing schema/version/provenance checks before adding new contracts.
- Define shared schema-validation primitives once, then use them for Tool A/B/C/D, options, and Finder artifacts.
- Reuse model-state artifact paths when deciding retention safety. Do not separately infer "current" from mutable aliases.

Work:

1. Add raw equity and FX hashes to replay manifests.
2. Add schema contracts for analytical outputs:
   - Tool A
   - Tool B
   - Tool C
   - Tool D
   - options features
   - option candidate artifacts
   - Candidate Finder input artifacts
3. Stamp `schema_version` in each artifact and manifest.
4. Validate required columns/dtypes on write and read.
5. Replace silent missing-column degradation with explicit warnings or failures depending on severity.
6. Add `prune-runs`:
   - keep latest N full model states
   - always keep artifacts referenced by current state
   - dry-run by default
7. Relabel normal `verify-replay` post-latest drift as informational instead of warning-level integrity failure.

Acceptance:

- A renamed/dropped analytical column fails loudly in tests.
- Replay manifests prove all major raw inputs, not only selected outputs.
- Retention cannot delete the currently active model state.
- Schema migrations can be deliberate and visible instead of accidental silent drift.
- Schema validation has one shared implementation and one shared error/report shape.
- Retention walks manifest-referenced artifacts first and treats mutable aliases as non-authoritative convenience files.

### Phase 6 - Smaller Cleanups After the Data Center

Goal: remove remaining drift after the big infrastructure pieces are stable.

Phase gate before coding:

- Treat every duplicated freshness/status/ticker/numeric helper as a correctness risk.
- Reconcile intended behavior before consolidating, especially if existing copies disagree.
- Keep cleanup scoped: consolidate shared plumbing without changing Tool A/B/C/D math.

Work:

1. Move Tool C/D hard-coded analytic thresholds and rank directions into config.
2. Report both Tool D spot latest and arbitrary scenario Tool D latest in status.
3. Extract duplicated freshness/alignment helpers from CLI and Candidate Finder into one shared module.
4. Extract remaining duplicated generic helpers when low-risk:
   - optional numeric coercion
   - optional Parquet read wrappers
   - ticker normalization
   - UTC timestamp formatting
5. Keep model functions pure and IO-free.

Acceptance:

- Tool C/D parameters follow the same centralized-config rule as Tool A/B.
- CLI and UI use the same alignment logic.
- No remaining new work depends on mutable latest aliases as the current-state authority.
- No remaining new work introduces local copies of helpers already available in `golden_vector/common/`.

## Recommended Milestone Split

### Milestone I1 - Atomic Model State and Honest Status

Includes Phases 0 and 1.

Why this split:

It gives immediate clarity and establishes the manifest in the right final shape: one atomic pointer to a coherent model state.

### Milestone I2 - Parent Refresh ID and One Product Button

Includes Phase 2.

Why this split:

Full-refresh publish discipline is important but subtle. It should not be mixed with option selection changes. This milestone makes the one UI refresh button rebuild everything and publish by flipping the manifest pointer.

### Milestone I3 - Options Data Center

Includes Phase 3 and option-specific cache cleanup.

Why this split:

This is the biggest performance win and should be reviewed on its own. It changes where option computation lives, not the finance logic itself.

Implementation rhythm:

1. Start with an artifact-contract commit.
2. Then add the refresh-time builder while the old request-time path still exists.
3. Add a parity test comparing persisted output to the old path.
4. Only after parity passes, move the serve layer to read persisted artifacts.
5. Delete or quarantine the old heavy request-time path once normal UI reads no longer need it.
6. End with a self-review focused on duplication, request-time raw-chain scans, manifest resolution, and cold-load timing.

### Milestone I4 - Source Reliability and Auditability

Includes Phases 4 and 5.

Why this split:

Retry/backoff, schema contracts, replay hashes, and retention are durability work. They are important, but they should not block the data-center refactor.

Implementation rhythm:

1. Add shared primitives first if the phase needs new generic behavior.
2. Apply them across all affected writers/readers in the same milestone.
3. Add tests proving both successful paths and failure/reporting paths.
4. Do not leave a new helper in one module if another module already has the same idea.

### Milestone I5 - Config and Status Cleanup

Includes Phase 6.

Why this split:

These are correctness/maintainability improvements, but lower risk than the operational fixes above.

Implementation rhythm:

1. Start by listing duplicated helpers and logic still present.
2. For each divergent copy, decide the intended behavior before merging.
3. Prefer one small shared helper plus call-site updates over broad rewrites.
4. Run focused regression tests for every screen or CLI command whose behavior depends on the consolidated helper.

## What Not To Do Yet

1. Do not add a scheduler. Manual refresh is still right for this local-first product.
2. Do not add another market-data vendor yet. First add retries, timing, and better manifests around Yahoo.
3. Do not add more request-time caches as the main speed fix. That hides the problem instead of moving computation to the pipeline.
4. Do not tune option candidate rules while moving the computation layer. Preserve behavior first, then improve selection logic in a separate review.
5. Do not rewrite Tool A/B/C/D math. The model layer is not the bottleneck.
6. Do not add local helper copies for filesystem writes, hashing, path formatting, unique-string extraction, score eligibility, status combining, ticker normalization, or freshness reconciliation.
7. Do not add a second current-state concept. `latest_model_state.json` is the pointer; mutable latest aliases are convenience outputs only.

## Historical First Build Brief - I1, Already Built

This brief is retained for history. I1/I2 are already built and hardened; the active next brief is the I3 brief below.

**Build I1: atomic current-state manifest and honest refresh status.**

Scope:

1. Verify Tool C/D correctness prerequisites before relying on rebuilt Finder output.
2. Add current-state manifest writer after full `refresh`, shaped as the single atomic pointer.
3. Add manifest reader and status summary.
4. Update CLI status to use the manifest and list all missing/mismatched outputs.
5. Update UI banners so users can distinguish:
   - complete model build
   - failed build, still showing previous complete build
   - incomplete/mixed legacy state
6. Add basic stage timing fields where available.
7. Add tests for:
   - complete manifest
   - missing Tool C/D
   - stale Tool A/B versus fresh options
   - legacy fallback when no manifest exists

Stop there. Do not yet move option computation. Do not yet rewrite candidate rules.

## Proposed Next Build Brief After I2

**Build I3: Options Data Center with strict parity and no duplicated helpers.**

Scope:

1. Start with a duplication preflight:
   - list the existing option/Finder compute functions to reuse
   - list the shared primitives from `golden_vector/common/` and `golden_vector/app/model_state.py`
   - confirm no new local copies of known helper suspects are planned
2. Define persisted artifact contracts for:
   - option contract metrics
   - liquidity measurements
   - candidate slots
   - selected put/call candidates
   - Option Trading overview rows
   - Candidate Finder option inputs
3. Register these artifacts in the model-state manifest shape using the M1 writer-records-`source_run_id` immutable artifact mechanism, not sha256 reconstruction.
4. Build refresh-time artifact writers around one non-serve shared builder that reuses the current option-selection code.
5. Insert the artifact writer into `run_refresh` between Tool D and the atomic model-state manifest publish.
6. Add before/after parity tests against the existing request-time path using identical cached chains and risk-free-rate inputs.
7. Cover GDX/GDXJ benchmark liquidity and proxy fallback in parity.
8. Move `serve/option_trading_data.py` and `serve/candidate_finder_data.py` to read persisted artifacts through the manifest.
9. Keep request-time sizing, but operate on persisted selected candidates instead of scanning raw chains.
10. Prove normal UI reads no longer scan raw chains.
11. Record cold-load timing before and after.

Stop at the I3 gate with:

- artifact contract summary
- parity-test proof
- manifest sample showing option/Finder artifacts
- cold-load before/after timing
- grep proof that normal serve paths do not scan raw chains
- duplication self-review findings

Out of scope for I3:

- changing option candidate rules
- changing DTE/delta/liquidity thresholds
- adding a scheduler
- adding another vendor
- adding request-time caches as the main speed fix
