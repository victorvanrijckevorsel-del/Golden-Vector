# Claude Review Request - Runtime Redesign, Manual Store, and Reliability Hardening

Date: 2026-04-22  
Author: Codex  
Mode required: Read-only review only. No implementation. No code edits. No silent assumptions.

## Review Objective

Please perform a deep, skeptical, implementation-level review of the **recent product/runtime redesign** in this repo.

This is not a quick scan and not a style review. Treat it as a serious review of the new operating model of the app.

Your job is to decide whether the code is:

1. logically correct,
2. aligned with the updated product decisions,
3. safe to rely on in normal use,
4. free of hidden data-quality regressions,
5. test-covered in the right places,
6. and actually in a better architectural state than before.

I want a **thorough review**. The code now works, tests pass, and live smoke runs pass. That is not enough. I want you to look for subtle mistakes, mismatches, and design drift.

## Current Product Direction

Please review against this **current** product model, not the older one:

### 1. Market data is explicit refresh, then local-first usage
- `update-data` is the heavy market-data refresh step
- `tool-a` uses the latest validated local market-data snapshot by default
- `tool-b` uses the latest validated local market-data snapshot by default
- normal usage should not re-fetch Yahoo data unless the user explicitly refreshes

### 2. Combined is no longer an active backend engine
- the old Combined backend was de-scoped from the active product
- it is preserved only as legacy reference code
- Combined will return later as a lightweight side-by-side compare view, not as a third analytics engine

### 3. Tool B manual inputs are no longer CSV-first
- Tool B now uses a local SQLite store
- slow-moving manual fields should be editable directly in the tool
- notes/comments per stock are now a real supported concept
- CSV is now only support infrastructure for import/export or migration

### 4. Reliability hardening was added
- FX staleness is now explicit in normalization
- market snapshot parsing was hardened
- run artifacts and CLI JSON output were hardened so user-facing inspect commands are clean

Please judge the code against **this** product shape.

## Primary Scope

Review these files carefully.

### Runtime / orchestration changes
- `golden_vector/cli.py`
- `golden_vector/app/latest_data.py`
- `golden_vector/app/paths.py`
- `golden_vector/app/run_context.py`
- `golden_vector/ingestion/foundation.py`
- `golden_vector/ingestion/persist.py`

### Tool B manual-data redesign
- `golden_vector/screening/manual_store.py`
- `golden_vector/screening/manual_data.py`
- `golden_vector/screening/pipeline.py`

### Reliability hardening
- `golden_vector/ingestion/standardize.py`
- `golden_vector/normalize/prices_usd.py`
- `golden_vector/normalize/market_snapshot.py`
- `golden_vector/qa/normalization_quality.py`
- `config/qa.yaml`
- `golden_vector/contracts/config_models.py`
- `golden_vector/contracts/data_models.py`

### Docs / operator-facing files
- `README.md`
- `docs/golden_vector_architecture_map.md`
- `golden_vector/combined/README_LEGACY.md`
- `reviews/codex/product_runtime_redesign_plan.md`

### Tests added or materially affected
- `tests/test_latest_data.py`
- `tests/test_manual_data.py`
- `tests/test_cli_manual_data.py`
- `tests/test_cli_tool_b.py`
- `tests/test_tool_b_pipeline.py`
- `tests/test_prices_usd.py`
- `tests/test_market_snapshot_normalization.py`
- `tests/test_normalization_quality.py`
- `tests/test_standardize.py`
- `tests/test_run_context.py`
- `tests/test_paths.py`
- `tests/test_config_models.py`

### Prior self-reviews from Codex
- `reviews/codex/codex_review_phase1_runtime_shift_findings.md`
- `reviews/codex/codex_review_phase3_manual_store_findings.md`
- `reviews/codex/codex_review_phase4_reliability_hardening_findings.md`

## Cross-Check Against These Source-of-Truth Docs

Please cross-check the implementation against:

- `AGENTS.md`
- `CLAUDE.md`
- `claude-python-rebuild-spec-gold-v1.md`
- `codex-full-briefing.md`
- `reviews/codex/golden_vector_master_plan.md`
- `reviews/codex/product_runtime_redesign_plan.md`

Important:
- if code and docs disagree, call that out explicitly
- if older docs still describe the previous Combined-backend model, call that out explicitly
- do not silently “resolve” ambiguity in your head

## What Changed Conceptually

The code now claims to support this behavior:

### A. Explicit local-first runtime
- `update-data` refreshes market data once
- latest validated artifacts are published and referenced by a manifest
- Tool A and Tool B run from those stored artifacts by default
- live fetch is not part of the normal command path anymore

### B. Tool B manual-data store
- Tool B manual data now lives in `data/manual/screening/manual_screening.sqlite3`
- the app can initialize, import, export, inspect, and edit that store through CLI commands
- notes/comments exist separately from the numeric company inputs

### C. CSV is no longer the main workflow
- CSV files still exist, but only as support paths for import/export/migration
- runtime should not depend on creating or editing CSV templates as a side effect anymore

### D. FX staleness and snapshot-hardening behavior
- normalization now records `fx_staleness_days`
- stale FX becomes an explicit normalization status
- QA can warn or fail on stale FX based on config
- snapshot parsing is more defensive and should fail cleanly on bad Yahoo payloads

Please verify that the code actually does all this safely and coherently.

## Mandatory Review Lenses

Please use all of these lenses, not just a subset.

### 1. Architecture correctness
Check that:
- the runtime really is local-first now
- `update-data` is the only active heavy refresh path
- Tool A and Tool B truly consume stored validated artifacts by default
- the active code no longer behaves like the older always-refresh model

Look for:
- hidden Yahoo fetches still happening during Tool A / Tool B normal use
- duplicated orchestration paths
- new drift introduced by the runtime redesign

### 2. Product-shape correctness
Check that:
- Combined is actually de-scoped from the active product
- current docs and current code agree on that
- no active command or output still implies Combined is a core engine

Look for:
- lingering active dependencies on Combined artifacts
- stale docs or stale tests still assuming Combined is live

### 3. Manual-data store design quality
Review whether the new Tool B manual-data model is actually an improvement.

Check:
- SQLite schema shape
- company inputs vs verification vs reporting vs notes separation
- import/export behavior
- direct update behavior
- whether normal Tool B execution is now read-only with respect to user-managed support files

Look for:
- accidental data loss on import/export
- duplicate row ambiguity
- hidden overwrites
- inability to represent missing vs blank cleanly
- notes contaminating calculation fields

### 4. Runtime/operator safety
Check whether the new commands are practical and safe:
- `manual-data init`
- `manual-data show`
- `manual-data set-company`
- `manual-data set-reporting`
- `manual-data set-verification`
- `manual-note add`
- `manual-note list`

I want you to look for:
- weak validation
- wrong ticker eligibility checks
- ugly or misleading output
- commands that can leave the store in a confusing state

### 5. Data-quality / correctness risks
Check whether the new reliability layer is really doing what it should:
- stale FX should be explicit, not silent
- snapshot parsing should be defensive, not brittle
- missing values should remain visible, not turn into fake strings or fake numbers
- JSON output should not emit invalid or confusing values

Look aggressively for:
- `NaN` / `NaT` leaking into stored or printed artifacts
- stale FX being marked `OK`
- malformed snapshot payloads producing misleading rows instead of explicit failures
- status fields becoming inconsistent between normalization and QA

### 6. Contract and dataset consistency
Check consistency between:
- actual emitted DataFrame columns
- contract models in `data_models.py`
- config in `qa.yaml`
- tests
- runtime summaries and run artifacts

Look for:
- fields produced but not documented
- fields documented but not actually produced
- mismatch around `fx_staleness_days`
- mismatch around manual store behavior vs README

### 7. Migration / backward compatibility sanity
The repo already had real starter CSV/manual data before the store redesign.

Please check whether:
- first-run CSV import into the store is sane
- import/export can round-trip without obvious corruption
- legacy support data can still be recovered or inspected
- the migration path is predictable for Emanuel later

### 8. Test quality
Review the tests seriously.

Tell me if they:
- actually protect the risky paths
- miss likely real-world regressions
- are too fixture-driven
- fail to cover live-operator commands properly

I especially want you to call out:
- missing tests for store migration
- missing tests for notes
- missing tests for runtime local-first behavior
- missing tests for stale FX fail-vs-warn behavior

## Required Checks

Please explicitly check for all of the following:

1. `tool-a` and `tool-b` no longer fetch Yahoo by default during normal usage.
2. `update-data` really is the active refresh path.
3. Normal Tool B runs no longer depend on creating/updating CSV templates.
4. The SQLite manual-data store does not silently corrupt missing values.
5. Notes are kept separate from core valuation inputs.
6. CLI update commands validate against the correct ticker set.
7. Store import/export is sane and non-destructive enough for this stage of the product.
8. `manual-data show` outputs clean machine-readable JSON.
9. FX staleness is explicit and correctly integrated into normalization status + QA.
10. Snapshot parsing now fails clearly on malformed or incomplete Yahoo payloads.
11. The current docs reflect the current product model better than the older Combined-engine model.

## What I Especially Want You To Be Hard On

Please be hard on these specific areas:

- any hidden regression introduced by moving Tool B away from CSV-first runtime behavior
- any place where stale FX could still slip through quietly
- any place where `NaN` / `NaT` / weird string values can still leak into user-visible output
- any place where the new CLI commands are too weak, too noisy, or too risky
- any place where the code claims “local-first” but still behaves like “live-first”

## Output Format

Please write your review to:

- `reviews/codex/claude_review_phase3_phase4_runtime_manual_store_findings.md`

Use this structure:

1. Findings first, ordered by severity (`P0` to `P3`)
2. Residual risks
3. Final verdict: `READY`, `READY WITH MINOR CHANGES`, or `NOT READY`

For each finding, include:
- severity
- short title
- exact file/section involved
- why it matters
- what needs to change or be clarified

If you find no real problems:
- say that explicitly
- still list any residual risks or future hardening opportunities

## Review Constraints

- Read-only review only
- No code edits
- No silent assumptions
- No vague approval
- If the code is good, say why specifically
- If a prior Codex self-review missed something important, call that out directly

## Success Standard

The review passes only if the code is:
- consistent with the current product direction,
- safer than the previous runtime model,
- operationally sane for local-first use,
- and not carrying new hidden fragility in the manual-data or normalization layers.
