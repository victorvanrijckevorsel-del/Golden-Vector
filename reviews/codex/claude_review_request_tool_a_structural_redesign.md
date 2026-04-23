# Claude Review Request: Tool A Structural Redesign

Please perform a deep, read-only review of the current Tool A structural redesign.

This review is intentionally broader than a normal bug pass. The goal is to judge:

- whether the new Tool A implementation is mathematically sound
- whether it is conceptually aligned with the Guo / Leung / Ward paper and the written implementation guide
- whether the new structural-first design is safer and more explainable than the old horizon-first model
- whether the workspace presentation is now accurate and decision-useful
- whether FX / normalization handling is robust through the entire Tool A path

Use this review to stress-test Claude Opus 4.7 properly. Do not keep the review shallow.

## Product Context

Golden Vector is now a local-first product:

- `update-data` refreshes market data and writes a validated local snapshot
- `tool-a` reads that local snapshot and now runs a structural weekly model
- `tool-b` is separate and unchanged for this review
- the workspace is the current product surface
- the old heavy Combined backend was removed from the active product
- the future compare view is intentionally deferred and is **not** part of this review

The important product decision for this milestone is:

- official Tool A is now **structural-first**
- official scoring should be driven by structural delta / gamma / asymmetry / confidence
- volatility is a **diagnostic / context layer**, not a co-equal score factor
- the old horizon-return engine still exists, but it is now **exploratory only**

## Most Important Conceptual Requirement

The user cares most about the Guo / Leung / Ward logic.

Please treat these two documents as first-class review sources:

- [ssrn-3172514.pdf](C:/Users/Emanuel/code/Golden-Vector/ssrn-3172514.pdf)
- [Gold_Framework_Implementation_Guide.docx](C:/Users/Emanuel/code/Golden-Vector/Gold_Framework_Implementation_Guide.docx)

Read them carefully before judging the code.

Important:
- do **not** treat the implementation guide as automatically correct
- if the guide disagrees with the paper, call that out
- if the code matches the guide but still looks conceptually weak relative to the paper, call that out
- if the guide itself has logic you disagree with, say so clearly

Secondary context for product intent and presentation:

- [sprott-gold-equities-strategy-q1-2025-commentary.pdf](C:/Users/Emanuel/code/Golden-Vector/sprott-gold-equities-strategy-q1-2025-commentary.pdf)
- [Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm](C:/Users/Emanuel/code/Golden-Vector/Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm)

## What Changed In This Milestone

The official Tool A path was redesigned from a horizon-first heuristic model into a structural weekly model.

The intended new design is:

- official structural windows fixed to `6M`, `12M`, `3Y`
- use **USD-normalized daily prices only**
- build weekly series from the **last trading day of each week**
- compute **weekly log returns**
- structural delta = regression beta of weekly stock returns vs weekly gold returns
- gamma = regime-sensitive gold exposure using **up-gold vs down-gold beta**
- asymmetry is explicit, not hidden inside gamma
- confidence uses sample size, fit quality, and consistency / stability logic
- volatility is diagnostic only:
  - total volatility
  - residual volatility
  - downside volatility
- explanations are now first-class output fields
- the old custom horizon system remains available, but only as an exploratory layer

## Files To Review

### Core runtime and contracts
- [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
- [golden_vector/app/latest_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/latest_data.py)
- [golden_vector/app/paths.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/paths.py)
- [golden_vector/contracts/config_models.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts/config_models.py)
- [golden_vector/contracts/data_models.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts/data_models.py)
- [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py)

### Tool A structural implementation
- [golden_vector/model/structural.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/structural.py)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py)
- [golden_vector/model/scoring.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/scoring.py)
- [golden_vector/model/labels.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/labels.py)
- [golden_vector/model/explanations.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/explanations.py)

### Exploratory horizon layer that must remain separate
- [golden_vector/features/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/pipeline.py)
- [golden_vector/features/returns.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/returns.py)
- [golden_vector/features/delta.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/delta.py)
- [golden_vector/features/stability.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/stability.py)
- [golden_vector/features/gamma.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/gamma.py)

### Workspace presentation
- [golden_vector/serve/workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py)

### Tests
- [tests/test_config_models.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_config_models.py)
- [tests/test_cli_tool_a.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_cli_tool_a.py)
- [tests/test_tool_a_pipeline.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_a_pipeline.py)
- [tests/test_tool_a_scoring.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_a_scoring.py)
- [tests/test_labels.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_labels.py)
- [tests/test_workspace_app.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_app.py)
- [tests/test_cli_workspace.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_cli_workspace.py)
- [tests/test_persist_tool_a.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_persist_tool_a.py)

## Cross-Check Documentation

- [AGENTS.md](C:/Users/Emanuel/code/Golden-Vector/AGENTS.md)
- [CLAUDE.md](C:/Users/Emanuel/code/Golden-Vector/CLAUDE.md)
- [claude-python-rebuild-spec-gold-v1.md](C:/Users/Emanuel/code/Golden-Vector/claude-python-rebuild-spec-gold-v1.md)
- [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md)
- [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md)
- [reviews/codex/product_runtime_redesign_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/product_runtime_redesign_plan.md)
- [reviews/codex/codex_review_post_workspace_hardening_2026-04-23.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/codex_review_post_workspace_hardening_2026-04-23.md)

## Live Artifacts To Inspect

Please inspect the latest produced Tool A output as part of the review, not just the source:

- [data/output/tool_a/tool_a_latest.csv](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_a/tool_a_latest.csv)
- [data/output/tool_a/tool_a_latest.parquet](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_a/tool_a_latest.parquet)
- [data/runs/20260423T111640Z-tool-a-25003370/metadata.json](C:/Users/Emanuel/code/Golden-Vector/data/runs/20260423T111640Z-tool-a-25003370/metadata.json)

You should use these artifacts to judge:
- whether the published schema makes sense
- whether the explanation text is faithful to the underlying metrics
- whether the volatility fields look sensible
- whether snapshot / FX provenance is carried through correctly

## Mandatory Review Lenses

### 1. Mathematical correctness
- Is structural delta actually implemented as intended?
- Is the weekly aggregation logic correct and robust?
- Are weekly joins and return calculations done in the right order?
- Is gamma truly regime-based, or is there still hidden proxy logic that does not match the stated intent?
- Is asymmetry explicit and interpretable?
- Are the volatility diagnostics mathematically coherent and ticker-safe?

### 2. Conceptual alignment with the paper and guide
- Does the code match the **spirit and useful logic** of the Guo / Leung / Ward paper?
- Does it match the written implementation guide where it should?
- Where the guide is weaker, overly simplified, or conceptually wrong, call that out.
- Is the final model still genuinely a delta / gamma / optionality framework, or has it drifted?

### 3. Exploratory vs official separation
- Verify that custom horizons are truly exploratory only.
- Find any path where horizon-return metrics still leak into official Tool A scoring, labels, or explanations.
- Find any naming or UI choice that could confuse users into thinking exploratory metrics are official structural metrics.

### 4. FX / normalization robustness
- Find any place where Tool A can operate on mixed currencies.
- Find any place where local-currency returns can leak into structural analytics.
- Find any place where stale FX or failed normalization is hidden instead of being surfaced.
- Verify that Tool A remains downstream of normalization and does not silently recompute FX logic.

### 5. Output contract and auditability
- Check that the published Tool A outputs match the documented schema and the intended product meaning.
- Find any field that is missing, misleading, under-tested, or internally inconsistent.
- Check whether snapshot provenance and FX policy context are sufficient to trust outputs later.

### 6. Explanation quality
- Are the user-facing explanation strings deterministic and defensible?
- Do they explain what the metric means in practical terms, rather than just restating the number?
- Are there cases where the tool could confidently explain something that the underlying metrics do not justify?
- Are the combined interaction explanations actually useful and correct?

### 7. Workspace presentation quality
- Does the new Tool A presentation help a user understand the stock?
- Are the structural cards, panels, and visuals intuitive?
- Is anything visually misleading or too busy?
- Does the workspace separate official structural insight from exploratory data clearly enough?

### 8. Tests and regression protection
- Are the important cases covered?
- What critical edge cases are still untested?
- Are there weak or brittle tests that could let bad math through?

## Required Checks

Please explicitly check for the following and call them out if found:

1. Any bug in weekly resampling, weekly joins, or log-return construction.
2. Any bug where structural delta or gamma is computed on the wrong subset or wrong currency basis.
3. Any incorrect handling of up-gold / down-gold beta splits.
4. Any asymmetry ratio bug, especially around sign handling or divide-by-small-number behavior.
5. Any volatility bug, especially:
   - mixing rows across tickers
   - using the wrong residual definition
   - annualization mistakes
   - downside-volatility mistakes
6. Any confidence / fit logic that is too permissive or too arbitrary.
7. Any profile-label or score-eligibility logic that could mislead users.
8. Any explanation output that overstates confidence or misstates the metric.
9. Any place where failed or weak upstream normalization can still produce apparently valid structural results.
10. Any persistence or latest-alias issue that could make the workspace show stale or broken Tool A output.
11. Any UI wording or layout choice that would confuse a non-technical user.
12. Any place where the guide and code align with each other but still fail to match the paper well.

## Specific Questions To Answer

Please answer these directly in the review:

1. Is the new official Tool A mathematically coherent?
2. Is it meaningfully closer to the Guo / Leung / Ward logic than the old horizon-first model?
3. Does the implementation guide still need conceptual refinement after this redesign?
4. Is volatility integrated in the right way, or should it be treated differently?
5. Are the new explanation fields genuinely valuable, or are they still too shallow or too risky?
6. Is the workspace now the right presentation shape for Tool A, or should it be improved before more feature work?
7. What are the most important remaining weaknesses before we can fully trust Tool A?

## Output Rules

- Read-only review only
- No code changes
- No silent assumptions
- Findings first, ordered by severity
- Be concrete and cite files / lines where possible
- Separate **bugs** from **conceptual disagreements**
- Do not hide behind "this is subjective" if you think the logic is weak

Please write your review to:

- `reviews/codex/claude_review_tool_a_structural_redesign_findings.md`

Use this structure:

1. Findings ordered `P0` to `P3`
2. Conceptual alignment with the Guo / Leung / Ward paper
3. Conceptual alignment with the implementation guide
4. FX / normalization assessment
5. Explanation and dashboard / workspace assessment
6. Missing tests / residual risks
7. Final verdict: `READY`, `READY WITH MINOR CHANGES`, or `NOT READY`
