# Claude Review Request - Phase 6 and 7 (Tool B + Combined)

Date: 2026-04-22  
Author: Codex  
Mode required: Read-only review only. No implementation. No code edits. No silent assumptions.

## Review Objective

Please perform a deep, skeptical, implementation-level review of the new **Phase 6 Tool B** and **Phase 7 Combined** code in this repo.

This is not a quick scan. Treat it as a serious pre-ship review of a new engine slice that now spans:

- shared backbone reuse
- manual screening inputs
- Tool B valuation logic
- Tool B standalone CLI execution
- combined join/ranking logic
- updated persistence contracts
- updated tests
- updated operator docs

Your job is to decide whether this code is:

1. logically correct,
2. consistent with the project rules and specs,
3. properly isolated by tool boundary,
4. safe against common edge cases,
5. test-covered in the right places,
6. and actually ready to build on.

I want a **very thorough review**. Assume subtle problems are more dangerous than obvious ones.

## Primary Scope

Review these files carefully:

### Tool B implementation
- `golden_vector/screening/manual_data.py`
- `golden_vector/screening/layer1.py`
- `golden_vector/screening/layer2.py`
- `golden_vector/screening/targets.py`
- `golden_vector/screening/verdicts.py`
- `golden_vector/screening/ranking.py`
- `golden_vector/screening/pipeline.py`

### Combined layer
- `golden_vector/combined/join.py`
- `golden_vector/combined/ranking.py`
- `golden_vector/combined/pipeline.py`

### Shared orchestration and persistence touched by this work
- `golden_vector/cli.py`
- `golden_vector/ingestion/persist.py`
- `golden_vector/contracts/data_models.py`
- `golden_vector/app/paths.py`

### Manual input templates and docs
- `data/manual/screening/company_inputs.csv`
- `data/manual/screening/source_verification.csv`
- `data/manual/screening/reporting_calendar.csv`
- `README.md`

### Tests added/changed for this work
- `tests/test_manual_data.py`
- `tests/test_screening_layer1.py`
- `tests/test_screening_layer2.py`
- `tests/test_tool_b_pipeline.py`
- `tests/test_cli_tool_b.py`
- `tests/test_persist_tool_b.py`
- `tests/test_combined_pipeline.py`
- `tests/test_cli_combined.py`

### Prior context / self-review
- `reviews/codex/codex_review_phase6_tool_b_findings.md`

## Cross-Check Against These Source-of-Truth Docs

Please cross-check the implementation against:

- `AGENTS.md`
- `CLAUDE.md`
- `claude-python-rebuild-spec-gold-v1.md`
- `codex-full-briefing.md`
- `reviews/codex/golden_vector_master_plan.md`

Important:
- if code and docs disagree, call that out explicitly
- if two docs disagree and the code picked one path, call that out explicitly
- do not silently “resolve” ambiguity in your head

## What Changed Conceptually

The app now claims to support:

1. **Tool B as a real standalone engine**
   - consumes normalized shared market snapshots
   - loads manual mining inputs from CSV
   - auto-creates blank template CSVs if missing
   - computes Layer 1 robustness gates
   - computes Layer 2 forward valuation metrics
   - computes target-price scenarios
   - assigns screening verdicts and Tool B score/rank
   - publishes full and latest Tool B outputs

2. **Combined View as a real merged engine**
   - runs Tool A and Tool B under one combined command
   - joins published outputs instead of mixing internal logic
   - preserves partial rows when only one side is usable
   - computes combined score/rank only when both sides are compatible
   - publishes full and latest combined outputs

You should verify that the code actually does this safely and coherently.

## Mandatory Review Lenses

Please use all of these lenses, not just a subset.

### 1. Architecture and tool-boundary correctness
Check that:
- Tool B truly uses the shared backbone rather than owning a shadow market-data path
- Combined truly operates on published tool outputs / compatible contracts, not on hidden internal coupling
- Tool A, Tool B, and Combined remain separable products
- CLI orchestration respects the intended build sequence and failure gates

Look for:
- hidden duplication
- accidental cross-tool leakage
- logic that bypasses the published contract layer
- one tool depending on another’s internals in a way the architecture did not intend

### 2. Formula correctness for Tool B
Cross-check Tool B logic against `codex-full-briefing.md` Appendix A and the master plan.

Review carefully:
- Layer 1 gates
- margin and FCF calculations
- leverage handling
- Layer 2 revenue / EBITDA / net income / EPS / PE / EV/EBITDA logic
- target-price scenario math
- jurisdiction discount application
- verdict logic
- Tool B score logic

I am especially interested in:
- incorrect units
- accidental use of USD vs million-USD in the wrong places
- share-count or market-cap conversion mistakes
- invalid behavior on negative earnings / negative EBITDA / negative FCF / zero shares
- target-price paths that can produce nonsense without being flagged

### 3. Contract and dataset consistency
Check consistency between:
- actual emitted DataFrame columns
- contract models in `data_models.py`
- persistence behavior
- what tests assume
- what README says
- what the master plan says

Look for:
- fields produced but not declared
- fields declared but never produced
- naming drift
- date-key drift
- score/rank fields not aligned with persistence helpers

### 4. Manual-data governance and auditability
Check whether the manual input path is safe and auditable.

Focus on:
- whether missing manual files are handled honestly
- whether auto-generated templates could hide missing data in a misleading way
- whether duplicate manual rows create ambiguity
- whether verification status logic is sound and deterministic
- whether “confidence” is computed exactly as the plan intends
- whether missing manual values are ever silently invented, defaulted, or disguised

### 5. QA and failure gating
Check that the new flow respects the hard rules:
- no analytics on mixed currencies without explicit normalization
- no composite scoring before QA gates
- no hidden manual overrides
- keep transformations auditable and testable

Specifically review:
- `tool-b` failure behavior on raw QA / normalization QA failure
- `combined` failure behavior on raw QA / normalization QA / horizon QA / Tool A output failure
- whether `combined` should tolerate Tool B failure by producing partial rows
- whether current status rollups are correct and unsurprising

If you think the chosen behavior is wrong, say so clearly.

### 6. Combined-layer logic quality
This is a key review area.

Please examine whether:
- join keys are right
- join semantics are right
- partial rows are represented correctly
- combined score should or should not exist on partial rows
- combined verdict taxonomy is coherent
- combined rank behavior is sensible
- the current combined score formula is too naive, acceptable for v1, or actively risky

Do not just accept the current formula if it is simplistic. Evaluate whether it is a defensible v1 choice or whether it creates misleading outputs.

### 7. Edge cases and hidden bugs
Look aggressively for subtle issues such as:
- duplicate rows from merges
- many-to-many joins
- dtype drift causing wrong comparisons
- empty DataFrame behavior
- broken rank sorting on latest snapshots
- missing `qa_summary.json` on some failure paths
- status values that can become inconsistent across commands
- accidentally treating missing values as zeros
- sorting / ranking instability across dates or scenarios
- improper `as_of_date` semantics
- wrong handling of `gold_price_assumption`

### 8. Test quality and coverage
Review the tests as seriously as the code.

Tell me if the tests:
- actually protect the risky behavior
- are too shallow
- miss the most likely regressions
- stub too much and therefore miss integration bugs
- assert the wrong things

I want you to call out:
- missing tests
- weak tests
- misleading tests
- tests that assume behavior not justified by the spec

### 9. Documentation and operator clarity
Review whether the updated README and template behavior are honest and practical for a human operator.

Check whether:
- the commands described match the current code
- manual template behavior is explained clearly
- output semantics are understandable
- partial combined rows are described clearly enough
- any user-facing behavior is likely to confuse Emanuel later

## Required Checks

Please explicitly check for all of the following:

1. Tool B is standalone in practice, not just in name.
2. Combined consumes tool outputs rather than smuggling shared logic across boundaries.
3. Tool B `as_of_date` semantics remain correct.
4. Tool B confidence logic is consistent with the plan.
5. Negative earnings / EBITDA / FCF paths do not accidentally produce misleading “cheap” signals.
6. Duplicate manual CSV rows do not create duplicate output rows.
7. Blank template creation does not falsely imply a clean data state.
8. Tool B latest snapshot exports sort correctly.
9. Combined partial rows do not get fake combined scores.
10. Combined scoring/ranking resets correctly by `as_of_date` and scenario.
11. CLI failure handling writes useful audit outputs on all important stop paths.
12. README and actual behavior match.
13. Tests cover the risky paths above with enough strength.

## Review Constraints

- Read-only review only
- Do not implement
- Do not patch code
- Do not rewrite tests
- Do not silently normalize ambiguities
- If you are unsure, call it out as uncertainty, not as fact

## Output Format

Write your review to:

- `reviews/codex/claude_review_phase6_phase7_toolb_combined_findings.md`

Use this structure exactly:

### 1. Findings

Order findings by severity:
- `P0` = must fix before trusting the feature
- `P1` = serious issue / likely bug / design gap that should be fixed now
- `P2` = important but non-blocking
- `P3` = minor clarity / hardening / documentation issue

For each finding include:
- severity
- short title
- exact file(s)
- relevant function / section
- why it matters
- what is wrong or ambiguous
- what needs to change

### 2. Residual Risks

List real remaining risks even if they are not findings.

### 3. Verdict

End with one of:
- `READY`
- `READY WITH MINOR CHANGES`
- `NOT READY`

Be explicit. If it is only ready because the current scope is v1-limited, say that.

## Extra Instruction

Please be harder on this review than a normal pass.

This code now touches:
- shared backbone reuse
- valuation math
- combined rankings
- CLI orchestration
- persistence contracts

That is exactly where subtle design mistakes become expensive later.

If you think something “works” but is architecturally weak, still call it out.
If you think a formula is plausible but not defensible from the source docs, call it out.
If you think a test is present but weak, call it out.

I would rather get a stricter review now than discover drift after Tool B data starts being filled in.
