# Merged Review: Phase 0 Scaffold

**Date**: 2026-04-22  
**Sources merged**:

- `reviews/codex/claude_review_phase0_scaffold_findings.md`
- `reviews/codex/codex_review_phase0_scaffold_findings.md`

## Resolved Findings

The following findings were accepted and fixed in code or docs:

1. **Currency must be explicit**
   - `UniverseTicker.currency` is now required instead of defaulting to `USD`.

2. **Currency codes must validate early**
   - Universe currencies now validate against the currently supported set:
     `USD`, `CAD`, `GBP`, `AUD`, `ZAR`, `EUR`, `SEK`.

3. **Core horizon format must validate**
   - Core horizons now require the grammar `positive integer + D/M/Y`.

4. **Score weights must sum to 1.0**
   - `ScoreWeights` now validates exact sum-to-one behavior.

5. **Duplicated test-path helper removed**
   - Shared test helper moved into `tests/helpers.py`.

6. **Missing validator test coverage added**
   - Added tests for:
     - duplicate tickers
     - invalid jurisdiction tier
     - unknown currency
     - invalid core horizon format
     - invalid gold price scenarios
     - invalid score weights

7. **Foundation summary counts corrected**
   - The foundation bootstrap now reports configured, active, Tool A enabled, and Tool B enabled ticker counts separately.

8. **CLI location now matches the master plan**
   - The plan now explicitly lists `golden_vector/cli.py`.

9. **`.gitignore` coverage tightened**
   - `.pytest_cache/` is now ignored.
   - Data outputs were already being ignored before the merged review.

## Not Adopted as a Code Change

1. **Unhandled stack traces on failure**
   - This was addressed beyond the review suggestion.
   - `foundation` now writes `FAIL` run metadata on exceptions instead of only crashing.

2. **Run-directory cleanup policy**
   - Deferred intentionally.
   - This is a maintenance concern, not a Phase 0 or Phase 1 blocker.

3. **Universe only has 8 tickers**
   - Deferred intentionally.
   - This is acceptable for scaffold and early-ingestion work. Broader currency coverage should be expanded during Phase 1 validation.

## Current Status

No open scaffold blockers remain from the merged review set.

Remaining practical risk:

- local execution in this shell is still constrained by the missing Python launcher, even though Claude confirmed the scaffold tests and `foundation` command ran successfully in review.

## Verdict

**Merged verdict: `READY WITH MINOR CHANGES`**

The requested minor changes from both reviews that materially improved scaffold safety have been applied. The codebase is ready to continue into Phase 1 ingestion work.
