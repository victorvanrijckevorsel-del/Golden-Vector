# Codex Review: Phase 3 / Phase 4 Runtime, Manual Store, and Reliability Hardening

Date: 2026-04-22
Mode: Read-only review only. No implementation changes made in this pass.

## Findings

### P1. Latest-snapshot invalidation is too narrow for the new QA policy
- Files:
  - [golden_vector/app/latest_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/latest_data.py)
  - [config/qa.yaml](C:/Users/Emanuel/code/Golden-Vector/config/qa.yaml)
  - [tests/test_latest_data.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_latest_data.py)
- Exact area:
  - `write_latest_foundation_manifest()`
  - `_foundation_signature()`
  - `_validate_foundation_signature()`
- What is wrong:
  - The latest-foundation manifest only fingerprints active tickers, currencies, and Tool A / Tool B enablement.
  - It does not include the refresh-affecting QA / normalization policy that now matters for correctness, especially `qa.max_fx_staleness_days` and `qa.block_on_stale_fx`.
  - That means the app can keep accepting an old local snapshot even after the operator changes FX-staleness policy in config.
- Why it matters:
  - The whole redesign now depends on `update-data` being the explicit point where market-data validity is established.
  - If the operator tightens FX staleness rules later, Tool A and Tool B can still run against a snapshot that was validated under looser rules.
  - That is a real local-first correctness hole because the manifest says "usable snapshot" when the policy under which it was produced has changed.
- What I would change:
  - Expand the foundation signature from "universe shape only" to "refresh-contract signature".
  - At minimum include:
    - active tickers / currencies / tool flags
    - gold symbol / FX source assumptions if configurable
    - `qa.max_fx_staleness_days`
    - `qa.block_on_stale_fx`
  - Add a regression test proving that changing FX freshness policy invalidates the snapshot and forces `update-data`.

### P1. Normal Tool B usage still mutates local manual-data state as a side effect
- Files:
  - [golden_vector/screening/manual_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_data.py)
  - [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
  - [tests/test_manual_data.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_manual_data.py)
  - [tests/test_tool_b_pipeline.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_b_pipeline.py)
- Exact area:
  - `load_manual_screening_data()`
  - `ensure_manual_store(..., import_csv_if_empty=True)`
  - `run_tool_b()`
  - `run_manual_data()`
  - `run_manual_note()`
- What is wrong:
  - The code moved away from editing CSVs directly, which is good, but it still performs hidden write-side effects during normal use.
  - `load_manual_screening_data()` always calls `ensure_manual_store(..., import_csv_if_empty=True)`.
  - So `tool-b`, `manual-note add`, `manual-note list`, and even `manual-data show` can:
    - create the SQLite store
    - seed active tickers
    - import legacy CSVs
  - as part of what should feel like normal read/use operations.
- Why it matters:
  - The redesign plan said normal Tool B runs should be read-only with respect to manual data.
  - `manual-data init` exists, but the current implementation makes it mostly ceremonial because other commands auto-bootstrap anyway.
  - This creates hidden state transitions during routine usage and makes operator behavior less explicit than the product direction now promises.
- What I would change:
  - Split the current loader into two modes:
    - `open_existing_manual_store()` for normal runtime / inspection
    - `bootstrap_manual_store()` for explicit initialization / migration
  - Make `tool-b`, `manual-data show`, and `manual-note list` fail cleanly with a clear instruction if the store does not exist yet.
  - Keep `manual-data init` and `manual-data import-csv` as the only commands that are allowed to create or migrate the store.

### P2. The new direct-edit CLI cannot clear values once they are set
- Files:
  - [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
  - [golden_vector/screening/manual_store.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_store.py)
- Exact area:
  - `run_manual_data()`
  - `upsert_company_input()`
  - `upsert_reporting_calendar()`
  - `upsert_source_verification()`
- What is wrong:
  - The new CLI can set fields, but it cannot intentionally set them back to blank / null.
  - `manual-data set-company` and `manual-data set-reporting` only update fields that were provided.
  - `set-verification` can overwrite values, but there is still no explicit clear/remove path for optional fields like `source_date`, `source_url`, or `notes`.
- Why it matters:
  - Direct in-tool editing is now the primary intended workflow.
  - If the user enters a wrong AISC, wrong date, or stale note, there is no clean command to clear it.
  - That pushes the operator back toward SQLite poking or CSV workarounds, which defeats the product direction.
- What I would change:
  - Add an explicit clear mechanism, for example:
    - `--clear production_oz,aisc_usd_per_oz`
    - or field-specific `--clear-*` flags
  - Allow the upsert helpers to distinguish:
    - "field omitted, leave unchanged"
    - "field explicitly cleared, write NULL"
  - Add tests for clearing numeric fields, reporting dates, and source-verification metadata.

### P2. CSV import/export is not a true backup or migration path for the new manual-data model
- Files:
  - [golden_vector/screening/manual_store.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_store.py)
  - [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md)
  - [tests/test_manual_data.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_manual_data.py)
- Exact area:
  - `import_support_csvs_into_store()`
  - `_import_csv_support_files()`
  - `export_store_to_csv()`
  - `stock_notes` schema and note commands
- What is wrong:
  - README now says CSV can be used for migration or backup, but the CSV support path only covers:
    - `company_inputs`
    - `source_verification`
    - `reporting_calendar`
  - It does not export or import `stock_notes`, even though notes are now a real product feature.
  - On top of that, CSV import is unconditional upsert. A stale support CSV can overwrite newer store values without conflict detection or dry-run preview.
- Why it matters:
  - The new manual-data store is now part of the real workflow, not just a transient technical detail.
  - If CSV is described as backup/migration support, it needs to reflect the real store contents, or the operator gets a false sense of recoverability.
  - Missing notes and silent overwrite behavior make the current CSV path weaker than the docs imply.
- What I would change:
  - Choose one of these two directions explicitly:
    1. Make CSV support a real migration/backup path:
       - export/import `stock_notes`
       - add conflict policy / overwrite summary / maybe dry-run mode
    2. Downgrade the docs and CLI language:
       - make it clear CSV is only a partial compatibility path for the older company-input tables
  - Add a round-trip test that includes notes if backup/migration remains a claimed use case.

### P2. Core manual-input tables still lack basic edit timestamps
- Files:
  - [golden_vector/screening/manual_store.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_store.py)
  - [golden_vector/screening/manual_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_data.py)
  - [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
- Exact area:
  - `_create_schema()`
  - `load_store_tables()`
  - `manual-data show`
- What is wrong:
  - `stock_notes` has `created_at_utc` and `updated_at_utc`, but the core editable tables do not:
    - `company_inputs`
    - `source_verification`
    - `reporting_calendar`
  - So the user can inspect current values, but cannot tell when those values were last changed.
- Why it matters:
  - These are exactly the slow-moving records the operator will maintain over time.
  - Without timestamps, the new store is operationally weaker than it should be: you can see the value, but not whether it was updated yesterday or six months ago.
  - That hurts trust and follow-up, especially since the product direction now emphasizes notes/comments and deliberate maintenance.
- What I would change:
  - Add `created_at_utc` and `updated_at_utc` columns to all core manual tables.
  - Update them in the upsert paths.
  - Expose them in `manual-data show` so the user can judge recency directly.

## Residual Risks

- The local-first runtime model itself is materially better than before, but it is only as safe as the manifest invalidation logic. Right now that invalidation logic is still too narrow.
- Combined de-scope looks clean enough at the active CLI level. I did not find evidence that the active product still depends on Combined artifacts.
- FX staleness hardening is directionally correct and the tests cover warn-vs-fail, but the snapshot-manifest issue weakens the real operator guarantee after config changes.
- The manual-store redesign is an improvement over CSV-first runtime behavior, but it is not fully aligned with the new "explicit app data" model until initialization/migration side effects are made explicit.
- Test coverage is strong compared with earlier phases, but there are still notable missing cases:
  - config changes invalidating the local snapshot manifest
  - clear/remove semantics for the new manual-data CLI
  - notes included in backup/migration behavior if that remains a product promise
  - read-only normal-use behavior for Tool B/manual inspection commands

## Final Verdict

`READY WITH MINOR CHANGES`

The redesign is directionally correct and materially better than the previous state:
- local-first runtime is real
- Combined is correctly de-scoped from the active backend
- Tool B has a proper local store now
- FX staleness and snapshot hardening are meaningful improvements

But I would not call this redesign fully closed yet. The remaining issues are not cosmetic:
- one affects local snapshot validity after QA-policy changes
- one still violates the intended explicit manual-data lifecycle
- and the new primary editing workflow still cannot clear values cleanly

So the code is usable and improved, but it still needs a small follow-up hardening pass before I would consider this product/runtime shift fully finished.
