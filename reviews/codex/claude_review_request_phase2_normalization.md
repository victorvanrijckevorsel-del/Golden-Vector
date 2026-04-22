# Claude Review Request: Phase 2 Normalization

## Review Target

Review the current Phase 2 normalization work on branch `dev-vic` in read-only mode.

Primary files to review:

- `golden_vector/contracts/data_models.py`
- `golden_vector/normalize/calendar.py`
- `golden_vector/normalize/prices_usd.py`
- `golden_vector/normalize/market_snapshot.py`
- `golden_vector/qa/raw_quality.py`
- `golden_vector/ingestion/registry.py`
- `tests/test_prices_usd.py`
- `tests/test_market_snapshot_normalization.py`
- `tests/test_raw_quality.py`
- `tests/test_registry.py`
- `reviews/codex/codex_review_phase2_normalization_findings.md`

Cross-check against:

- `AGENTS.md`
- `CLAUDE.md`
- `reviews/codex/golden_vector_master_plan.md`
- `claude-python-rebuild-spec-gold-v1.md`
- `codex-full-briefing.md`

## Review Objective

Decide whether this normalization layer is safe to wire into the main pipeline.

Focus on:

- correctness of USD normalization for equities
- correctness of USD normalization for Tool B market snapshots
- protection against hidden mixed-currency behavior
- whether the FX alignment behavior matches the project rules
- whether normalization statuses are complete enough for downstream gating
- whether the tests cover the important edge cases

## Review Constraints

- Read only
- No code changes
- No silent assumptions
- Findings first, ordered by severity

## Required Checks

1. Look for any path where mixed-currency math could still slip through silently.
2. Check whether the return-basis logic is safe for Tool A horizon math.
3. Check whether the market snapshot normalization is safe for Tool B consumption.
4. Look for hidden assumptions in the FX forward-fill behavior.
5. Check whether the data-model shapes are sufficient for later pipeline stages.
6. Look for missing tests around malformed rows, stale FX, or status handling.
7. Cross-check whether the normalization behavior matches the master plan and the repo hard rules.

## Output File

Write your findings to:

- `reviews/codex/claude_review_phase2_normalization_findings.md`

## Output Format

Use this structure:

1. Findings
2. Residual risks
3. Final verdict: `READY`, `READY WITH MINOR CHANGES`, or `NOT READY`

Each finding should include:

- severity (`P0` to `P3`)
- short title
- exact file and line or section
- why it matters
- what should change
