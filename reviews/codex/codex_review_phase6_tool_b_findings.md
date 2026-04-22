# Codex Review - Phase 6 Tool B

Date: 2026-04-22  
Reviewer: Codex  
Scope: `golden_vector/screening/*`, `golden_vector/cli.py`, `golden_vector/ingestion/persist.py`, Tool B tests and manual templates

## Findings

### Fixed during review

1. Duplicate manual company rows could duplicate whole Tool B outputs for one ticker.
Why it mattered: a user could accidentally keep two `NEM` rows in `company_inputs.csv`, and the merge would silently emit two valuation rows for the same ticker.
Fix: `load_manual_screening_data()` now deduplicates `company_inputs.csv` and `reporting_calendar.csv` by `ticker`, keeping the last row for deterministic behavior.

2. Latest Tool B exports were not sorted by Tool B rank.
Why it mattered: the shared persistence helper only knew about `tool_a_rank`, so the `tool_b_latest_*.csv` export could look arbitrarily ordered even when ranking existed.
Fix: `_latest_snapshot()` now sorts by `combined_rank`, `tool_a_rank`, `tool_b_rank`, then `ticker` when those columns exist.

3. `tool-b` could fail after normalization was skipped without writing a proper QA summary.
Why it mattered: that weakens the audit trail and makes failure diagnosis harder.
Fix: `run_tool_b()` now writes `qa_summary.json` before finalizing that failure path.

## Residual risks

1. I still could not execute `pytest` or the CLI in this shell because no Python launcher is exposed here (`python` and `py` are both unavailable).
2. Tool B currently supports one explicit gold-price scenario per CLI run. That is correct for the current command surface, but a future multi-scenario batch run will need its own orchestration path rather than looping silently inside one command.

## Verdict

Phase 6 is implementation-ready for the next integration step. The standalone Tool B path now has:

- real CLI execution
- manual template creation
- Layer 1 and Layer 2 outputs
- scenario target prices
- standalone Tool B scoring and ranking
- persisted full-history and latest exports
- direct tests for manual loading, Layer 1, Layer 2, pipeline behavior, CLI gating, and Tool B export sorting

No open blocker remained after the fixes above. The next step is Phase 7: combine published Tool A and Tool B outputs without bypassing the tool boundary.
