# Claude Review Request: Tool A Phase 4 Milestone

Please perform a deep, read-only review of the current Tool A milestone.

## Review Goal
- Decide whether the current Tool A implementation is internally coherent and safe to keep building on.
- Focus on the end-to-end Tool A path:
  - shared backbone
  - horizon-return stage
  - Tool A metric/scoring/ranking stage
  - exploratory `compare-horizons`

## Files To Review
- [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
- [golden_vector/features/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/pipeline.py)
- [golden_vector/features/returns.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/returns.py)
- [golden_vector/features/delta.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/delta.py)
- [golden_vector/features/stability.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/stability.py)
- [golden_vector/features/gamma.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/gamma.py)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py)
- [golden_vector/model/labels.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/labels.py)
- [golden_vector/model/scoring.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/scoring.py)
- [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py)
- [golden_vector/contracts/config_models.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts/config_models.py)
- [golden_vector/contracts/data_models.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts/data_models.py)
- [config/scoring.yaml](C:/Users/Emanuel/code/Golden-Vector/config/scoring.yaml)
- [tests/test_cli_tool_a.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_cli_tool_a.py)
- [tests/test_horizon_quality.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_horizon_quality.py)
- [tests/test_horizons.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_horizons.py)
- [tests/test_returns.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_returns.py)
- [tests/test_stability.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_stability.py)
- [tests/test_tool_a_pipeline.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_a_pipeline.py)

Cross-check against:
- [AGENTS.md](C:/Users/Emanuel/code/Golden-Vector/AGENTS.md)
- [CLAUDE.md](C:/Users/Emanuel/code/Golden-Vector/CLAUDE.md)
- [claude-python-rebuild-spec-gold-v1.md](C:/Users/Emanuel/code/Golden-Vector/claude-python-rebuild-spec-gold-v1.md)
- [codex-full-briefing.md](C:/Users/Emanuel/code/Golden-Vector/codex-full-briefing.md)
- [reviews/codex/golden_vector_master_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/golden_vector_master_plan.md)
- [reviews/codex/codex_review_phase4_tool_a_milestone_findings.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/codex_review_phase4_tool_a_milestone_findings.md)

## Mandatory Review Lenses
- Hard-gate correctness between normalization, horizons, and Tool A scoring
- Contract correctness of the published Tool A output table
- Whether positive/negative delta behavior matches the stated product rules
- Stability/gamma interpretation quality
- Ranking correctness by `as_of_date`
- Whether custom horizons remain exploratory and cannot leak into official scoring
- Missing tests or weak regression coverage
- Any misleading output that would confuse a user or downstream stage

## Required Checks
- Find any place where Tool A scoring can still happen after an upstream failed gate.
- Find any place where custom horizons can affect official scores.
- Find any contract mismatch between the code and the documented Tool A output schema.
- Find any metric definition that is too unstable, too arbitrary, or inconsistent with the docs.
- Find any ranking bug or tie-handling bug.
- Find any audit/persistence issue that could make a run hard to trust later.
- Find missing edge-case tests, especially around:
  - near-zero gold return windows
  - inverse delta names
  - insufficient eligible core horizons
  - empty or partial horizon tables

## Output Rules
- Read-only review only
- No code changes
- No silent assumptions
- Findings first, ordered by severity

Please write your review to:
- `reviews/codex/claude_review_phase4_tool_a_milestone_findings.md`

Use this structure:
1. Findings ordered `P0` to `P3`
2. Residual risks
3. Final verdict: `READY`, `READY WITH MINOR CHANGES`, or `NOT READY`
