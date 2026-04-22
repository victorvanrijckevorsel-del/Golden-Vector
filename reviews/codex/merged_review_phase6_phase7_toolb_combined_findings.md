# Merged Review - Phase 6 and 7 (Tool B + Combined)

Date: 2026-04-22  
Sources merged:
- `reviews/codex/codex_review_phase6_phase7_toolb_combined_findings.md`
- `reviews/codex/claude_review_phase6_phase7_toolb_combined_findings.md`

## Overlap Between Reviews

The two reviews were broadly aligned:

1. The core Tool B and Combined formulas are not the problem.
2. The real issues are around robustness, configuration hygiene, and edge-case honesty.
3. The implementation is close to ready, but a few gaps were worth fixing before building further.

## Fixes Applied After Review

### 1. Tool B no longer drops active tickers when market snapshots are missing

This was the main Codex finding.

What changed:
- Tool B now starts from the full active Tool B ticker list, not only from available snapshot rows.
- Missing snapshot tickers now emit explicit `INCOMPLETE` rows instead of disappearing.
- Tool B summary now records `missing_market_snapshot_row_count`.
- Missing-snapshot rows get a stable `as_of_date` anchor for the run instead of breaking output generation.

Why it matters:
- coverage gaps are now visible in Tool B output
- combined outputs can show partial/incomplete rows honestly instead of silently losing names

### 2. Combined join now fails on duplicate keys instead of silently multiplying rows

This was the second major Codex finding.

What changed:
- `golden_vector/combined/join.py` now asserts uniqueness of:
  - `ticker`
  - `as_of_date`
  - `gold_price_assumption`
  on both Tool A and Tool B inputs before merging.

Why it matters:
- prevents hidden many-to-many expansions
- makes combined ranking safer and more auditable

### 3. Manual template drift is now handled

This was another Codex finding.

What changed:
- manual template sync now updates existing `company_inputs.csv` and `reporting_calendar.csv`
  when new Tool B tickers are added to the universe later
- sync results distinguish:
  - created files
  - updated files
- run notes now mention when existing templates were updated

Why it matters:
- adding a new Tool B ticker no longer leaves stale templates behind
- operator workflow is now much closer to the intended config-driven model

### 4. Combined verdict thresholds were moved into config

This came from Claude’s review.

What changed:
- added `combined_verdict_thresholds` to `config/scoring.yaml`
- added validated config model support in `config_models.py`
- combined verdict logic now reads thresholds from config instead of hardcoding `75.0` and `60.0`

Why it matters:
- business rules that are likely to change are now versioned/config-driven
- this matches the repo’s hard rules more closely

### 5. Test coverage was expanded for the review gaps

From Claude’s review:
- added negative-net-debt coverage
- added combined ranking reset coverage by gold-price scenario

From Codex’s review:
- added duplicate combined-join-key failure coverage
- added missing-market-snapshot Tool B coverage
- added template-update coverage

## Findings Left as V1 Decisions, Not Bugs

### 1. Combined score is still a simple 50/50 average

Claude flagged this as a meaningful product choice, not a correctness bug.

Decision:
- left as-is for v1
- documented in `README.md`

### 2. Combined verdict does not yet downweight estimated Tool B confidence

Codex flagged this as a product-quality limitation.

Decision:
- left as-is for v1
- documented in `README.md`
- confidence remains visible in the output and should be read alongside the verdict

### 3. Market-cap divergence warning and snapshot-date consistency warning

Claude flagged these as worthwhile hardening items.

Decision:
- not patched in this pass
- reasonable for Phase 8 hardening

## Post-Merge Status

After the merged review pass:

- Tool B coverage honesty is materially improved
- Combined merge safety is materially improved
- manual template lifecycle is materially improved
- combined verdict thresholds are now config-driven
- the remaining open items are mostly hardening/documentation choices, not core correctness bugs

## Remaining Limitation

I still could not run `pytest` or the CLI in this shell because no Python launcher is exposed here. Claude previously ran the suite successfully before this latest patch set, but these newest changes still need one fresh test pass in a Python-enabled environment.
