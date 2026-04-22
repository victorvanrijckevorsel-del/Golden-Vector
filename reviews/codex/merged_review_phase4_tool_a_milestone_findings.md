# Merged Review: Tool A Phase 4 Milestone

## Sources
- [codex_review_phase4_tool_a_milestone_findings.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/codex_review_phase4_tool_a_milestone_findings.md)
- [claude_review_phase4_tool_a_milestone_findings.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_review_phase4_tool_a_milestone_findings.md)

## Fixed After Claude Review

### 1. Defensive status handling
- Claude flagged that `_combine_statuses()` would silently treat unknown statuses as `PASS`.
- Fix applied in [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py):
  - unsupported statuses now raise `ValueError`
- Regression coverage added in [tests/test_cli_tool_a.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_cli_tool_a.py)

### 2. Missing gamma edge-case regression
- Claude flagged the untested branch where all absolute gold returns are identical.
- Regression coverage added in [tests/test_gamma.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_gamma.py)

### 3. Missing multi-date ranking regression
- Claude flagged that ranking-by-`as_of_date` was only tested on a single date.
- Regression coverage added in [tests/test_tool_a_pipeline.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_a_pipeline.py)

## Additional Improvement Completed In The Same Pass
- Tool A outputs now publish:
  - full-history parquet
  - full-history CSV
  - latest-snapshot parquet
  - latest-snapshot CSV
- This was added in [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py) with coverage in [tests/test_persist_tool_a.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_persist_tool_a.py)

## Remaining Non-Blocking Items
- Performance of `returns.py` on the full max-history universe should still be monitored on the first real run.
- Inverse names are intentionally unranked and currently identified via:
  - `regime_tag = "INVERSE"`
  - `score_eligibility_reason = "NON_POSITIVE_CORE_DELTA"`
  This is documented in [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md) and can be made more explicit later in the serve layer if needed.

## Current State
- Claude review loop is closed for the current Tool A milestone.
- The next meaningful implementation area is either:
  - richer Tool A serve/export surfaces, or
  - Tool B buildout.
