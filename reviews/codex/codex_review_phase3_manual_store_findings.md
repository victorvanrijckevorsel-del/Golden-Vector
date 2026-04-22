# Codex Review: Phase 3 Manual Store

Date: 2026-04-22

## Scope

Review of the Tool B manual-data redesign:
- SQLite-backed local manual-data store
- direct CLI editing commands
- per-stock notes support
- Tool B pipeline migration from CSV-first runtime behavior

## Findings Fixed During Review

### 1. CSV import could crash on pandas `NaT`
- Issue: legacy CSV import normalized date-like columns into pandas date/`NaT` values, but the SQLite insert path still passed those objects directly.
- Risk: first-run migration from CSV could fail even though the underlying data was valid.
- Fix: normalize all SQLite-bound values through `_sqlite_value()` so `NaT` becomes `None` and `date`/`datetime` values become explicit ISO strings.

### 2. Manual-data show command could fail when writing run artifacts
- Issue: `manual-data show` correctly loaded reporting dates from the new store, but `RunContext.write_json()` still assumed JSON-native values only.
- Risk: direct inspection commands could fail even though the manual-data store itself was healthy.
- Fix: added shared JSON default serialization in [run_context.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/run_context.py) for `date`, `datetime`, and `Path`.

### 3. Direct Tool B manual-entry commands were too permissive
- Issue: the first draft allowed updates for any active ticker rather than only active Tool B tickers.
- Risk: the local Tool B store could accumulate rows for names that are not actually in the Tool B universe.
- Fix: `manual-data` and `manual-note add` now validate against the active Tool B ticker set.

### 4. Local SQLite store file was not ignored by git
- Issue: the new runtime-owned database file would have shown up as an untracked artifact.
- Risk: accidental commits of local analyst data.
- Fix: added `*.sqlite3` to [.gitignore](C:/Users/Emanuel/code/Golden-Vector/.gitignore).

## Final Verdict

No open blockers remain in this phase.

Phase 3 is now in a good state:
- Tool B uses the local manual-data store by default
- legacy CSVs are secondary import/export support only
- direct in-tool manual entry works through the CLI
- per-stock notes are stored separately from valuation inputs
- full suite passes
- live smoke path passes
