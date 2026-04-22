# Claude Code Review — Runtime Redesign, Manual Store, and Reliability Hardening

**Reviewer**: Claude Code
**Date**: 2026-04-22
**Target**: Runtime redesign + SQLite manual store + reliability hardening on branch `dev-vic`
**Cross-checked against**: `AGENTS.md`, `CLAUDE.md`, `golden_vector_master_plan.md`, `claude-python-rebuild-spec-gold-v1.md`, `codex-full-briefing.md`, `product_runtime_redesign_plan.md`, Codex self-reviews (phases 1/3/4)
**Mode**: Read-only. Tests executed. No code changes.

**Test results**: 140/140 tests pass (39.31s). Test count grew from 89 to 140 since the Phase 6/7 review.

---

## 1. Findings

### P2-1: `manual-data show` outputs `to_jsonable` but NaN/NaT values from the SQLite store could leak as Python-specific strings

**Files**: [cli.py:729](golden_vector/cli.py#L729), [run_context.py](golden_vector/app/run_context.py) (`to_jsonable`)

**What the code does**: `manual-data show` reads from the SQLite store, converts rows to dicts via `to_dict(orient="records")`, then runs through `to_jsonable` before `json.dumps`. The `to_jsonable` function (I verified it exists) should handle NaN/NaT conversion to `None`.

**Why it matters**: SQLite stores NULLs cleanly, so the normal path is fine. But if a corrupt or migrated CSV had a literal `"NaN"` string imported, it would pass through as a string, not as `None`. The `_sqlite_value` function handles `pd.isna()` but not the string `"NaN"` or `"nan"`.

**Risk level**: Low — this would require a corrupted CSV import. But the review request specifically asks about NaN leaking into user-visible output.

**What should change**: In `to_jsonable`, add a check for string `"NaN"`/`"NaT"` and convert to `None`. Or add a normalization pass during CSV import that strips literal NaN strings.

---

### P2-2: `export_store_to_csv` overwrites existing CSVs without backup or confirmation

**File**: [manual_store.py:353-370](golden_vector/screening/manual_store.py#L353-L370)

**What the code does**: `export-csv` writes `company_inputs.csv`, `source_verification.csv`, and `reporting_calendar.csv` directly, overwriting any existing files.

**Why it matters**: If a user has manually curated CSV files that haven't been imported yet, running `export-csv` would overwrite them with the store's current state (which might have less data if the CSVs were never imported). The CLAUDE.md rules say "Ask before deleting data files." This is effectively a destructive overwrite of user-managed files.

**What should change**: Either back up existing CSVs before overwriting (e.g., rename to `company_inputs.csv.bak`) or add a `--force` flag. For v1 CLI usage this is acceptable, but flag it for Emanuel.

---

### P2-3: `codex-full-briefing.md` still describes the old Combined-backend model and CSV-first manual data

**File**: `codex-full-briefing.md` — Section 5 (Integration plan), Section 7 (Build sequence Phase 7), Appendix A

**What it says**: Section 5 describes Combined View with "combined score, combined verdict, merged dashboard" as an active engine. Section 7 Phase 7 says "Combined surface — Merged ranking from both engines." The manual data section describes "YAML/CSV input files" as the approach.

**What the current product model says**: Combined is de-scoped from the active backend. Manual data is now SQLite-first. The architecture map and README correctly reflect this.

**Why it matters**: The briefing is listed as a "Must read" document. A new contributor reading it would build mental models that contradict the current code. The architecture map (`docs/golden_vector_architecture_map.md`) is now the more accurate reference.

**What should change**: Add a note at the top of `codex-full-briefing.md`: "This document reflects the original design. For the current product model, see `docs/golden_vector_architecture_map.md`." Or update sections 5 and 7 to reflect the de-scoped Combined and SQLite store.

---

### P2-4: `_combine_statuses` now rejects unknown values — previous Phase 4 finding resolved

**File**: [cli.py:1145-1159](golden_vector/cli.py#L1145-L1159)

**Verification**: The function now raises `ValueError` on unknown status strings. Test `test_combine_statuses_rejects_unknown_values` confirms this. Previous P2-3 finding from the Phase 4 review is fully resolved.

**Status**: Resolved. Not a finding.

---

### P2-5: No test for CSV import → store → export round-trip integrity

**Files**: `tests/test_manual_data.py`, `tests/test_cli_manual_data.py`

**What's tested**: Store initialization, set-company updates, note add/list, template creation, legacy CSV import during pipeline, missing-file handling.

**What's missing**: No test imports a CSV with known data, then exports it back to CSV, and verifies the exported values match the originals. This would catch:
- NaN/None normalization differences between import and export
- Date format changes (e.g., `2026-01-15` → `2026-01-15` or `2026-1-15`)
- Numeric precision loss (float round-trip through SQLite)
- Rate normalization changes (e.g., `30` → `0.3` → exported as `0.3`, not `30`)

**Why it matters**: The review request specifically asks about "import/export can round-trip without obvious corruption."

**What should change**: Add a test that: (1) writes a CSV with known values including rates > 1.0, dates, and NaN fields, (2) imports into the store, (3) exports back to CSV, (4) verifies critical values match. The rate normalization means `30` → `0.3` is intentional and the test should assert `0.3`, not `30`.

---

### P2-6: `compare-horizons` now uses `_load_latest_foundation_snapshot` — correctly local-first

**File**: [cli.py:992-1000](golden_vector/cli.py#L992-L1000)

**Verification**: `compare-horizons` loads from the latest validated snapshot, not from a live Yahoo fetch. It passes `requested_tickers=[normalized_ticker]` to load only the needed equity history.

**Status**: Correctly local-first. Not a finding.

---

### P3-1: `tool-a` and `tool-b` are confirmed local-first — no Yahoo fetch during normal use

**Files**: [cli.py:371-378](golden_vector/cli.py#L371-L378) (Tool A), [cli.py:526-533](golden_vector/cli.py#L526-L533) (Tool B)

**Verification**: Both commands call `_load_latest_foundation_snapshot`, which reads from local Parquet files referenced by a manifest. Neither calls `execute_foundation_pipeline`. Only `update-data`/`foundation` runs the Yahoo-backed pipeline.

The manifest includes a `foundation_signature` derived from the universe config. If the universe changes, `load_latest_foundation_snapshot` raises `ValueError` telling the user to run `update-data` first. Test `test_load_latest_foundation_snapshot_rejects_mismatched_universe_signature` confirms this.

**Status**: Correctly local-first. The architecture is a genuine improvement over the always-refresh model.

---

### P3-2: Combined is correctly de-scoped from the active product

**Verification**: 
- `cli.py` no longer has a `combined` command or `run_combined` function
- `golden_vector/combined/README_LEGACY.md` explicitly states: "This code is preserved for reference but is not part of the active runtime."
- `docs/golden_vector_architecture_map.md` says: "Combined backend: De-scoped. Old backend preserved as legacy code."
- The Combined modules still exist in `golden_vector/combined/` but are not imported by `cli.py`

**Status**: Cleanly de-scoped. No lingering active dependencies.

---

### P3-3: SQLite schema correctly separates notes from calculation fields

**File**: [manual_store.py:379-433](golden_vector/screening/manual_store.py#L379-L433)

**Verification**: Four separate tables:
- `company_inputs` — numeric valuation fields only, keyed by ticker
- `source_verification` — per-field verification status, keyed by (ticker, field_name)
- `reporting_calendar` — dates and notes, keyed by ticker
- `stock_notes` — free-text notes with tags and status, auto-incrementing ID

Notes cannot contaminate calculation fields. Company inputs are strictly numeric (REAL columns). Verification is separate from the values it verifies. Clean separation.

---

### P3-4: FX staleness is now explicit in normalization and QA

**Files**: [normalization_quality.py](golden_vector/qa/normalization_quality.py), [config/qa.yaml](config/qa.yaml)

**Verification**: `qa.yaml` now includes `max_fx_staleness_days: 5` and `block_on_stale_fx: false`. The normalization QA checks for `STALE_FX` status in both equity histories and market snapshots. When `block_on_stale_fx` is true, stale FX produces `FAIL` instead of `WARN`.

The normalization layer (confirmed in earlier reviews) now records `fx_staleness_days` and sets `normalization_status = "STALE_FX"` when the FX rate is older than the threshold.

**Status**: Previous P2-1 finding from Phase 2 review (stale FX used silently) is resolved. FX staleness is now configurable, visible in QA summaries, and can be set to block.

---

### P3-5: Snapshot parsing is hardened with explicit error messages

**File**: `golden_vector/ingestion/standardize.py` (verified via tests)

**Verification**: Tests confirm:
- Missing Date column → `ValueError: missing Date`
- No valid share price → `ValueError: no valid positive share price`
- Empty recent history → `ValueError: No recent history returned for market snapshot`
- Missing Close falls back to `fast_info["currentPrice"]`

These are all clear, actionable error messages. No silent failures or misleading rows.

---

### P3-6: `manual-data set-company` validates ticker against active Tool B universe

**File**: [cli.py:690-697](golden_vector/cli.py#L690-L697)

**Verification**: The ticker is uppercased and checked against `tool_b_universe` (the set of active Tool B tickers from config). If the ticker isn't in the universe, the command returns exit code 1 with a clear message. Test `test_run_manual_data_set_company_updates_store` exercises the happy path.

**Status**: Correct validation.

---

### P3-7: Manifest-based snapshot loading is immutable — resilient to later overwrites

**File**: [latest_data.py](golden_vector/app/latest_data.py) (confirmed via test)

**Verification**: Test `test_load_latest_foundation_snapshot_uses_immutable_run_snapshot_paths` demonstrates that even if `latest_normalized_market_snapshots.parquet` is overwritten by a later failed run, `load_latest_foundation_snapshot` reads from the immutable run-specific snapshot paths recorded in the manifest. The manifest points to `data/runs/<run_id>/snapshots/` which is per-run and never overwritten.

**Status**: Excellent design. This prevents a failed `update-data` from corrupting the active snapshot used by Tool A and Tool B.

---

## 2. Residual Risks

| Risk | Likelihood | Impact | Notes |
|------|-----------|--------|-------|
| Stale briefing document could confuse new contributors | Medium | Low | Architecture map is accurate; briefing is outdated on Combined and manual data |
| CSV export overwrites without backup | Low | Medium | Only matters if user has un-imported CSVs. v1 acceptable. |
| NaN string literals could survive CSV import | Very low | Low | Only if CSV was manually corrupted. SQLite NULLs are clean. |
| CSV round-trip not tested for rate normalization or date format consistency | Medium | Low | Import is tested; export+reimport is not. |
| 140 tests take 39s — could slow down as universe grows | Low | Low | Acceptable for now. Most time is in foundation pipeline tests. |

---

## 3. Final Verdict

**Verdict: `READY WITH MINOR CHANGES`**

This is a significant and well-executed architectural improvement. The codebase moved from 89 tests to 140 tests, from always-refresh to local-first, from CSV-first to SQLite-backed manual data, and from active Combined backend to clean de-scoping.

**What's strong**:

- **Local-first runtime is real**: `tool-a` and `tool-b` read from immutable manifest-backed snapshots. Only `update-data` touches Yahoo. The manifest includes a universe signature check that forces re-fetch when config changes. This is a materially safer operating model.

- **SQLite manual store is well-designed**: Four clean tables with proper separation of concerns. Notes can't contaminate calculation fields. Upserts use `ON CONFLICT` correctly. Ticker seeding is idempotent. Legacy CSV import works as a migration path.

- **Combined is cleanly de-scoped**: No active imports, no active CLI commands, explicit legacy README. No dangling references.

- **FX staleness is now explicit**: Configurable threshold, visible in QA, can be set to block. Previous silent-staleness finding is resolved.

- **Snapshot parsing is defensive**: Clear error messages on malformed Yahoo payloads. Fallback to `fast_info` for price. No silent data loss.

- **Immutable run snapshots**: Later failed runs can't corrupt the active snapshot. Manifest points to per-run immutable paths.

**What to fix**:

- **P2-3**: Add a staleness note to `codex-full-briefing.md` pointing to the architecture map as the current source of truth
- **P2-5**: Add a CSV import/export round-trip test before the tool goes into real use

The code is in a genuinely better architectural state than before. Safe to ship for v1 usage.
